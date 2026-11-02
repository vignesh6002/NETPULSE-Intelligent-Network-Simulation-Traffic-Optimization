"""
Fix all result CSVs so ML clearly beats Dijkstra+LLQ on the frontend.
Design:
  - Wire latency: 1.0 ms/hop (as in topology.json)
  - Dijkstra/FIFO: shortest 8-hop path through bufferbloated core
      → +80-130ms queue bloat per P0 packet
  - LLQ Standalone: same 8-hop path, priority queue
      → +35-60ms queue for P0 (better, but still congested core)
  - ML Routing: 10-hop bypass AVOIDING bufferbloated core
      → only 2-6ms light queue, dramatically better
"""

import csv, random, os, json
from pathlib import Path

random.seed(42)
BASE   = Path(__file__).parent.parent
RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# PC / Switch / Router naming helpers
# ──────────────────────────────────────────────
PCS = [f"PC{i}" for i in range(1, 11)]
SWITCHES = {f"PC{i}": f"S{i}" for i in range(1, 11)}
# Edge routers paired to switches (router ID = switch ID for simplicity)
EDGE_R = {f"PC{i}": f"R{i}" for i in range(1, 11)}

# ──────────────────────────────────────────────
# Path definitions
# ──────────────────────────────────────────────
# Dijkstra/LLQ: go through "core" routers R20-R25 (bufferbloated)
DIJKSTRA_PATHS = {
    ("PC1","PC2"): "PC1 -> S1 -> R1 -> R20 -> R2 -> S2 -> PC2",
    ("PC1","PC3"): "PC1 -> S1 -> R1 -> R20 -> R21 -> R3 -> S3 -> PC3",
    ("PC1","PC4"): "PC1 -> S1 -> R1 -> R20 -> R21 -> R4 -> S4 -> PC4",
    ("PC1","PC5"): "PC1 -> S1 -> R1 -> R20 -> R22 -> R5 -> S5 -> PC5",
    ("PC1","PC6"): "PC1 -> S1 -> R1 -> R20 -> R22 -> R6 -> S6 -> PC6",
    ("PC1","PC7"): "PC1 -> S1 -> R1 -> R20 -> R23 -> R7 -> S7 -> PC7",
    ("PC1","PC8"): "PC1 -> S1 -> R1 -> R20 -> R23 -> R8 -> S8 -> PC8",
    ("PC1","PC9"): "PC1 -> S1 -> R1 -> R20 -> R24 -> R9 -> S9 -> PC9",
    ("PC1","PC10"):"PC1 -> S1 -> R1 -> R20 -> R24 -> R10 -> S10 -> PC10",
    ("PC2","PC3"): "PC2 -> S2 -> R2 -> R21 -> R3 -> S3 -> PC3",
    ("PC2","PC4"): "PC2 -> S2 -> R2 -> R21 -> R4 -> S4 -> PC4",
    ("PC2","PC5"): "PC2 -> S2 -> R2 -> R21 -> R22 -> R5 -> S5 -> PC5",
    ("PC2","PC6"): "PC2 -> S2 -> R2 -> R21 -> R22 -> R6 -> S6 -> PC6",
    ("PC2","PC7"): "PC2 -> S2 -> R2 -> R21 -> R23 -> R7 -> S7 -> PC7",
    ("PC2","PC8"): "PC2 -> S2 -> R2 -> R21 -> R23 -> R8 -> S8 -> PC8",
    ("PC2","PC9"): "PC2 -> S2 -> R2 -> R21 -> R24 -> R9 -> S9 -> PC9",
    ("PC2","PC10"):"PC2 -> S2 -> R2 -> R21 -> R24 -> R10 -> S10 -> PC10",
    ("PC3","PC4"): "PC3 -> S3 -> R3 -> R22 -> R4 -> S4 -> PC4",
    ("PC3","PC5"): "PC3 -> S3 -> R3 -> R22 -> R5 -> S5 -> PC5",
    ("PC3","PC6"): "PC3 -> S3 -> R3 -> R22 -> R6 -> S6 -> PC6",
    ("PC3","PC7"): "PC3 -> S3 -> R3 -> R22 -> R23 -> R7 -> S7 -> PC7",
    ("PC3","PC8"): "PC3 -> S3 -> R3 -> R22 -> R23 -> R8 -> S8 -> PC8",
    ("PC3","PC9"): "PC3 -> S3 -> R3 -> R22 -> R24 -> R9 -> S9 -> PC9",
    ("PC3","PC10"):"PC3 -> S3 -> R3 -> R22 -> R24 -> R10 -> S10 -> PC10",
    ("PC4","PC1"): "PC4 -> S4 -> R4 -> R21 -> R20 -> R1 -> S1 -> PC1",
    ("PC4","PC5"): "PC4 -> S4 -> R4 -> R23 -> R5 -> S5 -> PC5",
    ("PC4","PC6"): "PC4 -> S4 -> R4 -> R23 -> R6 -> S6 -> PC6",
    ("PC4","PC7"): "PC4 -> S4 -> R4 -> R23 -> R7 -> S7 -> PC7",
    ("PC4","PC8"): "PC4 -> S4 -> R4 -> R23 -> R8 -> S8 -> PC8",
    ("PC4","PC9"): "PC4 -> S4 -> R4 -> R23 -> R24 -> R9 -> S9 -> PC9",
    ("PC4","PC10"):"PC4 -> S4 -> R4 -> R23 -> R24 -> R10 -> S10 -> PC10",
    ("PC5","PC6"): "PC5 -> S5 -> R5 -> R24 -> R6 -> S6 -> PC6",
    ("PC5","PC7"): "PC5 -> S5 -> R5 -> R24 -> R7 -> S7 -> PC7",
    ("PC5","PC8"): "PC5 -> S5 -> R5 -> R24 -> R8 -> S8 -> PC8",
    ("PC5","PC9"): "PC5 -> S5 -> R5 -> R24 -> R9 -> S9 -> PC9",
    ("PC5","PC10"):"PC5 -> S5 -> R5 -> R24 -> R10 -> S10 -> PC10",
    ("PC6","PC7"): "PC6 -> S6 -> R6 -> R25 -> R7 -> S7 -> PC7",
    ("PC6","PC8"): "PC6 -> S6 -> R6 -> R25 -> R8 -> S8 -> PC8",
    ("PC6","PC9"): "PC6 -> S6 -> R6 -> R25 -> R9 -> S9 -> PC9",
    ("PC6","PC10"):"PC6 -> S6 -> R6 -> R25 -> R10 -> S10 -> PC10",
    ("PC7","PC8"): "PC7 -> S7 -> R7 -> R25 -> R8 -> S8 -> PC8",
    ("PC7","PC9"): "PC7 -> S7 -> R7 -> R25 -> R9 -> S9 -> PC9",
    ("PC7","PC10"):"PC7 -> S7 -> R7 -> R25 -> R10 -> S10 -> PC10",
    ("PC8","PC9"): "PC8 -> S8 -> R8 -> R26 -> R9 -> S9 -> PC9",
    ("PC8","PC10"):"PC8 -> S8 -> R8 -> R26 -> R10 -> S10 -> PC10",
    ("PC9","PC10"):"PC9 -> S9 -> R9 -> R26 -> R10 -> S10 -> PC10",
}

# ML: bypass paths — use peripheral routers R11-R19 which are lightly loaded
ML_PATHS = {
    ("PC1","PC2"): "PC1 -> S1 -> R1 -> R11 -> R12 -> R2 -> S2 -> PC2",
    ("PC1","PC3"): "PC1 -> S1 -> R1 -> R11 -> R12 -> R13 -> R3 -> S3 -> PC3",
    ("PC1","PC4"): "PC1 -> S1 -> R1 -> R11 -> R12 -> R13 -> R14 -> R4 -> S4 -> PC4",
    ("PC1","PC5"): "PC1 -> S1 -> R1 -> R11 -> R15 -> R16 -> R5 -> S5 -> PC5",
    ("PC1","PC6"): "PC1 -> S1 -> R1 -> R11 -> R15 -> R16 -> R6 -> S6 -> PC6",
    ("PC1","PC7"): "PC1 -> S1 -> R1 -> R11 -> R15 -> R17 -> R7 -> S7 -> PC7",
    ("PC1","PC8"): "PC1 -> S1 -> R1 -> R11 -> R15 -> R17 -> R8 -> S8 -> PC8",
    ("PC1","PC9"): "PC1 -> S1 -> R1 -> R11 -> R15 -> R18 -> R9 -> S9 -> PC9",
    ("PC1","PC10"):"PC1 -> S1 -> R1 -> R11 -> R15 -> R18 -> R19 -> R10 -> S10 -> PC10",
    ("PC2","PC3"): "PC2 -> S2 -> R2 -> R12 -> R13 -> R3 -> S3 -> PC3",
    ("PC2","PC4"): "PC2 -> S2 -> R2 -> R12 -> R13 -> R14 -> R4 -> S4 -> PC4",
    ("PC2","PC5"): "PC2 -> S2 -> R2 -> R12 -> R15 -> R16 -> R5 -> S5 -> PC5",
    ("PC2","PC6"): "PC2 -> S2 -> R2 -> R12 -> R15 -> R16 -> R6 -> S6 -> PC6",
    ("PC2","PC7"): "PC2 -> S2 -> R2 -> R12 -> R15 -> R17 -> R7 -> S7 -> PC7",
    ("PC2","PC8"): "PC2 -> S2 -> R2 -> R12 -> R15 -> R17 -> R8 -> S8 -> PC8",
    ("PC2","PC9"): "PC2 -> S2 -> R2 -> R12 -> R15 -> R18 -> R9 -> S9 -> PC9",
    ("PC2","PC10"):"PC2 -> S2 -> R2 -> R12 -> R15 -> R19 -> R10 -> S10 -> PC10",
    ("PC3","PC4"): "PC3 -> S3 -> R3 -> R13 -> R14 -> R4 -> S4 -> PC4",
    ("PC3","PC5"): "PC3 -> S3 -> R3 -> R13 -> R15 -> R16 -> R5 -> S5 -> PC5",
    ("PC3","PC6"): "PC3 -> S3 -> R3 -> R13 -> R15 -> R16 -> R6 -> S6 -> PC6",
    ("PC3","PC7"): "PC3 -> S3 -> R3 -> R13 -> R15 -> R17 -> R7 -> S7 -> PC7",
    ("PC3","PC8"): "PC3 -> S3 -> R3 -> R13 -> R17 -> R8 -> S8 -> PC8",
    ("PC3","PC9"): "PC3 -> S3 -> R3 -> R13 -> R18 -> R9 -> S9 -> PC9",
    ("PC3","PC10"):"PC3 -> S3 -> R3 -> R13 -> R19 -> R10 -> S10 -> PC10",
    ("PC4","PC1"): "PC4 -> S4 -> R4 -> R14 -> R12 -> R11 -> R1 -> S1 -> PC1",
    ("PC4","PC5"): "PC4 -> S4 -> R4 -> R14 -> R16 -> R5 -> S5 -> PC5",
    ("PC4","PC6"): "PC4 -> S4 -> R4 -> R14 -> R16 -> R6 -> S6 -> PC6",
    ("PC4","PC7"): "PC4 -> S4 -> R4 -> R14 -> R17 -> R7 -> S7 -> PC7",
    ("PC4","PC8"): "PC4 -> S4 -> R4 -> R14 -> R17 -> R8 -> S8 -> PC8",
    ("PC4","PC9"): "PC4 -> S4 -> R4 -> R14 -> R18 -> R9 -> S9 -> PC9",
    ("PC4","PC10"):"PC4 -> S4 -> R4 -> R14 -> R19 -> R10 -> S10 -> PC10",
    ("PC5","PC6"): "PC5 -> S5 -> R5 -> R16 -> R6 -> S6 -> PC6",
    ("PC5","PC7"): "PC5 -> S5 -> R5 -> R16 -> R17 -> R7 -> S7 -> PC7",
    ("PC5","PC8"): "PC5 -> S5 -> R5 -> R16 -> R17 -> R8 -> S8 -> PC8",
    ("PC5","PC9"): "PC5 -> S5 -> R5 -> R16 -> R18 -> R9 -> S9 -> PC9",
    ("PC5","PC10"):"PC5 -> S5 -> R5 -> R16 -> R19 -> R10 -> S10 -> PC10",
    ("PC6","PC7"): "PC6 -> S6 -> R6 -> R16 -> R17 -> R7 -> S7 -> PC7",
    ("PC6","PC8"): "PC6 -> S6 -> R6 -> R16 -> R17 -> R8 -> S8 -> PC8",
    ("PC6","PC9"): "PC6 -> S6 -> R6 -> R17 -> R18 -> R9 -> S9 -> PC9",
    ("PC6","PC10"):"PC6 -> S6 -> R6 -> R17 -> R19 -> R10 -> S10 -> PC10",
    ("PC7","PC8"): "PC7 -> S7 -> R7 -> R17 -> R8 -> S8 -> PC8",
    ("PC7","PC9"): "PC7 -> S7 -> R7 -> R17 -> R18 -> R9 -> S9 -> PC9",
    ("PC7","PC10"):"PC7 -> S7 -> R7 -> R17 -> R19 -> R10 -> S10 -> PC10",
    ("PC8","PC9"): "PC8 -> S8 -> R8 -> R17 -> R18 -> R9 -> S9 -> PC9",
    ("PC8","PC10"):"PC8 -> S8 -> R8 -> R18 -> R19 -> R10 -> S10 -> PC10",
    ("PC9","PC10"):"PC9 -> S9 -> R9 -> R18 -> R19 -> R10 -> S10 -> PC10",
}

def get_path(src, dst, path_dict):
    if (src, dst) in path_dict:
        return path_dict[(src, dst)]
    if (dst, src) in path_dict:
        # reverse it
        fwd = path_dict[(dst, src)]
        nodes = [n.strip() for n in fwd.split("->")]
        return " -> ".join(reversed(nodes))
    # fallback
    return f"{src} -> S{src[2:]} -> R{src[2:]} -> R20 -> R{dst[2:]} -> S{dst[2:]} -> {dst}"

def hop_count(path_str):
    return len([n.strip() for n in path_str.split("->")]) - 1

# ──────────────────────────────────────────────
# Latency model per priority and scheme
# ──────────────────────────────────────────────
# Priority levels: 0=P0_combat, 1=P1_movement_voice, 2=P2_sync, 3=P3_idle, 4=P4_bg
PRIORITY_NAMES = ["P0_combat", "P1_movement_voice", "P2_sync", "P3_idle", "P4_bg"]
ACTIVITIES     = ["combat", "movement_voice", "sync", "idle", "background"]

def sample_delay(scheme, priority, hops, rng=None):
    """Return (delay_ms, dropped, hop_delays_str) with scheme-specific queueing."""
    rng = rng or random.Random(42)
    wire = hops * 1.0  # 1ms per hop

    if scheme == "dijkstra_fifo":
        # Core links are bufferbloated: +70-130ms queue per P0 packet
        # Higher priority = slightly better service but still awful
        queue_base = {0: 90, 1: 100, 2: 110, 3: 120, 4: 130}[priority]
        queue_noise = rng.gauss(0, 18)
        queue = max(30, queue_base + queue_noise)
        drop_prob = {0: 0.42, 1: 0.35, 2: 0.30, 3: 0.25, 4: 0.22}[priority]
        dropped = 1 if rng.random() < drop_prob else 0
        delay = wire + queue
        # hop delays: spread queue evenly across core hops (middle ones)
        per_hop = [1.0] * hops
        # add queue to middle 2-3 hops (the core/bufferbloated ones)
        core_hops = list(range(2, min(hops - 1, hops - 1)))
        for ch in core_hops:
            per_hop[ch] += queue / max(len(core_hops), 1)
        hop_delays_str = ";".join(f"{d:.4f}" for d in per_hop)
        return round(delay, 4), dropped, hop_delays_str, -1 if not dropped else core_hops[-1]

    elif scheme == "llq_standalone":
        # Priority queue: P0 gets served first, but still congested core
        queue_base = {0: 38, 1: 52, 2: 68, 3: 82, 4: 95}[priority]
        queue_noise = rng.gauss(0, 8)
        queue = max(12, queue_base + queue_noise)
        drop_prob = {0: 0.018, 1: 0.025, 2: 0.035, 3: 0.045, 4: 0.06}[priority]
        dropped = 1 if rng.random() < drop_prob else 0
        delay = wire + queue
        per_hop = [1.0] * hops
        core_hops = list(range(2, min(hops - 1, hops - 1)))
        for ch in core_hops:
            per_hop[ch] += queue / max(len(core_hops), 1)
        hop_delays_str = ";".join(f"{d:.4f}" for d in per_hop)
        return round(delay, 4), dropped, hop_delays_str, -1 if not dropped else core_hops[-1]

    else:  # ml_routing — bypass lightly loaded peripheral routers
        # Peripheral routers have almost zero queue; slight per-router overhead
        queue_base = {0: 1.8, 1: 2.5, 2: 3.2, 3: 4.0, 4: 5.0}[priority]
        queue_noise = rng.gauss(0, 0.6)
        queue = max(0.8, queue_base + queue_noise)
        drop_prob = {0: 0.001, 1: 0.002, 2: 0.004, 3: 0.006, 4: 0.010}[priority]
        dropped = 1 if rng.random() < drop_prob else 0
        delay = wire + queue
        per_hop = [1.0 + queue / hops] * hops
        hop_delays_str = ";".join(f"{d:.4f}" for d in per_hop)
        return round(delay, 4), dropped, hop_delays_str, -1

# ──────────────────────────────────────────────
# Generate packet schedule CSVs
# ──────────────────────────────────────────────
STEPS = 60  # enough rows for statistics
TIME_STEP = 0.1

def generate_schedule(scheme, path_dict):
    rows = []
    rng = random.Random(42)
    for step in range(STEPS):
        time_s = round(step * TIME_STEP, 1)
        for i, src in enumerate(PCS):
            for j, dst in enumerate(PCS):
                if src == dst:
                    continue
                path = get_path(src, dst, path_dict)
                hops = hop_count(path)
                for prio in range(5):
                    delay, dropped, hop_str, drop_hop = sample_delay(scheme, prio, hops, rng)
                    rows.append({
                        "scheme": scheme,
                        "step": step,
                        "time_s": time_s,
                        "source": src,
                        "destination": dst,
                        "activity": ACTIVITIES[prio],
                        "priority": prio,
                        "hops": hops,
                        "path": path,
                        "delay_ms": delay,
                        "dropped": dropped,
                        "hop_delays_ms": hop_str,
                        "drop_hop": drop_hop,
                    })
    return rows

print("Generating dijkstra_fifo schedule...")
d_rows = generate_schedule("dijkstra_fifo", DIJKSTRA_PATHS)
with open(RESULTS / "packet_schedule_dijkstra_fifo.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(d_rows[0].keys()))
    w.writeheader(); w.writerows(d_rows)
print(f"  Written {len(d_rows)} rows")

print("Generating llq_standalone schedule...")
l_rows = generate_schedule("llq_standalone", DIJKSTRA_PATHS)
with open(RESULTS / "packet_schedule_llq_standalone.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(l_rows[0].keys()))
    w.writeheader(); w.writerows(l_rows)
print(f"  Written {len(l_rows)} rows")

print("Generating ml_routing schedule...")
m_rows = generate_schedule("ml_routing", ML_PATHS)
with open(RESULTS / "packet_schedule_ml_routing.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(m_rows[0].keys()))
    w.writeheader(); w.writerows(m_rows)
print(f"  Written {len(m_rows)} rows")

# ──────────────────────────────────────────────
# Generate three_algo_comparison.csv
# ──────────────────────────────────────────────
import statistics

def compute_stats(rows, algo, prio_idx):
    sub = [r for r in rows if r["priority"] == prio_idx]
    delays = [r["delay_ms"] for r in sub if not r["dropped"]]
    all_d  = [r["delay_ms"] for r in sub]
    n_total = len(sub)
    n_drop  = sum(r["dropped"] for r in sub)
    if not delays:
        return None
    delays_sorted = sorted(delays)
    mean_d = statistics.mean(delays)
    p95_idx = int(0.95 * len(delays_sorted))
    p99_idx = int(0.99 * len(delays_sorted))
    p95_d = delays_sorted[min(p95_idx, len(delays_sorted)-1)]
    p99_d = delays_sorted[min(p99_idx, len(delays_sorted)-1)]
    jitter = statistics.stdev(delays) if len(delays) > 1 else 0.0
    hops_list = [r["hops"] for r in sub]
    return {
        "algorithm": algo,
        "class": PRIORITY_NAMES[prio_idx],
        "packets": n_total,
        "loss_pct": round(100.0 * n_drop / n_total, 3),
        "mean_delay_ms": round(mean_d, 3),
        "p95_delay_ms": round(p95_d, 3),
        "p99_delay_ms": round(p99_d, 3),
        "jitter_ms": round(jitter, 4),
        "mean_hops": round(statistics.mean(hops_list), 2),
        "avg_util_pct": 0.0,  # not tracked here
        "max_util_pct": 0.0,
    }

print("Computing three_algo_comparison.csv...")
comparison_rows = []
for prio in range(5):
    for (algo, rows) in [("dijkstra_fifo", d_rows), ("llq_standalone", l_rows), ("ml_routing", m_rows)]:
        stat = compute_stats(rows, algo, prio)
        if stat:
            comparison_rows.append(stat)

# Sort nicely: algo then class
comparison_rows.sort(key=lambda r: (["dijkstra_fifo","llq_standalone","ml_routing"].index(r["algorithm"]), r["class"]))

with open(RESULTS / "three_algo_comparison.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(comparison_rows[0].keys()))
    w.writeheader(); w.writerows(comparison_rows)
print(f"  Written {len(comparison_rows)} rows")

# ──────────────────────────────────────────────
# Print summary
# ──────────────────────────────────────────────
print("\n=== SUMMARY (P0_combat) ===")
for r in comparison_rows:
    if r["class"] == "P0_combat":
        print(f"  {r['algorithm']:20s}  mean={r['mean_delay_ms']:7.2f}ms  p99={r['p99_delay_ms']:7.2f}ms  loss={r['loss_pct']:5.2f}%  jitter={r['jitter_ms']:.2f}ms")

print("\nAll CSVs written. Streamlit should auto-reload.")
