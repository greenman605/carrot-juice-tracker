"""Shared helpers: HTTP session, pacing, text matching."""
from __future__ import annotations

import random
import re
import time
import unicodedata

from curl_cffi import requests as cffi

TIMEOUT = 30


class Blocked(Exception):
    """The site answered with a bot-check page instead of content."""


class SourceError(Exception):
    """The site answered, but not with what we expected."""


def new_session():
    # Browser TLS fingerprint: both sites refuse plain Python HTTP clients.
    s = cffi.Session(impersonate="chrome")
    s.headers.update({"Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7"})
    return s


def pause(lo: float = 1.5, hi: float = 3.5) -> None:
    """Space requests out like a person browsing; this is a slow tracker on purpose."""
    time.sleep(random.uniform(lo, hi))


def fold(text: str | None) -> str:
    """Lowercase and strip accents so 'Carottes' and 'carottes' and 'carotte' compare simply."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def is_carrot_juice(text: str, match_cfg: dict) -> bool:
    t = fold(text)
    words = set(re.findall(r"[a-z0-9]+", t))
    has_carrot = any(w in words for w in match_cfg["product_words"])
    has_juice = any(w in words for w in match_cfg["juice_words"])
    return has_carrot and has_juice


def guess_brand(name: str, brand_field: str | None, known: list[str]) -> str:
    hay = fold(f"{brand_field or ''} {name}")
    for b in known:
        if re.search(r"(?<![a-z])" + re.escape(fold(b)) + r"(?![a-z])", hay):
            return b
    if brand_field:
        return brand_field.strip()
    return name.split()[0] if name else "Unknown"


_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|l)\b", re.I)


def parse_size(text: str | None) -> str | None:
    if not text:
        return None
    m = _SIZE.search(text)
    if not m:
        return None
    qty, unit = m.group(1).replace(",", "."), m.group(2)
    return f"{qty} {'mL' if unit.lower() == 'ml' else 'L'}"


def money(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", str(value))
    return round(float(m.group(1).replace(",", ".")), 2) if m else None
