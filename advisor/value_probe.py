"""Does the network's value head know your late turn is better? From the start of each of your
logged turns in rounds 9-13 (advisor.engine_exam's positions): your End Turn (rebuilt from the
turn's last decision; `--replay`: your actions replayed in TavernGym, the Tavern following the
log, choices taking your pick) and the network's own greedy turn from the same start; the value head (its expected placement reward, 1st = 1, 8th = -1) and the
warband's stats at both End Turns. If it prefers your turn where yours is bigger, a search over
turns scored by it would find your play; if not, the value head has to learn it first.

    python -X utf8 -m advisor.value_probe data/models/best.pt
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, engine_exam, search, turn_replay
from advisor.policy import load

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())


def act_of(d, g):
    """turn_replay.action_of, plus what it leaves out: End Turn (no chosen option), a minion's
    Activate without a target (position 0) and a move (a position), and Lionfish-style targets
    in the Tavern. ([actions], target eid, where: "board"/"shop") or None (can't follow)."""
    ch = d.get("chosen")
    if not isinstance(ch, dict):
        return [L["A_END"]], None, None
    act = turn_replay.action_of(d, L, g)
    opt = next((o for o in d["options"] if o["id"] == ch.get("option")), None) or {}
    e = opt.get("entity") or {}
    s = d["state"]
    board = [m["eid"] for m in s["friendly"]["board"]]
    t = ch.get("target") if isinstance(ch.get("target"), dict) else None
    where = "shop" if t and t.get("owner") == "bob" else "board"
    if act is not None:
        return act[0], act[1], where
    if e.get("zone") == "PLAY" and e.get("owner") == "friendly" and e.get("type") == "MINION" and e.get("eid") in board:
        i = board.index(e["eid"])
        if t is not None:
            return [L["A_ACTIVATE"] + i], t.get("eid"), where
        pos = ch.get("position") or 0
        if pos == 0:
            return [L["A_ACTIVATE"] + i], None, None
        return [L["A_MOVE"] + i * L["N_BOARD"] + min(len(board), pos) - 1], None, None
    return None


def choose_target(g, d, target, where):
    """Answer the simulator's pending target with the logged one (on the board or in the
    Tavern, by position: the Tavern follows the log). False when it isn't offered."""
    v = json.loads(g.view(0))
    pend = v["me"]["pending"] or {}
    if pend.get("kind") != "target":
        return True
    logged = d["state"]["shop"] if where == "shop" else d["state"]["friendly"]["board"]
    sim = v["me"]["shop"] if where == "shop" else v["me"]["board"]
    pos = next((i for i, m in enumerate(logged) if m.get("eid") == target), None)
    if pos is None or pos >= len(sim):
        return False
    opts = pend.get("targets") or []
    for key in ("eid", "sid"):
        if sim[pos].get(key) in opts:
            g.step(0, L["A_CHOOSE"] + opts.index(sim[pos][key]))
            return True
    return False


def your_turn(turn, combats):
    """The game at your End Turn (TavernGym after your logged actions), or None."""
    while turn and turn[0]["kind"] != "options":
        turn = turn[1:]
    if not turn:
        return None
    g, gaps = bridge.build(turn[0], bridge.game_combats(combats, turn[0]))
    if gaps:
        return None
    for k, d in enumerate(turn):
        v = json.loads(g.view(0))
        if d["kind"] != "options":
            if v["me"]["pending"] and not turn_replay.pick(g, d, L):
                return None
            continue
        if v["me"]["pending"]:
            return None
        if k:
            g = turn_replay.set_shop(g, d["state"])
        act = act_of(d, g)
        if act is None:
            return None
        actions, target, where = act
        if actions == [L["A_END"]]:
            return g
        try:
            for a in actions:
                g.step(0, a)
            if target is not None and not choose_target(g, d, target, where):
                return None
        except ValueError:
            return None
    return None


def net_turn(net, d, combats, seed=11):
    g, gaps = bridge.build(d, bridge.game_combats(combats, d), seed=seed)
    if gaps:
        return None
    for _ in range(300):
        v = json.loads(g.view(0))
        if v["phase"].lower() != "recruit":
            return None
        probs, _ = search._policy(net, g, 0)
        a = int(np.argmax(probs))
        if a == v["actions"]["END"] and not v["me"]["pending"]:
            return g
        g.step(0, a)
    return None


def at_end(net, g):
    v = json.loads(g.view(0))
    _, value = search._policy(net, g, 0)
    return value, sum(m["atk"] + m["hp"] for m in v["me"]["board"])


@torch.no_grad()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--out")
    ap.add_argument("--replay", action="store_true", help="replay your turn instead of rebuilding its end")
    ap.add_argument("--rounds", type=int, nargs=2, default=[9, 13], metavar=("FROM", "TO"))
    a = ap.parse_args()
    torch.set_num_threads(4)
    net, _ = load(a.checkpoint, "cpu")
    net.eval()
    from advisor import library
    decisions = [d for d in map(json.loads, open(a.decisions, encoding="utf-8")) if library.in_split(d["log"])]  # BG_SPLIT
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    turns = {}
    for d in decisions:
        if d["turn"] % 2 == 1:
            turns.setdefault((d["log"], d["segment"], d["turn"]), []).append(d)
    rows = []
    by_turn = {}
    for (log, seg, t), ds in turns.items():  # a reconnect splits a turn: its longest segment
        ds = [x for x in ds if x["kind"] == "options" or x is not ds[0]]
        if len(ds) > len(by_turn.get((log, t), [])):
            by_turn[(log, t)] = ds
    for d0, _ in engine_exam.positions(decisions, combats, range(a.rounds[0], a.rounds[1] + 1)):
        turn = by_turn.get((d0["log"], d0["turn"]), [])
        while turn and turn[0]["kind"] != "options":
            turn = turn[1:]
        if len(turn) < 2:
            continue
        d = turn[0]  # both turns from the same decision (a reconnect's: mid-turn)
        # Your End Turn: rebuilt from the turn's last decision (its state is after all your
        # actions); `--replay`: your actions replayed in TavernGym instead (fewer get through)
        if a.replay:
            gy = your_turn(turn, combats)
        else:
            gy, gaps = bridge.build(turn[-1], bridge.game_combats(combats, turn[-1]))
            gy = None if gaps else gy
        gn = net_turn(net, d, combats)
        if gy is None or gn is None:
            continue
        (vy, sy), (vn, sn) = at_end(net, gy), at_end(net, gn)
        top = max(d["state"]["friendly"]["board"], key=engine_exam.stats, default={})
        rows.append({"log": d["log"], "turn": d["turn"], "engine": top.get("card"),
                     "value_you": vy, "value_net": vn, "stats_you": sy, "stats_net": sn})
        print(f"{d['log'][-8:]} r{(d['turn'] + 1) // 2}: you {sy:>7} value {vy:+.3f} | net {sn:>7} value {vn:+.3f}", flush=True)
    bigger = [r for r in rows if r["stats_you"] > 1.2 * r["stats_net"]]
    smaller = [r for r in rows if r["stats_net"] > 1.2 * r["stats_you"]]
    diff = [r["value_you"] - r["value_net"] for r in rows]
    print(json.dumps({
        "n": len(rows),
        "value_you_minus_net": (round(float(np.mean(diff)), 4), round(float(np.std(diff, ddof=1) / math.sqrt(len(diff))), 4)) if len(diff) > 1 else None,
        "prefers_yours": round(float(np.mean([x > 0 for x in diff])), 3) if diff else None,
        "where_yours_is_bigger": {"n": len(bigger), "prefers_yours": round(float(np.mean([r["value_you"] > r["value_net"] for r in bigger])), 3) if bigger else None},
        "where_its_own_is_bigger": {"n": len(smaller), "prefers_yours": round(float(np.mean([r["value_you"] > r["value_net"] for r in smaller])), 3) if smaller else None},
    }))
    if a.out:
        Path(a.out).write_text(json.dumps(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
