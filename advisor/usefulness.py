"""How the advice fared in your games (docs/ROBUSTNESS.md section 6): at every recruit decision
the overlay advised on (history.jsonl, matched to the log's decision by what it was based on),
the advice's first step against what you did next: the same kind of step (buy, sell, play,
Refresh, Freeze, Upgrade, End Turn...), and for a buy, sell or play the same card; and whether
you took that step later in the turn (another order of the same plan). Per game,
and where you went another way, what each did (the advice's step -> yours): the cases to read.

    python -X utf8 -m advisor.usefulness           # every logged game with advice
Writes data/progress/usefulness.json (the progress page).
"""

import collections
import json
import os
from pathlib import Path

import taverngym

from advisor import bridge, compare_play, decisions, library, logs, recruit_diff
from advisor.live import CARDS

ROOT = Path(__file__).resolve().parents[1]
HISTORY = Path(os.environ.get("LOCALAPPDATA", "")) / "TavernAdvisor" / "history.jsonl"
OUT = ROOT / "data" / "progress" / "usefulness.json"
L = dict(taverngym.layout())


def key(log, d):
    """What an advice was based on (live.record's `seen`), from a log's decision. (Not the
    segment: the live tracker counts them from 1, the offline extractor one more.)"""
    me = d["state"]["friendly"]
    return (log, d.get("turn"), me.get("gold"),
            tuple(x["card"] for x in d["state"].get("shop", [])),
            tuple(h.get("card") for h in bridge.hand_cards(me)), tuple(m["card"] for m in me["board"]))


def seen_key(s):
    return (s.get("log"), s.get("game_turn"), s.get("gold"), tuple(s.get("tavern") or ()),
            tuple(s.get("hand") or ()), tuple(s.get("board") or ()))


def your_step(d):
    """(kind, card) of the option you chose at `d`; None when the log has no choice."""
    ch = d.get("chosen")
    opt = next((o for o in d["options"] if isinstance(ch, dict) and o["id"] == ch.get("option")), None)
    if opt is None:
        return None
    if opt.get("type") == "END_TURN":
        return "end", None
    acts = recruit_diff.chosen_actions(d)
    return compare_play.logged_kind(d), (acts[2] if acts else None)


# An advice from before its actions were kept (Oct 30): its first row's verb, in any locale
VERB_KIND = {"end": "end", "refresh": "refresh", "freeze": "freeze", "upgrade": "upgrade",
             "hero_power": "hero_power", "buy": "buy", "sell": "sell", "activate": "activate",
             "play": "play", "magnetize": "play", "arrange": "move"}


def _verb_kind(verb):
    from advisor import display
    for loc in display.TEXT:
        for k, kind in VERB_KIND.items():
            if verb and verb.split(" ×")[0] == display.t(loc, k):
                return kind
    return None


def advice_step(advice):
    """(kind, card) of the advice's first step; None when it can't be told."""
    acts = advice.get("actions")
    rows = (advice.get("display") or {}).get("rows") or []
    if not acts:
        if not rows:
            return None
        return _verb_kind(rows[0].get("verb")), rows[0].get("card_id")
    a = acts[0]
    if a == L["A_END"]:
        return "end", None
    if a >= L["A_MOVE"]:
        return "move", None
    return compare_play.kind_of(a), (rows[0].get("card_id") if rows else None)


def same_card(a, b):
    strip = lambda c: (c or "").removesuffix("_G")
    return a is None or b is None or strip(a) == strip(b)


def review(history=HISTORY):
    shown = {}
    for line in open(history, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        s = r.get("seen") or {}
        if s.get("kind") == "options":
            shown[seen_key(s)] = r["advice"]  # the last advice shown for that position
    skins = logs.skin_parents(CARDS)
    out = {}
    for f in library.bg_logs():
        log = f.parent.name
        if not any(k[0] == log for k in shown):
            continue
        n = kind_same = card_same = later = 0
        other = collections.Counter()
        ds = [d for d in decisions.extract(f, skins) if d["kind"] == "options" and d["turn"] % 2 == 1]
        turn_steps = collections.defaultdict(list)  # (segment, turn) -> [(index, your step)]
        for i, d in enumerate(ds):
            turn_steps[(d["segment"], d["turn"])].append((i, your_step(d)))
        for i, d in enumerate(ds):
            a = shown.get(key(log, d))
            if a is None:
                continue
            mine, adv = your_step(d), advice_step(a)
            if mine is None or adv is None or mine[0] is None or adv[0] is None:
                continue
            n += 1
            later += any(m is not None and m[0] == adv[0] and same_card(m[1], adv[1])
                         for j, m in turn_steps[(d["segment"], d["turn"])] if j >= i)
            if mine[0] == adv[0]:
                kind_same += 1
                card_same += same_card(mine[1], adv[1])
            else:
                other[f"{adv[0]} -> {mine[0]}"] += 1
        if n:
            out[log] = {"decisions": n, "same_kind": round(kind_same / n, 3), "followed": round(card_same / n, 3),
                        "in_turn": round(later / n, 3),
                        "otherwise": dict(other.most_common(6))}
    return out


def main():
    res = review()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    for log, r in res.items():
        print(f"{log}: {r['decisions']} decisions, followed {r['followed']:.0%} (same kind {r['same_kind']:.0%},"
              f" later that turn {r['in_turn']:.0%});"
              f" otherwise {r['otherwise']}")


if __name__ == "__main__":
    main()
