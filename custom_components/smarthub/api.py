"""SmartHub API client for Home Assistant integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List
from enum import StrEnum

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
    METER_NAME,
)
from .exceptions import (
    SmartHubAuthenticationError,
    SmartHubConnectionError,
    SmartHubDataError,
    SmartHubError as SmartHubAPIError,
)
from .utils import sanitize_host, parse_epoch_set_timezone

_LOGGER = logging.getLogger(__name__)

class ParseType(StrEnum):
    FORWARD = "FORWARD"
    NET = "NET"
    RETURN = "RETURN"

class Aggregation(StrEnum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"

    @property
    def label(self) -> str:
        """Return human readable label."""
        if self == Aggregation.HOURLY:
            return "Hourly"
        if self == Aggregation.DAILY:
            return "Daily"
        if self == Aggregation.MONTHLY:
            return "Monthly"
        return "Unknown"

    @property
    def suffix(self) -> str:
        """Return statistic ID suffix."""
        if self == Aggregation.HOURLY:
            return ""
        if self == Aggregation.DAILY:
            return "_daily"
        if self == Aggregation.MONTHLY:
            return "_monthly"
        return "_unknown"

    @property
    def period(self) -> str:
        """Return statistic period."""
        if self == Aggregation.HOURLY:
            return "hour"
        if self == Aggregation.DAILY:
            return "day"
        if self == Aggregation.MONTHLY:
            return "month"
        return "unknown"

class SmartHubLocation():
    """Smarthub Location object - contains location_id, location_description, etc"""

    def __init__(
        self,
        id: str,
        service: str,
        description: str,
        provider: str,
    )  -> None:
        """Initialize the SmartHubLocation."""
        self.id = id
        self.service = service
        self.description = description
        self.provider = provider

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
        self.host = sanitize_host(host)
        self.timeout = timeout
        self.token: Optional[str] = None
        self.primary_username: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_created_at: Optional[datetime] = None

    def parse_usage_series(self, usage_data: List[Dict], parseType: ParseType = ParseType.FORWARD) -> List[Dict]:
        parsed_data = []
        _LOGGER.debug(f"First 10 entries of usage data: {usage_data[:10]}")
        for usage in usage_data:
            # convert microseconds to timestmap -> read data as if it was in provider TZ
            event_time = parse_epoch_set_timezone(usage.get("x") / 1000.0, ZoneInfo(self.timezone))
            # HA stats import wants timestamps only at standard intervals -
            # https://github.com/home-assistant/core/blob/4fef19c7bc7c1f7be827f6c489ad1df232e44906/homeassistant/components/recorder/statistics.py#L2634
             # If the first entry isn't aligned with the top of the hour - treat it as if it was
            if event_time.minute != 0 and len(parsed_data) == 0:
              _LOGGER.warning("Initial usage data is not aligned with top of the hour, inserting a 0 entry at 0 minutes: event_time:%s, %s", event_time, usage.get("x"))
              zero_time = event_time.replace(minute=0)
              parsed_data.append({
                "reading_time" : zero_time,
                "consumption" : 0,
                "raw_timestamp": int(zero_time.replace(tzinfo=timezone.utc).timestamp()*1000), # convert zero_time to UTC, and multiply by 1000
              })

            # If the previous parsed time is in a different hour, and we still don't have a 00 minute - insert a 0 entry
            if len(parsed_data) > 0 and parsed_data[-1]["reading_time"].hour != event_time.hour and event_time.minute != 0:
              _LOGGER.warning("Usage data is not aligned with top of the hour, inserting a 0 entry at 0 minutes: event_time:%s, %s", event_time, usage.get("x"))
              zero_time = event_time.replace(minute=0)
              parsed_data.append({
                "reading_time" : zero_time,
                "consumption" : 0,
                "raw_timestamp": int(zero_time.replace(tzinfo=timezone.utc).timestamp()*1000), # convert zero_time to UTC, and multiply by 1000
              })

            # When doing a normal energy monitoring - never report negative numbers
            # When doing a NET usage, only report negative numbers, but invert them to be positive
            usage_energy = usage.get("y")
            if parseType == ParseType.NET:
              if usage_energy > 0:
                usage_energy = 0
              else:
                usage_energy = abs(usage_energy)
            else: # both FORWARD and RETURN use postive values
              usage_energy = max(0,usage_energy)


            if event_time.minute != 0:
              _LOGGER.debug("consolidating sub hour data: %s, %s + %s", event_time, parsed_data[-1]['consumption'], usage.get("y"))
              parsed_data[-1]['consumption'] += usage_energy
              continue

            # Ignore events with no energy recording
            if usage_energy == 0:
              continue

            parsed_data.append({
              "reading_time" : event_time,
              "consumption" : usage_energy,
              "raw_timestamp": usage.get("x"),
            })

        return parsed_data

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
              _LOGGER.debug(data)

            for entry in electric_data:
                # Find the entry with type "USAGE"
                if entry.get("type","") == "USAGE":
                    _LOGGER.debug("Usage: %s", entry)

                    meters = entry.get("meters", [])
                    forward_series = ""
                    net_series = ""
                    return_series = ""
                    if len(meters) > 2:
                      _LOGGER.warning("More then 2 meters in usage data: %s", meters)
                    for meter in meters:
                      # assume forward is default if not present
                      flow_direction = meter.get("flowDirection", ParseType.FORWARD)
                      match flow_direction:
                        case ParseType.FORWARD:
                          forward_series = meter["seriesId"]
                        case ParseType.NET:
                          net_series = meter["seriesId"]
                        case ParseType.RETURN:
                          return_series = meter["seriesId"]
                        case _:
                          _LOGGER.warning("Unknown flow direction in meter: %s", meter)

                    series = entry.get("series", [])
                    for serie in series:
                        if serie.get("name", "") == return_series:
                            usage_data = serie.get("data", [])
                            parsed_response["USAGE_RETURN"] = self.parse_usage_series(usage_data, ParseType.RETURN)
                            _LOGGER.debug("Parsed %d items for USAGE_RETURN history", len(parsed_response["USAGE_RETURN"]))

                        # If there is a NetMeter, use that for both Return and Usage (as it combines both).
                        # NOTE - there must always be a FORWARD or NET meter - or the "USAGE" is not being returned.
                        if serie.get("name", "") == (net_series if net_series != "" else forward_series):
                            parsed_response[METER_NAME] = serie.get("name")

                            # Extract the last data point in the "data" array
                            usage_data = serie.get("data", [])
                            parsed_response["USAGE"] = self.parse_usage_series(usage_data)
                            _LOGGER.debug("Parsed %d items for USAGE history", len(parsed_response["USAGE"]))

                            if net_series != "":
                              parsed_response["USAGE_RETURN"] = self.parse_usage_series(usage_data, ParseType.NET)
                              _LOGGER.debug("Parsed %d items for USAGE_RETURN history", len(parsed_response["USAGE_RETURN"]))
                else:
                    _LOGGER.debug("Unknown Usage: %s", entry)

            return parsed_response

        except Exception as e:
            _LOGGER.error("Error parsing usage data: %s", data)
            raise SmartHubDataError(f"Error parsing usage data: {e}") from e

    def parse_locations(self, location_json) -> List[SmartHubLocation]:
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
        _LOGGER.debug(location_json)

        for entry in location_json:
          if entry.get("inactive", False): # assume active by default
            continue # Don't include inactive accounts in list

          services = entry.get("services",[])
          serviceToProviders = entry.get("serviceToProviders", {})
          serviceToServiceDescription = entry.get("serviceToServiceDescription",{'ELEC': 'Electric Service'})
          serviceLocationToUserDataServiceLocationSummaries = entry.get("serviceLocationToUserDataServiceLocationSummaries", {})
          providerOrServiceDescription = entry.get("providerToDescription",{})

          # Loop through the locations looking for the service description `ELECTRIC_SERVICE` which maps the service key - usually ELEC, but sometimes 1ELEC
          electric_service_keys = {
                service for service, desc in serviceToServiceDescription.items()
                if desc == ELECTRIC_SERVICE
          }

          # Some smarthub systems don't return 'Electric Service' as a distinct entity. hsvutil.smarthub.coop returns
          # 'serviceToServiceDescription': {'WATER|NGAS|ELEC|SEWER|TRASH': 'City Utilities'},
          if 'ELEC' in services:
            electric_service_keys.add('ELEC')

          for electric_service in electric_service_keys:
              electrical_providers = serviceToProviders.get(electric_service,["unknown"])
              electrical_provider = electrical_providers[0] if electrical_providers else "unknown"
              for locationID, serviceDescriptions in serviceLocationToUserDataServiceLocationSummaries.items():
                for serviceDescription in serviceDescriptions:
                  # for now only support electric service type
                  if any(service in [electric_service] for service in serviceDescription.get("services",[])):
                    # Try to find a good description
                    description = serviceDescription.get("description", "")

                    locations.append(
                      SmartHubLocation(
                        id=locationID,
                        service=ELECTRIC_SERVICE,
                        description=description,
                        provider=providerOrServiceDescription.get(electrical_provider,electrical_provider),
                      )
                    )

        return locations

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
            SmartHubAuthenticationError: If authentication fails.
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
            async with session.post(auth_url, headers=headers, data=payload) as response:
                _ = await response.text()
                _LOGGER.debug("Auth response status: %s", response.status)

                if response.status == 401:
                    raise SmartHubAuthenticationError("Invalid credentials")
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
                    raise SmartHubAuthenticationError("No authorization token in response")

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
                    raise SmartHubAuthenticationError("Invalid credentials")
                elif response.status != 200:
                    raise SmartHubConnectionError(
                        f"User_data request failed with HTTP status: {response.status}"
                    )

                try:
                    response_json = await response.json()
                except Exception as e:
                    raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                return self.parse_locations(response_json)

        except ClientError as e:
            raise SmartHubConnectionError(f"Connection error during User_data request: {e}") from e

    async def get_energy_data(self, location, aggregation:Aggregation, start_datetime=None) -> Optional[Dict[str, Any]]:
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
                            raise SmartHubAuthenticationError("Authentication failed after token refresh")
                    elif response.status != 200:
                        error_text = await response.text()
                        _LOGGER.warning("HTTP error %d: %s", response.status, error_text)
                        raise SmartHubConnectionError(
                            f"HTTP error {response.status}: {error_text}"
                        )

                    try:
                        response_json = await response.json()
                        # _LOGGER.debug(response_json) # Specific parts of usage are logged separately - uncomment for full response
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

            except SmartHubAuthenticationError:
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

