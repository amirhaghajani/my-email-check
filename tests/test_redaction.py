from mailagent.output import redact


def test_redact_masks_english_secret():
    out = redact("my password is hunter2")
    assert "hunter2" not in out
    assert "***" in out


def test_redact_show_secrets_passthrough():
    text = "password hunter2"
    assert redact(text, show_secrets=True) == text


def test_redact_masks_persian_secret():
    out = redact("رمز عبور 1234")
    assert "1234" not in out
    assert "***" in out


def test_redact_key_value_token():
    out = redact("api_key=abcdef123456")
    assert "abcdef123456" not in out