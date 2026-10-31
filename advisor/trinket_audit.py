"""Are the trinkets simulated right? The simulator's checks against your games (advisor.fidelity)
split by trinket: for every trinket you or the opponent had, the logged combats it was in (how
likely the simulator finds the real result, and how often it is a surprise), and for yours the
turns replayed whole (advisor.turn_replay: never part from the log) and the turn transitions
(Gold, Tier, costs at the next turn), against the same numbers without it. A trinket whose
numbers are clearly below the rest is the one to read.

    python -X utf8 -m advisor.trinket_audit
Writes data/progress/trinket_audit.json.
"""

import collections
import json
from pathlib import Path

import taverngym

from advisor import bridge, replay, transition_check, turn_replay
from advisor.train import wait_while_playing

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "replay"
OUT = ROOT / "data" / "progress" / "trinket_audit.json"
CAT = {c["id"]: c for c in json.loads(taverngym.catalog_json())}


def ids(side):
    return {t["card"] for t in (side or {}).get("trinkets") or [] if t.get("card")}


def main():
    rows = [json.loads(l) for l in open(DATA / "decisions.jsonl", encoding="utf-8")]
    combats = [json.loads(l) for l in open(DATA / "combats.jsonl", encoding="utf-8")]
    per = collections.defaultdict(lambda: {"combats": [], "turns": [], "transitions": []})
    allc = []
    for c in combats:
        if not c.get("start"):
            continue
        wait_while_playing(print)
        r = replay.replay(c, 200, "start", 7)
        if r is None or r["gaps"]:
            continue
        allc.append(r["p_win"])
        for t in ids(c["start"]["friendly"]) | ids(c["start"]["opponent"]):
            per[t]["combats"].append(r["p_win"])
    L = dict(taverngym.layout())
    turns = collections.defaultdict(list)
    for d in rows:
        if d["turn"] % 2 == 1 and d["turn"] > 0:
            turns[(d["log"], d["segment"], d["turn"])].append(d)
    allt, allx = [], []
    for key, turn in sorted(turns.items()):
        wait_while_playing(print)
        res = turn_replay.replay_turn(turn, combats, L)
        opts = [d for d in turn if d["kind"] == "options"]
        if res is None or not opts:
            continue
        mine = ids(opts[0]["state"]["friendly"])
        allt.append(not res)
        for t in mine:
            per[t]["turns"].append(not res)
        nxt = turns.get((key[0], key[1], key[2] + 2))
        nxt = [d for d in nxt or [] if d["kind"] == "options"]
        last = opts[-1]
        ch = last.get("chosen") or {}
        opt = next((o for o in last["options"] if o["id"] == ch.get("option")), None)
        if not nxt or (opt is not None and opt["type"] != "END_TURN"):
            continue
        g, gaps = bridge.build(last, bridge.game_combats(combats, last))
        if gaps:
            continue
        try:
            v = transition_check.next_turn(g)
        except ValueError:
            continue
        if v is None:
            continue
        diff = {f for f in transition_check.compare(v, nxt[0]) if f in ("max gold", "tier", "upgrade cost", "tavern size")}
        allx.append(not diff)
        for t in mine:
            per[t]["transitions"].append(not diff)
    mean = lambda x: round(sum(x) / len(x), 3) if x else None
    out = {"all": {"combats": [mean(allc), len(allc)], "turns": [mean(allt), len(allt)],
                   "transitions": [mean(allx), len(allx)]}, "trinkets": {}}
    for t, x in sorted(per.items(), key=lambda kv: -len(kv[1]["combats"])):
        c = CAT.get(t, {})
        out["trinkets"][t] = {"name": c.get("name"), "name_zh": c.get("name_zh"), "implemented": c.get("implemented"),
                              "combats": [mean(x["combats"]), len(x["combats"])],
                              "turns": [mean(x["turns"]), len(x["turns"])],
                              "transitions": [mean(x["transitions"]), len(x["transitions"])]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("all:", out["all"])
    for t, r in out["trinkets"].items():
        print(f"{t:24s} {r['name'] or '?':28s} combats {r['combats']} turns {r['turns']} transitions {r['transitions']}"
              f"{'' if r['implemented'] else '  NOT IMPLEMENTED'}")


if __name__ == "__main__":
    main()
