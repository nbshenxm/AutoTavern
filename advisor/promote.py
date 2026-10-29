"""Promote a training run's best checkpoint to the network the advisor uses.

Each candidate (a run's best.pt) plays the bot gate on the same 1,000 unseen seeds the current
network (data/models/best.pt) was judged on; it replaces the current one only when clearly better:
its mean placement lower by more than twice the combined standard error. The replaced network is
kept in data/models/archive/, every decision is logged in data/models/promotions.jsonl, and a
checkpoint already judged at its current version is not judged again.

    python -X utf8 -m advisor.promote data/train/office2/best.pt [more candidates...]
"""

import argparse
import json
import math
import shutil
import time
from datetime import datetime
from pathlib import Path

import torch

from advisor.policy import load
from advisor.train import evaluate

MODELS = Path(__file__).resolve().parents[1] / "data" / "models"
GATE = {"episodes": 1000, "seed": 20_000_000}  # advisor.train --evaluate: unseen by training


def gate(path, device, threads):
    net, ck = load(path, device)
    ev = evaluate(net, device, GATE["episodes"], seed=GATE["seed"], threads=threads)
    return ev, ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="+")
    ap.add_argument("--models", default=str(MODELS))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args()
    models = Path(a.models)
    models.mkdir(parents=True, exist_ok=True)
    best_path, log_path = models / "best.pt", models / "promotions.jsonl"
    judged_path = models / "judged.json"
    judged = json.loads(judged_path.read_text()) if judged_path.exists() else {}

    def log(row):
        row = {"time": datetime.now().isoformat(timespec="seconds"), **row}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    current = None
    if best_path.exists():
        ck = torch.load(best_path, map_location="cpu", weights_only=False)
        current = ck.get("gate")
        if not current or current.get("n") != GATE["episodes"]:
            current, _ = gate(best_path, a.device, a.threads)
    for cand in map(Path, a.candidates):
        if not cand.is_file():
            continue
        version = f"{cand.resolve()}@{cand.stat().st_mtime_ns}"
        if judged.get(str(cand.resolve())) == version:
            continue
        ev, ck = gate(cand, a.device, a.threads)
        judged[str(cand.resolve())] = version
        judged_path.write_text(json.dumps(judged, indent=1))
        margin = 2 * math.sqrt(ev["se"] ** 2 + (current or {"se": 0})["se"] ** 2)
        better = current is None or ev["mean_place"] < current["mean_place"] - margin
        log({"candidate": str(cand), "iteration": ck.get("iteration"), "arch": ck["config"].get("arch"),
             "gate": ev, "current": current, "margin": round(margin, 3), "promoted": better})
        if not better:
            continue
        if best_path.exists():
            (models / "archive").mkdir(exist_ok=True)
            shutil.copy(best_path, models / "archive" / f"best_{time.strftime('%Y%m%d_%H%M%S')}.pt")
        ck["gate"] = {**ev, "vs": "7 scripted bots, unseen seeds"}
        ck["source"] = f"{cand.parent.name} iteration {ck.get('iteration')} ({datetime.now():%Y-%m-%d %H:%M})"
        ck.pop("opt", None)
        tmp = best_path.with_suffix(".tmp")
        torch.save(ck, tmp)
        tmp.replace(best_path)
        current = ck["gate"]


if __name__ == "__main__":
    main()
