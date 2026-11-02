import csv
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.topology import build_topology

GAME_FILE = ROOT / "results" / "game_flows.csv"
BACKGROUND_FILE = ROOT / "results" / "background_router_loads.csv"

LINK_LOAD_FILE = ROOT / "results" / "link_loads.csv"
SUMMARY_FILE = ROOT / "results" / "link_load_summary.csv"

TOPOLOGY_FILE = ROOT / "configs" / "topology.json"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with open(path, "r", newline="") as file:
        return list(csv.DictReader(file))


def load_access_mapping():
    import json

    with open(TOPOLOGY_FILE, "r") as file:
        config = json.load(file)

    pc_to_router = {}

    for switch, connections in config["access_links"].items():
        pc = connections["pc"]
        router = connections["router"]
        pc_to_router[pc] = router

    return pc_to_router


def build_directed_graph(G):
    """
    Preserve the physical undirected topology while creating
    two directed edges for every bidirectional physical link.
    """
    D = nx.DiGraph()

    for node, attributes in G.nodes(data=True):
        D.add_node(node, **attributes)

    for a, b, attributes in G.edges(data=True):
        D.add_edge(a, b, **attributes)
        D.add_edge(b, a, **attributes)

    return D


def calculate_link_loads():
    G = build_topology()
    D = build_directed_graph(G)

    game_records = read_csv(GAME_FILE)
    background_records = read_csv(BACKGROUND_FILE)

    pc_to_router = load_access_mapping()

    if not game_records:
        raise ValueError("Game traffic file is empty")

    if not background_records:
        raise ValueError("Background traffic file is empty")

    # ---------------------------------------------------------
    # 1. Identify simulation intervals
    # ---------------------------------------------------------

    steps = set()
    time_by_step = {}

    for record in game_records + background_records:
        step = int(record["step"])
        time_seconds = float(record["time_seconds"])

        steps.add(step)
        time_by_step[step] = time_seconds

    steps = sorted(steps)

    # ---------------------------------------------------------
    # 2. Prepare directional load storage
    # ---------------------------------------------------------

    game_loads = defaultdict(float)
    background_loads = defaultdict(float)

    # ---------------------------------------------------------
    # 3. Calculate initial shortest-propagation paths
    # ---------------------------------------------------------

    # These paths are used only to estimate where the generated
    # traffic travels. Congestion-aware Dijkstra comes later.

    route_cache = {}

    for record in game_records:
        source = record["source"]
        destination = record["destination"]

        if source not in pc_to_router:
            raise ValueError(f"Unknown source PC: {source}")

        if destination not in pc_to_router:
            raise ValueError(f"Unknown destination PC: {destination}")

        if source == destination:
            raise ValueError(f"Self-directed flow found: {source}")

        pair = (source, destination)

        if pair not in route_cache:
            route_cache[pair] = nx.shortest_path(
                G,
                source=source,
                target=destination,
                weight="delay_ms"
            )

    # ---------------------------------------------------------
    # 4. Aggregate game traffic over its actual paths
    # ---------------------------------------------------------

    for record in game_records:
        step = int(record["step"])
        source = record["source"]
        destination = record["destination"]
        rate = float(record["offered_mbps"])

        if rate < 0:
            raise ValueError("Game traffic rate cannot be negative")

        path = route_cache[(source, destination)]

        for a, b in zip(path, path[1:]):
            game_loads[(step, a, b)] += rate

    # ---------------------------------------------------------
    # 5. Distribute background router load
    # ---------------------------------------------------------

    for record in background_records:
        step = int(record["step"])
        router = record["router"]
        rate = float(record["background_mbps"])

        if router not in G:
            raise ValueError(f"Unknown background router: {router}")

        if G.nodes[router]["type"] != "router":
            raise ValueError(f"{router} is not a router")

        if rate < 0:
            raise ValueError("Background traffic cannot be negative")

        backbone_neighbors = [
            neighbor
            for neighbor in G.neighbors(router)
            if G.nodes[neighbor]["type"] == "router"
        ]

        if not backbone_neighbors:
            raise ValueError(
                f"{router} has no backbone neighbors"
            )

        # Explicit simulation assumption:
        # Divide this router's outgoing background demand equally
        # among its backbone links.

        share = rate / len(backbone_neighbors)

        for neighbor in backbone_neighbors:
            background_loads[(step, router, neighbor)] += share

    # ---------------------------------------------------------
    # 6. Calculate load and utilisation for every directed link
    # ---------------------------------------------------------

    link_rows = []

    # Store measurements for the across-simulation summary.
    summary_values = defaultdict(list)

    for step in steps:
        for a, b in D.edges():

            game = game_loads[(step, a, b)]
            background = background_loads[(step, a, b)]

            offered = game + background

            bandwidth = D[a][b]["bandwidth_mbps"]

            utilisation = (
                offered / bandwidth
            ) * 100 if bandwidth > 0 else 0

            row = {
                "step": step,
                "time_seconds": time_by_step[step],
                "from_node": a,
                "to_node": b,
                "game_mbps": round(game, 6),
                "background_mbps": round(background, 6),
                "offered_mbps": round(offered, 6),
                "bandwidth_mbps": round(bandwidth, 6),
                "utilization_pct": round(utilisation, 6)
            }

            link_rows.append(row)

            summary_values[(a, b)].append(
                (offered, game, background, utilisation)
            )

    # ---------------------------------------------------------
    # 7. Save detailed interval-level link loads
    # ---------------------------------------------------------

    LINK_LOAD_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(LINK_LOAD_FILE, "w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "step",
                "time_seconds",
                "from_node",
                "to_node",
                "game_mbps",
                "background_mbps",
                "offered_mbps",
                "bandwidth_mbps",
                "utilization_pct"
            ]
        )

        writer.writeheader()
        writer.writerows(link_rows)

    # ---------------------------------------------------------
    # 8. Calculate average and peak link statistics
    # ---------------------------------------------------------

    summary_rows = []

    for (a, b), values in sorted(summary_values.items()):

        offered_values = [v[0] for v in values]
        game_values = [v[1] for v in values]
        background_values = [v[2] for v in values]
        utilization_values = [v[3] for v in values]

        bandwidth = D[a][b]["bandwidth_mbps"]

        summary_rows.append({
            "from_node": a,
            "to_node": b,
            "bandwidth_mbps": round(bandwidth, 6),
            "avg_game_mbps": round(
                sum(game_values) / len(game_values), 6
            ),
            "avg_background_mbps": round(
                sum(background_values) / len(background_values), 6
            ),
            "avg_offered_mbps": round(
                sum(offered_values) / len(offered_values), 6
            ),
            "max_offered_mbps": round(
                max(offered_values), 6
            ),
            "avg_utilization_pct": round(
                sum(utilization_values) / len(utilization_values), 6
            ),
            "max_utilization_pct": round(
                max(utilization_values), 6
            )
        })

    with open(SUMMARY_FILE, "w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "from_node",
                "to_node",
                "bandwidth_mbps",
                "avg_game_mbps",
                "avg_background_mbps",
                "avg_offered_mbps",
                "max_offered_mbps",
                "avg_utilization_pct",
                "max_utilization_pct"
            ]
        )

        writer.writeheader()
        writer.writerows(summary_rows)

    # ---------------------------------------------------------
    # 9. Print validation summary
    # ---------------------------------------------------------

    all_utilizations = [
        row["utilization_pct"] for row in link_rows
    ]

    print("\n===== NETPULSE LINK LOAD ENGINE =====")
    print("Simulation intervals:", len(steps))
    print("Game flow records:", len(game_records))
    print("Background records:", len(background_records))
    print("Physical links:", G.number_of_edges())
    print("Directed links:", D.number_of_edges())
    print("Interval-level link records:", len(link_rows))

    print("\n===== UTILISATION VALIDATION =====")
    print(
        "Average utilisation:",
        f"{sum(all_utilizations) / len(all_utilizations):.2f}%"
    )
    print(
        "Maximum utilisation:",
        f"{max(all_utilizations):.2f}%"
    )
    print(
        "Links above 95%:",
        sum(1 for value in all_utilizations if value >= 95)
    )

    print("\n===== OUTPUT FILES =====")
    print("Detailed:", LINK_LOAD_FILE)
    print("Summary:", SUMMARY_FILE)

    print("\n===== COMPLETE =====")


if __name__ == "__main__":
    calculate_link_loads()