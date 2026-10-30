"""Can the network scale from where real players stand? From the player's own position at the
start of a logged round (the bridge's game: their warband, hand, gold, tier, the opponents last
seen), the network plays every seat on in TavernGym for a few rounds; its seat's warband
(Attack+Health at each turn's end) is compared with the player's real one in the next combats.
If the network keeps pace from a real midgame, the gap in self-play (advisor.study --curve) is
where its games go, not what the simulator can do.

    python -X utf8 -m advisor.continue_test data/models/best.pt --rounds 6 8 10 --ahead 4
"""

import argparse
import collections
import json
from pathlib import Path

import numpy as np
import torch

from advisor import bridge, search
from advisor.policy import load
from advisor.train import wait_while_playing

ROOT = Path(__file__).resolve().parents[1]


def rollout(g, net, start, ahead, rng, sample, k=0):
    """Seat 0's warband Attack+Health at the end of each round from `start` to start+ahead.
    `k` > 0: seat 0 plays the plan search's turn (advisor.search, as the live advisor does)."""
    out, script = {}, []
    for _ in range(100_000):
        if g.is_over():
            break
        stepped = False
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            v = json.loads(g.view(seat))
            if v["turn"] > start + ahead:
                return out
            a = None
            if seat == 0 and k and v["phase"].lower() == "recruit":
                if not script:
                    script = list(search.best_plan(g, net, 0, None, k)[0])
                a = script.pop(0) if script else None
                if a is not None and not v["mask"][a]:
                    a, script = None, []
            if a is None:
                probs, _ = search._policy(net, g, seat)
                a = int(rng.choice(len(probs), p=probs / probs.sum())) if sample else int(probs.argmax())
            if seat == 0 and v["phase"].lower() == "recruit" and not v["me"]["pending"] \
                    and a == v["actions"]["END"]:
                out[v["turn"]] = sum(m["atk"] + m["hp"] for m in v["me"]["board"])
            g.step(seat, a)
            stepped = True
        if not stepped:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--rounds", type=int, nargs="+", default=[6, 8, 10])
    ap.add_argument("--ahead", type=int, default=4)
    ap.add_argument("--trials", type=int, default=2)
    ap.add_argument("--greedy", action="store_true")
    ap.add_argument("--search", type=int, default=0, metavar="K", help="seat 0 plays the plan search's turns")
    a = ap.parse_args()
    torch.set_num_threads(4)
    net, _ = load(a.checkpoint, "cpu")
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    real = {}
    for c in combats:
        real[(c["log"], c["segment"], (c["turn"] + 1) // 2)] = sum(
            m["atk"] + m["hp"] for m in c["start"]["friendly"]["board"])
    starts = {}
    for line in open(a.decisions, encoding="utf-8"):
        d = json.loads(line)
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        r = (d["turn"] + 1) // 2
        key = (d["log"], d["segment"], r)
        if r in a.rounds and key not in starts:
            starts[key] = d
    rng = np.random.default_rng(5)
    ratio = collections.defaultdict(list)  # (start, rounds ahead): simulated / real
    for (log, seg, r), d in sorted(starts.items()):
        wait_while_playing(print)  # home rule: no heavy jobs while you play
        g0, gaps = bridge.build(d, bridge.game_combats(combats, d))
        line = []
        for t in range(a.trials):
            g, _ = bridge.build(d, bridge.game_combats(combats, d), seed=11 + t)
            sim = rollout(g, net, r, a.ahead, rng, not a.greedy, a.search)
            for k in range(a.ahead + 1):
                rr = (log, seg, r + k)
                if rr in real and r + k in sim and real[rr] > 0:
                    ratio[(r, k)].append(sim[r + k] / real[rr])
            line.append(" ".join(f"{sim.get(r + k, '-')}" for k in range(a.ahead + 1)))
        reals = " ".join(f"{real.get((log, seg, r + k), '-')}" for k in range(a.ahead + 1))
        print(f"{log[-8:]} seg {seg} round {r}: real {reals} | network {' ; '.join(line)}"
              + (f" (gaps: {len(gaps)})" if gaps else ""), flush=True)
    print("\nmedian network/real warband stats, by start round and rounds ahead")
    for r in a.rounds:
        print(f"  from round {r}: " + "  ".join(
            f"+{k} {np.median(ratio[(r, k)]):.2f} (n {len(ratio[(r, k)])})" for k in range(a.ahead + 1)
            if ratio.get((r, k))))


if __name__ == "__main__":
    main()
