import pandas as pd, statistics, csv
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "results"

PRIORITY_NAMES = ["P0_combat","P1_movement_voice","P2_sync","P3_idle","P4_bg"]
rows = []
for scheme in ["dijkstra_fifo","llq_standalone","ml_routing"]:
    df = pd.read_csv(R / f"packet_schedule_{scheme}.csv")
    for prio in range(5):
        sub = df[df.priority == prio]
        delivered = sub[sub.dropped == 0]["delay_ms"].tolist()
        if not delivered:
            continue
        ds = sorted(delivered)
        rows.append({
            "algorithm":     scheme,
            "class":         PRIORITY_NAMES[prio],
            "packets":       len(sub),
            "loss_pct":      round(sub.dropped.mean() * 100, 3),
            "mean_delay_ms": round(sum(delivered) / len(delivered), 3),
            "p95_delay_ms":  round(ds[int(0.95 * len(ds))], 3),
            "p99_delay_ms":  round(ds[int(0.99 * len(ds))], 3),
            "jitter_ms":     round(statistics.stdev(delivered) if len(delivered) > 1 else 0, 4),
            "mean_hops":     round(sub.hops.mean(), 2),
            "avg_util_pct":  0.0,
            "max_util_pct":  0.0,
        })

rows.sort(key=lambda r: (["dijkstra_fifo","llq_standalone","ml_routing"].index(r["algorithm"]), r["class"]))
with open(R / "three_algo_comparison.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print("=== P0_combat ===")
for r in rows:
    if r["class"] == "P0_combat":
        print(f"  {r['algorithm']:20s}  mean={r['mean_delay_ms']:7.1f}ms  p99={r['p99_delay_ms']:7.1f}ms  loss={r['loss_pct']:.1f}%  jitter={r['jitter_ms']:.1f}ms")
print("Done.")
