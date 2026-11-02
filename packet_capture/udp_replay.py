"""
NETPULSE real UDP replay (runs natively on Windows, standard library only).

Replays results/game_flows.csv as REAL UDP packets over loopback so that
Wireshark/TShark can capture them (use the "Npcap Loopback Adapter").
Each PC maps to its own UDP port (PC<n> -> BASE_PORT + n), so Wireshark
can filter per-flow with e.g.  udp.port == 50003.

Payload header (big-endian): magic(4s) step(I) src_pc(B) dst_pc(B) seq(I) send_ts(d)
padded to PACKET_BYTES.

Usage:
    python packet_capture/udp_replay.py --steps 30 --speed 1.0
"""
import argparse
import csv
import select
import socket
import struct
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_FILE = ROOT / "results" / "game_flows.csv"
RX_LOG = ROOT / "results" / "udp_receiver_log.csv"

HOST = "127.0.0.1"
BASE_PORT = 50000
PACKET_BYTES = 500
HEADER = struct.Struct("!4sIBBId")
MAGIC = b"NPLS"


def pc_number(name):
    return int(name.replace("PC", ""))


def receiver(stop_event, rows, lock):
    socks = []
    for n in range(1, 11):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOST, BASE_PORT + n))
        s.settimeout(0.2)
        socks.append(s)

    while not stop_event.is_set():
        readable, _, _ = select.select(socks, [], [], 0.2)
        for s in readable:
            try:
                data, _ = s.recvfrom(2048)
            except OSError:
                continue
            now = time.time()
            if len(data) < HEADER.size:
                continue
            magic, step, src, dst, seq, ts = HEADER.unpack(data[:HEADER.size])
            if magic != MAGIC:
                continue
            with lock:
                rows.append((step, src, dst, seq, ts, now, len(data)))
    for s in socks:
        s.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=30,
                        help="number of 1-second simulation steps to replay")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="time compression factor (2.0 = twice as fast)")
    args = parser.parse_args()

    if not GAME_FILE.exists():
        raise FileNotFoundError(f"Run the traffic generator first: {GAME_FILE}")

    flows_by_step = defaultdict(list)
    with open(GAME_FILE, newline="") as f:
        for r in csv.DictReader(f):
            step = int(r["step"])
            if step < args.steps:
                flows_by_step[step].append(r)

    rows, lock, stop = [], threading.Lock(), threading.Event()
    rx = threading.Thread(target=receiver, args=(stop, rows, lock), daemon=True)
    rx.start()
    time.sleep(0.3)

    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    seq_by_flow = defaultdict(int)
    start = time.time()
    print(f"Replaying {args.steps} steps over UDP {HOST}:{BASE_PORT + 1}-{BASE_PORT + 10}")

    for step in range(args.steps):
        step_start = time.time()
        interval = 1.0 / args.speed
        flows = flows_by_step.get(step, [])
        # packets per flow in this interval, spread evenly across the interval
        schedule = []
        for r in flows:
            n_pkts = max(1, round(float(r["offered_mbps"]) * 1e6 / 8 * 1.0 / PACKET_BYTES))
            for k in range(n_pkts):
                schedule.append((k / n_pkts * interval, r))
        schedule.sort(key=lambda x: x[0])

        for offset, r in schedule:
            delay = step_start + offset - time.time()
            if delay > 0:
                time.sleep(delay)
            src, dst = pc_number(r["source"]), pc_number(r["destination"])
            key = (src, dst)
            seq_by_flow[key] += 1
            payload = HEADER.pack(MAGIC, step, src, dst, seq_by_flow[key], time.time())
            payload += b"\x00" * (PACKET_BYTES - len(payload))
            tx.sendto(payload, (HOST, BASE_PORT + dst))
            sent += 1

        remaining = step_start + interval - time.time()
        if remaining > 0:
            time.sleep(remaining)

    time.sleep(0.5)
    stop.set()
    rx.join(timeout=2)

    RX_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RX_LOG, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step", "src_pc", "dst_pc", "seq", "send_ts", "recv_ts", "bytes"])
        w.writerows(rows)

    print(f"Sent: {sent}  Received: {len(rows)}  Elapsed: {time.time() - start:.1f}s")
    print(f"Receiver log: {RX_LOG}")


if __name__ == "__main__":
    main()
