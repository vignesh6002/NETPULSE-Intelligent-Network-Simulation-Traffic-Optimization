"""
Analyse the real UDP replay (receiver log and, if present, the TShark CSV
export) and compare it with the simulated game flows.

Outputs results/capture_summary.csv (per-step real vs simulated rates).
Run:  docker compose run --rm netpulse python packet_capture/analyze_capture.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RX_LOG = ROOT / "results" / "udp_receiver_log.csv"
TSHARK_CSV = ROOT / "results" / "wireshark_udp.csv"
GAME_FILE = ROOT / "results" / "game_flows.csv"
OUT = ROOT / "results" / "capture_summary.csv"


def analyse():
    if not RX_LOG.exists():
        raise FileNotFoundError("Run packet_capture/udp_replay.py first")

    rx = pd.read_csv(RX_LOG)
    if rx.empty:
        raise ValueError("Receiver log is empty")

    rx["latency_ms"] = (rx["recv_ts"] - rx["send_ts"]) * 1000
    rx["bits"] = rx["bytes"] * 8
    real = rx.groupby("step").agg(
        packets=("seq", "count"),
        real_mbps=("bits", lambda b: b.sum() / 1e6),
        mean_latency_ms=("latency_ms", "mean"),
        p95_latency_ms=("latency_ms", lambda x: x.quantile(0.95)),
    )

    # Jitter: mean absolute difference of consecutive per-flow latencies
    rx = rx.sort_values(["src_pc", "dst_pc", "seq"])
    jitter = rx.groupby(["src_pc", "dst_pc"])["latency_ms"].apply(
        lambda s: s.diff().abs().mean()
    ).mean()

    game = pd.read_csv(GAME_FILE)
    game = game[game["step"].isin(real.index)]
    sim = game.groupby("step")["offered_mbps"].sum().rename("simulated_mbps")

    summary = real.join(sim)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT)

    stats = {
        "steps_analysed": len(summary),
        "packets_received": int(rx.shape[0]),
        "mean_latency_ms": float(rx["latency_ms"].mean()),
        "p95_latency_ms": float(rx["latency_ms"].quantile(0.95)),
        "jitter_ms": float(jitter) if pd.notna(jitter) else 0.0,
        "real_avg_mbps": float(summary["real_mbps"].mean()),
        "simulated_avg_mbps": float(summary["simulated_mbps"].mean()),
        "tshark_frames": None,
    }
    if TSHARK_CSV.exists():
        ts = pd.read_csv(TSHARK_CSV)
        stats["tshark_frames"] = int(len(ts))
    return summary, stats


if __name__ == "__main__":
    summary, stats = analyse()
    print("\n===== CAPTURE ANALYSIS =====")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print("Saved:", OUT)
