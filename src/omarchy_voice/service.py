"""Bounded, same-UID Unix IPC and the voice lifecycle state machine."""

from pathlib import Path
import fcntl
import json
import os
import secrets
import socket
import stat
import struct
import subprocess
import threading
import time
from .audio import PipeWireRecorder
from .core import VoiceError, Router, parse
from .providers import IsolatedSTT

MAX_REQUEST = 4096


def runtime_dir():
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value or not Path(value).is_absolute():
        raise VoiceError("XDG_RUNTIME_DIR must be an absolute owned directory")
    base = Path(value)
    try:
        info = base.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
        ):
            raise VoiceError("Unsafe runtime directory")
        path = base / "omarchy-voice"
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise VoiceError("Unsafe voice runtime directory")
        return path
    except OSError as exc:
        raise VoiceError("Cannot access runtime directory") from exc


class Controller:
    def __init__(
        self, config, *, recorder_factory=None, worker_factory=None, router=None
    ):
        self.config = config
        self.recorder_factory = recorder_factory or (
            lambda: PipeWireRecorder(runtime_dir())
        )
        self.worker_factory = worker_factory or (lambda: IsolatedSTT(config))
        self.router = router or Router(config)
        self.lock = threading.RLock()
        self.state = "idle"
        self.message = "Ready"
        self.recorder = None
        self.worker = None
        self.thread = None
        self.timer = None
        self.event = threading.Event()
        self.generation = 0
        self.pending = None
        self.window_address = None
        self.action_thread = None

    def _set(self, state, message):
        self.state = state
        self.message = message

    def _expire(self):
        if self.pending and time.monotonic() >= self.pending[2]:
            self.pending = None
            self._set("idle", "Confirmation expired")

    def status(self):
        with self.lock:
            self._expire()
            result = {"state": self.state, "message": self.message}
            if self.pending:
                result["confirmation_token"] = self.pending[1]
            return result

    def start(self):
        with self.lock:
            self._expire()
            if self.state not in ("idle", "error"):
                raise VoiceError("Voice service is busy")
            self.generation += 1
            self.event = threading.Event()
            self.pending = None
            # Failure to identify focus disables close, not unrelated commands.
            try:
                self.window_address = self.router.capture_window()
            except VoiceError:
                self.window_address = None
            recorder = None
            try:
                recorder = self.recorder_factory()
                recorder.start()
            except Exception:
                if recorder is not None:
                    recorder.cleanup()
                self._set("error", "Recording failed")
                raise VoiceError("Recording failed")
            self.recorder = recorder
            self._set("listening", "Listening")
            generation = self.generation
            self.timer = threading.Timer(
                self.config.max_seconds, self._limit, args=(generation,)
            )
            self.timer.daemon = True
            self.timer.start()
            return self.status()

    def _limit(self, generation):
        with self.lock:
            if generation != self.generation or self.state != "listening":
                return
            self.cancel()
            self._set("error", "Recording time limit reached")

    def stop(self):
        with self.lock:
            if self.state != "listening":
                raise VoiceError("Not recording")
            if self.timer:
                self.timer.cancel()
                self.timer = None
            recorder = self.recorder
            try:
                audio = recorder.stop()
                self.worker = self.worker_factory()
            except Exception:
                recorder.cleanup()
                self.recorder = None
                self._set("error", "Recording failed")
                raise VoiceError("Recording failed")
            self._set("transcribing", "Transcribing locally")
            self.thread = threading.Thread(
                target=self._work,
                args=(self.generation, recorder, self.worker, audio, self.event),
                daemon=True,
            )
            self.thread.start()
            return self.status()

    def _work(self, generation, recorder, worker, audio, event):
        try:
            try:
                text = worker.transcribe(audio, self.config.language, event)
            finally:
                recorder.cleanup()
            intent = parse(text)
            with self.lock:
                if generation != self.generation or event.is_set():
                    return
                self._apply(intent)
        except Exception as exc:
            with self.lock:
                if generation == self.generation and not event.is_set():
                    self._set(
                        "error",
                        str(exc)
                        if isinstance(exc, VoiceError)
                        else "Voice processing failed",
                    )
        finally:
            with self.lock:
                if generation == self.generation:
                    self.recorder = None
                    self.worker = None

    def _apply(self, intent):
        self.router.plan(intent)
        if intent.action == "window.close":
            address = self.router.validate_window(self.window_address)
            self.pending = (
                intent,
                secrets.token_urlsafe(24),
                time.monotonic() + self.config.confirmation_seconds,
                address,
            )
            self._set("confirmation", "Confirm closing the original window")
            return
        self._queue_action(intent)

    def _queue_action(self, intent, *, confirmed=False, window_address=None):
        # Caller holds the state lock; execution must never hold it. Returning
        # immediately also keeps the single-client IPC loop available to the UI.
        self._set("executing", "Executing command")
        self.action_thread = threading.Thread(
            target=self._execute_action,
            args=(intent, confirmed, window_address), daemon=True,
        )
        self.action_thread.start()

    def _execute_action(self, intent, confirmed, window_address):
        try:
            self.router.execute(intent, confirmed=confirmed, window_address=window_address)
        except Exception as exc:
            with self.lock:
                self._set("error", str(exc) if isinstance(exc, VoiceError) else "Command failed")
            return
        with self.lock:
            self._set("idle", "Command completed")
        if self.config.notifications:
            try:
                subprocess.run(
                    ["notify-send", "Omarchy Voice", "Command completed"],
                    timeout=2,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    def run(self, text):
        with self.lock:
            self._expire()
            if self.state not in ("idle", "error"):
                raise VoiceError("Voice service is busy")
            try:
                intent = parse(text)
                if intent.action == "window.close":
                    self.window_address = self.router.capture_window()
                self._apply(intent)
            except VoiceError:
                self._set("error", "Command failed")
                raise
            return self.status()

    def confirm(self, token):
        with self.lock:
            self._expire()
            if (
                not self.pending
                or type(token) is not str
                or not token.isascii()
                or len(token) > 64
                or not secrets.compare_digest(token, self.pending[1])
            ):
                raise VoiceError("Invalid or expired confirmation")
            intent, _, _, address = self.pending
            self.pending = None
            self._queue_action(intent, confirmed=True, window_address=address)
            return self.status()

    def cancel(self):
        with self.lock:
            if self.state == "executing":
                raise VoiceError("Action already executing; cannot cancel")
            self.generation += 1
            self.event.set()
            self.pending = None
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if self.worker:
                self.worker.cancel()
                self.worker = None
            if self.recorder:
                self.recorder.cleanup()
                self.recorder = None
            self._set("idle", "Cancelled")
            return self.status()

    def close(self):
        with self.lock:
            # Reserve shutdown before transcription can enqueue a new action.
            executing = self.state == "executing"
            if not executing:
                self.cancel()
        if self.action_thread and self.action_thread is not threading.current_thread():
            self.action_thread.join(13)
        if executing:
            self.cancel()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(3)


def _receive(connection):
    data = bytearray()
    deadline = time.monotonic() + 2
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VoiceError("Request timed out")
        connection.settimeout(remaining)
        part = connection.recv(min(1024, MAX_REQUEST + 1 - len(data)))
        if not part:
            raise VoiceError("Incomplete request")
        data.extend(part)
        if len(data) > MAX_REQUEST:
            raise VoiceError("Request too large")
    line, rest = bytes(data).split(b"\n", 1)
    if rest:
        raise VoiceError("Only one request permitted")
    try:
        value = json.loads(line)
        if type(value) is not dict:
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise VoiceError("Invalid JSON request") from exc


def dispatch(controller, request):
    command = request.get("command")
    if type(command) is not str:
        raise VoiceError("Invalid request")
    allowed = {
        "status": set(),
        "start": set(),
        "stop": set(),
        "cancel": set(),
        "confirm": {"token"},
        "run": {"text"},
    }
    if command not in allowed or set(request) != {"command"} | allowed[command]:
        raise VoiceError("Unknown command or parameters")
    if command == "confirm":
        return controller.confirm(request["token"])
    if command == "run":
        return controller.run(request["text"])
    return getattr(controller, command)()


class Server:
    def __init__(self, controller):
        self.controller = controller
        self.stop_event = threading.Event()
        self.sock = None

    def serve(self):
        directory = runtime_dir()
        path = directory / "control.sock"
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(directory / "daemon.lock", flags, 0o600)
        bound = False
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise VoiceError("Unsafe daemon lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise VoiceError("Voice service already running")
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise VoiceError("Unsafe socket path")
                path.unlink()
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.bind(str(path))
            bound = True
            path.chmod(0o600)
            self.sock.listen(8)
            self.sock.settimeout(0.2)
            while not self.stop_event.is_set():
                try:
                    connection, _ = self.sock.accept()
                except socket.timeout:
                    continue
                with connection:
                    try:
                        _, uid, _ = struct.unpack(
                            "3i",
                            connection.getsockopt(
                                socket.SOL_SOCKET,
                                socket.SO_PEERCRED,
                                struct.calcsize("3i"),
                            ),
                        )
                        if uid != os.getuid():
                            raise VoiceError("Peer UID not permitted")
                        result = dispatch(self.controller, _receive(connection))
                    except (VoiceError, OSError) as exc:
                        result = {
                            "state": "error",
                            "message": str(exc)
                            if isinstance(exc, VoiceError)
                            else "IPC request failed",
                        }
                    try:
                        connection.settimeout(2)
                        connection.sendall((json.dumps(result) + "\n").encode())
                    except OSError:
                        pass
        finally:
            self.controller.close()
            if self.sock:
                self.sock.close()
            if bound:
                path.unlink(missing_ok=True)
            os.close(fd)


def request(command, **parameters):
    path = runtime_dir() / "control.sock"
    try:
        info = path.lstat()
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise VoiceError("Unsafe service socket")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(15)
            connection.connect(str(path))
            _, uid, _ = struct.unpack(
                "3i",
                connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                ),
            )
            if uid != os.getuid():
                raise VoiceError("Peer UID not permitted")
            payload = (json.dumps({"command": command, **parameters}) + "\n").encode()
            if len(payload) > MAX_REQUEST:
                raise VoiceError("Request too large")
            connection.sendall(payload)
            # Actions are bounded at 10s; response reads get their own bound.
            data = b""
            deadline = time.monotonic() + 15
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VoiceError("Service response timed out")
                connection.settimeout(remaining)
                chunk = connection.recv(1024)
                if not chunk or len(data) + len(chunk) > MAX_REQUEST:
                    raise VoiceError("Invalid service response")
                data += chunk
            response = json.loads(data)
            if (
                type(response) is not dict
                or type(response.get("state")) is not str
                or type(response.get("message")) is not str
            ):
                raise VoiceError("Invalid service response")
            return response
    except (OSError, ValueError, RecursionError) as exc:
        raise VoiceError("Voice service unavailable; run omarchy-voice serve") from exc
