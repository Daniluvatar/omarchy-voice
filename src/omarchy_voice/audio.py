"""Independent PipeWire capture into a private, ephemeral WAV."""

from pathlib import Path
import os
import signal
import subprocess
import tempfile
from .core import VoiceError


class PipeWireRecorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = None
        self.process = None

    def start(self):
        fd, name = tempfile.mkstemp(
            prefix="capture-", suffix=".wav", dir=self.directory
        )
        os.close(fd)
        self.path = Path(name)
        try:
            self.process = subprocess.Popen(
                [
                    "pw-record",
                    "--rate",
                    "16000",
                    "--channels",
                    "1",
                    "--format",
                    "s16",
                    str(self.path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.cleanup()
            raise VoiceError("PipeWire recorder unavailable") from exc

    def _finish(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)

    def stop(self):
        self._finish()
        if self.path is None or self.path.stat().st_size <= 44:
            raise VoiceError("No audio captured")
        return self.path

    def cleanup(self):
        self._finish()
        if self.path is not None:
            self.path.unlink(missing_ok=True)
