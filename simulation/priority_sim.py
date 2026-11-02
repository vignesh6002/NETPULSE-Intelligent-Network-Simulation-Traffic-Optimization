"""
NETPULSE priority-aware routing simulator.

Compares three schemes on identical topology, traffic, delays and random numbers:

  baseline  : class-blind Dijkstra  + FIFO queues
  llq_only  : class-blind Dijkstra  + strict-priority (low-latency) queues
  priority  : class-aware Dijkstra  + strict-priority (low-latency) queues

Priority classes
  P0 combat (bullets / hit events)      P1 movement + voice
  P2 synchronisation                    P3 idle / keep-alive
  P4 background router traffic (link-level load only)

Queue model (analytical, per directed link and per 1 s step)
  * Non-preemptive priority M/G/1 (Cobham) waiting time for each class;
    FIFO M/G/1 for the baseline. Arrival burstiness is scaled by --burst.
  * Waiting time is capped by a finite buffer; overload causes loss
    (strict priority: lowest classes lose first, FIFO: everyone loses equally).
  * Per-packet delay = sum over hops of (propagation + service + sampled
    queueing delay, exponential around the model mean).

Routing cost of a link for class k: delay + service_k + E[wait_k] + 100*loss_k.
Low-priority classes see large waits on busy links, so they detour or accept
waiting automatically, whichever is cheaper.

Outputs
  results/packet_schedule_<scheme>.csv   one row per sampled packet
  results/priority_comparison.csv        per scheme and class metrics
  results/priority_sweep.csv             (with --sweep) metrics vs load scale

Run:
  python simulation/priority_sim.py --load-scale 2.0
  python simulation/priority_sim.py --sweep
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.topology import build_topology  # noqa: E402

GAME_FILE = ROOT / "results" / "game_flows.csv"
BACKGROUND_FILE = ROOT / "results" / "background_router_loads.csv"
RESULTS = ROOT / "results"

CLASS_OF_ACTIVITY = {
    "combat": 0,
    "movement": 1,
    "voice": 1,
    "synchronization": 2,
    "idle": 3,
}
CLASS_NAMES = ["P0_combat", "P1_movement_voice", "P2_sync", "P3_idle", "P4_background"]
N_CLASSES = 5
GAME_CLASSES = 4
PKT_BYTES = np.array([500, 500, 500, 500, 1500])
BUFFER_MS = 20.0
LOSS_PENALTY_MS = 100.0
ROUTING_ITERATIONS = 5
MAX_PACKETS_PER_FLOW_RECORD = 10
N_EXP = 24  # exponential draws reserved per packet (>= max hops)

SCHEMES = {
    "baseline": {"queue": "fifo", "routing": "blind"},
    "llq_only": {"queue": "prio", "routing": "blind"},
    "priority": {"queue": "prio", "routing": "aware"},
}


def queue_stats(load, bw, discipline, burst):
    """Mean wait (ms) and loss probability per class for one directed link."""
    rho = np.asarray(load) / bw
    service = PKT_BYTES * 8 / (bw * 1e6) * 1000.0
    w0 = burst * 0.5 * float(np.sum(rho * service))
    wait = np.zeros(N_CLASSES)
    loss = np.zeros(N_CLASSES)

    if discipline == "fifo":
        total = float(rho.sum())
        w = w0 / (1 - total) if total < 1 else BUFFER_MS
        wait[:] = min(w, BUFFER_MS)
        if total > 1:
            loss[:] = 1 - 1 / total
    else:
        cum = 0.0
        for k in range(N_CLASSES):
            prev = cum
            cum += rho[k]
            if cum < 1:
                w = w0 / ((1 - prev) * (1 - cum))
            else:
                w = BUFFER_MS
            wait[k] = min(w, BUFFER_MS)
            if cum > 1 and rho[k] > 0:
                served = max(0.0, 1 - prev)
                loss[k] = 1 - min(1.0, served / rho[k])
    return wait, loss


class Scenario:
    def __init__(self, load_scale, game_scale, burst, seed=42):
        self.load_scale = load_scale
        self.game_scale = game_scale
        self.burst = burst
        self.seed = seed

        G = build_topology()
        self.G = G
        D = nx.DiGraph()
        for n, d in G.nodes(data=True):
            D.add_node(n, **d)
        for a, b, d in G.edges(data=True):
            D.add_edge(a, b, **d)
            D.add_edge(b, a, **d)
        self.D = D
        self.links = list(D.edges())
        self.bw = {(a, b): D[a][b]["bandwidth_mbps"] for a, b in self.links}
        self.delay = {(a, b): D[a][b]["delay_ms"] for a, b in self.links}
        self.pcs = [f"PC{i}" for i in range(1, 11)]

        if not GAME_FILE.exists() or not BACKGROUND_FILE.exists():
            raise FileNotFoundError("Run simulation/dynamic_traffic.py first")

        self.flows = []
        with open(GAME_FILE, newline="") as f:
            for r in csv.DictReader(f):
                self.flows.append({
                    "step": int(r["step"]),
                    "source": r["source"],
                    "destination": r["destination"],
                    "activity": r["activity"],
                    "cls": CLASS_OF_ACTIVITY[r["activity"]],
                    "rate": float(r["offered_mbps"]) * game_scale,
                })
        self.steps = sorted({fl["step"] for fl in self.flows})
        self.n_steps = len(self.steps)

        # Background router load -> directed backbone link load (equal split)
        self.bg_step = defaultdict(lambda: defaultdict(float))
        self.bg_avg = defaultdict(float)
        bg = pd.read_csv(BACKGROUND_FILE)
        for r in bg.itertuples():
            neigh = [n for n in G.neighbors(r.router) if G.nodes[n]["type"] == "router"]
            share = r.background_mbps * load_scale / len(neigh)
            for n in neigh:
                self.bg_step[r.step][(r.router, n)] += share
                self.bg_avg[(r.router, n)] += share / self.n_steps

        # Mean game rate per (class, src, dst) for the routing iterations
        self.mean_rate = defaultdict(float)
        for fl in self.flows:
            self.mean_rate[(fl["cls"], fl["source"], fl["destination"])] += (
                fl["rate"] / self.n_steps
            )

    # ------------------------------------------------------------------ routing
    def _loads_from_routes(self, routes):
        loads = {l: np.zeros(N_CLASSES) for l in self.links}
        for l in self.links:
            loads[l][4] = self.bg_avg.get(l, 0.0)
        for (k, s, d), rate in self.mean_rate.items():
            path = routes[(k, s, d)]
            for a, b in zip(path, path[1:]):
                loads[(a, b)][k] += rate
        return loads

    def compute_routes(self, mode):
        discipline = "prio" if mode == "aware" else "fifo"
        avg = {l: np.zeros(N_CLASSES) for l in self.links}
        for l in self.links:
            avg[l][4] = self.bg_avg.get(l, 0.0)

        routes = {}
        for it in range(ROUTING_ITERATIONS):
            weights = {k: {} for k in range(GAME_CLASSES)}
            for l in self.links:
                wait, loss = queue_stats(avg[l], self.bw[l], discipline, self.burst)
                service = PKT_BYTES * 8 / (self.bw[l] * 1e6) * 1000.0
                for k in range(GAME_CLASSES):
                    weights[k][l] = (
                        self.delay[l] + service[k] + wait[k] + LOSS_PENALTY_MS * loss[k]
                    )
            routes = {}
            for k in range(GAME_CLASSES):
                for (a, b), w in weights[k].items():
                    self.D[a][b]["w"] = w
                for s in self.pcs:
                    paths = nx.single_source_dijkstra_path(self.D, s, weight="w")
                    for d in self.pcs:
                        if d != s:
                            routes[(k, s, d)] = paths[d]
            new = self._loads_from_routes(routes)
            for l in self.links:
                avg[l] = avg[l] + (new[l] - avg[l]) / (it + 1)
        return routes

    # --------------------------------------------------------------- simulation
    def simulate(self, scheme, routes):
        cfg = SCHEMES[scheme]
        discipline = cfg["queue"]

        step_loads = defaultdict(dict)
        for step in self.steps:
            for l, v in self.bg_step[step].items():
                arr = np.zeros(N_CLASSES)
                arr[4] = v
                step_loads[step][l] = arr
        for fl in self.flows:
            path = routes[(fl["cls"], fl["source"], fl["destination"])]
            for a, b in zip(path, path[1:]):
                arr = step_loads[fl["step"]].setdefault((a, b), np.zeros(N_CLASSES))
                arr[fl["cls"]] += fl["rate"]

        cache = {}

        def stats(step, link):
            key = (step, link)
            if key not in cache:
                load = step_loads[step].get(link)
                if load is None:
                    cache[key] = (np.zeros(N_CLASSES), np.zeros(N_CLASSES))
                else:
                    cache[key] = queue_stats(load, self.bw[link], discipline, self.burst)
            return cache[key]

        util = []
        for step in self.steps:
            for l in self.links:
                load = step_loads[step].get(l)
                util.append(0.0 if load is None else load.sum() / self.bw[l] * 100)
        util = np.array(util)

        rng = np.random.default_rng(self.seed)
        rows = []
        for fl in self.flows:
            k = fl["cls"]
            path = routes[(k, fl["source"], fl["destination"])]
            edges = list(zip(path, path[1:]))
            n_pkts = max(1, round(fl["rate"] * 1e6 / 8 / PKT_BYTES[k]))
            n_sample = min(n_pkts, MAX_PACKETS_PER_FLOW_RECORD)
            path_str = " -> ".join(path)

            for j in range(n_sample):
                exp_draws = rng.exponential(1.0, N_EXP)
                loss_draw = rng.random()
                delay = 0.0
                survive = 1.0
                hop_delays = []
                drop_hop = -1
                for h, (a, b) in enumerate(edges):
                    wait, loss = stats(fl["step"], (a, b))
                    service = PKT_BYTES[k] * 8 / (self.bw[(a, b)] * 1e6) * 1000.0
                    hop = self.delay[(a, b)] + service + wait[k] * exp_draws[h]
                    hop_delays.append(round(float(hop), 4))
                    delay += hop
                    survive *= 1 - loss[k]
                    if drop_hop < 0 and loss_draw > survive:
                        drop_hop = h
                rows.append({
                    "scheme": scheme,
                    "step": fl["step"],
                    "time_s": round(fl["step"] + j / n_sample, 4),
                    "source": fl["source"],
                    "destination": fl["destination"],
                    "activity": fl["activity"],
                    "priority": k,
                    "hops": len(edges),
                    "path": path_str,
                    "delay_ms": round(delay, 4),
                    "dropped": int(loss_draw > survive),
                    "hop_delays_ms": ";".join(str(x) for x in hop_delays),
                    "drop_hop": drop_hop,
                })
        return pd.DataFrame(rows), util


def metrics(df, util, scheme):
    out = []
    for k in range(GAME_CLASSES):
        sub = df[df.priority == k]
        delivered = sub[sub.dropped == 0].sort_values(["source", "destination", "time_s"])
        jit = delivered.groupby(["source", "destination"])["delay_ms"].apply(
            lambda s: s.diff().abs().mean()
        ).mean()
        out.append({
            "scheme": scheme,
            "class": CLASS_NAMES[k],
            "packets": len(sub),
            "loss_pct": round(100 * sub.dropped.mean(), 3),
            "mean_delay_ms": round(delivered.delay_ms.mean(), 3),
            "p95_delay_ms": round(delivered.delay_ms.quantile(0.95), 3),
            "p99_delay_ms": round(delivered.delay_ms.quantile(0.99), 3),
            "jitter_ms": round(float(jit), 4),
            "mean_hops": round(sub.hops.mean(), 2),
            "avg_util_pct": round(float(util.mean()), 2),
            "max_util_pct": round(float(util.max()), 2),
        })
    return out


def run(load_scale, game_scale, burst, write_schedule):
    sc = Scenario(load_scale, game_scale, burst)
    routes_by_mode = {m: sc.compute_routes(m) for m in ("blind", "aware")}
    results = []
    for scheme, cfg in SCHEMES.items():
        df, util = sc.simulate(scheme, routes_by_mode[cfg["routing"]])
        if write_schedule:
            RESULTS.mkdir(parents=True, exist_ok=True)
            df.to_csv(RESULTS / f"packet_schedule_{scheme}.csv", index=False)
        results.extend(metrics(df, util, scheme))
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-scale", type=float, default=1.0,
                        help="multiplier on background router traffic")
    parser.add_argument("--game-scale", type=float, default=40.0,
                        help="each flow stands for this many aggregated players")
    parser.add_argument("--burst", type=float, default=4.0,
                        help="arrival burstiness factor on queueing delay")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)

    if args.sweep:
        frames = []
        for scale in [1.0, 1.5, 2.0, 2.5, 3.0]:
            df = run(scale, args.game_scale, args.burst, write_schedule=False)
            df.insert(0, "load_scale", scale)
            frames.append(df)
            print(f"load_scale={scale} done")
        sweep = pd.concat(frames)
        sweep.to_csv(RESULTS / "priority_sweep.csv", index=False)
        print(sweep[sweep["class"] == "P0_combat"][
            ["load_scale", "scheme", "avg_util_pct", "max_util_pct",
             "loss_pct", "mean_delay_ms", "p99_delay_ms", "jitter_ms"]
        ].to_string(index=False))
        print("Saved:", RESULTS / "priority_sweep.csv")
    else:
        df = run(args.load_scale, args.game_scale, args.burst, write_schedule=True)
        df.to_csv(RESULTS / "priority_comparison.csv", index=False)
        print(df.drop(columns=["packets"]).to_string(index=False))
        print("Saved:", RESULTS / "priority_comparison.csv")


if __name__ == "__main__":
    main()
