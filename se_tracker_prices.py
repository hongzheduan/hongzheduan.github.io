"""SE Tracker: price of each added / removed stock one month after the index change.

Reads data/index_changes.json and writes data/se_tracker_prices.json, shown in the
"1 month later" table at the bottom of se_tracker.html. Added 2026-10-24.

Removed tickers are no longer in data/candles.json, so closes come from Yahoo's
public chart endpoint (stdlib only, the workflow has no pip step).
  - Start = close on the change date (or the next trading day if it was a holiday).
  - One month later = close on the first trading day on or after the same calendar
    day of the next month (e.g. 2026-09-22 -> 2026-10-22).
  - % change uses adjusted closes so a split inside the month doesn't distort it;
    the prices shown are the actual closes.
  - No bar on or after the 1-month date yet -> "pending" (current close shown instead).
  - Ticker with no price history (acquired / delisted) -> "unavailable".
Run: python se_tracker_prices.py
"""
import calendar
import json
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "index_changes.json"
OUT = ROOT / "data" / "se_tracker_prices.json"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1={p1}&period2={p2}&interval=1d"
IDX = ("sp500", "nasdaq100")


def plus_one_month(d):
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fetch(ticker, start):
    """[(date, close, adjclose)] from `start` to today, oldest first; [] on failure."""
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(time.time()) + 86400
    req = urllib.request.Request(URL.format(t=ticker.replace(".", "-"), p1=p1, p2=p2),
                                 headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except Exception as e:
            if attempt == 2:
                print(f"  {ticker}: fetch failed ({e})")
                return []
            time.sleep(2 * (attempt + 1))
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    # Yahoo timestamps are the session open in exchange time; shift by the GMT offset
    # so the calendar date is the US trading date.
    off = res.get("meta", {}).get("gmtoffset", -14400)
    bars = []
    for t, c, a in zip(ts, q["close"], adj):
        if c is None or a is None:
            continue
        bars.append((datetime.fromtimestamp(t + off, tz=timezone.utc).date(), c, a))
    return bars


def first_on_or_after(bars, d):
    return next((b for b in bars if b[0] >= d), None)


def main():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    events = []
    for e in src.get("entries", []):
        for k in IDX:
            x = e.get(k) or {}
            for t in x.get("added") or []:
                events.append((e["date"], k, True, t))
            for t in x.get("removed") or []:
                events.append((e["date"], k, False, t))

    cache = {}
    rows = []
    for d_iso, idx, added, t in events:
        d0 = date.fromisoformat(d_iso)
        if t not in cache:
            earliest = min(date.fromisoformat(ev[0]) for ev in events if ev[3] == t)
            cache[t] = fetch(t, earliest - timedelta(days=7))
        bars = cache[t]
        target = plus_one_month(d0)
        row = {"date": d_iso, "idx": idx, "added": added, "ticker": t, "dueDate": target.isoformat()}
        start = first_on_or_after(bars, d0)
        if not start or (start[0] - d0).days > 7:
            row["status"] = "unavailable"
            rows.append(row)
            continue
        row["startDate"], row["startClose"] = start[0].isoformat(), round(start[1], 2)
        end = first_on_or_after(bars, target)
        if end:
            row["status"] = "done"
            row["endDate"], row["endClose"] = end[0].isoformat(), round(end[1], 2)
            row["pct"] = round((end[2] / start[2] - 1) * 100, 2)
        else:
            last = bars[-1]
            # A ticker whose history stops well before the 1-month date was acquired / delisted.
            row["status"] = "pending" if (date.today() - last[0]).days <= 7 else "unavailable"
            row["lastDate"], row["lastClose"] = last[0].isoformat(), round(last[1], 2)
            row["pct"] = round((last[2] / start[2] - 1) * 100, 2)
        rows.append(row)

    rows.sort(key=lambda r: r["date"], reverse=True)
    out = {"updated": date.today().isoformat(), "rows": rows}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    n = {s: sum(r["status"] == s for r in rows) for s in ("done", "pending", "unavailable")}
    print(f"wrote {OUT.name}: {len(rows)} rows {n}")


if __name__ == "__main__":
    main()
