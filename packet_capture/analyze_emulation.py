"""
Compare per-class delay, jitter and loss measured in the Wireshark capture
with the values predicted by the simulation, for each captured scheme.

Reads  results/capture_<scheme>.csv (TShark export) and
       results/packet_schedule_<scheme>.csv.
Writes results/wireshark_comparison.csv.

Run:  docker compose run --rm netpulse python packet_capture/analyze_emulation.py
"""
import struct
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
HEADER = struct.Struct("!4sIBBBIddd")
CLASS_NAMES = ["P0_combat", "P1_movement_voice", "P2_sync", "P3_idle"]


def parse_capture(path):
    raw = pd.read_csv(path, dtype={"udp.payload": str})
    rows = []
    for epoch, dscp, hexdata in zip(raw["frame.time_epoch"], raw["ip.dsfield.dscp"],
                                    raw["udp.payload"]):
        payload = bytes.fromhex(str(hexdata).replace(":", ""))
        if len(payload) < HEADER.size:
            continue
        magic, step, src, dst, prio, seq, nominal, delay, t0 = HEADER.unpack(payload[:HEADER.size])
        if magic != b"NPLS":
            continue
        frame_epoch = float(epoch)
        rows.append({
            "source": src, "destination": dst, "priority": prio, "seq": seq,
            "nominal_s": nominal, "sim_delay_ms": delay,
            "captured_delay_ms": (frame_epoch - t0 - nominal) * 1000.0,
            "dscp": dscp,
        })
    return pd.DataFrame(rows)


def jitter(df, col):
    return df.sort_values(["source", "destination", "nominal_s"]).groupby(
        ["source", "destination"])[col].apply(lambda s: s.diff().abs().mean()).mean()


def analyse(scheme):
    cap = parse_capture(RESULTS / f"capture_{scheme}.csv")
    sched = pd.read_csv(RESULTS / f"packet_schedule_{scheme}.csv")
    max_step = (cap.nominal_s.max() if len(cap) else 0)
    sched = sched[sched.time_s <= max_step + 1]
    out = []
    for k in range(4):
        c = cap[cap.priority == k]
        s = sched[sched.priority == k]
        if c.empty:
            continue
        out.append({
            "scheme": scheme,
            "class": CLASS_NAMES[k],
            "packets_captured": len(c),
            "sim_loss_pct": round(100 * s.dropped.mean(), 3),
            "sim_mean_delay_ms": round(c.sim_delay_ms.mean(), 3),
            "cap_mean_delay_ms": round(c.captured_delay_ms.mean(), 3),
            "sim_p99_ms": round(c.sim_delay_ms.quantile(0.99), 3),
            "cap_p99_ms": round(c.captured_delay_ms.quantile(0.99), 3),
            "sim_jitter_ms": round(float(jitter(c, "sim_delay_ms")), 4),
            "cap_jitter_ms": round(float(jitter(c, "captured_delay_ms")), 4),
            "dscp_values": ",".join(map(str, sorted(c.dscp.dropna().unique().astype(int)))),
        })
    return out


if __name__ == "__main__":
    rows = []
    for f in sorted(RESULTS.glob("capture_*.csv")):
        scheme = f.stem.replace("capture_", "")
        if not (RESULTS / f"packet_schedule_{scheme}.csv").exists():
            continue
        rows.extend(analyse(scheme))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print(df.to_string(index=False))
    df.to_csv(RESULTS / "wireshark_comparison.csv", index=False)
    print("Saved:", RESULTS / "wireshark_comparison.csv")
