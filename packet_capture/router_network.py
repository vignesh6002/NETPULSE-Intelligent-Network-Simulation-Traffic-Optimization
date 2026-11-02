"""
NETPULSE router-network emulator (native Windows, standard library only).

Every simulated node gets its own loopback IP and UDP socket, so Wireshark sees
each hop of each packet as a real datagram between node IPs:

    Router Rn  -> 127.0.1.n      Switch Sn -> 127.0.2.n      PC n -> 127.0.3.n
    (all on UDP port 40000; port 5000 is reserved on some Windows setups)

Routes come from the simulation (Dijkstra, class-aware or blind, per scheme):
packet_schedule_<scheme>.csv holds each packet's node path and its per-hop
delay (propagation + service + queueing under the priority/FIFO model).
Each node holds the packet for the hop delay, then forwards it over UDP to the
next node. A packet the simulation drops stops at the node where it was dropped.

Hold times are scheduled on absolute time (t0 + nominal + cumulative hop delay)
so per-hop scheduling error does not accumulate.

Payload (big-endian):
  magic(4s) pkt_id(I) prio(B) nhops(B) cur(B) drop_hop(b) nominal_s(d) t0(d)
  path(13B node codes)  hop_delays(12f ms)  padded to 500 bytes.
Node codes: R1..R30 -> 1..30, S1..S10 -> 41..50, PC1..PC10 -> 61..70.
DSCP marks the priority class (P0=46, P1=34, P2=26, P3=10).

Usage: python packet_capture/router_network.py --scheme llq_only --steps 30
"""
import argparse
import csv
import heapq
import select
import socket
import struct
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

PORT = 40000
MAX_HOPS = 12
HEADER = struct.Struct("!4sIBBBbdd13B12f")
MAGIC = b"NPRT"
PACKET_BYTES = 500
DSCP = {0: 46, 1: 34, 2: 26, 3: 10, 4: 0}


def node_code(name):
    if name.startswith("PC"):
        return 60 + int(name[2:])
    if name.startswith("R"):
        return int(name[1:])
    return 40 + int(name[1:])


def code_name(code):
    if code > 60:
        return f"PC{code - 60}"
    if code > 40:
        return f"S{code - 40}"
    return f"R{code}"


def node_ip(code):
    if code > 60:
        return f"127.0.3.{code - 60}"
    if code > 40:
        return f"127.0.2.{code - 40}"
    return f"127.0.1.{code}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheme", default="llq_only")
    parser.add_argument("--steps", type=int, default=30)
    args = parser.parse_args()

    path = RESULTS / f"packet_schedule_{args.scheme}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Run simulation/priority_sim.py first: {path}")

    packets = []
    with open(path, newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            if int(r["step"]) >= args.steps:
                continue
            nodes = r["path"].split(" -> ")
            if len(nodes) - 1 > MAX_HOPS:
                continue
            delays = [float(x) for x in r["hop_delays_ms"].split(";")]
            packets.append({
                "id": i,
                "prio": int(r["priority"]),
                "nodes": [node_code(n) for n in nodes],
                "delays": delays,
                "nominal": float(r["time_s"]),
                "drop_hop": int(r["drop_hop"]) if int(r["dropped"]) else -1,
            })

    # One socket per node, bound to that node's own loopback IP
    socks, by_fd = {}, {}
    all_codes = set()
    for p in packets:
        all_codes.update(p["nodes"])
    for code in sorted(all_codes | set(range(1, 31)) | set(range(41, 51)) | set(range(61, 71))):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((node_ip(code), PORT))
        socks[code] = s
        by_fd[s.fileno()] = code
    try:
        for code, s in socks.items():
            s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0)
    except OSError:
        pass
    tos_cache = {}

    t0_epoch = time.time()
    t0 = time.perf_counter()
    print(f"Router network up: {len(socks)} node IPs, scheme={args.scheme}, "
          f"{len(packets)} packets")

    # event: (due_perf_time, seq, src_code, dst_code, payload)
    heap, counter = [], 0
    delivered, dropped_in_net, forwarded = 0, 0, 0

    def build(p, cur):
        nodes = p["nodes"] + [0] * (MAX_HOPS + 1 - len(p["nodes"]))
        delays = p["delays"] + [0.0] * (MAX_HOPS - len(p["delays"]))
        payload = HEADER.pack(MAGIC, p["id"], p["prio"], len(p["nodes"]) - 1, cur,
                              p["drop_hop"], p["nominal"], t0_epoch,
                              *nodes[:13], *delays[:12])
        return payload + b"\x00" * (PACKET_BYTES - len(payload))

    def due_time(p, edge):
        return t0 + p["nominal"] + sum(p["delays"][:edge + 1]) / 1000.0

    # Injection: the source PC forwards over edge 0
    pending = sorted(packets, key=lambda p: due_time(p, 0))
    pi = 0
    by_id = {p["id"]: p for p in packets}
    total = len(packets)
    finished = 0
    last_activity = time.perf_counter()

    def set_tos(code, prio):
        key = (code, prio)
        if key not in tos_cache:
            try:
                socks[code].setsockopt(socket.IPPROTO_IP, socket.IP_TOS, DSCP[prio] << 2)
            except OSError:
                pass
            tos_cache[key] = True
        else:
            socks[code].setsockopt(socket.IPPROTO_IP, socket.IP_TOS, DSCP[prio] << 2)

    while finished < total:
        now = time.perf_counter()

        # source PCs release packets onto edge 0
        while pi < len(pending) and due_time(pending[pi], 0) <= now:
            p = pending[pi]
            pi += 1
            if p["drop_hop"] == 0:
                dropped_in_net += 1
                finished += 1
                continue
            counter += 1
            heapq.heappush(heap, (due_time(p, 0), counter, p["nodes"][0], p["nodes"][1],
                                  build(p, 1), p["prio"]))

        # send due events (hop delay elapsed)
        while heap and heap[0][0] <= now:
            _, _, src, dst, payload, prio = heapq.heappop(heap)
            set_tos(src, prio)
            socks[src].sendto(payload, (node_ip(dst), PORT))
            forwarded += 1
            last_activity = time.perf_counter()

        # next wake-up
        nxt = []
        if heap:
            nxt.append(heap[0][0])
        if pi < len(pending):
            nxt.append(due_time(pending[pi], 0))
        timeout = min(nxt) - time.perf_counter() if nxt else 0.05
        # select() timeouts are coarse on Windows, so poll sockets without
        # blocking and use short high-resolution sleeps (<=1 ms) to wait.
        if timeout > 0.0025:
            time.sleep(0.001)
        readable, _, _ = select.select(list(socks.values()), [], [], 0)

        for s in readable:
            try:
                data, _ = s.recvfrom(2048)
            except OSError:
                continue
            if len(data) < HEADER.size:
                continue
            fields = HEADER.unpack(data[:HEADER.size])
            if fields[0] != MAGIC:
                continue
            pid, cur = fields[1], fields[4]
            p = by_id[pid]
            if cur == len(p["nodes"]) - 1:
                delivered += 1
                finished += 1
                continue
            if p["drop_hop"] == cur:
                dropped_in_net += 1
                finished += 1
                continue
            counter += 1
            heapq.heappush(heap, (due_time(p, cur), counter, p["nodes"][cur],
                                  p["nodes"][cur + 1], build(p, cur + 1), p["prio"]))

        if time.perf_counter() - last_activity > 5 and not heap and pi >= len(pending):
            break

    time.sleep(0.3)
    print(f"Done. Hop datagrams sent: {forwarded}  delivered: {delivered}  "
          f"dropped in network: {dropped_in_net}")
    for s in socks.values():
        s.close()


if __name__ == "__main__":
    main()
