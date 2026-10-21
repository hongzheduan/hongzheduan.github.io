#!/usr/bin/env python3
"""
One-off repair (2026-10-21): rebuild data/baiz_score_trend.json and
data/baizscore_trailing.json after they froze at their 2026-08-19 commit.

scanner.yml's "Commit updated data" step backs up generated files, runs git stash +
rebase, then restores them, but these two were missing from the backup list, so every
scan's update was discarded. The live BaizPersist / BaizConviction since then were
computed from the frozen August window plus that day's score, i.e. wrong.

BaizScore and BaizMomentum themselves don't depend on history, and every session's
values were committed correctly in data/latest.json. This replays those from git
(last non-midday version per session date, after the frozen file's last session)
and recomputes BaizPersist / BaizConviction exactly as scanner_tiingo.py does.

Run from the repo root:  python backtests/rebuild_score_history_from_git.py
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREND = ROOT / "data" / "baiz_score_trend.json"
TRAILING = ROOT / "data" / "baizscore_trailing.json"
FROZEN_COMMIT = "35795100"     # last commit that touched both files (2026-08-19)
FROZEN_LAST_SESSION = "2026-08-14"  # matched against latest.json history: trend[-1] == 08-14
PERSIST_WINDOW = 21
TREND_WINDOW = 252
COLS = ["BaizScore", "BaizMomentum", "BaizPersist", "BaizConviction"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def sessions_after(last):
    """{date: latest.json payload} for each finished session after `last`, newest version per date."""
    out = {}
    for sha in git("log", "--since=2026-08-10", "--format=%H", "--", "data/latest.json").split():
        try:
            d = json.loads(git("show", f"{sha}:data/latest.json"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        date = d.get("date")
        if date and date > last and not d.get("midday") and date not in out:
            out[date] = d   # git log is newest first, so the first one seen is the final version
    return dict(sorted(out.items()))


def frozen_dates():
    """Session dates of the frozen trend file's positions, from candles.json as of that commit."""
    candles = json.loads(git("show", f"{FROZEN_COMMIT}:data/candles.json"))
    dates = [x for x in candles["dates"] if x <= FROZEN_LAST_SESSION]
    assert dates[-1] == FROZEN_LAST_SESSION, dates[-3:]
    return dates[-TREND_WINDOW:]


def main():
    trend = json.loads(git("show", f"{FROZEN_COMMIT}:data/baiz_score_trend.json"))
    dates = frozen_dates()
    sessions = sessions_after(FROZEN_LAST_SESSION)
    print(f"frozen trend ends {FROZEN_LAST_SESSION}; replaying {len(sessions)} sessions "
          f"{min(sessions)} .. {max(sessions)}")

    for date, payload in sessions.items():
        dates.append(date)
        for r in payload.get("data", []):
            t = r.get("Ticker")
            entry = trend.setdefault(t, {c: [] for c in COLS})
            score, mom = r.get("BaizScore"), r.get("BaizMomentum")
            entry["BaizScore"].append(score)
            entry["BaizMomentum"].append(mom)
            window = [v for v in entry["BaizScore"] if v is not None][-PERSIST_WINDOW:]
            if score is not None and len(window) >= PERSIST_WINDOW:
                persist = sum(window) / len(window)
                entry["BaizPersist"].append(round(persist))
                entry["BaizConviction"].append(round((persist * score) ** 0.5))
            else:
                entry["BaizPersist"].append(None)
                entry["BaizConviction"].append(None)

    last = max(sessions)
    trailing = {"__session__": last}
    for t, entry in trend.items():
        for c in COLS:
            entry[c] = entry[c][-TREND_WINDOW:]
        trailing[t] = [float(v) for v in entry["BaizScore"] if v is not None][-PERSIST_WINDOW:]
    trend["__session__"] = last
    trend["__dates__"] = dates[-TREND_WINDOW:]

    TREND.write_text(json.dumps(trend), encoding="utf-8")
    TRAILING.write_text(json.dumps(trailing), encoding="utf-8")
    print(f"wrote {TREND.name} and {TRAILING.name} through {last}")


if __name__ == "__main__":
    main()
