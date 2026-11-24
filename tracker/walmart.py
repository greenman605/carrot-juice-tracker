"""Walmart.ca: set the Saint-Hyacinthe store as the default pickup store, then read stock.

How it works
  1. Look up the store's pickup access point (store-selector query).
  2. Call setPickup, the same mutation walmart.ca's "Make this my store" button sends.
     From then on, search results and prices are for that store.
  3. Search for carrot juice and collect matching products.
  4. For every known carrot juice product (including ones that dropped out of search),
     load the same product data the product page loads (DynamicItemById). With the
     store set, its pickup option gives that store's stock status and the quantity
     Walmart will sell online from that store.

  Search results are only used to discover products: their stock fields are not
  store-specific (every grocery item shows IN_STOCK there).

Walmart only runs GraphQL operations it has registered, identified by a hash. Those
hashes are stored in walmart_ops.json; if Walmart ships a new site build and they stop
working, discover_ops() re-reads them from the site's public JavaScript.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import pathlib
import re

from .common import (Blocked, SourceError, TIMEOUT, guess_brand, is_carrot_juice,
                     money, new_session, parse_size, pause)

BASE = "https://www.walmart.ca"
OPS_FILE = pathlib.Path(__file__).with_name("walmart_ops.json")
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
IN_STOCK = {"IN_STOCK", "LIMITED_STOCK", "LOW_STOCK", "AVAILABLE"}

GQL_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "x-o-bu": "WALMART-CA",
    "x-o-mart": "B2C",
    "x-o-platform": "rweb",
    "x-o-segment": "oaoh",
    "origin": BASE,
    "referer": f"{BASE}/en/search?q=carrot%20juice",
    "wm_mp": "true",
}

# Which GraphQL endpoint each operation lives on, and how to recognise its definition in the JS.
OP_SPECS = {
    "nearByNodes": {"endpoint": "cartxo/graphql", "kind": "query",
                    "marker": 'name:"nearByNodes",query:"query nearByNodes('},
    "setPickup": {"endpoint": "graphql", "kind": "mutation",
                  "marker": 'name:"setPickup",query:"mutation setPickup('},
    "DynamicItemById": {"endpoint": "graphql", "kind": "query",
                        "marker": 'name:"DynamicItemById",query:"query DynamicItemById('},
}


class OpError(SourceError):
    pass


# ---------------------------------------------------------------- GraphQL plumbing

def load_ops() -> dict:
    return json.loads(OPS_FILE.read_text("utf-8"))


def _looks_blocked(status: int, text: str) -> bool:
    return status in (403, 412, 429) or "Verify Your Identity" in text[:20000] or "px-captcha" in text[:20000]


def gql(s, ops: dict, name: str, variables: dict) -> dict:
    spec = OP_SPECS[name]
    headers = dict(GQL_HEADERS)
    headers["x-apollo-operation-name"] = name
    headers["x-o-gql-query"] = f"{spec['kind']} {name}"
    url = f"{BASE}/orchestra/{spec['endpoint']}/{name}/{ops[name]}"
    r = s.post(url, headers=headers, data=json.dumps({"variables": variables}), timeout=TIMEOUT)
    if _looks_blocked(r.status_code, r.text):
        raise Blocked(f"Walmart bot check on {name} (HTTP {r.status_code})")
    try:
        body = r.json()
    except ValueError:
        raise OpError(f"{name}: HTTP {r.status_code}, not JSON")
    if r.status_code != 200 or (body.get("errors") and not body.get("data")):
        raise OpError(f"{name}: HTTP {r.status_code} {json.dumps(body)[:200]}")
    return body["data"]


def gql_with_rediscovery(s, ops: dict, name: str, variables: dict, log) -> dict:
    try:
        return gql(s, ops, name, variables)
    except OpError as e:
        log(f"  walmart: {e} - re-reading operation ids from walmart.ca")
        fresh = discover_ops(s, log)
        if fresh == ops:
            raise
        ops.update(fresh)
        OPS_FILE.write_text(json.dumps(ops, indent=2) + "\n", "utf-8")
        return gql(s, ops, name, variables)


def discover_ops(s, log) -> dict:
    """Find current hashes for our operations in walmart.ca's public JavaScript chunks."""
    html = s.get(f"{BASE}/en/search?q=carrot%20juice", timeout=TIMEOUT).text
    m = re.search(r'src="([^"]*/_next/static/chunks/webpack-[^"]+\.js)"', html)
    if not m:
        raise SourceError("could not find walmart.ca webpack runtime")
    runtime_url = m.group(1)
    if runtime_url.startswith("/"):
        runtime_url = BASE + runtime_url
    base = runtime_url.split("static/chunks/")[0]
    js = s.get(runtime_url, timeout=TIMEOUT).text
    start = js.find("k.u=") if "k.u=" in js else js.find(".u=function")
    seg = js[start:js.find('[c]+".js"', start) + 10] if start >= 0 else js
    paths = {cid: f"static/chunks/{cid}-{h}.js"
             for cid, h in re.findall(r'"(\d+)"===\w\?"static/chunks/"\+\w\+"-([0-9a-f]+)\.js"', seg)}
    maps = re.findall(r"\(\{([^}]*)\}\)\[\w\]", seg)
    if maps:
        names = dict(re.findall(r'(\d+):"([^"]+)"', maps[0])) if len(maps) > 1 else {}
        for cid, h in re.findall(r'(\d+):"([^"]+)"', maps[-1]):
            paths.setdefault(cid, f"static/chunks/{names.get(cid, cid)}.{h}.js")
    # Page chunks referenced directly by the HTML are worth checking first.
    direct = re.findall(r'src="([^"]*/_next/static/chunks/[^"]+\.js)"', html)
    urls = [u if u.startswith("http") else BASE + u for u in direct] + [base + p for p in paths.values()]
    log(f"  walmart: scanning {len(urls)} JS chunks for operation ids")

    found: dict[str, str] = {}

    def scan(url):
        try:
            text = s.get(url, timeout=TIMEOUT).text
        except Exception:
            return {}
        hits = {}
        for name, spec in OP_SPECS.items():
            i = text.find(spec["marker"])
            if i >= 0:
                j = text.find('",hash:"', i)
                if j > 0:
                    hits[name] = text[j + 8:j + 72]
        return hits

    with cf.ThreadPoolExecutor(8) as pool:
        for hits in pool.map(scan, urls):
            found.update(hits)
            if len(found) == len(OP_SPECS):
                break
    missing = set(OP_SPECS) - set(found)
    if missing:
        raise SourceError(f"walmart.ca no longer defines: {', '.join(sorted(missing))}")
    return found


# ---------------------------------------------------------------- queries

def _nearby_vars(postal_code: str) -> dict:
    return {
        "input": {"postalCode": postal_code, "accessTypes": ["PICKUP_INSTORE", "PICKUP_CURBSIDE"],
                  "nodeTypes": None, "latitude": None, "longitude": None, "radius": None,
                  "city": None, "stateOrProvince": None},
        "checkItemAvailability": False, "checkWeeklyReservation": False,
        "enableStoreSelectorMarketplacePickup": False, "enableVisionStoreSelector": False,
        "enableStorePagesAndFinderPhase2": False, "enableStoreBrandFormat": False,
        "disableNodeAddressPostalCode": False, "enableWICStoreSelector": False,
    }


def store_stock(s, ops: dict, sku: str, store_id: str, log) -> dict:
    """Stock of one product at the current default store, from the product-page data."""
    p = gql_with_rediscovery(s, ops, "DynamicItemById", {"iId": sku, "fSId": True}, log)["product"]
    if not p:
        raise SourceError(f"product {sku} not found")
    at = str(((p.get("location") or {}).get("pickupLocation") or {}).get("storeId") or "")
    if at != store_id:
        raise SourceError(f"product data came back for store {at or '?'}, not {store_id}")
    opts = {o.get("type"): o for o in p.get("fulfillmentOptions") or []}
    pickup = opts.get("PICKUP") or opts.get("DELIVERY") or {}
    price = p.get("priceInfo") or {}
    return {
        "status": pickup.get("availabilityStatus") or p.get("availabilityStatus"),
        "qty": pickup.get("availableQuantity"),
        "price": money((price.get("currentPrice") or {}).get("price")),
        "was": money((price.get("wasPrice") or {}).get("price")),
    }


def search(s, term: str) -> tuple[dict, list[dict]]:
    r = s.get(f"{BASE}/en/search", params={"q": term}, timeout=TIMEOUT)
    m = NEXT_RE.search(r.text)
    if not m or _looks_blocked(r.status_code, r.text):
        raise Blocked(f"Walmart bot check on search (HTTP {r.status_code})")
    init = json.loads(m.group(1))["props"]["pageProps"]["initialData"]
    location = (init.get("pageMetadata") or {}).get("location") or {}
    items = [it for stack in (init.get("searchResult") or {}).get("itemStacks") or []
             for it in stack.get("items") or [] if it.get("__typename") == "Product"]
    return location, items


def _product_from_item(it: dict, known_brands: list[str]) -> dict:
    name = it.get("name") or ""
    url = (it.get("canonicalUrl") or "").split("?")[0]
    return {
        "chain": "walmart",
        "sku": it["usItemId"],
        "name": name,
        "brand": guess_brand(name, it.get("brand"), known_brands),
        "size": parse_size(name),
        "url": BASE + url if url.startswith("/") else url or f"{BASE}/en/ip/{it['usItemId']}",
        "image": (it.get("imageInfo") or {}).get("thumbnailUrl"),
    }


# ---------------------------------------------------------------- main entry

def check(cfg: dict, known_products: dict, log) -> list[dict]:
    """Return one result dict per configured Walmart store."""
    wcfg = cfg["walmart"]
    results = []
    s = new_session()
    ops = load_ops()
    s.get(f"{BASE}/en/search?q=carrot%20juice", timeout=TIMEOUT)  # pick up session cookies
    pause()

    for store in wcfg["stores"]:
        res = {"store_key": store["key"], "ok": False, "online": True, "default_store_set": False,
               "observations": [], "error": None, "note": None}
        results.append(res)
        try:
            # 1-2. make this store the default pickup store
            data = gql_with_rediscovery(s, ops, "nearByNodes", _nearby_vars(store["postal_code"]), log)
            node = next((n for n in data["nearByNodes"]["nodes"] if str(n["id"]) == store["id"]), None)
            if not node:
                raise SourceError(f"store {store['id']} not found near {store['postal_code']}")
            caps = [c for c in node.get("capabilities") or [] if c.get("isActive", True) and not c.get("isTest")]
            caps.sort(key=lambda c: c.get("accessPointType") != "PICKUP_INSTORE")
            if not caps:
                raise SourceError(f"store {store['id']} has no pickup access point")
            pause()
            gql_with_rediscovery(s, ops, "setPickup", {"input": {
                "accessPointId": caps[0]["accessPointId"], "cartId": "",
                "postalCode": store["postal_code"], "storeId": int(store["id"])}}, log)
            pause()

            # 3. search with that store as the default
            listed: dict[str, dict] = {}
            for term in wcfg["search_terms"]:
                location, items = search(s, term)
                if str(location.get("storeId")) != store["id"]:
                    raise SourceError(f"Walmart kept store {location.get('storeId')} instead of {store['id']}")
                res["default_store_set"] = True
                for it in items:
                    if it.get("usItemId") and is_carrot_juice(it.get("name") or "", cfg["match"]):
                        listed.setdefault(it["usItemId"], it)
                pause()

            # 4. per-product stock at this store
            skus = list(listed) + [p["sku"] for p in known_products.values() if p["sku"] not in listed]
            for sku in skus:
                it = listed.get(sku)
                product = _product_from_item(it, cfg["known_brands"]) if it else dict(known_products[f"walmart:{sku}"])
                try:
                    stock = store_stock(s, ops, sku, store["id"], log)
                except (OpError, SourceError) as e:
                    log(f"  walmart: stock lookup failed for {sku}: {e}")
                    stock = {"status": None, "qty": None, "price": None, "was": None}
                raw = stock["status"]
                res["observations"].append({
                    "product_key": f"walmart:{sku}",
                    "product": product,
                    "listed": it is not None,
                    "in_stock": None if raw is None else raw in IN_STOCK,
                    "raw": raw,
                    "qty": stock["qty"] if raw in IN_STOCK else (0 if raw else None),
                    "price": stock["price"],
                    "regular_price": stock["was"],
                })
                pause(1.0, 2.5)
            res["ok"] = True
        except Blocked as e:
            res["error"] = f"Blocked by Walmart's bot check: {e}"
        except Exception as e:  # keep other stores going
            res["error"] = f"{type(e).__name__}: {e}"
    return results
