
import sys
from pathlib import Path
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.topology import build_topology

G = build_topology()

pairs = [
    ("PC1", "PC10"),
    ("PC6", "PC10"),
    ("PC1", "PC7"),
    ("PC3", "PC9")
]

print("\n===== ROUTE INSPECTION =====")

for src, dst in pairs:
    path = nx.shortest_path(G, src, dst)

    print(f"\n{src} -> {dst}")
    print("Minimum possible hops:", len(path) - 1)
    print("Path:", " -> ".join(path))

print("\n===== COMPLETE =====")
