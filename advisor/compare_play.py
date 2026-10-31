"""Your turns against the network's, from the same positions (mid and late game). For every turn
you played from round 7 on, its first decision is rebuilt; the network plays the turn out there
(greedy, as the advice's first plan); your own actions that turn come from the log. Per round
band: Refreshes, buys, sells, plays, Upgrades, Activates, Hero Powers per turn, and the Gold left
when the turn ended. Where the two differ is what the network has to learn.

    python -X utf8 -m advisor.compare_play data/models/best.pt
"""

import argparse
import collections
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, search
from advisor.policy import load

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
KINDS = ["refresh", "buy", "sell", "play", "upgrade", "activate", "hero_power", "freeze"]
BANDS = [("rounds 7-9", range(7, 10)), ("rounds 10-12", range(10, 13)), ("rounds 13+", range(13, 30))]


def kind_of(a):
    if a == L["A_REFRESH"]:
        return "refresh"
    if a == L["A_UPGRADE"]:
        return "upgrade"
    if a == L["A_FREEZE"]:
        return "freeze"
    if a in (L["A_HERO_POWER"], L["A_HERO_POWER"] + 1):
        return "hero_power"
    if L["A_BUY"] <= a < L["A_BUY"] + L["N_SHOP"]:
        return "buy"
    if L["A_SELL"] <= a < L["A_SELL"] + L["N_BOARD"]:
        return "sell"
    if L["A_ACTIVATE"] <= a < L["A_ACTIVATE"] + L["N_BOARD"]:
        return "activate"
    if L["A_PLAY"] <= a < L["A_MOVE"]:
        return "play"
    return None


def logged_kind(d):
    """The kind of the player's chosen option at Options decision `d` (as kind_of)."""
    ch = d.get("chosen")
    opt = next((o for o in d["options"] if isinstance(ch, dict) and o["id"] == ch.get("option")), None)
    if opt is None:
        return None
    e = opt.get("entity") or {}
    card = e.get("card") or ""
    if "Reroll" in card:
        return "refresh"
    if "TechUp" in card:
        return "upgrade"
    if "LockAll" in card:
        return "freeze"
    if card.startswith("TB_BaconShop_DragBuy"):
        return "buy"
    if card == "TB_BaconShop_DragSell":
        return "sell"
    if e.get("type") == "HERO_POWER" and e.get("owner") == "friendly":
        return "hero_power"
    if e.get("owner") == "friendly" and e.get("zone") == "HAND":
        return "play"
    if e.get("owner") == "friendly" and e.get("zone") == "PLAY" and e.get("type") == "MINION" and opt.get("targets"):
        return "activate"
    return None


def network_turn(g, net, max_steps=120):
    """The network's greedy turn from `g`: (Counter of kinds, Gold left at End)."""
    c = g.copy()
    counts = collections.Counter()
    gold = None
    for _ in range(max_steps):
        if not c.needs_action(0):
            break
        v = json.loads(c.view(0))
        probs, _ = search._policy(net, c, 0)
        a = int(probs.argmax())
        k = kind_of(a)
        if k:
            counts[k] += 1
        if a == L["A_END"] and not v["me"]["pending"]:
            gold = v["me"]["gold"]
            break
        c.step(0, a)
    return counts, gold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--json", help="write the table here too")
    a = ap.parse_args()
    from advisor.train import wait_while_playing
    torch.set_num_threads(4)
    net, ck = load(a.checkpoint)
    rows = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    turns = collections.defaultdict(list)
    for d in rows:
        if d["kind"] == "options" and d["turn"] % 2 == 1 and (d["turn"] + 1) // 2 >= 7:
            turns[(d["log"], d["segment"], d["turn"])].append(d)
    acc = {b: {"you": collections.Counter(), "net": collections.Counter(), "n": 0,
               "gold_you": [], "gold_net": []} for b, _ in BANDS}
    for key, ds in sorted(turns.items()):
        rnd = (key[2] + 1) // 2
        band = next((b for b, r in BANDS if rnd in r), None)
        first = ds[0]
        g, gaps = bridge.build(first, bridge.game_combats(combats, first))
        if gaps or band is None:
            continue
        wait_while_playing(print)
        you = collections.Counter(k for k in map(logged_kind, ds) if k)
        net_counts, net_gold = network_turn(g, net)
        x = acc[band]
        x["you"].update(you)
        x["net"].update(net_counts)
        x["n"] += 1
        x["gold_you"].append(ds[-1]["state"]["friendly"].get("gold", 0))  # Gold at the last decision
        if net_gold is not None:
            x["gold_net"].append(net_gold)
    print(f"{a.checkpoint} ({ck.get('source') or ck.get('iteration')}): per turn, you | network")
    print(f"{'':14s}" + "".join(f"{k:>16s}" for k in KINDS + ['gold left']))
    table = {}
    for band, _ in BANDS:
        x = acc[band]
        if not x["n"]:
            continue
        cells = {k: (x["you"][k] / x["n"], x["net"][k] / x["n"]) for k in KINDS}
        cells["gold left"] = (float(np.mean(x["gold_you"])) if x["gold_you"] else 0.0,
                              float(np.mean(x["gold_net"])) if x["gold_net"] else 0.0)
        table[band] = {"turns": x["n"], **{k: [round(u, 2), round(v, 2)] for k, (u, v) in cells.items()}}
        print(f"{band} ({x['n']:3d})" + "".join(f"{u:9.2f} |{v:5.2f}" for u, v in cells.values()))
    if a.json:
        Path(a.json).write_text(json.dumps({"checkpoint": a.checkpoint, "bands": table}), encoding="utf-8")


if __name__ == "__main__":
    main()
