"""Run one stock check:  python -m tracker  [--only walmart|iga] [--publish] [--log FILE]"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
MAX_LOG_BYTES = 1_000_000


def _open_log(path: str):
    """Send output to a log file (pythonw has no console). Keeps one older copy."""
    f = ROOT / path
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists() and f.stat().st_size > MAX_LOG_BYTES:
        f.replace(f.with_suffix(f.suffix + ".old"))
    stream = open(f, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream


def main() -> int:
    ap = argparse.ArgumentParser(description="Check carrot juice stock in Saint-Hyacinthe.")
    ap.add_argument("--only", choices=["walmart", "iga"])
    ap.add_argument("--publish", action="store_true",
                    help="pull from GitHub first, then commit and push the results")
    ap.add_argument("--log", help="append output to this file instead of the console")
    args = ap.parse_args()
    if args.log:
        _open_log(args.log)

    from . import iga, state as st, walmart  # after logging is set up

    def log(msg: str) -> None:
        print(msg, flush=True)

    started = time.time()
    ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    log(f"=== {ts} ===")

    if args.publish:
        from . import publish
        publish.pull(log)

    cfg = json.loads((ROOT / "config.json").read_text("utf-8"))
    state = st.load(DATA_DIR)
    st.sync_stores(state, cfg)

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

    if args.publish:
        from . import publish
        publish.push(log, ts.replace("T", " ").replace("Z", " UTC"))
    # Non-zero only when every store failed.
    return 0 if any(s["ok"] for s in summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
