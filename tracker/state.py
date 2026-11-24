"""Tracker state: current status per (store, product), restock events, run log.

Only changes are recorded as events, so the history stays small even after years of
checks every few hours.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

MAX_RUNS = 120
HISTORY_DAYS = 45


def empty() -> dict:
    return {"schema": 1, "updated": None, "stores": {}, "products": {}, "status": {},
            "events": [], "runs": []}


def load(data_dir: pathlib.Path) -> dict:
    f = data_dir / "state.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else empty()


def save(state: dict, data_dir: pathlib.Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=1, ensure_ascii=False)
    (data_dir / "state.json").write_text(text + "\n", "utf-8")
    # Same data as a script, so the page also works when opened straight from disk.
    (data_dir / "state.js").write_text(f"window.TRACKER_STATE = {text};\n", "utf-8")


def sync_stores(state: dict, cfg: dict) -> None:
    for chain in ("walmart", "iga"):
        for st in cfg[chain]["stores"]:
            cur = state["stores"].setdefault(st["key"], {})
            cur.update({"chain": chain, "name": st["name"], "short": st["short"],
                        "address": st["address"]})
    state["check_every_hours"] = cfg.get("check_every_hours", 3)
    state["timezone"] = cfg.get("timezone", "America/Toronto")
    state["personalize_for"] = cfg.get("personalize_for")
    state["fresh_hours"] = cfg.get("fresh_hours", 48)


def _record_qty(cur: dict, ts: str, qty) -> None:
    """Keep Walmart's quantity as change points (for the stock-level charts)."""
    if qty is None:
        return
    hist = cur.setdefault("qty_history", [])
    if not hist or hist[-1][1] != qty:
        hist.append([ts, qty])
    cutoff = (dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) - dt.timedelta(days=HISTORY_DAYS))
    cutoff_s = cutoff.isoformat().replace("+00:00", "Z")
    # drop old points but keep the last one before the cutoff, so the line starts at the right level
    while len(hist) > 1 and hist[1][0] <= cutoff_s:
        hist.pop(0)


def products_for(state: dict, chain: str) -> dict:
    return {k: v for k, v in state["products"].items() if v.get("chain") == chain}


def apply(state: dict, result: dict, ts: str, min_increase: int = 3) -> dict:
    """Fold one store's check into the state. Returns a short summary for the run log.

    Events:
      restock   - was out of stock (or not carried), now in stock
      sold_out  - was in stock, now out
      top_up    - stayed in stock but the quantity jumped by at least min_increase
                  (Walmart only: IGA does not publish quantities)
    """
    key = result["store_key"]
    store = state["stores"][key]
    store["last_attempt"] = ts
    if not result["ok"]:
        store["last_error"] = result["error"]
        store["health"] = "error"
        return {"ok": False, "error": result["error"]}

    store.update(last_ok=ts, last_error=None, online=result["online"],
                 default_store_set=result["default_store_set"], note=result.get("note"),
                 health="ok" if result["online"] else "no_online_inventory")
    changes = 0
    for ob in result["observations"]:
        pk = ob["product_key"]
        prod = state["products"].setdefault(pk, {"first_seen": ts})
        prod.update({k: v for k, v in ob["product"].items() if v not in (None, "")})
        if ob.get("listed"):
            prod["last_listed"] = ts
        if ob["in_stock"] is None:
            continue  # unknown this time: keep the last known status

        sk = f"{key}|{pk}"
        cur = state["status"].get(sk)
        qty = ob.get("qty")
        if cur is None:
            state["status"][sk] = {
                "store": key, "product": pk, "in_stock": ob["in_stock"], "since": ts,
                "since_first_check": True, "last_checked": ts, "raw": ob["raw"], "qty": qty,
                "price": ob["price"], "regular_price": ob["regular_price"],
                "last_in_stock": ts if ob["in_stock"] else None,
                "last_restock": None, "restocks": 0,
            }
            _record_qty(state["status"][sk], ts, qty)
            continue

        event = None
        if cur["in_stock"] != ob["in_stock"]:
            event = "restock" if ob["in_stock"] else "sold_out"
            cur.update(in_stock=ob["in_stock"], since=ts, since_first_check=False)
        elif (ob["in_stock"] and qty is not None and cur.get("qty") is not None
              and qty - cur["qty"] >= min_increase):
            event = "top_up"
        if event:
            changes += 1
            state["events"].insert(0, {
                "ts": ts, "after": cur["last_checked"], "store": key, "product": pk,
                "type": event, "price": ob["price"], "qty_before": cur.get("qty"), "qty": qty,
            })
            if event != "sold_out":
                cur["last_restock"] = ts
                cur["restocks"] = cur.get("restocks", 0) + 1
        cur.update(last_checked=ts, raw=ob["raw"], qty=qty)
        _record_qty(cur, ts, qty)
        if ob["price"] is not None:
            cur["price"], cur["regular_price"] = ob["price"], ob["regular_price"]
        if ob["in_stock"]:
            cur["last_in_stock"] = ts
    return {"ok": True, "checked": len(result["observations"]), "changes": changes,
            "online": result["online"]}


def log_run(state: dict, ts: str, summary: dict, seconds: float) -> None:
    # The run log is capped, so remember when tracking started separately.
    state.setdefault("tracking_since", state["runs"][-1]["ts"] if state["runs"] else ts)
    state["updated"] = ts
    state["runs"].insert(0, {"ts": ts, "seconds": round(seconds), "stores": summary})
    del state["runs"][MAX_RUNS:]
