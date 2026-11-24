"""Run one stock check:  python -m tracker  [--only walmart|iga]"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

from . import iga, state as st, walmart

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"


def main() -> int:
    ap = argparse.ArgumentParser(description="Check carrot juice stock in Saint-Hyacinthe.")
    ap.add_argument("--only", choices=["walmart", "iga"])
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text("utf-8"))
    state = st.load(DATA_DIR)
    st.sync_stores(state, cfg)
    started = time.time()
    ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def log(msg: str) -> None:
        print(msg, flush=True)

    summary: dict = {}
    for name, module in (("walmart", walmart), ("iga", iga)):
        if args.only and args.only != name:
            continue
        log(f"{name}: checking {len(cfg[name]['stores'])} store(s)")
        try:
            results = module.check(cfg, st.products_for(state, name), log)
        except Exception as e:  # whole chain failed before reaching any store
            results = [{"store_key": s["key"], "ok": False, "error": f"{type(e).__name__}: {e}"}
                       for s in cfg[name]["stores"]]
        for res in results:
            summary[res["store_key"]] = st.apply(state, res, ts, cfg.get("top_up_min_increase", 3))
            s = summary[res["store_key"]]
            if not s["ok"]:
                log(f"  {res['store_key']}: FAILED - {s['error']}")
            elif not s.get("online"):
                log(f"  {res['store_key']}: no online inventory at this store")
            else:
                log(f"  {res['store_key']}: {s['checked']} products checked, {s['changes']} changes")

    st.log_run(state, ts, summary, time.time() - started)
    st.save(state, DATA_DIR)
    in_stock = sum(1 for v in state["status"].values() if v["in_stock"])
    log(f"done in {time.time() - started:.0f}s - {in_stock}/{len(state['status'])} store-products in stock")
    # Fail the run (so GitHub emails you) only when every store failed.
    return 0 if any(s["ok"] for s in summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
