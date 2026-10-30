"""Promote a training run's best checkpoint to the network the advisor uses.

Each candidate (a run's best.pt) replaces the current network (data/models/best.pt) only when
it is clearly better head to head: on one seat against seven copies of the current network, its
mean placement over 1,000 unseen games is under 4.5 by more than twice its standard error. The bot
gate (seven scripted bots, the same 1,000 unseen seeds as the current network's) must not be
clearly worse either; against bots alone strong networks all place near 2 and can't be told
apart. A winner must then win again on 1,000 games of seeds no gate has used (winner's curse: with
many candidates judged on the same seeds, the luckiest one wins). The replaced network is kept in data/models/archive/, every decision is logged in
data/models/promotions.jsonl, and a checkpoint already judged at its current version is not
judged again.

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
from advisor.train import CONFIG, evaluate, evaluate_league

MODELS = Path(__file__).resolve().parents[1] / "data" / "models"
GATE = {"episodes": 1000, "seed": 20_000_000}  # advisor.train --evaluate: unseen by training
HEAD_TO_HEAD = {"episodes": 1000, "seed": 40_000_000}  # seeds no other gate uses


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
        # Measured again when the game rules changed since (a gate is only comparable under one)
        if not current or current.get("n") != GATE["episodes"] or current.get("rules") != CONFIG:
            current, _ = gate(best_path, a.device, a.threads)
            current["rules"] = CONFIG
    for cand in map(Path, a.candidates):
        if not cand.is_file():
            continue
        version = f"{cand.resolve()}@{cand.stat().st_mtime_ns}"
        if judged.get(str(cand.resolve())) == version:
            continue
        ev, ck = gate(cand, a.device, a.threads)
        judged[str(cand.resolve())] = version
        judged_path.write_text(json.dumps(judged, indent=1))
        h2h = None
        if current is None:
            better = True
        else:
            # Not clearly worse against the bots, and clearly better head to head
            margin = 2 * math.sqrt(ev["se"] ** 2 + current["se"] ** 2)
            not_worse = ev["mean_place"] <= current["mean_place"] + margin
            cand_net, _ = load(cand, a.device)
            cur_net, _ = load(best_path, a.device)
            h2h = evaluate_league(cand_net, [cur_net], a.device, HEAD_TO_HEAD["episodes"],
                                  seed=HEAD_TO_HEAD["seed"], threads=a.threads)
            h2h.pop("pool", None)
            better = not_worse and h2h["mean_place"] < 4.5 - 2 * h2h["se"]
            if better:
                # Winner's curse: many candidates judged on the same seeds, the luckiest wins.
                # A winner must win again on seeds no gate has used.
                fresh = 60_000_000 + (int(time.time()) % 1_000_000) * 1000
                confirm = evaluate_league(cand_net, [cur_net], a.device, HEAD_TO_HEAD["episodes"],
                                          seed=fresh, threads=a.threads)
                confirm.pop("pool", None)
                h2h["confirm"] = {**confirm, "seed": fresh}
                better = confirm["mean_place"] < 4.5 - 2 * confirm["se"]
        log({"candidate": str(cand), "iteration": ck.get("iteration"), "arch": ck["config"].get("arch"),
             "gate": ev, "current": current, "head_to_head": h2h, "promoted": better})
        if not better:
            continue
        if best_path.exists():
            (models / "archive").mkdir(exist_ok=True)
            shutil.copy(best_path, models / "archive" / f"best_{time.strftime('%Y%m%d_%H%M%S')}.pt")
        ck["gate"] = {**ev, "vs": "7 scripted bots, unseen seeds", "rules": CONFIG}
        if h2h:
            ck["head_to_head"] = h2h
        ck["source"] = f"{cand.parent.name} iteration {ck.get('iteration')} ({datetime.now():%Y-%m-%d %H:%M})"
        ck.pop("opt", None)
        tmp = best_path.with_suffix(".tmp")
        torch.save(ck, tmp)
        tmp.replace(best_path)
        current = ck["gate"]


if __name__ == "__main__":
    main()
