
import json
import random
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = ROOT / "configs" / "dynamic_traffic_config.json"
OUT = ROOT / "results"


def load_config():
    with open(CONFIG, "r") as f:
        return json.load(f)


def generate_background(cfg, rng):
    bg = cfg["background_traffic"]

    values = {
        f"R{i}": rng.uniform(
            bg["initial_minimum_mbps"],
            bg["initial_maximum_mbps"]
        )
        for i in range(1, 31)
    }

    rows = []

    for step in range(cfg["simulation_steps"]):
        for router in values:
            change = rng.uniform(
                -bg["maximum_change_per_interval_mbps"],
                bg["maximum_change_per_interval_mbps"]
            )

            values[router] += change

            values[router] = max(
                bg["minimum_mbps"],
                min(bg["maximum_mbps"], values[router])
            )

            rows.append({
                "step": step,
                "time_seconds": step * cfg["interval_seconds"],
                "router": router,
                "background_mbps": round(values[router], 3)
            })

    return rows


def generate_game_flows(cfg, rng):
    game = cfg["game_traffic"]

    activities = list(
        game["activity_probabilities"].keys()
    )

    weights = list(
        game["activity_probabilities"].values()
    )

    players = [f"PC{i}" for i in range(1, 11)]

    rows = []

    for step in range(cfg["simulation_steps"]):
        for _ in range(game["flows_per_interval"]):

            src = rng.choice(players)

            dst = rng.choice([
                p for p in players if p != src
            ])

            activity = rng.choices(
                activities,
                weights=weights,
                k=1
            )[0]

            low, high = game["activity_rates_mbps"][activity]

            rate = rng.uniform(low, high)

            rows.append({
                "step": step,
                "time_seconds": step * cfg["interval_seconds"],
                "source": src,
                "destination": dst,
                "activity": activity,
                "offered_mbps": round(rate, 4)
            })

    return rows


def save_csv(filename, rows):
    path = OUT / filename

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=rows[0].keys()
        )
        writer.writeheader()
        writer.writerows(rows)

    print("Saved:", path)


def main():
    cfg = load_config()

    rng = random.Random(cfg["seed"])

    OUT.mkdir(exist_ok=True)

    background = generate_background(cfg, rng)
    game = generate_game_flows(cfg, rng)

    save_csv("background_router_loads.csv", background)
    save_csv("game_flows.csv", game)

    print("\n===== NETPULSE DYNAMIC TRAFFIC =====")
    print("Simulation steps:", cfg["simulation_steps"])
    print("Interval:", cfg["interval_seconds"], "seconds")
    print("Background records:", len(background))
    print("Game flow records:", len(game))
    print("Random seed:", cfg["seed"])
    print("Generation complete!")


if __name__ == "__main__":
    main()
