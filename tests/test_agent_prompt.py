from mailagent.agent import _system_prompt


def test_system_prompt_includes_today():
    prompt = _system_prompt()
    assert "Today's date is" in prompt
    assert "relative dates" in prompt


def test_system_prompt_forbids_hallucination():
    prompt = _system_prompt()
    assert "count: 0" in prompt
    assert "Do not generate example emails" in prompt
    assert "If you cannot cite an item_id" in prompt