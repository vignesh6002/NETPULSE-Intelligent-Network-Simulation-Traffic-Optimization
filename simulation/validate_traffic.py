
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"

bg = pd.read_csv(OUT / "background_router_loads.csv")
game = pd.read_csv(OUT / "game_flows.csv")

print("\n===== TRAFFIC VALIDATION =====")

print("\nBackground traffic")
print("Routers:", bg["router"].nunique())
print("Records:", len(bg))
print("Minimum Mbps:", bg["background_mbps"].min())
print("Maximum Mbps:", bg["background_mbps"].max())
print("Average Mbps:", round(bg["background_mbps"].mean(), 3))

print("\nGame traffic")
print("Unique sources:", game["source"].nunique())
print("Unique destinations:", game["destination"].nunique())
print("Records:", len(game))
print("Activities:")
print(game["activity"].value_counts())
print("Average flow Mbps:", round(game["offered_mbps"].mean(), 4))

print("\nMissing values:")
print("Background:", bg.isnull().sum().sum())
print("Game:", game.isnull().sum().sum())

print("\nSelf-directed flows:",
      (game["source"] == game["destination"]).sum())

print("\n===== VALIDATION COMPLETE =====")
