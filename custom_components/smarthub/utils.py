"""Utility functions for SmartHub integration."""
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

def sanitize_host(host: str) -> str:
    """Sanitize host: remove protocol and trailing slashes."""
    if not host:
        return ""
    return host.split("://")[-1].rstrip("/")

def parse_epoch_set_timezone(epoch: float, target_tz: ZoneInfo) -> datetime:
    """Return a Datetime object based on a provided epoch as if that epoch was set in a specific timezone."""
    utc_datetime = datetime.fromtimestamp(epoch, tz=timezone.utc) # Set UTC to get a tz aware object
    zone_datetime = utc_datetime.replace(tzinfo=target_tz) # replace the TZ, to not adjust based on Timezones
    return zone_datetime

