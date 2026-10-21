#!/usr/bin/env python3
"""
Baizora Tracker: daily top-ranked list from the price & volume scanner (2026-10-21).

Each finished trading session, records the TOP_N S&P 500 / Nasdaq-100 stocks with
the highest BaizConviction (ties: BaizScore, then market cap) into
data/baizora_tracker.json, along with each stock's close that day and SPY's close.
baizora_tracker.html shows today's list and every past list's return since it was
recorded, next to SPY over the same span, so hits and misses both stay visible.

Rule-based ranking only, no discretion. BaizConviction is the one Baizora score
whose backtest (assets/baizscore_backtest.html) showed a clean edge over BaizScore
at matched sample size, at 3 to 12 month horizons; it was never tested day-to-day.

Idempotent: skips if latest.json is a midday snapshot or its date is already logged.

Usage:
    python baizora_tracker.py                # append today's list if new
    python baizora_tracker.py --backfill 30  # rebuild the last 30 sessions from git history
"""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
LATEST = ROOT / "data" / "latest.json"
OUT = ROOT / "data" / "baizora_tracker.json"
TOP_N = 10


def build_entry(data):
    stale = set(data.get("staleTickers") or [])
    rows = [r for r in data.get("data", [])
            if (r.get("InSP500") or r.get("InNASDAQ100"))
            and r.get("Ticker") not in stale
            and r.get("BaizConviction") is not None
            and r.get("Price")]
    if len(rows) < TOP_N:
        return None
    rows.sort(key=lambda r: (-r["BaizConviction"], -(r.get("BaizScore") or 0),
                             -(r.get("MarketCap") or 0), r["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    picks = []
    for i, r in enumerate(rows[:TOP_N]):
        picks.append({
            "rank": i + 1,
            "ticker": r["Ticker"],
            "name": r.get("CompanyName") or "",
            "sector": r.get("Sector") or "",
            "price": r["Price"],
            "conviction": r["BaizConviction"],
            "score": r.get("BaizScore"),
            "persist": r.get("BaizPersist"),
            "chg1d": rnd(r.get("PriceChange1D")),
            "chg1y": rnd(r.get("1YPriceChange")),
            "pxVsMa21": rnd(r.get("PriceVsMA21_1D"), 3),
            "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
        })
    return {"date": data["date"], "spy": spy.get("Price") if spy else None, "picks": picks}


def load_out():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"entries": []}


def save_out(out):
    out["entries"].sort(key=lambda e: e["date"], reverse=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


def add(out, data, backfilled=False):
    if data.get("midday"):
        return False
    if any(e["date"] == data.get("date") for e in out["entries"]):
        return False
    entry = build_entry(data)
    if entry is None:
        return False
    if backfilled:
        entry["backfilled"] = True
    out["entries"].append(entry)
    return True


def backfill(out, sessions):
    """Replay the last committed, finished latest.json of each past session."""
    log = subprocess.run(["git", "log", "--format=%H", "--", "data/latest.json"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    seen = set()
    for sha in log:  # newest first, so the first finished version per date wins
        if len(seen) >= sessions:
            break
        try:
            data = json.loads(subprocess.run(["git", "show", f"{sha}:data/latest.json"], cwd=ROOT,
                                             capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        d = data.get("date")
        if not d or d in seen or data.get("midday"):
            continue
        seen.add(d)
        if add(out, data, backfilled=True):
            print("backfilled", d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="rebuild this many past sessions from git history")
    args = ap.parse_args()

    out = load_out()
    if args.backfill:
        backfill(out, args.backfill)
    data = json.loads(LATEST.read_text(encoding="utf-8"))
    if add(out, data):
        print("added", data["date"])
    else:
        print(f"no new list (latest.json {data.get('date')}, midday={data.get('midday')})")
    save_out(out)


if __name__ == "__main__":
    main()
