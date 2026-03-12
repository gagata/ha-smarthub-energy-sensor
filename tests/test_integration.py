"""Test file for basic SmartHub integration functionality."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthub import async_setup_entry
from custom_components.smarthub.api import SmartHubAPI, SmartHubAPIError, SmartHubLocation
from custom_components.smarthub.const import DOMAIN, ELECTRIC_SERVICE


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="SmartHub Test",
        data={
            "email": "test@example.com",
            "password": "testpass",
            "account_id": "123456",
            "location_id": "789012",
            "host": "test.smarthub.coop",
            "poll_interval": 60,
            "timezone": "UTC",
            "mfa_totp": "",
        },
        unique_id="test@example.com_test.smarthub.coop_123456",
    )


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.data = {}
    return hass

@pytest.fixture
def api_instance():
    """Create an API instance for testing."""
    return SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

def test_parse_usage_valid_data(api_instance):
    """Test parsing valid usage data."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "meters": [
                             {'meterNumber': '1ND81111111', 'seriesId': '1ND81111111', 'flowDirection': 'NET', 'isNetMeter': True}, # Non net meters have Forward flow as default
                            ],
                            "data": [
                                {"x": 1640995200000, "y": 100.5},
                                {"x": 1641081600000, "y": 150.2},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    result = api_instance.parse_usage(test_data)

    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 2
    assert result["USAGE"][1]["consumption"] == 150.2

def test_parse_usage_offset_hourly(api_instance):
    """Test parsing valid usage data."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "meters": [
                             {'meterNumber': '1ND81111111', 'seriesId': '1ND81111111', 'flowDirection': 'FORWARD', 'isNetMeter': False}, # Non net meters have Forward flow as default
                            ],
                            "data": [
                                {"x": 1762215300000, "y":   1.1},
                                {"x": 1762216200000, "y":  10.2},
                                {"x": 1762217100000, "y": 100.3},
                                {"x": 1762218900000, "y": 1.1},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    result = api_instance.parse_usage(test_data)

    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 2
    assert result["USAGE"][0]["consumption"] == 111.6
    assert result["USAGE"][1]["consumption"] == 1.1
    assert result["USAGE"][1]["raw_timestamp"] == 1762218000000 # not 1762218900000, because thats :15 min after the hour

def test_parse_usage_offset_start(api_instance):
    """Test parsing valid usage data."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "meters": [
                             {'meterNumber': '1ND81111111', 'seriesId': '1ND81111111', 'flowDirection': 'NET', 'isNetMeter': True}, # Non net meters have Forward flow as default
                            ],
                            "data": [
                                {"x": 1762215300000, "y":   1.1},
                                {"x": 1762216200000, "y":  10.2},
                                {"x": 1762217100000, "y": 100.3},
                                {"x": 1762218000000, "y": 1.1},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    result = api_instance.parse_usage(test_data)

    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 2
    assert result["USAGE"][0]["consumption"] == 111.6
    assert result["USAGE"][1]["consumption"] == 1.1
    assert result["USAGE"][1]["raw_timestamp"] == 1762218000000

def test_parse_usage_fifteen_min(api_instance):
    """Test parsing valid usage data."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "meters": [
                             {'meterNumber': '1ND81111111', 'seriesId': '1ND81111111', 'flowDirection': 'NET', 'isNetMeter': True}, # Non net meters have Forward flow as default
                            ],
                            "data": [
                                {"x": 1762218000000, "y":    1.1},
                                {"x": 1762218900000, "y":   10.2},
                                {"x": 1762219800000, "y":  100.3},
                                {"x": 1762220700000, "y": 1000.4},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    result = api_instance.parse_usage(test_data)

    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 1
    assert result["USAGE"][0]["consumption"] == 1112.0
    assert result["USAGE"][0]["raw_timestamp"] == 1762218000000

def test_parse_usage_no_data(api_instance):
    """Test parsing when no usage data is available."""
    test_data = {"data": {"ELECTRIC": []}}

    result = api_instance.parse_usage(test_data)

    # parse_usage returns {} if no usage found (or rather, the dict might be empty of USAGE key)
    # Looking at code: parsed_response = {}, if len(electric_data) == 0 log warning.
    # Returns parsed_response. So it returns {}.
    assert result == {}

def test_parse_locations(api_instance):
    """Test parsing location description."""
    test_data = [
      {
        'customer': 'XXXXXXXX', 'customerName': 'CUSTOMER_NAME', 'additionalCustomerName': 'ADDITIONAL_CUSTOMER_NAME', 'account': 'ACCOUNT', 'address': 'ADDRESS, CITY, STATE ZIP_CODE', 'email': 'USER_ID', 'inactive': False, 'primaryServiceLocationId': 'LOCATION_ID',
        'serviceLocationIdToServiceLocationSummary': {
        'LOCATION_ID': {
           'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'meterNumbersToExternalMeterBaseIds': {'350017381': 'LOCATION_ID+1'},
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        },
       'serviceLocationToUserDataServiceLocationSummaries': {
         'LOCATION_ID': [
           {'services': ['ELEC'], 'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        ]},
        'serviceLocationToIndustries': {'LOCATION_ID': ['ELECTRIC']},
        'providerToDescription': {'NOVEC': 'NOVEC Electric Service'}, 'providerToProviderDescription': {'NOVEC': 'NOVEC Electric Service'}, 'serviceToServiceDescription': {'ELEC': 'Electric Service'},
        'serviceToProviders': {'ELEC': ['NOVEC']}, 'serviceLocationToProviders': {"LOCATION_ID": ['NOVEC']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'NOVEC Electric Service', 'services': ['ELEC']
      },
      {
        'customer': 'XXXXXX1', 'customerName': 'CUSTOMER2', 'additionalCustomerName': 'CUSTOMER2 DISPLAY NAME', 'account': 'ACCOUNT1', 'address': 'ADDRESS, CITY, STATE ZIP_CODE', 'email': 'USER_ID', 'inactive': False, 'primaryServiceLocationId': 'LOCATION_ID2',
        'serviceLocationIdToServiceLocationSummary': {
          'LOCATION_ID2': {
            'id': {'srvLocNbr': 'LOCATION_ID2', 'serviceLocation': 'LOCATION_ID2'},
            'location': 'LOCATION_ID2b',
            'description': 'NICKNAME',
            'address': {'addr1': 'XXXXXX', 'city': 'YYYY', 'state': 'ZZZZ', 'zip': 'RRRRR', 'description': 'NICKNAME'},
            'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765688400000, 'lastBillPresReadDtTm': 1768366800000,
            'meterNumbersToExternalMeterBaseIds': {'LOCATION_ID2?': 'LOCATION_ID2+1'}, 'activeRateSchedules': ['RES01:1ELEC']}},
            'serviceLocationToUserDataServiceLocationSummaries': {
              'LOCATION_ID2': [
                {'services': ['ELEC'], 'id': {'srvLocNbr': 'LOCATION_ID2', 'serviceLocation': 'LOCATION_ID2'}, 'location': 'LOCATION_ID2b', 'description': 'NICKNAME',
                 'address': {'addr1': 'XXXXXX', 'city': 'YYYY', 'state': 'ZZZZ', 'zip': 'RRRRR', 'description': 'NICKNAME'}, 'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765688400000, 'lastBillPresReadDtTm': 1768366800000, 'activeRateSchedules': ['RES01:1ELEC']}]},
            'serviceLocationToIndustries': {'LOCATION_ID2': ['ELECTRIC']},
            'providerToDescription': {'1ELEC': 'Electric Service'}, 'providerToProviderDescription': {'1ELEC': 'Electric Service'}, 'serviceToServiceDescription': {'ELEC': 'Electric Service'}, 'serviceToProviders': {'ELEC': ['1ELEC']}, 'serviceLocationToProviders': {'LOCATION_ID2': ['1ELEC']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'Electric Service', 'services': ['ELEC']}
    ]

    result = api_instance.parse_locations(test_data)
    expected_locations = [
      SmartHubLocation(
        id="LOCATION_ID",
        service=ELECTRIC_SERVICE,
        description="",
        provider="NOVEC Electric Service",
      ),
      SmartHubLocation(
        id="LOCATION_ID2",
        service=ELECTRIC_SERVICE,
        description="NICKNAME",
        provider="Electric Service",
      ),
    ]

    assert len(result) == len(expected_locations)
    for a,b in zip(result, expected_locations):
      compare_SmartHubLocation(a,b)

def test_parse_usage_no_usage(api_instance):
    """Test parsing when no usage data is available."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "meters": [],
                            "data": []
                        }
                    ]
                }
            ]
        }
    }

    result = api_instance.parse_usage(test_data)

    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 0


def test_parse_usage_invalid_data(api_instance):
    """Test parsing invalid data raises appropriate error."""
    # The api.py raises SmartHubDataError if not dict.
    from custom_components.smarthub.api import SmartHubDataError
    with pytest.raises(SmartHubDataError):
        api_instance.parse_usage("invalid_data")


@pytest.mark.asyncio
async def test_async_setup_entry_success(mock_hass, mock_config_entry):
    """Test successful setup of config entry."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token = AsyncMock(return_value="test_token")
        mock_api.close = AsyncMock()
        mock_api_class.return_value = mock_api

        with patch("custom_components.smarthub.SmartHubDataUpdateCoordinator") as mock_coordinator_cls:
             mock_coordinator = mock_coordinator_cls.return_value
             mock_coordinator.async_config_entry_first_refresh = AsyncMock()

             # Configure mock_hass to support await
             mock_hass.config_entries.async_forward_entry_setups = AsyncMock()

             result = await async_setup_entry(mock_hass, mock_config_entry)

             assert result is True
             # In the new code, runtime_data is set on entry
             assert hasattr(mock_config_entry, "runtime_data")


@pytest.mark.asyncio
async def test_async_setup_entry_connection_failure(mock_hass, mock_config_entry):
    """Test setup failure due to connection error."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token = AsyncMock(side_effect=Exception("Connection failed"))
        mock_api.close = AsyncMock()
        mock_api_class.return_value = mock_api

        from homeassistant.exceptions import ConfigEntryError
        with pytest.raises(ConfigEntryError):
            await async_setup_entry(mock_hass, mock_config_entry)


def test_smarthub_api_basic_functionality():
    """Test basic SmartHub API functionality."""
    api = SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="123456",
        host="test.smarthub.coop"
    )

    # Test that API object is created correctly
    assert api.email == "test@example.com"
    assert api.account_id == "123456"
    assert api.timezone == "UTC"
    assert api.mfa_totp == "123456"
    assert api.host == "test.smarthub.coop"
    assert api.token is None

def compare_SmartHubLocation(a: SmartHubLocation, b: SmartHubLocation):
    """comprae two SmartHubLocation objects."""
    # Test that API object is created correctly
    assert a.id == b.id
    assert a.service == b.service
    assert a.description == b.description
    assert a.provider == b.provider
