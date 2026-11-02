
import json
from pathlib import Path
from collections import deque

FILE = Path(__file__).resolve().parents[1] / "configs" / "topology.json"

def validate():
    with open(FILE, "r") as f:
        data = json.load(f)

    links = data["router_links"]
    access = data["access_links"]
    errors = []

    # 1. Check node counts
    if len(links) != 30:
        errors.append(f"Expected 30 routers, found {len(links)}")

    if len(access) != 10:
        errors.append(f"Expected 10 switches, found {len(access)}")

    # 2. Check router references and degrees
    for r, neighbors in links.items():
        if not 2 <= len(neighbors) <= 4:
            errors.append(f"{r} has {len(neighbors)} neighbors")

        for n in neighbors:
            if n not in links:
                errors.append(f"{r} references unknown router {n}")
            elif r not in links[n]:
                errors.append(f"Link {r}-{n} is not reciprocal")

    # 3. Count unique undirected links
    edges = {
        tuple(sorted((r, n)))
        for r, neighbors in links.items()
        for n in neighbors
    }

    # 4. Check backbone connectivity
    if links:
        start = next(iter(links))
        visited = {start}
        queue = deque([start])

        while queue:
            current = queue.popleft()
            for neighbor in links[current]:
                if neighbor in links and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        if len(visited) != len(links):
            errors.append(
                f"Backbone disconnected: reached {len(visited)} of {len(links)} routers"
            )

    # 5. Check access layer
    pcs = []
    for switch, info in access.items():
        pc = info.get("pc")
        router = info.get("router")

        if pc is None or router is None:
            errors.append(f"{switch} is missing a PC or router")
            continue

        pcs.append(pc)

        if router not in links:
            errors.append(f"{switch} references unknown router {router}")

    if len(pcs) != 10 or len(set(pcs)) != 10:
        errors.append("Expected 10 unique PCs, one per switch")

    # 6. Print results
    print("\n===== NETPULSE TOPOLOGY VALIDATION =====")

    print(f"Routers: {len(links)}")
    print(f"Switches: {len(access)}")
    print(f"PCs: {len(pcs)}")
    print(f"Unique router links: {len(edges)}")

    if errors:
        print("\nVALIDATION FAILED")
        for error in errors:
            print(" -", error)
    else:
        print("\nALL CHECKS PASSED")
        print("Router links are reciprocal.")
        print("Every router has 2-4 neighbors.")
        print("Backbone is connected.")
        print("Access layer references are valid.")

if __name__ == "__main__":
    validate()
