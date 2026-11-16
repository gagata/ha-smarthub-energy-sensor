import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from custom_components.smarthub.api import SmartHubAPI

@pytest.mark.parametrize("password", [
    "simplepassword",
    "password with spaces",
    "password#with#hashes",
    "password&with&ampersands",
    "password?with?questions",
    "password%with%percents",
    "password+with+plus",
    "complex!@#$%^&*()_+-=[]{}|;':\",./<>?password"
])
@pytest.mark.asyncio
async def test_get_token_encoding(password):
    """Test get_token correctly handles and encodes various passwords."""
    email = "test+user@example.com"
    
    api = SmartHubAPI(
        email=email,
        password=password,
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"authorizationToken": "fake_token"}')
    mock_response.json = AsyncMock(return_value={"authorizationToken": "fake_token"})

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    # Ensure the context manager works for 'async with session.post(...)'
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.post.return_value.__aexit__ = AsyncMock()

    with patch.object(SmartHubAPI, "_get_session", return_value=mock_session):
        token = await api.get_token()
        
        assert token == "fake_token"
        
        # Check the arguments to post
        args, kwargs = mock_session.post.call_args
        
        # We must use 'data' for form-encoded POST body, not 'params' for URL
        assert "data" in kwargs, "Credentials should be sent in the request body (data), not URL parameters"
        assert "params" not in kwargs or not kwargs["params"], "Credentials should not be sent as URL parameters"
        
        sent_payload = kwargs.get("data")
        assert sent_payload["password"] == password
        assert sent_payload["userId"] == email


def test_parse_usage_prefers_registers_over_net_series():
    """FORWARD + REVERSE registers win over splitting a (gappy) NET series by sign."""
    api = SmartHubAPI(email="test@example.com", password="p", account_id="1", timezone="UTC", mfa_totp="",
                      host="test.smarthub.coop")
    # Two 15-minute intervals in one hour: imports and exports happen in the same hour.
    xs = [1762218000000, 1762218900000]
    data = {"data": {"ELECTRIC": [{
        "type": "USAGE",
        "meters": [
            {"meterNumber": "1", "seriesId": "1 - Consumption", "flowDirection": "FORWARD", "isNetMeter": True},
            {"meterNumber": "1", "seriesId": "1 - Generation", "flowDirection": "REVERSE", "isNetMeter": True},
            {"meterNumber": "1", "seriesId": "1 - Net", "flowDirection": "NET", "isNetMeter": True},
        ],
        "series": [
            {"name": "1 - Consumption", "data": [{"x": xs[0], "y": 0.5}, {"x": xs[1], "y": 0.1}]},
            {"name": "1 - Generation", "data": [{"x": xs[0], "y": -0.2}, {"x": xs[1], "y": -0.4}]},
            # NET is missing the second interval, as real utilities sometimes do
            {"name": "1 - Net", "data": [{"x": xs[0], "y": 0.3}]},
        ],
    }]}}
    parsed = api.parse_usage(data)
    assert parsed["meter_name"] == "1 - Consumption"
    assert [round(r["consumption"], 3) for r in parsed["USAGE"]] == [0.6]
    assert [round(r["consumption"], 3) for r in parsed["USAGE_RETURN"]] == [0.6]


def test_parse_usage_net_only_still_splits_by_sign():
    """Without a return register the NET series is still used for both directions."""
    api = SmartHubAPI(email="test@example.com", password="p", account_id="1", timezone="UTC", mfa_totp="",
                      host="test.smarthub.coop")
    data = {"data": {"ELECTRIC": [{
        "type": "USAGE",
        "meters": [{"meterNumber": "1", "seriesId": "1 - Net", "flowDirection": "NET", "isNetMeter": True}],
        "series": [{"name": "1 - Net", "data": [{"x": 1762218000000, "y": 0.3}, {"x": 1762221600000, "y": -0.2}]}],
    }]}}
    parsed = api.parse_usage(data)
    assert [r["consumption"] for r in parsed["USAGE"]] == [0.3, 0]
    assert [r["consumption"] for r in parsed["USAGE_RETURN"]] == [0, 0.2]
