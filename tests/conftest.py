"""Fixtures for SmartHub tests."""
from unittest.mock import patch
import pytest

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for testing."""
    yield

@pytest.fixture(autouse=True)
def mock_recorder(hass):
    """Mock the recorder component to avoid setup failures in tests."""
    with patch("homeassistant.components.recorder.async_setup", return_value=True):
        hass.data["recorder"] = True
        yield