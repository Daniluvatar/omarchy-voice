"""Interchangeable local STT contract; optional dependencies are lazy."""

from pathlib import Path
from typing import Protocol
import importlib.util
import multiprocessing
import threading
import time
from .core import VoiceError


class STTProvider(Protocol):
    def available(self) -> bool: ...
    def capabilities(self) -> dict: ...
    def transcribe(self, audio: Path, language: str | None) -> str: ...


class FasterWhisper:
    def __init__(self, config):
        self.config = config

    def available(self):
        return importlib.util.find_spec("faster_whisper") is not None

    def capabilities(self):
        return {
            "local": True,
            "offline": True,
            "languages": "multilingual",
            "audio": "file",
        }

    def transcribe(self, audio, language):
        if not self.available():
            raise VoiceError("Install the stt extra first")
        from faster_whisper import WhisperModel

        model = WhisperModel(
            self.config.model,
            device=self.config.device,
            compute_type=self.config.compute_type,
            local_files_only=True,
        )
        segments, _ = model.transcribe(
            str(audio), language=language, beam_size=1, vad_filter=True
        )
        text = " ".join(s.text.strip() for s in segments)
        if not text or len(text) > 512:
            raise VoiceError("No supported speech command detected")
        return text


def download_model(config):
    if not FasterWhisper(config).available():
        raise VoiceError("Install the stt extra first")
    from faster_whisper.utils import download_model as download

    try:
        return download(config.model, local_files_only=False)
    except Exception as exc:
        raise VoiceError("Model download failed") from exc


def _child(connection, config, audio, language):
    try:
        connection.send(("ok", FasterWhisper(config).transcribe(Path(audio), language)))
    except VoiceError as exc:
        # Curated, user-facing failure; never includes transcript text or paths.
        message = str(exc) or "Local transcription failed; check provider and downloaded model"
        connection.send(("error", message))
    except Exception as exc:
        # An unexpected provider/environment crash (e.g. the PyAV 19
        # `metadata_errors` regression). Record the full exception in the local
        # diagnostic log for support, but surface only a concise, path-free,
        # actionable message to the service/UI.
        from .log import write_log

        write_log(
            "ERROR",
            "transcription-crashed",
            provider=f"{type(exc).__module__}.{type(exc).__name__}",
            error=f"{type(exc).__name__}: {exc}",
        )
        connection.send(("error", "Local transcription failed; check provider and downloaded model"))
    finally:
        connection.close()


class IsolatedSTT:
    """Killable worker: no model imports or work survive cancellation."""

    def __init__(self, config):
        self.config = config
        self.process = None
        self.lock = threading.Lock()
        self.cancelled = False

    def cancel(self):
        with self.lock:
            self.cancelled = True
            p = self.process
            if p is not None:
                if p.is_alive():
                    p.terminate()
                p.join(1)
                if p.is_alive():
                    p.kill()
                    p.join(1)

    def transcribe(self, audio, language, cancel):
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        try:
            with self.lock:
                if self.cancelled or cancel.is_set():
                    raise VoiceError("Cancelled")
                self.process = ctx.Process(
                    target=_child,
                    args=(sender, self.config, str(audio), language),
                    daemon=True,
                )
                self.process.start()
            sender.close()
            deadline = time.monotonic() + self.config.timeout_seconds
            while time.monotonic() < deadline:
                if cancel.is_set():
                    raise VoiceError("Cancelled")
                if receiver.poll(0.05):
                    try:
                        kind, value = receiver.recv()
                    except EOFError:
                        raise VoiceError("Transcription worker exited")
                    if kind != "ok":
                        raise VoiceError(value)
                    return value
                if not self.process.is_alive():
                    raise VoiceError("Transcription worker exited")
            raise VoiceError("Transcription timed out")
        finally:
            self.cancel()
            receiver.close()
            sender.close()
