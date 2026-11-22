from mailagent.secret_scan import scan_text


def test_detects_password():
    hits = scan_text("my password is hunter2")
    assert any(h["type"] == "password" and h["value"] == "hunter2" for h in hits)


def test_detects_persian_password():
    hits = scan_text("رمز عبور 1234")
    assert any(h["value"] == "1234" for h in hits)


def test_detects_url_credentials():
    hits = scan_text("postgres://admin:secret@db.local/app")
    assert any(
        h["type"] == "url_credentials" and "admin:secret" in h["value"] for h in hits
    )


def test_detects_connection_string():
    hits = scan_text("Server=db;Password=P@ssw0rd;Database=x")
    assert any(h["value"] == "P@ssw0rd" for h in hits)


def test_detects_private_key():
    hits = scan_text("-----BEGIN RSA PRIVATE KEY-----")
    assert any(h["type"] == "private_key" for h in hits)


def test_ignores_placeholder():
    assert scan_text("password: password") == []


def test_empty_text():
    assert scan_text("") == []