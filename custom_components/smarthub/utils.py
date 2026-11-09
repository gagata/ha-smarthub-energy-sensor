"""Utility functions for SmartHub integration."""
import hashlib
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# External statistic ids use the entity-id alphabet: lowercase, digits, underscores.
_INVALID_STAT_FRAGMENT = re.compile(r"[^a-z0-9_]+")
_REPEATED_UNDERSCORE = re.compile(r"_+")
# Short, order-independent discriminator for ids that normalize to the same fragment.
_COLLISION_SUFFIX_LEN = 8

def normalize_meter_id(meter_id: str) -> str:
    """Return a lowercase statistic-id fragment for a meter id.

    Home Assistant rejects external statistic ids that are not lowercase
    letters, digits, and single underscores. Meter numbers such as
    ``1ND91111111`` otherwise raise ``Invalid statistic_id``.

    This is a per-id transform. When two different meter ids collapse to the
    same fragment, use :func:`assign_unique_meter_fragments` so they do not
    overwrite one statistic series.
    """
    cleaned = _INVALID_STAT_FRAGMENT.sub("_", str(meter_id or "").strip().lower())
    cleaned = _REPEATED_UNDERSCORE.sub("_", cleaned).strip("_")
    return cleaned or "meter"

def _collision_suffix(meter_id: str) -> str:
    """Return a stable suffix derived only from the raw meter id."""
    digest = hashlib.sha256(str(meter_id).encode("utf-8")).hexdigest()
    return digest[:_COLLISION_SUFFIX_LEN]

def assign_unique_meter_fragments(
    meter_ids: Iterable[str],
    saved: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map each raw meter id to a unique statistic-id fragment.

    Fragments already stored in ``saved`` are kept as-is, including when the
    other meter that caused a collision later disappears. A meter with no
    saved fragment keeps :func:`normalize_meter_id` when that fragment is
    still free. Only a newly discovered meter whose base is already taken
    gets ``{base}_{suffix}``.

    On the first sight of two colliding ids, the lexicographically smaller
    raw id claims the unsuffixed base and the other gets the suffix. That
    choice is then what ``saved`` should remember.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for meter_id in meter_ids:
        raw = str(meter_id)
        if raw in seen:
            continue
        seen.add(raw)
        ordered.append(raw)

    remembered = {str(raw): str(fragment) for raw, fragment in (saved or {}).items() if fragment}
    fragments: dict[str, str] = {}
    used: set[str] = set(remembered.values())
    for raw in ordered:
        if raw in remembered:
            fragments[raw] = remembered[raw]

    for raw in sorted(raw for raw in ordered if raw not in fragments):
        base = normalize_meter_id(raw)
        if base not in used:
            fragment = base
        else:
            fragment = f"{base}_{_collision_suffix(raw)}"
            extra = 2
            while fragment in used:
                fragment = f"{fragment}_{extra}"
                extra += 1
        fragments[raw] = fragment
        used.add(fragment)
    return fragments

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

