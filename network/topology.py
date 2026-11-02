
import json
from pathlib import Path
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]

TOPOLOGY_FILE = ROOT / "configs" / "topology.json"
TRAFFIC_FILE = ROOT / "configs" / "traffic_config.json"


def build_topology():
    with open(TOPOLOGY_FILE, "r") as f:
        config = json.load(f)

    with open(TRAFFIC_FILE, "r") as f:
        traffic_config = json.load(f)

    matrix = traffic_config["initial_matrix"]

    if len(matrix) != 4 or any(len(row) != 10 for row in matrix):
        raise ValueError("Traffic matrix must be 4 x 10")

    max_traffic = max(max(row) for row in matrix)

    defaults = config["link_defaults"]
    G = nx.Graph()

    # Create router nodes
    for i in range(1, config["network"]["routers"] + 1):
        G.add_node(f"R{i}", type="router")

    # Create router backbone links
    for router, neighbors in config["router_links"].items():
        for neighbor in neighbors:
            if not G.has_edge(router, neighbor):
                G.add_edge(router, neighbor)

    # Assign router capacity based on backbone degree
    for router in G.nodes:
        if G.nodes[router]["type"] != "router":
            continue

        degree = sum(
            1 for neighbor in G.neighbors(router)
            if G.nodes[neighbor]["type"] == "router"
        )

        if degree == 0:
            raise ValueError(f"{router} has no backbone connections")

        G.nodes[router]["capacity_mbps"] = (
            2 * max_traffic / degree
        )

    # Create switches, PCs and access links
    for switch, connections in config["access_links"].items():
        pc = connections["pc"]
        router = connections["router"]

        G.add_node(switch, type="switch")
        G.add_node(pc, type="pc")

        G.add_edge(
            pc,
            switch,
            bandwidth_mbps=2 * max_traffic,
            delay_ms=defaults["delay_ms"],
            packet_loss=defaults["packet_loss"]
        )

        G.add_edge(
            switch,
            router,
            bandwidth_mbps=2 * max_traffic,
            delay_ms=defaults["delay_ms"],
            packet_loss=defaults["packet_loss"]
        )

    # Assign bandwidth and properties to every link
    for a, b, data in G.edges(data=True):

        if (
            G.nodes[a]["type"] == "router"
            and G.nodes[b]["type"] == "router"
        ):
            data["bandwidth_mbps"] = min(
                G.nodes[a]["capacity_mbps"],
                G.nodes[b]["capacity_mbps"]
            )

        else:
            data["bandwidth_mbps"] = 2 * max_traffic

        data["delay_ms"] = defaults["delay_ms"]
        data["packet_loss"] = defaults["packet_loss"]

    return G


if __name__ == "__main__":
    G = build_topology()

    print("\n===== NETPULSE NETWORK GRAPH =====")
    print("Total nodes:", G.number_of_nodes())
    print("Total links:", G.number_of_edges())
    print("Connected:", nx.is_connected(G))

    print("\n===== ROUTER CAPACITIES =====")

    for router in sorted(
        [n for n in G.nodes if G.nodes[n]["type"] == "router"],
        key=lambda x: int(x[1:])
    ):
        print(
            f"{router}: "
            f"{G.nodes[router]['capacity_mbps']:.2f} Mbps"
        )

    print("\n===== BACKBONE LINK BANDWIDTHS =====")

    for a, b, data in G.edges(data=True):
        if (
            G.nodes[a]["type"] == "router"
            and G.nodes[b]["type"] == "router"
        ):
            print(
                f"{a}-{b}: "
                f"{data['bandwidth_mbps']:.2f} Mbps"
            )

    print("\n===== COMPLETE =====")
