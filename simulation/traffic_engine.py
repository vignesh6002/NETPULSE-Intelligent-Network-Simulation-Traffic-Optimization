# docker compose run --rm netpulse python -m simulation.traffic_engine

import json
from pathlib import Path
from network.topology import build_topology

FILE = Path(__file__).resolve().parents[1] / "configs" / "traffic_config.json"


def load_matrix():
    with open(FILE, "r") as f:
        data = json.load(f)

    matrix = data["initial_matrix"]

    if len(matrix) != 4 or any(len(row) != 10 for row in matrix):
        raise ValueError("Traffic matrix must be 4 x 10")

    return matrix


def router_value(router, matrix):
    num = int(router[1:])
    row = num // 10
    col = num % 10

    if row >= 4 or col >= 10:
        raise ValueError(f"Invalid router ID: {router}")

    return matrix[row][col]


def calculate_traffic():
    G = build_topology()
    matrix = load_matrix()
    results = []

    for a, b in G.edges():
        if G.nodes[a]["type"] != "router":
            continue
        if G.nodes[b]["type"] != "router":
            continue

        x = router_value(a, matrix)
        y = router_value(b, matrix)

        results.append({
            "link": f"{a}-{b}",
            "traffic": x + y,
            "queued_traffic": abs(x - y)
        })

    return results


if __name__ == "__main__":
    results = calculate_traffic()

    print("\n===== NETPULSE TRAFFIC ENGINE =====")
    print("Router links analysed:", len(results))

    for item in results:
        print(
            f'{item["link"]:10} '
            f'Traffic: {item["traffic"]:3} Mbps | '
            f'Queued value: {item["queued_traffic"]:3} Mbps'
        )
