from omarchy_voice.log import write_log, log_path
from omarchy_voice.cli import main


def test_log_records_transcript(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    write_log("ERROR", "process-failed", text="open term", error="Application 'term' is unavailable or ambiguous")
    path = log_path()
    content = path.read_text()
    assert "open term" in content
    assert "unavailable" in content
    assert main(["logs"]) == 0
    output = capsys.readouterr().out
    assert str(path) in output
    assert "open term" in output
