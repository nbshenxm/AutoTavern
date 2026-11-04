"""The player's own choices as training targets: every logged recruit decision rebuilt by the
bridge (the observation TavernGym gives in that position) with the action the player took, in
the search shards' format (advisor.search_games), for advisor.train --human-data. A 6-7k
player's choices aren't the best ones, but in real late games they are far better than the
network's own (advisor.continue_test): a small cross-entropy toward them, beside PPO.

    python -X utf8 -m advisor.human_data --out data/search/human   # and data/search/human_eval
"""

import argparse
import json
from pathlib import Path

import taverngym

from advisor import bridge, search_games, turn_replay
from advisor.policy import observe

ROOT = Path(__file__).resolve().parents[1]


def rows(decisions, combats, L, full=False):
    """[(features, cards, mask, action)] for every Options decision whose chosen action maps to a
    TavernGym action legal in the rebuilt state (a turn's last decision: End Turn). `full`: also
    a minion's Activate and a move (advisor.value_probe.act_of; turn_replay leaves them out: the
    Lionfish activations the late-game case study is about)."""
    from advisor import value_probe
    out = []
    by_turn = {}
    for d in decisions:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            by_turn.setdefault((d["log"], d["segment"], d["turn"]), []).append(d)
    for ds in by_turn.values():
        for k, d in enumerate(ds):
            g, gaps = bridge.build(d, bridge.game_combats(combats, d))
            if gaps:
                continue
            act = value_probe.act_of(d, g) if full else turn_replay.action_of(d, L, g)
            if act is not None:
                a = act[0][0]
            elif k == len(ds) - 1 and not d.get("chosen"):
                a = L["A_END"]  # the log keeps no answer for End Turn
            else:
                continue
            f, c, m = observe(g, 0)
            if m[a] and bridge.allowed_mask(m.tolist(), d)[a]:
                out.append((f, c, m, a))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "search" / "human"))
    ap.add_argument("--held-out", type=int, default=2, help="the last N games: evaluation only")
    ap.add_argument("--rounds", type=int, nargs=2, metavar=("FROM", "TO"),
                    help="only these rounds' decisions, Activates and moves mapped too (mid1: 5 8)")
    ap.add_argument("--min-last-round", type=int, default=0,
                    help="only games that lasted at least to this round (the ones whose plan worked)")
    ap.add_argument("--better-than", metavar="PROBE_JSON",
                    help="only the turns advisor.value_probe's rows (--out) rate above the network's "
                         "own (value_you > value_net), with Activates and moves mapped too")
    a = ap.parse_args()
    L = dict(taverngym.layout())
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    if a.better_than:
        keep_turns = {(r["log"], r["turn"]) for r in json.loads(Path(a.better_than).read_text(encoding="utf-8"))
                      if r["value_you"] > r["value_net"]}
        decisions = [d for d in decisions if (d["log"], d["turn"]) in keep_turns]
        print(f"{len(keep_turns)} turns rated above the network's own, {len(decisions)} decisions")
    if a.min_last_round:  # (before the round filter: a game's length is its last round)
        last = {}
        for d in decisions:
            last[d["log"]] = max(last.get(d["log"], 0), (d["turn"] + 1) // 2)
        decisions = [d for d in decisions if last[d["log"]] >= a.min_last_round]
    if a.rounds:
        decisions = [d for d in decisions if a.rounds[0] <= (d["turn"] + 1) // 2 <= a.rounds[1]]
    if a.rounds or a.min_last_round:
        print(f"{len({d['log'] for d in decisions})} games, {len(decisions)} decisions after the filters")
    logs = sorted({d["log"] for d in decisions})
    held = set(logs[-a.held_out:]) if a.held_out else set()
    for name, keep in ((a.out, lambda d: d["log"] not in held), (a.out + "_eval", lambda d: d["log"] in held)):
        r = rows([d for d in decisions if keep(d)], combats, L, full=bool(a.better_than or a.rounds))
        out = Path(name)
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("shard_*.npz"):
            old.unlink()  # one set: the logs as they are now
        if r:
            print(f"{len(r)} decisions -> {search_games.write_shard(out, r)}")


if __name__ == "__main__":
    main()
