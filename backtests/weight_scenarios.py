"""
Test alternate BaizScore weight schemes against the same 70/80/90 forward-return
backtest, reusing the component scores already saved in baiz_score_history.csv
(RSScore, MomentumScore, BreakoutScore, TrendScore, VolPressureScore) — no
refetch needed.
"""
import pandas as pd
import json

df = pd.read_csv("baiz_score_history.csv")

rs_norm = (df["RSScore"] - 1) / 98 * 100
vp_norm = (df["VolPressureScore"] + 100) / 2

SCENARIOS = {
    "current":            {"rs": 0.30, "mom": 0.25, "brk": 0.20, "trend": 0.15, "vp": 0.10},
    "equal":              {"rs": 0.20, "mom": 0.20, "brk": 0.20, "trend": 0.20, "vp": 0.20},
    "pure_momentum":      {"rs": 0.50, "mom": 0.50, "brk": 0.00, "trend": 0.00, "vp": 0.00},
    "momentum_amplified": {"rs": 0.40, "mom": 0.35, "brk": 0.15, "trend": 0.05, "vp": 0.05},
    "technical_tilted":   {"rs": 0.10, "mom": 0.10, "brk": 0.40, "trend": 0.10, "vp": 0.30},
    "trend_consistency":  {"rs": 0.20, "mom": 0.15, "brk": 0.10, "trend": 0.45, "vp": 0.10},
}

horizons = ["1M", "3M", "6M", "9M", "1Y"]
thresholds = [70, 80, 90]

all_results = {}

for name, w in SCENARIOS.items():
    score = (
        w["rs"] * rs_norm + w["mom"] * df["MomentumScore"] + w["brk"] * df["BreakoutScore"]
        + w["trend"] * df["TrendScore"] + w["vp"] * vp_norm
    ).round().clip(0, 100)

    scen_result = {"weights": w, "thresholds": {}}
    for thresh in thresholds:
        hi = df[score >= thresh]
        rows = []
        for h in horizons:
            col = f"Fwd{h}"
            base = df[col].dropna()
            b = hi[col].dropna()
            rows.append({
                "horizon": h,
                "n": int(len(b)),
                "mean": round(float(b.mean()), 3) if len(b) else None,
                "median": round(float(b.median()), 3) if len(b) else None,
                "win": round(float((b > 0).mean() * 100), 2) if len(b) else None,
                "edge_mean": round(float(b.mean() - base.mean()), 3) if len(b) else None,
                "edge_median": round(float(b.median() - base.median()), 3) if len(b) else None,
            })
        scen_result["thresholds"][thresh] = {
            "n_obs": int(len(hi)),
            "pct_of_total": round(len(hi) / len(df) * 100, 3),
            "rows": rows,
        }
    all_results[name] = scen_result

    print(f"\n=== {name}  (RS={w['rs']*100:.0f} Mom={w['mom']*100:.0f} Brk={w['brk']*100:.0f} "
          f"Trend={w['trend']*100:.0f} VP={w['vp']*100:.0f}) ===")
    for thresh in thresholds:
        t = scen_result["thresholds"][thresh]
        print(f"  >= {thresh}: N={t['n_obs']:6d} ({t['pct_of_total']:.2f}%)")
        for r in t["rows"]:
            if r["n"] > 0:
                print(f"    {r['horizon']}: N={r['n']:6d}  mean={r['mean']:7.3f}%  "
                      f"median={r['median']:7.3f}%  win={r['win']:5.2f}%  "
                      f"edge_mean={r['edge_mean']:7.3f}pp  edge_median={r['edge_median']:7.3f}pp")
            else:
                print(f"    {r['horizon']}: N=0 (no observations at this threshold)")

with open("weight_scenarios_results.json", "w") as f:
    json.dump(all_results, f, indent=2)

print("\nSaved weight_scenarios_results.json")
