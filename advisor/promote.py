"""Promote a training run's best checkpoint to the network the advisor uses.

Each candidate (a run's best.pt) replaces the current network (data/models/best.pt) only when
it is clearly better head to head: on one seat against seven copies of the current network, its
mean placement over 1,000 unseen games is under 4.5 by more than twice its standard error. The bot
gate (seven scripted bots, the same 1,000 unseen seeds as the current network's) must not be
clearly worse either; against bots alone strong networks all place near 2 and can't be told
apart. A winner must then win again on 1,000 games of seeds no gate has used (winner's curse: with
many candidates judged on the same seeds, the luckiest one wins). A candidate not clearly better
head to head (but not clearly worse) can also win in lobbies with real warbands (two library
seats, advisor.library): clearly better there than the current best on the same seeds, twice;
or from the player's own positions (every logged round start, advisor.train.evaluate_real):
clearly better than the best there, paired start by start, twice.
The replaced network is kept in data/models/archive/, every decision is logged in
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

import taverngym

from advisor.policy import load
from advisor.train import CONFIG, RealStarts, evaluate, evaluate_league, evaluate_real

MODELS = Path(__file__).resolve().parents[1] / "data" / "models"
# A gate is only comparable under one set of rules and one simulator build (a fixed card or
# combat rule changes every network's numbers): both are kept with the current network's gate
RULES = {**CONFIG, "sim": taverngym.build_info()["source_hash"]}
GATE = {"episodes": 1000, "seed": 20_000_000}  # advisor.train --evaluate: unseen by training
HEAD_TO_HEAD = {"episodes": 1000, "seed": 40_000_000}  # seeds no other gate uses
# Lobbies closer to real ones: one seat against seven copies of the current best, two of
# them library seats (real warbands from the logs, advisor.library); candidate and best on the
# same seeds
LIBRARY = {"episodes": 1000, "seed": 45_000_000, "seats": [6, 7], "bot_slack": 0.1}
# From the player's own positions: each logged round start `reps` times (other seeds), the
# candidate and the best each in the player's seat with the best in the seven others
REAL = {"reps": 3, "seed": 47_000_000}


def real_pair(cand_net, cur_net, device, threads, seed):
    """{candidate, current, diff, se, n}: mean placements from the logged round starts and
    the paired difference (candidate minus best); None without starts."""
    states = RealStarts(1.0, 0, log=lambda r: None).states
    if not states:
        return None
    places = ([], [])
    for r in range(REAL["reps"]):
        for n, out in zip((cand_net, cur_net), places):
            evaluate_real(n, cur_net, states, device, seed=seed + r * 1000, threads=threads,
                          places_out=out)
    d = [a - b for a, b in zip(*places)]
    mean = sum(d) / len(d)
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / max(1, len(d) - 1))
    return {"candidate": round(sum(places[0]) / len(d), 3), "current": round(sum(places[1]) / len(d), 3),
            "diff": round(mean, 3), "se": round(sd / math.sqrt(len(d)), 3), "n": len(d)}


def real_better(r):
    return r is not None and r["diff"] < -2 * r["se"]


def library_pair(cand_net, cur_net, device, threads, seed):
    """(candidate, current best): each on seat 0 in lobbies of the best with library seats, on
    the same seeds; None without a library."""
    from advisor import library
    if not library.BOARDS.exists():
        return None
    config = {**CONFIG, "library": library.library(LIBRARY["seats"])}
    out = []
    for n in (cand_net, cur_net):
        r = evaluate_league(n, [cur_net], device, LIBRARY["episodes"], seed=seed, threads=threads,
                            config=config)
        r.pop("pool", None)
        out.append(r)
    return out


def clearly_lower(a, b):
    return a["mean_place"] < b["mean_place"] - 2 * math.sqrt(a["se"] ** 2 + b["se"] ** 2)


def pick_device(need_gb=2.0):
    """The GPU when it has `need_gb` free (training runs share it), else the CPU (slower)."""
    if torch.cuda.is_available():
        try:
            free, _ = torch.cuda.mem_get_info()
            if free >= need_gb * 2**30:
                return "cuda"
        except RuntimeError:  # no context could be made: the GPU is full
            pass
    return "cpu"


def gate(path, device, threads):
    net, ck = load(path, device)
    ev = evaluate(net, device, GATE["episodes"], seed=GATE["seed"], threads=threads)
    return ev, ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="+")
    ap.add_argument("--models", default=str(MODELS))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--device", default=None, help="default: the GPU if it has room, else the CPU")
    a = ap.parse_args()
    a.device = a.device or pick_device()
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
        if not current or current.get("n") != GATE["episodes"] or current.get("rules") != RULES:
            current, _ = gate(best_path, a.device, a.threads)
            current["rules"] = RULES
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
            # Not promoted head to head (a near miss included): the other two ways
            lib = None
            # (the bots' floor with 0.1 places to spare: near 1.5 against bots, a network trained
            # against real warbands may give up a hair there)
            lib_floor = ev["mean_place"] <= current["mean_place"] + margin + LIBRARY["bot_slack"]
            if not better and lib_floor and h2h["mean_place"] <= 4.5 + 2 * h2h["se"]:
                # Or: clearly better in lobbies with real warbands, and not clearly worse head to
                # head (what real games ask of it); confirmed on fresh seeds too
                pair = library_pair(cand_net, cur_net, a.device, a.threads, LIBRARY["seed"])
                if pair and clearly_lower(*pair):
                    fresh = 70_000_000 + (int(time.time()) % 1_000_000) * 1000
                    again = library_pair(cand_net, cur_net, a.device, a.threads, fresh)
                    lib = {"candidate": pair[0], "current": pair[1],
                           "confirm": {"candidate": again[0], "current": again[1], "seed": fresh}}
                    better = clearly_lower(*again)
                elif pair:
                    lib = {"candidate": pair[0], "current": pair[1]}
                h2h["library"] = lib
                if not better:
                    # Or: clearly better from the player's own positions; confirmed on fresh seeds
                    real = real_pair(cand_net, cur_net, a.device, a.threads, REAL["seed"])
                    if real_better(real):
                        fresh = 80_000_000 + (int(time.time()) % 1_000_000) * 1000
                        real["confirm"] = real_pair(cand_net, cur_net, a.device, a.threads, fresh)
                        better = real_better(real["confirm"])
                    h2h["real"] = real
        log({"candidate": str(cand), "iteration": ck.get("iteration"), "arch": ck["config"].get("arch"),
             "gate": ev, "current": current, "head_to_head": h2h, "promoted": better})
        if not better:
            continue
        if best_path.exists():
            (models / "archive").mkdir(exist_ok=True)
            shutil.copy(best_path, models / "archive" / f"best_{time.strftime('%Y%m%d_%H%M%S')}.pt")
        ck["gate"] = {**ev, "vs": "7 scripted bots, unseen seeds", "rules": RULES}
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
