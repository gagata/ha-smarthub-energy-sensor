"""Fixtures for SmartHub tests."""
from unittest.mock import patch, AsyncMock
from collections.abc import Generator

from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.smarthub.const import DOMAIN

import pytest

@pytest.fixture(autouse=True)
def base_recorder_fixture(recorder_mock, enable_custom_integrations):
    pass
