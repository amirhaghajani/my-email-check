from mailagent.config import Settings


def test_dotenv_loaded_when_given_explicit_path(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXCHANGE_SERVER=dotenv.local\n", encoding="utf-8")
    settings = Settings(_env_file=str(env))
    assert settings.exchange_server == "dotenv.local"


def test_credentials_are_not_settings_fields():
    # Credentials are prompted at runtime, never stored in Settings.
    assert "exchange_username" not in Settings.model_fields
    assert "exchange_password" not in Settings.model_fields