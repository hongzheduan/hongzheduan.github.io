#!/usr/bin/env python3
"""
Baizora Tracker: daily top-ranked list from the price & volume scanner (2026-10-21).

Each finished trading session, records the TOP_N S&P 500 / Nasdaq-100 stocks with
the highest rank score (ties: BaizScore, then market cap) into
data/baizora_tracker.json, along with each stock's close that day and SPY's close.
baizora_tracker.html shows today's list and every past list's return HORIZON trading
days after it was recorded, next to SPY over the same span, so hits and misses both
stay visible. Once a list reaches its HORIZON-th session, that session's closes are
stored on the entry as "exit" {date, spy, prices}, so the result is fixed from then on.

Rank score: CONV_WEIGHT x BaizConviction percentile + MOM_WEIGHT x 3-month price change
percentile, within that day's eligible stocks. User asked to add plain momentum (50/50),
then set 25/75 (2026-10-22). backtests/momentum_blend_backtest.py, 25/75: +1.10pp mean /
+0.56pp median per 13 sessions vs BaizConviction alone over 239 sessions, not significant. On 2026-10-22 every
existing list was re-ranked with it from git history (--rerank); the formula was
picked on that same period, so those lists are in-sample.

Rule-based ranking only, no discretion. BaizConviction is the one Baizora score
whose backtest (assets/baizscore_backtest.html) showed a clean edge over BaizScore
at matched sample size, at 3 to 12 month horizons; it was never tested day-to-day.

Idempotent: skips if latest.json is a midday snapshot or its date is already logged.
Exits are filled from latest.json on the exit date, or from git history when missed.

Usage:
    python baizora_tracker.py                # append today's list if new
    python baizora_tracker.py --backfill 30  # rebuild the last 30 sessions from git history
"""
import argparse
import json
from bisect import bisect_left, bisect_right
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
LATEST = ROOT / "data" / "latest.json"
OUT = ROOT / "data" / "baizora_tracker.json"
CANDLES = ROOT / "data" / "candles.json"
TOP_N = 10
CONV_WEIGHT, MOM_WEIGHT = 0.25, 0.75  # rank score weights (user, 2026-10-22; was 50/50)
HORIZON = 13  # trading sessions after the list date (user, 2026-10-22)


def build_entry(data):
    stale = set(data.get("staleTickers") or [])
    rows = [r for r in data.get("data", [])
            if (r.get("InSP500") or r.get("InNASDAQ100"))
            and r.get("Ticker") not in stale
            and r.get("BaizConviction") is not None
            and r.get("Price")]
    if len(rows) < TOP_N:
        return None
    def pct(col):
        vals = sorted(r[col] for r in rows if r.get(col) is not None)
        n = len(vals)
        # average rank for ties; missing momentum = neutral 0.5
        return {r["Ticker"]: (0.5 if r.get(col) is None or n < 2 else
                              (bisect_left(vals, r[col]) + bisect_right(vals, r[col]) - 1) / 2 / (n - 1))
                for r in rows}
    pc, pm = pct("BaizConviction"), pct("3MPriceChange")
    for r in rows:
        r["_rank"] = CONV_WEIGHT * pc[r["Ticker"]] + MOM_WEIGHT * pm[r["Ticker"]]
    rows.sort(key=lambda r: (-r["_rank"], -(r.get("BaizScore") or 0),
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
            "chg3m": rnd(r.get("3MPriceChange")),
            "rankScore": rnd(r["_rank"] * 100, 1),
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


def _session_dates():
    """Trading session dates from candles.json (about the last year)."""
    try:
        dates = set(json.loads(CANDLES.read_text(encoding="utf-8")).get("dates", []))
    except (FileNotFoundError, json.JSONDecodeError):
        dates = set()
    return dates


def _finished_latest_by_date(wanted):
    """{date: latest.json} for the wanted dates, from the last finished commit of each."""
    found = {}
    log = subprocess.run(["git", "log", "-400", "--format=%H", "--", "data/latest.json"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for sha in log:
        if wanted <= set(found):
            break
        try:
            data = json.loads(subprocess.run(["git", "show", f"{sha}:data/latest.json"], cwd=ROOT,
                                             capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        d = data.get("date")
        if d in wanted and d not in found and not data.get("midday"):
            found[d] = data
    return found


def fill_exits(out, latest):
    """Store the HORIZON-th session's closes on every list that has reached it."""
    sessions = _session_dates() | {e["date"] for e in out["entries"]}
    if latest.get("date") and not latest.get("midday"):
        sessions.add(latest["date"])
    sessions = sorted(sessions)
    last = latest["date"] if not latest.get("midday") else max(d for d in sessions if d < latest["date"])
    need = {}
    for e in out["entries"]:
        if e.get("exit") or e["date"] not in sessions:
            continue
        k = sessions.index(e["date"]) + HORIZON
        if k < len(sessions) and sessions[k] <= last:
            need.setdefault(sessions[k], []).append(e)
    if not need:
        return
    sources = {}
    if latest.get("date") in need and not latest.get("midday"):
        sources[latest["date"]] = latest
    missing = set(need) - set(sources)
    if missing:
        sources.update(_finished_latest_by_date(missing))
    candles = None
    for d, entries in need.items():
        data = sources.get(d)
        if data is not None:
            px = {r["Ticker"]: r.get("Price") for r in data.get("data", [])}
        else:
            # The workflow's checkout is shallow, so git history is usually not there. Fall
            # back to candles.json closes (dividend-adjusted, so a fraction of a percent off).
            if candles is None:
                candles = json.loads(CANDLES.read_text(encoding="utf-8"))
            if d not in candles["dates"]:
                print("no close found for exit date", d)
                continue
            back = len(candles["dates"]) - candles["dates"].index(d)  # newer tickers have shorter, end-aligned arrays
            px = {t: (bars[-back][3] if back <= len(bars) and bars[-back] else None)
                  for t, bars in candles["data"].items()}
            print("exit date", d, "priced from candles.json")
        for e in entries:
            e["exit"] = {"date": d, "spy": px.get("SPY"),
                         "prices": {p["ticker"]: px.get(p["ticker"]) for p in e["picks"]}}
            print("exit", e["date"], "->", d)


def _corrected_scores():
    """BaizPersist/BaizConviction as published before 2026-10-21 were computed from a
    frozen August window (see backtests/rebuild_score_history_from_git.py). The rebuilt
    data/baiz_score_trend.json holds the correct per-session values, keyed by __dates__."""
    trend = json.loads((ROOT / "data" / "baiz_score_trend.json").read_text(encoding="utf-8"))
    dates = trend.get("__dates__", [])

    def lookup(ticker, col, date):
        arr = (trend.get(ticker) or {}).get(col) or []
        if date not in dates:
            return None
        k = dates.index(date) - len(dates) + len(arr)
        return arr[k] if 0 <= k < len(arr) else None
    return lookup


def backfill(out, sessions):
    """Replay the last committed, finished latest.json of each past session."""
    lookup = _corrected_scores()
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
        for r in data.get("data", []):
            for col in ("BaizPersist", "BaizConviction"):
                r[col] = lookup(r.get("Ticker"), col, d)
        if add(out, data, backfilled=True):
            print("backfilled", d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="rebuild this many past sessions from git history")
    ap.add_argument("--rerank", action="store_true",
                    help="discard all lists and rebuild every logged session with the current rule")
    args = ap.parse_args()

    out = load_out()
    if args.rerank:
        args.backfill = max(args.backfill, len(out["entries"]))
        out = {"entries": []}
    if args.backfill:
        backfill(out, args.backfill)
    data = json.loads(LATEST.read_text(encoding="utf-8"))
    if add(out, data):
        print("added", data["date"])
    else:
        print(f"no new list (latest.json {data.get('date')}, midday={data.get('midday')})")
    fill_exits(out, data)
    save_out(out)


if __name__ == "__main__":
    main()
