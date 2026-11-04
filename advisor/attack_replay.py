"""Combats replayed attack by attack: each logged combat from its first attack (after Start of
Combat, the logged side first), TavernGym's targets forced to the logged defenders
(`Game::forced_targets`), and every attack's attacker and defender compared with the log's
(card and stats just before it). The random part of a combat is mostly the targets; with them
fixed, the first attack where TavernGym's stats part from the log points at what it got wrong
(an effect too weak or too strong, a trigger missing), where the combat replay (advisor.replay)
can only say a fight was won less often than it should have been.

    python -X utf8 -m advisor.attack_replay [--combats data/replay/combats.jsonl] [--top 25]
"""

import argparse
import collections
import json
from pathlib import Path

from advisor import replay
from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]


def name(card):
    return (CAT.get(normal_form(card or "")[0]) or {}).get("name", card)


def follow(c, seed=1):
    """(attacks followed, the first one that parts from the log or None, how far TavernGym's
    forced targets went). A part: {i, what, logged, simulated}."""
    snap = c.get("first_attack")
    if not snap or not c.get("attacks"):
        return None
    g, gaps = replay.setup(c, snap, seed, (), ())
    if gaps:
        return None
    forced = [[a["defender"], a["datk"], a["dhp"]] for a in c["attacks"]]
    r = json.loads(g.debug(json.dumps({
        "cmd": "combat_preview", "a": 0, "b": 1, "n": 1, "details": True, "after_start": True,
        "first_attacker": 0 if c["first_attacker"] == "friendly" else 1, "forced": forced,
        "waiting": replay.waiting_space(c)})))
    # (side, attacker, atk, hp, defender, datk, dhp) as each attack was declared
    sim = [tuple(x) for x in r["trials"][0].get("attack_trace") or []]
    for i, (la, sa) in enumerate(zip(c["attacks"], sim)):
        side = 0 if la["side"] == "friendly" else 1
        same_cards = (side == sa[0] and normal_form(la["attacker"])[0] == normal_form(sa[1] or "")[0]
                      and normal_form(la["defender"])[0] == normal_form(sa[4] or "")[0])
        if not same_cards:
            return i, {"i": i, "what": "attacker or defender",
                       "logged": [la["side"], la["attacker"], la["defender"]],
                       "simulated": ["friendly" if sa[0] == 0 else "opponent", sa[1], sa[4]]}, len(sim)
        if (la["atk"], la["hp"]) != (sa[2], sa[3]):
            return i, {"i": i, "what": "attacker stats", "card": la["attacker"], "side": la["side"],
                       "logged": [la["atk"], la["hp"]], "simulated": [sa[2], sa[3]]}, len(sim)
        if (la["datk"], la["dhp"]) != (sa[5], sa[6]):
            return i, {"i": i, "what": "defender stats", "card": la["defender"],
                       "side": "opponent" if la["side"] == "friendly" else "friendly",
                       "logged": [la["datk"], la["dhp"]], "simulated": [sa[5], sa[6]]}, len(sim)
    n = min(len(c["attacks"]), len(sim))
    return n, None, len(sim)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", help="JSON: one row per combat")
    a = ap.parse_args()
    rows, parts = [], collections.Counter()
    exact = followed = 0
    for line in open(a.combats, encoding="utf-8"):
        c = json.loads(line)
        res = follow(c)
        if res is None:
            continue
        n, part, sim_n = res
        rows.append({"log": c["log"], "turn": c["turn"], "attacks": len(c["attacks"]), "followed": n,
                     "part": part})
        followed += 1
        if part is None and sim_n >= len(c["attacks"]):
            exact += 1
        elif part and part["what"] != "attacker or defender":
            parts[(part["what"], part["side"], name(part["card"]))] += 1
        elif part:
            parts[("attacker or defender", "", name(part["logged"][1]) + " / " + name(part["simulated"][1] or ""))] += 1
    print(f"{followed} combats followed attack by attack; every attack as logged in {exact} "
          f"({exact / max(1, followed):.1%})")
    print("where the first difference was (what, whose, card): combats")
    for (what, side, card), k in parts.most_common(a.top):
        print(f"  {k:4d}  {what:20s} {side:9s} {card}")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
