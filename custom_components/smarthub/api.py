"""SmartHub API client for Home Assistant integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List
from enum import Enum

import aiohttp
from aiohttp import ClientTimeout, ClientError
import pyotp

from .const import (
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    SESSION_TIMEOUT,
    ELECTRIC_SERVICE,
    SUPPORTED_SERVICES,
)

_LOGGER = logging.getLogger(__name__)

class Aggregation(Enum):
  HOURLY = "HOURLY"
  MONTHLY = "MONTHLY"


class SmartHubAPIError(Exception):
    """Base exception for SmartHub API errors."""


class SmartHubAuthError(SmartHubAPIError):
    """Authentication error."""


class SmartHubConnectionError(SmartHubAPIError):
    """Connection error."""


class SmartHubDataError(SmartHubAPIError):
    """Data parsing error."""

class SmartHubLocation():
    """Smarthub Location object - contains location_id, location_description, etc"""

    def __init__(
        self,
        id: str,
        service: str,
        description: str
    )  -> None:
        """Initialize the SmartHubLocation."""
        self.id = id
        self.service = service
        self.description = description

    def __str__(self):
        return f"[SmartHubLocation: '{self.id}' '{self.service}' '{self.description}']"

class SmartHubAPI:
    """Class to interact with the SmartHub API."""

    def __init__(
        self,
        email: str,
        password: str,
        account_id: str,
        timezone: str,
        mfa_totp: str,
        host: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the SmartHub API client."""
        self.email = email
        self.password = password
        self.account_id = account_id
        self.timezone = timezone
        self.mfa_totp = mfa_totp
        self.host = host
        self.timeout = timeout
        self.token: Optional[str] = None
        self.primary_username: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_created_at: Optional[datetime] = None


    def parse_usage(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse the JSON data and extract the last data point for usage.

        Args:
            data: The JSON data as a Python dictionary.

        Returns:
            A dictionary containing the "USAGE" with a list of parsed data and metadata, or an empty dictionary if not found.

        Raises:
            SmartHubDataError: If there's an error parsing the data.
        """
        try:
            parsed_response = {}

            if not isinstance(data, dict):
                raise SmartHubDataError("Invalid data format: expected dictionary")

            # Locate the "ELECTRIC" data
            electric_data = data.get("data", {}).get("ELECTRIC", [])
            if len(electric_data) == 0:
              _LOGGER.warning("No ELECTRIC data found in response")

            for entry in electric_data:
                # Find the entry with type "USAGE"
                if entry.get("type","") == "USAGE":
                    parsed_data = []
                    series = entry.get("series", [])
                    for serie in series:
                        # Extract the last data point in the "data" array
                        usage_data = serie.get("data", [])

                        for usage in usage_data:
                            event_time = datetime.fromtimestamp(usage.get("x") / 1000.0, tz=timezone.utc).replace(tzinfo=ZoneInfo(self.timezone)) # convert microseconds to timestmap -> read data as if it was in provider TZ, then conver to UTC for statistics
                            # HA stats import wants timestamps only at standard intervals -
                            # https://github.com/home-assistant/core/blob/4fef19c7bc7c1f7be827f6c489ad1df232e44906/homeassistant/components/recorder/statistics.py#L2634
                            if event_time.minute != 0:
                              _LOGGER.debug("consolidating sub hour data: %s, %s + %s", event_time, parsed_data[-1]['consumption'], usage.get("y"))
                              parsed_data[-1]['consumption'] += usage.get("y")
                              continue

                            # Ignore events with no energy recording
                            if usage.get("y") == 0:
                              continue

                            parsed_data.append({
                              "reading_time" : event_time,
                              "consumption" : usage.get("y"),
                              "raw_timestamp": usage.get("x"),
                            })
                    _LOGGER.debug("Parsed %d items for usage history", len(parsed_data))
                    parsed_response["USAGE"] = parsed_data

            return parsed_response

        except Exception as e:
            raise SmartHubDataError(f"Error parsing usage data: {e}") from e


    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        now = datetime.now()

        # Check if session needs refresh due to age
        if (self._session_created_at and
            (now - self._session_created_at).total_seconds() > SESSION_TIMEOUT):
            _LOGGER.debug("Session timeout reached, refreshing session")
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
            self._session_created_at = None

        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(ssl=True, limit=10),
            )
            self._session_created_at = now
            _LOGGER.debug("Created new aiohttp session")
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _refresh_authentication(self) -> None:
        """
        Refresh authentication by clearing session and getting new token.

        This method ensures we start with a clean session state when
        authentication issues occur.
        """
        _LOGGER.debug("Refreshing authentication and session")

        # Close existing session to clear any stale state
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._session_created_at = None

        # Clear the old token
        self.token = None

        # Get a fresh token with a new session
        await self.get_token()

    async def get_token(self) -> str:
        """
        Authenticate and retrieve the token asynchronously.

        Returns:
            The authentication token.

        Raises:
            SmartHubAuthError: If authentication fails.
            SmartHubConnectionError: If there's a connection error.
        """
        auth_url = f"https://{self.host}/services/oauth/auth/v2"
        headers = {
            "Authority": self.host,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "HomeAssistant SmartHub Integration",
        }

        payload = {
          "password": self.password,
          "userId": self.email,
        }

        if self.mfa_totp != "":
          totp = pyotp.TOTP(self.mfa_totp)
          current_otp = totp.now()
          payload["twoFactorCode"] = current_otp

        _LOGGER.debug("Sending authentication request to: %s", auth_url)

        try:
            session = await self._get_session()
            async with session.post(auth_url, headers=headers, params=payload) as response:
                _ = await response.text()
                _LOGGER.debug("Auth response status: %s", response.status)

                if response.status == 401:
                    raise SmartHubAuthError("Invalid credentials")
                elif response.status != 200:
                    raise SmartHubConnectionError(
                        f"Authentication failed with HTTP status: {response.status}"
                    )

                try:
                    response_json = await response.json()
                except Exception as e:
                    raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                self.token = response_json.get("authorizationToken")
                self.primary_username = response_json.get("primaryUsername", self.email)

                if not self.token:
                    raise SmartHubAuthError("No authorization token in response")

                _LOGGER.debug("Successfully retrieved authentication token")
                return self.token

        except ClientError as e:
            raise SmartHubConnectionError(f"Connection error during authentication: {e}") from e

    async def get_service_locations(self) -> List[SmartHubLocation]:
        """
        Retrieve details about the service locaitons

        Returns:
            List of SmartHubLocation

        Raises:
            SmartHubAPIError: If the request fails after retries.
        """
        user_data_url = f"https://{self.host}/services/secured/user-data"
        payload = {
          "userId" : self.primary_username,
        }

        if not self.token:
            await self._refresh_authentication()

        headers = {
            "Authority": self.host,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Nisc-Smarthub-Username": self.email,
            "User-Agent": "HomeAssistant SmartHub Integration",
        }

        try:
            session = await self._get_session()
            async with session.get(user_data_url, headers=headers, params=payload) as response:
                _ = await response.text()
                _LOGGER.debug("User Data response status: %s", response.status)

                if response.status == 401:
                    raise SmartHubAuthError("Invalid credentials")
                elif response.status != 200:
                    raise SmartHubConnectionError(
                        f"User_data request failed with HTTP status: {response.status}"
                    )

                try:
                    response_json = await response.json()
                except Exception as e:
                    raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                # Response format is structured as a list of dictionaries -
                # each dictionary has the following keys
                #   "account",
                #   "additionalCustomerName",
                #   "address",
                #   "agreementStatus",
                #   "consumerClassCode",
                #   "customer",
                #   "customerName",
                #   "disconnectNonPay",
                #   "email",
                #   "inactive",
                #   "invoiceGroupNumber",
                #   "isAutoPay",
                #   "isDisconnected",
                #   "isMultiService",
                #   "isPendingDisconnect",
                #   "isUnCollectible",
                #   "primaryServiceLocationId",
                #   "providerOrServiceDescription",
                #   "providerToDescription",
                #   "providerToProviderDescription",
                #   "serviceLocationIdToServiceLocationSummary",
                #   "serviceLocationToIndustries",
                #   "serviceLocationToProviders",
                #   "serviceLocationToUserDataServiceLocationSummaries",
                #   "serviceToProviders",
                #   "serviceToServiceDescription",
                #   "services"
                # `serviceLocationToUserDataServiceLocationSummaries` Includes human readable information about the service location.
                # Which is a map of the location_id, to a list of
                  #  "activeRateSchedules",
                  #  "address",
                  #  "description",
                  #  "id",
                  #  "lastBillPresReadDtTm",
                  #  "lastBillPrevReadDtTm",
                  #  "location",
                  #  "serviceStatus",
                  #  "services"

                locations = []
                _LOGGER.debug(response_json)

                for entry in response_json:
                  for location_id, service_descriptions in entry.get("serviceLocationToUserDataServiceLocationSummaries", {}).items():
                    for service_description in service_descriptions:
                      # for now only support electric service type
                      if any(service in SUPPORTED_SERVICES for service in service_description.get("services",[])):
                        locations.append(
                          SmartHubLocation(
                            id=location_id,
                            service=ELECTRIC_SERVICE,
                            description=service_description.get("description", "unknown"),
                          )
                        )

                return locations

        except ClientError as e:
            raise SmartHubConnectionError(f"Connection error during User_data request: {e}") from e

    async def get_energy_data(self, location, start_datetime=None, aggregation:Aggregation=Aggregation.HOURLY) -> Optional[Dict[str, Any]]:
        """
        Retrieve energy usage data asynchronously with retry logic.

        Returns:
            Parsed energy usage data or None if no data available.

        Raises:
            SmartHubAPIError: If the request fails after retries.
        """
        poll_url = f"https://{self.host}/services/secured/utility-usage/poll"

        # Calculate startDateTime and endDateTime
        now = datetime.now()
        # Get data since specified start (or last 30 days) as of midnight yesterday
        end_datetime = now.replace(minute=0, second=0, microsecond=0)
        if start_datetime is None:
          # fetch data from last period
          start_datetime = end_datetime - timedelta(days=30)

        start_timestamp = int(start_datetime.timestamp()) * 1000
        end_timestamp = int(end_datetime.timestamp()) * 1000

        data = {
            "timeFrame": aggregation.value,
            "userId": self.email,
            "screen": "USAGE_EXPLORER",
            "includeDemand": False,
            "serviceLocationNumber": location.id,
            "accountNumber": self.account_id,
            "industries": ["ELECTRIC"],
            "startDateTime": str(start_timestamp),
            "endDateTime": str(end_timestamp),
        }

        _LOGGER.debug("Requesting energy data from: %s", poll_url)

        # Track if we've already tried refreshing the token
        token_refreshed = False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # If token is unset - refresh auth
                if not self.token:
                    await self._refresh_authentication()
                    token_refreshed = True

                headers = {
                    "Authority": self.host,
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "X-Nisc-Smarthub-Username": self.email,
                    "User-Agent": "HomeAssistant SmartHub Integration",
                }

                session = await self._get_session()
                async with session.post(poll_url, headers=headers, json=data) as response:
                    _LOGGER.debug("Attempt %d: Response status: %s", attempt, response.status)

                    if response.status == 401:
                        if not token_refreshed:
                            # Token expired, refresh and retry
                            _LOGGER.info("Token expired, refreshing authentication...")
                            await self._refresh_authentication()
                            token_refreshed = True
                            continue
                        else:
                            # Already tried refreshing, this is a persistent auth issue
                            raise SmartHubAuthError("Authentication failed after token refresh")
                    elif response.status != 200:
                        error_text = await response.text()
                        _LOGGER.warning("HTTP error %d: %s", response.status, error_text)
                        raise SmartHubConnectionError(
                            f"HTTP error {response.status}: {error_text}"
                        )

                    try:
                        response_json = await response.json()
                    except Exception as e:
                        raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                    # Check if the status is still pending
                    status = response_json.get("status")
                    if status == "PENDING":
                        _LOGGER.debug("Attempt %d: Status is PENDING, retrying...", attempt)
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            _LOGGER.warning("Maximum retries reached, data still PENDING")
                            return None
                    elif status == "COMPLETE":
                        _LOGGER.debug("Successfully retrieved energy data")
                        return self.parse_usage(response_json)
                    else:
                        _LOGGER.warning("Unexpected status in response: %s", status)
                        return None

            except SmartHubAuthError:
                # Re-raise auth errors immediately
                raise
            except ClientError as e:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Attempt %d failed with connection error: %s, retrying...",
                        attempt, e
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                else:
                    raise SmartHubConnectionError(
                        f"Connection failed after {MAX_RETRIES} attempts: {e}"
                    ) from e

        raise SmartHubAPIError(f"Failed to retrieve data after {MAX_RETRIES} attempts")

