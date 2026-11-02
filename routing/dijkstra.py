import csv
from pathlib import Path
import networkx as nx
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.topology import build_topology

SUMMARY_FILE = ROOT / "results" / "link_load_summary.csv"
OUT = ROOT / "results" / "dijkstra_routes.csv"

ALPHA = 2.0
SATURATION_LIMIT = 95.0
SATURATION_PENALTY = 1000.0


def build_directed_graph_with_weights(G, summary_file):
    if not summary_file.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_file}")

    D = nx.DiGraph()

    for node, attributes in G.nodes(data=True):
        D.add_node(node, **attributes)

    with open(summary_file, "r", newline="") as file:
        reader = csv.DictReader(file)
        summary_data = {(row["from_node"], row["to_node"]): row for row in reader}

    for a, b, edge_attrs in G.edges(data=True):
        delay = edge_attrs.get("delay_ms", 5)

        for src, dst in [(a, b), (b, a)]:
            record = summary_data.get((src, dst))
            if record:
                bandwidth = float(record["bandwidth_mbps"])
                offered = float(record["avg_offered_mbps"])
                utilization = float(record["avg_utilization_pct"])
            else:
                bandwidth = edge_attrs.get("bandwidth_mbps", 190.0)
                offered = 0.0
                utilization = 0.0

            if utilization >= SATURATION_LIMIT:
                penalty = SATURATION_PENALTY
            else:
                penalty = ALPHA * utilization / (100.0 - utilization) if (100.0 - utilization) > 0 else SATURATION_PENALTY

            routing_cost = delay + penalty

            D.add_edge(
                src,
                dst,
                bandwidth_mbps=bandwidth,
                delay_ms=delay,
                offered_mbps=offered,
                utilization_pct=utilization,
                congestion_penalty_ms=penalty,
                routing_cost_ms=routing_cost
            )

    return D


def find_route(D, source, destination):
    path = nx.shortest_path(
        D,
        source=source,
        target=destination,
        weight="routing_cost_ms",
        method="dijkstra"
    )

    total_cost = nx.path_weight(D, path, weight="routing_cost_ms")
    total_delay = sum(D[a][b]["delay_ms"] for a, b in zip(path, path[1:]))

    return {
        "source": source,
        "destination": destination,
        "path": " -> ".join(path),
        "hops": len(path) - 1,
        "propagation_delay_ms": total_delay,
        "routing_cost_ms": round(total_cost, 3)
    }


def main():
    G = build_topology()
    D = build_directed_graph_with_weights(G, SUMMARY_FILE)

    players = [f"PC{i}" for i in range(1, 11)]
    results = []

    for src in players:
        for dst in players:
            if src != dst:
                results.append(find_route(D, src, dst))

    OUT.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source",
                "destination",
                "path",
                "hops",
                "propagation_delay_ms",
                "routing_cost_ms"
            ]
        )
        writer.writeheader()
        writer.writerows(results)

    print("\n===== NETPULSE DIJKSTRA ROUTING =====")
    print("Algorithm: Directional Congestion-Aware Dijkstra")
    print("Weight: Propagation delay + congestion penalty")
    print("Congestion coefficient (alpha):", ALPHA)
    print("Total routes calculated:", len(results))

    sample = find_route(D, "PC6", "PC10")
    print("\n===== SAMPLE ROUTE =====")
    print("PC6 -> PC10")
    print("Path:", sample["path"])
    print("Hops:", sample["hops"])
    print("Propagation delay:", sample["propagation_delay_ms"], "ms")
    print("Composite routing cost:", sample["routing_cost_ms"], "ms")

    sample_rev = find_route(D, "PC10", "PC6")
    print("\nPC10 -> PC6")
    print("Path:", sample_rev["path"])
    print("Hops:", sample_rev["hops"])
    print("Propagation delay:", sample_rev["propagation_delay_ms"], "ms")
    print("Composite routing cost:", sample_rev["routing_cost_ms"], "ms")

    print(f"\nResults successfully written to: {OUT}")


if __name__ == "__main__":
    main()
