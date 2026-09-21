"""Ordinary sentence punctuation from STT must not break MVP commands."""
import pytest
from omarchy_voice.core import parse, VoiceError


@pytest.mark.parametrize('text', ['Workspace two.', 'Mute!', 'Lock computer?', 'Open Brave.'])
def test_single_sentence_terminator(text):
    assert parse(text) == parse(text[:-1])


@pytest.mark.parametrize('text', ['mute; shutdown', 'lock computer. shutdown', 'workspace two..', 'mute\nshutdown', 'mute && reboot'])
def test_compound_commands_still_rejected(text):
    with pytest.raises(VoiceError):
        parse(text)
