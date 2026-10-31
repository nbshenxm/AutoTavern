"""Does the network play like a strong player? Pattern checks for a checkpoint (docs/PLAY_PLAN.md),
each a number that should move as training learns the pattern:

- beatboxer: positions with a Polarizing Beatboxer, another minion and a Magnetic card in hand.
  Of the network's probability for magnetizing, the share onto another minion (both get it:
  the Beatboxer also magnetizes to itself) rather than onto the Beatboxer.
- late turns: from the player's own positions at round 9 or later with a full warband and Gold
  to spend, the network plays the turn out (greedy): Refreshes, buys, and buys sold again the
  same turn (what a strong player avoids: buying whatever is there instead of finding what
  strengthens the warband), and cards lost to a full hand (10: the order of plays avoids it).

    python -X utf8 -m advisor.patterns data/models/best.pt
"""

import argparse
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, search
from advisor.policy import load
from advisor.state import CAT, debug, recruit_game

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
BEATBOXER = "BG26_149"


def _magnetic(tier):
    cat = json.loads(taverngym.catalog_json())
    return [c["id"] for c in cat if "MAGNETIC" in (c.get("keywords") or []) and c.get("in_pool")
            and (c.get("tier") or 9) <= tier and not c["id"].endswith("_G")]


def beatboxer_positions(n=40, seed=0):
    """Games at round 8 with the Beatboxer and three other Mechs on the warband and a Magnetic
    card in hand."""
    rng = np.random.default_rng(seed)
    mags = _magnetic(5)
    # The others are Mechs (only a Mech takes a Magnetic card), without Magnetic themselves
    pool = [c["id"] for c in json.loads(taverngym.catalog_json()) if c["kind"] == "minion"
            and c.get("in_pool") and 2 <= (c.get("tier") or 0) <= 5 and not c["id"].endswith("_G")
            and "MAGNETIC" not in (c.get("keywords") or []) and "MECHANICAL" in (c.get("races") or [])]
    out = []
    for i in range(n):
        g = recruit_game(int(seed * 1000 + i))
        debug(g, cmd="set_turn", turn=8)
        debug(g, cmd="set_player", p=0, gold=6, tier=5)
        debug(g, cmd="clear_zone", p=0, zone="board")
        debug(g, cmd="clear_zone", p=0, zone="hand")
        others = list(rng.choice(pool, 3, replace=False))
        board = [BEATBOXER] + others
        rng.shuffle(board)
        for c in board:
            debug(g, cmd="add_minion", p=0, zone="board", card=str(c), no_triple=True)
        debug(g, cmd="add_minion", p=0, zone="hand", card=str(rng.choice(mags)), no_triple=True)
        out.append(g)
    return out


@torch.no_grad()
def beatboxer(net, games):
    """(share of the magnetize probability onto another minion, share of positions whose most
    likely magnetization is onto another minion, share where magnetizing is the first choice)."""
    onto_other, best_other, first_mag = [], [], []
    for g in games:
        v = json.loads(g.view(0))
        board = [m["id"] for m in v["me"]["board"]]
        probs, _ = search._policy(net, g, 0)
        lo = L["A_MAGNETIZE"]  # hand 0 x warband slot
        mag = probs[lo:lo + L["N_BOARD"]][:len(board)]
        if mag.sum() <= 0:
            continue
        bb = board.index(BEATBOXER)
        onto_other.append(1 - mag[bb] / mag.sum())
        best_other.append(int(np.argmax(mag)) != bb)
        first_mag.append(lo <= int(probs.argmax()) < lo + L["N_BOARD"])
    return (float(np.mean(onto_other)), float(np.mean(best_other)), float(np.mean(first_mag)))


def late_turns(net, decisions, combats, limit=40):
    """From logged positions at round 9+ with 7 minions and 4+ Gold: the network's turn (greedy).
    Mean Refreshes, buys, and buys sold again the same turn, per turn."""
    picked, seen = [], set()
    for d in decisions:
        key = (d["log"], d["segment"], d["turn"])
        fr = d["state"]["friendly"]
        if d["kind"] != "options" or d["turn"] < 17 or key in seen or len(fr["board"]) < 7 \
                or fr.get("gold", 0) < 4:
            continue
        seen.add(key)
        picked.append(d)
    refresh = buys = resold = lost = 0
    n = 0
    for d in picked[:limit]:
        g, gaps = bridge.build(d, bridge.game_combats(combats, d))
        if gaps:
            continue
        c = g.copy()
        bought = set()
        n += 1
        lost0 = json.loads(c.state_json())["players"][0]["stats"].get("cards_lost", 0)
        for _ in range(60):
            if not c.needs_action(0):
                break
            v = json.loads(c.view(0))
            probs, _ = search._policy(net, c, 0)
            a = int(probs.argmax())
            if a == L["A_REFRESH"]:
                refresh += 1
            elif L["A_BUY"] <= a < L["A_BUY"] + L["N_SHOP"]:
                buys += 1
                slot = a - L["A_BUY"]
                if slot < len(v["me"]["shop"]):
                    bought.add(v["me"]["shop"][slot].get("eid"))
            elif L["A_SELL"] <= a < L["A_SELL"] + L["N_BOARD"]:
                slot = a - L["A_SELL"]
                if slot < len(v["me"]["board"]) and v["me"]["board"][slot].get("eid") in bought:
                    resold += 1
            c.step(0, a)
            if a == L["A_END"]:
                break
        lost += json.loads(c.state_json())["players"][0]["stats"].get("cards_lost", 0) - lost0
    n = max(1, n)
    return {"turns": n, "refreshes": round(refresh / n, 2), "buys": round(buys / n, 2),
            "bought_then_sold": round(resold / n, 2), "cards_lost": round(lost / n, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoints", nargs="+")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    a = ap.parse_args()
    torch.set_num_threads(4)
    games = beatboxer_positions()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    for path in a.checkpoints:
        net, ck = load(path)
        bb = beatboxer(net, games)
        lt = late_turns(net, decisions, combats)
        print(json.dumps({"checkpoint": path, "source": ck.get("source") or ck.get("iteration"),
                          "beatboxer": {"prob_onto_other": round(bb[0], 3), "best_onto_other": round(bb[1], 3),
                                        "magnetize_first": round(bb[2], 3)},
                          "late_turns": lt}, ensure_ascii=False))


if __name__ == "__main__":
    main()
