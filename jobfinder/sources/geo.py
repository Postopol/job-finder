"""Small country-name -> ISO-2 helper shared by the API sources."""
from __future__ import annotations

import re
from datetime import UTC, datetime

COUNTRIES = {
    "united states": "US", "usa": "US", "us": "US", "u.s.": "US", "u.s.a.": "US", "america": "US",
    "canada": "CA", "mexico": "MX", "brazil": "BR", "argentina": "AR", "colombia": "CO",
    "chile": "CL", "peru": "PE",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "great britain": "GB", "england": "GB",
    "ireland": "IE", "germany": "DE", "france": "FR", "spain": "ES", "portugal": "PT",
    "italy": "IT", "netherlands": "NL", "belgium": "BE", "luxembourg": "LU",
    "switzerland": "CH", "austria": "AT", "poland": "PL", "czech republic": "CZ",
    "czechia": "CZ", "slovakia": "SK", "hungary": "HU", "romania": "RO", "bulgaria": "BG",
    "greece": "GR", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "estonia": "EE", "latvia": "LV", "lithuania": "LT", "croatia": "HR", "serbia": "RS",
    "slovenia": "SI", "ukraine": "UA", "turkey": "TR", "israel": "IL",
    "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA",
    "russia": "RU", "belarus": "BY", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "kyrgyzstan": "KG", "armenia": "AM", "azerbaijan": "AZ", "georgia": "GE",
    "moldova": "MD", "tajikistan": "TJ",
    "india": "IN", "pakistan": "PK", "bangladesh": "BD", "philippines": "PH",
    "indonesia": "ID", "vietnam": "VN", "thailand": "TH", "malaysia": "MY",
    "singapore": "SG", "japan": "JP", "south korea": "KR", "china": "CN",
    "taiwan": "TW", "hong kong": "HK", "australia": "AU", "new zealand": "NZ",
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "egypt": "EG",
}
_NOISE = re.compile(r"\b(?:only|based|residents?|citizens?|remote|candidates?)\b", re.I)


def country_code(name: str) -> str | None:
    key = _NOISE.sub(" ", name or "").strip(" .,;:-").lower()
    key = re.sub(r"\s+", " ", key)
    if key in COUNTRIES:
        return COUNTRIES[key]
    if len(key) == 2 and key.upper() in COUNTRIES.values():
        return key.upper()
    return None


def countries_from(names: list[str]) -> tuple[list[str], list[str]]:
    """Return (ISO-2 codes without duplicates, names that were not recognised)."""
    codes: list[str] = []
    unknown: list[str] = []
    for n in names:
        code = country_code(n)
        if code is None:
            if n and n.strip():
                unknown.append(n.strip())
        elif code not in codes:
            codes.append(code)
    return codes, unknown


def split_places(text: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;/]|\band\b", text or "") if p.strip()]


def utc_from_epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def utc_from_iso(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


_WORLDWIDE = re.compile(r"\b(?:worldwide|anywhere|global|world)\b", re.I)
_ONLY = re.compile(r"\bonly\b", re.I)


def scope_from_location(text: str | None) -> tuple[str, list[str]]:
    """(remote_scope, countries) from a free-form job location string."""
    if not text or not text.strip():
        return "unknown", []
    if _WORLDWIDE.search(text):
        return "worldwide", []
    names = split_places(text)
    codes, unknown = countries_from(names)
    if codes and not unknown:
        # «Russia only» is not open to Kazakhstan: an «only» list stays visible only with KZ
        if _ONLY.search(text) and "KZ" not in codes:
            return "restricted", []
        return "countries", codes
    return "unknown", []
