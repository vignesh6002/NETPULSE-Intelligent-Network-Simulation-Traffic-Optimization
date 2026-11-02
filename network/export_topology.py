#docker compose run --rm netpulse python network/export_topology.py


from topology import build_topology
import networkx as nx
from pathlib import Path

# Build the network
G = build_topology()

# Set graph information
G.graph["name"] = "NETPULSE"
G.graph["description"] = "30-router multiplayer network simulation"

# Export path
OUT = (
    Path(__file__).resolve().parents[1]
    / "results"
    / "netpulse_topology.graphml"
)

# Export as an undirected graph
nx.write_graphml(G, OUT)

# Display results
print("\n===== NETPULSE GRAPH EXPORT =====")
print("Export successful!")
print("Total nodes:", G.number_of_nodes())
print("Physical links:", G.number_of_edges())
print("Directed:", G.is_directed())
print("Connected:", nx.is_connected(G))
print("Saved to:", OUT)
