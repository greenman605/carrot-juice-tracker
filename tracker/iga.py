"""IGA (commerce.iga.net): select each Saint-Hyacinthe store, then read stock.

How it works
  1. Ask IGA's store finder which nearby stores take online orders. A store with neither
     pickup nor delivery has no online catalogue, so IGA publishes no stock for it.
  2. For each store, in its own browser session, call setSelectedStore, the same request
     the "Shop this store" button on a store page sends.
  3. Search for carrot juice. Results only include products that store carries.
  4. Open each known carrot juice product page. With a store selected, IGA adds the notice
     "le produit n'est pas disponible au magasin sélectionné" when that store is out.
"""
from __future__ import annotations

import html as htmllib
import re

from .common import (Blocked, SourceError, TIMEOUT, guess_brand, is_carrot_juice,
                     money, new_session, parse_size, pause)

BASE = "https://commerce.iga.net"
XHR = {"accept": "application/json, text/javascript, */*; q=0.01",
       "x-requested-with": "XMLHttpRequest", "origin": BASE, "referer": f"{BASE}/fr"}
DATA_PRODUCT = re.compile(r'data-product="([^"]*)"')
UNAVAILABLE = ("pas disponible au magasin", "not available at the selected store")


def _get(s, path: str, params: dict | None = None) -> str:
    r = s.get(BASE + path, params=params, timeout=TIMEOUT)
    text = r.content.decode("utf-8", "replace")
    if r.status_code == 403 or "<TITLE>Access Denied</TITLE>" in text[:500]:
        raise Blocked(f"IGA refused {path} (HTTP {r.status_code})")
    if r.status_code != 200:
        raise SourceError(f"IGA {path}: HTTP {r.status_code}")
    return text


def _field(raw: str, name: str) -> str | None:
    m = re.search(r"'" + name + r"':'((?:[^'\\]|\\.)*)'", raw)
    return m.group(1).replace("\\'", "'") if m else None


def _number(raw: str, name: str) -> float | None:
    m = re.search(r"'" + name + r"':(-?\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


def parse_products(page: str) -> list[dict]:
    out = []
    for m in DATA_PRODUCT.finditer(page):
        raw = htmllib.unescape(m.group(1))
        pid = _field(raw, "ProductId")
        if not pid:
            continue
        out.append({
            "id": pid,
            "brand_field": _field(raw, "BrandName"),
            "name": _field(raw, "FullDisplayName") or "",
            "size": _field(raw, "Size"),
            "url": _field(raw, "ProductUrl"),
            "image": _field(raw, "ProductImageUrl"),
            "regular": _number(raw, "RegularPrice"),
            "sale": _number(raw, "SalesPrice"),
        })
    return out


def _product_meta(p: dict, known_brands: list[str]) -> dict:
    return {
        "chain": "iga",
        "sku": p["id"],
        "name": p["name"],
        "brand": guess_brand(p["name"], p["brand_field"], known_brands),
        "size": parse_size(p["size"]) or (p["size"] or None),
        "url": BASE + p["url"] if (p.get("url") or "").startswith("/") else p.get("url"),
        "image": p.get("image"),
    }


def online_flags(s, near: dict) -> dict:
    """{store GUID: True if the store takes online orders}."""
    r = s.get(f"{BASE}/api/fr/Store/get", headers=XHR, timeout=TIMEOUT, params={
        "bannerMaxWidth": 100, "bannerMaxHeight": 100,
        "Longitude": near["longitude"], "Latitude": near["latitude"], "max": 10})
    if r.status_code != 200:
        raise SourceError(f"IGA store finder: HTTP {r.status_code}")
    return {st["Id"].lower(): bool(st.get("IsPickupSupported") or st.get("IsDeliverySupported"))
            for st in r.json().get("Data") or []}


def select_store(s, store: dict) -> None:
    r = s.post(f"{BASE}/api/fr/Store/setSelectedStore", headers=XHR, timeout=TIMEOUT, params={
        "storeId": store["id"], "fulfillmentMethod": "Pickup", "postalCode": store["postal_code"]})
    if r.status_code == 403:
        raise Blocked("IGA refused setSelectedStore")
    data = (r.json() or {}).get("Data") or {}
    if str(data.get("Id", "")).lower() != store["id"].lower():
        raise SourceError(f"IGA did not accept store {store['number']} as the selected store")


def product_status(s, product: dict) -> tuple[bool, dict | None]:
    path = product["url"].replace(BASE, "") if product.get("url") else f"/fr/produit/p/{product['sku']}"
    page = _get(s, path)
    unavailable = any(msg in htmllib.unescape(page) for msg in UNAVAILABLE)
    this = next((p for p in parse_products(page) if p["id"] == product["sku"]), None)
    return (not unavailable), this


def check(cfg: dict, known_products: dict, log) -> list[dict]:
    icfg = cfg["iga"]
    results = []
    flags: dict = {}
    try:
        s0 = new_session()
        _get(s0, "/fr")
        flags = online_flags(s0, icfg["search_near"])
    except Exception as e:
        log(f"  iga: could not read store finder ({e}); assuming every store sells online")

    def fail(res, e):
        res["error"] = (f"Blocked by IGA's bot protection: {e}" if isinstance(e, Blocked)
                        else f"{type(e).__name__}: {e}")

    # Phase 1: select each store in its own session and search it.
    active = []  # (store, res, session, listed)
    found_anywhere: dict[str, dict] = {}
    for store in icfg["stores"]:
        res = {"store_key": store["key"], "ok": False, "online": True, "default_store_set": False,
               "observations": [], "error": None, "note": None}
        results.append(res)
        if flags and not flags.get(store["id"].lower(), True):
            res.update(ok=True, online=False,
                       note="No online ordering at this store, so IGA publishes no stock for it.")
            continue
        try:
            s = new_session()  # one session per store keeps the selected store isolated
            _get(s, "/fr")
            pause()
            select_store(s, store)
            res["default_store_set"] = True
            pause()
            listed: dict[str, dict] = {}
            for term in icfg["search_terms"]:
                page = _get(s, "/fr/search", {"k": term, "pageSize": 60})
                for p in parse_products(page):
                    if is_carrot_juice(f"{p['brand_field'] or ''} {p['name']}", cfg["match"]):
                        listed.setdefault(p["id"], p)
                        found_anywhere.setdefault(p["id"], p)
                pause()
            active.append((store, res, s, listed))
        except Exception as e:
            fail(res, e)

    # Phase 2: check every carrot juice seen at any store (now or before) at every store,
    # so a product one store carries is also checked where it is missing.
    products = {sku: _product_meta(p, cfg["known_brands"]) for sku, p in found_anywhere.items()}
    for p in known_products.values():
        products.setdefault(p["sku"], dict(p))
    for store, res, s, listed in active:
        try:
            for sku, product in products.items():
                try:
                    in_stock, detail = product_status(s, product)
                except SourceError as e:
                    log(f"  iga: product page failed for {sku} at {store['short']}: {e}")
                    in_stock, detail = None, None
                info = detail or listed.get(sku) or {}
                regular, sale = money(info.get("regular")), money(info.get("sale"))
                res["observations"].append({
                    "product_key": f"iga:{sku}",
                    "product": product,
                    "listed": sku in listed,
                    "in_stock": in_stock,
                    "raw": None if in_stock is None else ("available" if in_stock else "not available at this store"),
                    "price": sale if sale is not None else regular,
                    "regular_price": regular if sale is not None else None,
                })
                pause(1.0, 2.5)
            res["ok"] = True
        except Exception as e:
            fail(res, e)
    return results
