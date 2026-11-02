"""
NETPULSE emulated replay (native Windows, standard library only).

Replays results/packet_schedule_<scheme>.csv as REAL UDP packets over loopback.
Each packet is put on the wire at   t0 + time_s + simulated_delay_ms   so the
timing that Wireshark captures is the timing predicted by the simulated
network (queues, hops, priority). Packets the simulation dropped are not sent.

Priority is signalled by DSCP in the IP header (P0=EF/46, P1=AF41/34,
P2=AF31/26, P3=CS1/10... see DSCP below) and repeated in the payload, because
Windows may ignore IP_TOS; analyse_emulation.py reports whether DSCP survived.

Payload (big-endian): magic(4s) step(I) src(B) dst(B) prio(B) seq(I)
                      nominal_s(d) sim_delay_ms(d) t0_epoch(d), padded to 500 B.

Usage:
    python packet_capture/emulated_replay.py --scheme llq_only --steps 30
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
RESULTS = ROOT / "results"

HOST = "127.0.0.1"
BASE_PORT = 50000
PACKET_BYTES = 500
HEADER = struct.Struct("!4sIBBBIddd")
MAGIC = b"NPLS"
DSCP = {0: 46, 1: 34, 2: 26, 3: 10, 4: 0}


def sink(stop, counter):
    socks = []
    for n in range(1, 11):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOST, BASE_PORT + n))
        socks.append(s)
    while not stop.is_set():
        readable, _, _ = select.select(socks, [], [], 0.2)
        for s in readable:
            try:
                s.recvfrom(2048)
                counter[0] += 1
            except OSError:
                pass
    for s in socks:
        s.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheme", default="llq_only")
    parser.add_argument("--steps", type=int, default=30)
    args = parser.parse_args()

    path = RESULTS / f"packet_schedule_{args.scheme}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Run simulation/priority_sim.py first: {path}")

    events = []
    dropped = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if int(r["step"]) >= args.steps:
                continue
            if int(r["dropped"]):
                dropped += 1
                continue
            nominal = float(r["time_s"])
            delay = float(r["delay_ms"])
            events.append((nominal + delay / 1000.0, nominal, delay, r))
    events.sort(key=lambda e: e[0])

    counter, stop = [0], threading.Event()
    rx = threading.Thread(target=sink, args=(stop, counter), daemon=True)
    rx.start()
    time.sleep(0.3)

    socks = {}
    for p, dscp in DSCP.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, dscp << 2)
        except OSError:
            pass
        socks[p] = s

    seq = defaultdict(int)
    t0 = time.time()
    t0_perf = time.perf_counter()
    print(f"Replaying scheme={args.scheme} steps={args.steps}: "
          f"{len(events)} packets ({dropped} dropped by simulation)")

    for emit, nominal, delay, r in events:
        target = t0_perf + emit
        while True:
            remaining = target - time.perf_counter()
            if remaining <= 0:
                break
            if remaining > 0.003:
                time.sleep(remaining - 0.002)
        prio = int(r["priority"])
        src = int(r["source"].replace("PC", ""))
        dst = int(r["destination"].replace("PC", ""))
        seq[(src, dst, prio)] += 1
        payload = HEADER.pack(MAGIC, int(r["step"]), src, dst, prio,
                              seq[(src, dst, prio)], nominal, delay, t0)
        payload += b"\x00" * (PACKET_BYTES - len(payload))
        socks[prio].sendto(payload, (HOST, BASE_PORT + dst))

    time.sleep(0.5)
    stop.set()
    rx.join(timeout=2)
    print(f"Sent: {len(events)}  Received by sink: {counter[0]}")


if __name__ == "__main__":
    main()
