"""
Analyse the Wireshark capture of the 50-node router network.

For every packet (pkt_id) the per-hop datagrams are regrouped from the capture:
  * the path is reconstructed from the IP addresses (ip.src -> ip.dst) and
    checked against the route chosen by Dijkstra in the simulation,
  * end-to-end delay = arrival of the last hop - (t0 + nominal send time),
  * per-class delay, p99, jitter and loss are compared with the simulation.

Writes results/router_comparison.csv and results/router_path_check.csv.
Run: docker compose run --rm netpulse python packet_capture/analyze_router_capture.py
"""
import struct
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
HEADER = struct.Struct("!4sIBBBbdd13B12f")
CLASS_NAMES = ["P0_combat", "P1_movement_voice", "P2_sync", "P3_idle"]


def ip_to_node(ip):
    a, b, c, d = (int(x) for x in ip.split("."))
    return {1: f"R{d}", 2: f"S{d}", 3: f"PC{d}"}[c]


def parse(path):
    raw = pd.read_csv(path, dtype=str)
    rows = []
    for epoch, src, dst, dscp, hexdata in zip(raw["frame.time_epoch"], raw["ip.src"],
                                              raw["ip.dst"], raw["ip.dsfield.dscp"],
                                              raw["udp.payload"]):
        data = bytes.fromhex(str(hexdata).replace(":", ""))
        if len(data) < HEADER.size:
            continue
        f = HEADER.unpack(data[:HEADER.size])
        if f[0] != b"NPRT":
            continue
        rows.append({"pkt_id": f[1], "prio": f[2], "nominal": f[6], "t0": f[7],
                     "epoch": float(epoch), "src": ip_to_node(src), "dst": ip_to_node(dst),
                     "dscp": int(dscp)})
    return pd.DataFrame(rows)


def jitter(df, col):
    return df.sort_values(["source", "destination", "nominal"]).groupby(
        ["source", "destination"])[col].apply(lambda s: s.diff().abs().mean()).mean()


def analyse(scheme):
    frames = parse(RESULTS / f"router_{scheme}.csv")
    sched = pd.read_csv(RESULTS / f"packet_schedule_{scheme}.csv")
    sched["pkt_id"] = sched.index
    sched = sched[sched.pkt_id.isin(frames.pkt_id.unique()) | (sched.step < frames.nominal.max())]
    sched = sched[sched.step < int(frames.nominal.max()) + 1]

    packets = []
    for pid, g in frames.groupby("pkt_id"):
        g = g.sort_values("epoch")
        path = [g.iloc[0].src] + list(g.dst)
        packets.append({
            "pkt_id": pid,
            "captured_path": " -> ".join(path),
            "captured_delay_ms": (g.epoch.iloc[-1] - g.t0.iloc[0] - g.nominal.iloc[0]) * 1000,
            "hop_frames": len(g),
            "dscp": int(g.dscp.iloc[0]),
        })
    cap = pd.DataFrame(packets).merge(sched, on="pkt_id", suffixes=("", "_sim"))
    cap["delivered"] = cap.dropped == 0
    cap["path_match"] = cap.captured_path == cap.path
    check = cap[cap.delivered]

    out = []
    for k in range(4):
        s = sched[sched.priority == k]
        c = cap[(cap.priority == k) & cap.delivered].rename(columns={"time_s": "nominal"})
        if c.empty:
            continue
        out.append({
            "scheme": scheme, "class": CLASS_NAMES[k], "delivered": len(c),
            "sim_loss_pct": round(100 * s.dropped.mean(), 3),
            "paths_match_pct": round(100 * c.path_match.mean(), 2),
            "sim_mean_ms": round(c.delay_ms.mean(), 3),
            "cap_mean_ms": round(c.captured_delay_ms.mean(), 3),
            "sim_p99_ms": round(c.delay_ms.quantile(0.99), 3),
            "cap_p99_ms": round(c.captured_delay_ms.quantile(0.99), 3),
            "sim_jitter_ms": round(float(jitter(c, "delay_ms")), 4),
            "cap_jitter_ms": round(float(jitter(c, "captured_delay_ms")), 4),
            "dscp": ",".join(map(str, sorted(c.dscp.unique()))),
        })
    return out, check[["pkt_id", "source", "destination", "priority", "path", "captured_path",
                       "path_match", "delay_ms", "captured_delay_ms"]].assign(scheme=scheme)


if __name__ == "__main__":
    rows, checks = [], []
    for f in sorted(RESULTS.glob("router_*.csv")):
        scheme = f.stem.replace("router_", "")
        if not (RESULTS / f"packet_schedule_{scheme}.csv").exists():
            continue
        r, c = analyse(scheme)
        rows.extend(r)
        checks.append(c)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 20)
    print(df.to_string(index=False))
    df.to_csv(RESULTS / "router_comparison.csv", index=False)
    pd.concat(checks).to_csv(RESULTS / "router_path_check.csv", index=False)
    print("Saved router_comparison.csv and router_path_check.csv")
