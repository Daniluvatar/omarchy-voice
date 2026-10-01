"""PyAV/faster-whisper compatibility guard and worker diagnostics.

PyAV 19 removed the `metadata_errors` keyword that faster-whisper 1.x still
passes to `av.open()`; the `stt` extra must keep pinning `av<19`. An unexpected
provider crash is recorded to the local diagnostic log (so such regressions stay
diagnosable) while the service/UI only ever sees a concise, path-free, curated
message.
"""
import tomllib
from pathlib import Path

from omarchy_voice.config import Config
from omarchy_voice.core import VoiceError
from omarchy_voice.providers import FasterWhisper, _child

REPO = Path(__file__).resolve().parents[1]


class Connection:
    def __init__(self, sink):
        self.sink = sink

    def send(self, value):
        self.sink.append(value)

    def close(self):
        pass


def run_child(transcribe):
    sink = []
    original = FasterWhisper.transcribe
    FasterWhisper.transcribe = transcribe
    try:
        _child(Connection(sink), Config(), "does-not-matter.wav", "en")
    finally:
        FasterWhisper.transcribe = original
    return sink


def test_stt_extra_pins_av_below_19():
    extras = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    pins = [dep for dep in extras["stt"] if dep.startswith("av")]
    assert pins, f"stt extra lost its av pin: {extras['stt']}"
    assert any(pin.startswith("av<19") for pin in pins), (
        "stt extra must keep pinning av<19 until faster-whisper drops the "
        f"`metadata_errors` keyword PyAV 19 removed (got {extras['stt']})"
    )


def test_worker_preserves_curated_voice_errors():
    def transcribe(*args, **kwargs):
        raise VoiceError("Install the stt extra first")

    assert run_child(transcribe) == [("error", "Install the stt extra first")]


def test_worker_reports_environment_crashes(tmp_path, monkeypatch):
    def transcribe(*args, **kwargs):
        # Mirrors the PyAV 19 regression: open() metadata_errors removed.
        raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    sink = []
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    original = FasterWhisper.transcribe
    FasterWhisper.transcribe = transcribe
    try:
        _child(Connection(sink), Config(), "does-not-matter.wav", "en")
    finally:
        FasterWhisper.transcribe = original

    # The service/UI-visible payload must be the concise, path-free fallback,
    # never the raw exception text.
    assert sink == [("error", "Local transcription failed; check provider and downloaded model")]

    # The detailed exception must be captured in the local diagnostic log.
    log = (tmp_path / "omarchy-voice" / "voice.log").read_text(encoding="utf-8")
    assert "metadata_errors" in log
    assert "TypeError" in log
    assert "transcription-crashed" in log
