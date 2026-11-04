"""Utility functions for SmartHub integration."""
import re
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

# External statistic ids use the entity-id alphabet: lowercase, digits, underscores.
_INVALID_STAT_FRAGMENT = re.compile(r"[^a-z0-9_]+")
_REPEATED_UNDERSCORE = re.compile(r"_+")

def normalize_meter_id(meter_id: str) -> str:
    """Return a lowercase statistic-id fragment for a meter id.

    Home Assistant rejects external statistic ids that are not lowercase
    letters, digits, and single underscores. Meter numbers such as
    ``1ND91111111`` otherwise raise ``Invalid statistic_id``.
    """
    cleaned = _INVALID_STAT_FRAGMENT.sub("_", str(meter_id or "").strip().lower())
    cleaned = _REPEATED_UNDERSCORE.sub("_", cleaned).strip("_")
    return cleaned or "meter"

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

