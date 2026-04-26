"""Tests for settings hot-reload and settings panel."""
import pytest
from unittest.mock import patch


def test_registry_reload_registers_new_key():
    """After mutating settings and calling reload, new provider appears."""
    from app.llm.provider_registry import ProviderRegistry

    registry = ProviderRegistry()
    # Start with no keys
    assert registry.list_available() == []

    # Simulate user entering a key -- patch the settings object
    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-ant-test-key"
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" in registry.list_available()


def test_registry_reload_removes_invalid_key():
    """After key is cleared, provider is deregistered."""
    from app.llm.provider_registry import ProviderRegistry

    registry = ProviderRegistry()

    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-ant-test-key"
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" in registry.list_available()

    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" not in registry.list_available()


def test_settings_panel_validates_key_before_writing(tmp_path, monkeypatch):
    """settings panel does not write .env when validation fails."""
    from app.tui.settings_panel import SettingsPanel

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\n")

    from app.llm.provider_registry import ProviderRegistry
    from unittest.mock import MagicMock
    registry = ProviderRegistry()

    panel = SettingsPanel(registry=registry, env_path=str(env_file))

    # Simulate _validate_key returning False (invalid key)
    monkeypatch.setattr(panel, "_validate_key", lambda name, val: False)
    result = panel._save_key("ANTHROPIC_API_KEY", "invalid-key")

    assert result is False
    content = env_file.read_text()
    assert "invalid-key" not in content


def test_settings_panel_writes_valid_key(tmp_path, monkeypatch):
    """settings panel writes .env and returns True when key validates."""
    from app.tui.settings_panel import SettingsPanel
    from app.llm.provider_registry import ProviderRegistry

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\n")

    registry = ProviderRegistry()
    panel = SettingsPanel(registry=registry, env_path=str(env_file))

    monkeypatch.setattr(panel, "_validate_key", lambda name, val: True)
    result = panel._save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")

    assert result is True
    assert "sk-ant-abc123" in env_file.read_text()
