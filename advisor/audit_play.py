"""The play audit a candidate must pass before promotion (advisor.promote), beside the training
gates: a network can score well against its own copies while its advice makes no sense in a
real game (a reward hack, a loop, a habit self-play doesn't punish). Two parts:

- advice: the live advisor's plan (plan search, as the overlay shows it) at the player's logged
  round starts (data/library/starts.jsonl). Per plan: a first step the client wouldn't allow,
  a detour (sell a minion and play the same card, either order, no Battlecry), ending the turn
  with 3+ Gold while a buy or a Refresh is legal, two or more Freeze presses, more than two
  Arrange steps, more than 25 steps;
- games: complete games with the network in every seat (sampled): games that stall or reach the
  turn cap, the share of actions that are moves and Freeze presses, cards lost to a full hand,
  Gold left at End Turn while it could buy or refresh, plays of cards that work from the hand
  (search.HAND_ONLY: Flighty Scout).

`check(candidate, current)` lists what the candidate does clearly worse than the current best.

    python -X utf8 -m advisor.audit_play data/train/big2/best.pt data/models/best.pt
"""

import argparse
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import search
from advisor.policy import load
from advisor.state import GAME_CONFIG

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
# How much worse than the current best a candidate may be before the audit fails it (rates are
# shares of plans or of actions; games are counts)
MARGINS = {"illegal_first": 0.02, "detour": 0.01, "end_with_gold": 0.08, "freeze_toggles": 0.05,
           "long_arrange": 0.05, "long_plan": 0.05, "stalled_games": 0, "move_share": 0.05,
           "freeze_share": 0.02, "cards_lost": 0.5, "gold_left": 1.0, "hand_only_plays": 0.02}


def advice_audit(net, starts, n=60, k=4):
    """Rates over the live advice at `n` logged round starts (late ones first)."""
    from advisor import live
    live.SEARCH["k"] = k
    picked = sorted(starts, key=lambda r: -r["d"]["turn"])[:n]
    counts = dict.fromkeys(["illegal_first", "detour", "end_with_gold", "freeze_toggles",
                            "long_arrange", "long_plan"], 0)
    done, samples = 0, []
    for r in picked:
        d = r["d"]
        try:
            a = live.advise(d, r["combats"], net=net)
        except Exception:
            continue
        done += 1
        plan = a["plan"] or []
        if len(samples) < 6:  # for reading: what it advises at real late positions
            samples.append(f"round {(d['turn'] + 1) // 2}, {a.get('gold')} gold: " + " -> ".join(plan))
        if "the first step is not offered by the client" in (a.get("warnings") or []):
            counts["illegal_first"] += 1
        for i, p in enumerate(plan):
            if p.startswith("Sell ") and any(q.startswith("Play " + p[5:] + " at") for q in plan[i + 1:]):
                counts["detour"] += 1
                break
        counts["freeze_toggles"] += sum(p.startswith("Freeze") for p in plan) >= 2
        counts["long_arrange"] += sum(p.startswith("Arrange") for p in plan) > 2
        counts["long_plan"] += len(plan) > 25
        if plan and plan[-1].startswith("End") and a.get("could_spend") and (a.get("gold_left") or 0) >= 3:
            counts["end_with_gold"] += 1
    return {k_: round(v / max(1, done), 3) for k_, v in counts.items()} | {"plans": done, "samples": samples}


def game_audit(net, games=4, seed=55_000_000):
    """Complete games with `net` in every seat (sampled)."""
    stalled = moves = freezes = actions = lost = hand_only = plays = 0
    gold_left, ends = 0, 0
    rng = np.random.default_rng(seed)
    for i in range(games):
        g = taverngym.Game(seed + i, json.dumps(GAME_CONFIG))
        for _ in range(300_000):
            if g.is_over():
                break
            moved = False
            for seat in range(g.num_players):
                if not g.needs_action(seat):
                    continue
                v = json.loads(g.view(seat))
                probs, _ = search._policy(net, g, seat)
                a = int(rng.choice(len(probs), p=probs / probs.sum()))
                actions += 1
                moves += a >= L["A_MOVE"]
                if L["A_PLAY"] <= a < L["A_MAGNETIZE"]:  # a card that works from the hand, played
                    plays += 1
                    h = (a - L["A_PLAY"]) // L["N_POS"]
                    hand_only += h < len(v["me"]["hand"]) and v["me"]["hand"][h].get("id") in search.HAND_ONLY
                freezes += a == L["A_FREEZE"]
                if a == L["A_END"] and v["phase"].lower() == "recruit" and not v["me"]["pending"]:
                    m = v["mask"]
                    if m[L["A_REFRESH"]] or any(m[L["A_BUY"]:L["A_BUY"] + L["N_SHOP"]]):
                        gold_left += v["me"]["gold"]
                    ends += 1
                g.step(seat, a)
                moved = True
            if not moved:
                break
        st = json.loads(g.state_json())
        stalled += (not g.is_over()) or bool(g.turn_limit_end) or bool(st.get("stopped_reason"))
        lost += sum(p["stats"].get("cards_lost", 0) for p in st["players"])
    return {"stalled_games": stalled, "move_share": round(moves / max(1, actions), 3),
            "freeze_share": round(freezes / max(1, actions), 3),
            "cards_lost": round(lost / max(1, games * 8), 2), "gold_left": round(gold_left / max(1, ends), 2),
            "hand_only_plays": round(hand_only / max(1, plays), 4),
            "games": games}


def audit(path, starts, plans=60, games=4):
    torch.set_num_threads(4)
    net, _ = load(path, "cpu")
    return {**advice_audit(net, starts, plans), **game_audit(net, games)}


def check(cand, cur):
    """The measures where the candidate is worse than the current best by more than MARGINS."""
    return {k: (cand[k], cur.get(k)) for k, m in MARGINS.items()
            if k in cand and cur.get(k) is not None and cand[k] > cur[k] + m}


def load_starts():
    from advisor import library
    if not library.STARTS.exists():
        return []
    return [json.loads(l) for l in open(library.STARTS, encoding="utf-8")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("current", nargs="?")
    ap.add_argument("--plans", type=int, default=60)
    ap.add_argument("--games", type=int, default=4)
    a = ap.parse_args()
    starts = load_starts()
    cand = audit(a.candidate, starts, a.plans, a.games)
    print(json.dumps({"candidate": a.candidate, **cand}))
    if a.current:
        cur = audit(a.current, starts, a.plans, a.games)
        print(json.dumps({"current": a.current, **cur}))
        print("worse:", check(cand, cur) or "nothing")


if __name__ == "__main__":
    main()
