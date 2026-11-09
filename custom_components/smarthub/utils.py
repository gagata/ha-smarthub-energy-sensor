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

def assign_unique_meter_fragments(meter_ids: Iterable[str]) -> dict[str, str]:
    """Map each raw meter id to a unique statistic-id fragment.

    Ids that do not share a normalized form keep :func:`normalize_meter_id`
    unchanged, so existing statistics and entity ids stay valid.

    When several raw ids collapse together (``A-B`` and ``A B`` both become
    ``a_b``), every id in that group gets ``{base}_{suffix}``. The suffix is
    a hash of the original id, so it does not depend on discovery order and
    does not change when another colliding meter appears later.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for meter_id in meter_ids:
        raw = str(meter_id)
        if raw in seen:
            continue
        seen.add(raw)
        ordered.append(raw)

    bases = {raw: normalize_meter_id(raw) for raw in ordered}
    counts: dict[str, int] = {}
    for base in bases.values():
        counts[base] = counts.get(base, 0) + 1

    fragments: dict[str, str] = {}
    used: set[str] = set()
    for raw in ordered:
        base = bases[raw]
        if counts[base] == 1:
            fragments[raw] = base
            used.add(base)

    for raw in sorted(raw for raw in ordered if raw not in fragments):
        base = bases[raw]
        fragment = f"{base}_{_collision_suffix(raw)}"
        candidate = fragment
        extra = 2
        while candidate in used:
            candidate = f"{fragment}_{extra}"
            extra += 1
        fragments[raw] = candidate
        used.add(candidate)
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

