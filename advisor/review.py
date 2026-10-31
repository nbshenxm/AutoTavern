"""Every piece of advice reviewed (docs/ROBUSTNESS.md, section 1): a session's log replayed
through the live advisor (the same code and network as the overlay), each advice checked on the
full rebuilt state. Two kinds of findings:

- rules without exceptions (any one is a bug to fix): the first step not offered by the client,
  a sell-and-replay detour, a step the simulator refuses;
- signals that are usually wrong (reported, never banned): the turn ended with 3+ Gold that could
  still buy or refresh, a card lost to a full hand by the plan's own order, the plan leaving the
  warband clearly weaker (Attack+Health) or with clearly worse odds against the next opponent's
  last seen warband, and regret: at the turn's first decision, the warband you actually ended the
  turn with beat the next opponent clearly more often than the advised one.

    python -X utf8 -m advisor.review                  # the newest Battlegrounds log
    python -X utf8 -m advisor.review --all            # every log
Writes data/review/<log>.json and prints the findings by pattern, worst first.
"""

import argparse
import collections
import json
from pathlib import Path

import taverngym

from advisor import bridge, decisions, library, live, logs, search
from advisor.live import CARDS, Policy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "review"
# How much worse a signal must be to be reported
ODDS_DROP, STATS_DROP, REGRET = 0.2, 0.25, 0.25


def win(odds):
    return None if not odds else odds["win"] - odds["loss"]


def review_log(path, net, k=8, locale="zhCN"):
    """[finding] for one log: {kind, rule (bool), round, gold, plan, detail}."""
    from advisor.train import wait_while_playing
    skins = logs.skin_parents(CARDS)
    ds = decisions.extract(path, skins)
    combats, _ = logs.extract(path, skins)
    live.SEARCH["k"] = k
    by_turn = collections.defaultdict(list)
    for d in ds:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            by_turn[(d["segment"], d["turn"])].append(d)
    out = []
    for (seg, turn), turn_ds in sorted(by_turn.items()):
        wait_while_playing(print)  # home rule
        for i, d in enumerate(turn_ds):
            game_combats = bridge.game_combats(combats, d)
            try:
                a = live.advise(d, game_combats, locale=locale, net=net)
            except Exception as e:  # an advice that crashes is a rule broken
                out.append(finding(d, None, "crash", True, f"{type(e).__name__}: {e}"))
                continue
            plan = a.get("plan") or []
            if "the first step is not offered by the client" in (a.get("warnings") or []):
                out.append(finding(d, a, "first step not offered", True))
            for j, p in enumerate(plan):
                if p.startswith("Sell ") and any(q.startswith("Play " + p[5:] + " at") for q in plan[j + 1:]):
                    out.append(finding(d, a, "sell-and-replay detour", True, p))
                    break
            if plan and plan[-1].startswith("End") and a.get("could_spend") and (a.get("gold_left") or 0) >= 3:
                out.append(finding(d, a, "ended with spendable Gold", False, f"{a['gold_left']} Gold"))
            if (a.get("cards_lost") or 0) > 0:
                out.append(finding(d, a, "card lost to a full hand", False, f"{a['cards_lost']} lost"))
            before, after = a.get("stats_before") or 0, a.get("stats_after") or 0
            if before >= 20 and after < before * (1 - STATS_DROP) and plan and plan[-1].startswith("End"):
                out.append(finding(d, a, "warband weaker after the plan", False, f"{before} -> {after}"))
            w0, w1 = win(a.get("odds_now")), win(a.get("odds_after_plan"))
            if w0 is not None and w1 is not None and w1 < w0 - ODDS_DROP:
                out.append(finding(d, a, "odds worse after the plan", False, f"{w0:+.2f} -> {w1:+.2f}"))
            if i == 0 and len(turn_ds) > 1:
                r = regret(turn_ds[-1], game_combats, a)
                if r is not None:
                    out.append(finding(d, a, "you did better", False, r))
    return out


def regret(last, game_combats, advice):
    """At a turn's first decision: the warband the player ended the turn with (its last decision)
    against the advised one, by odds against the next opponent's last seen warband; a detail
    string when the player's was clearly better."""
    w_adv = win(advice.get("odds_after_plan"))
    if w_adv is None:
        return None
    g, gaps = bridge.build(last, game_combats)
    if gaps:
        return None
    w_real = win(live.combat_odds(g))
    if w_real is not None and w_real > w_adv + REGRET:
        return f"your warband {w_real:+.2f}, advised {w_adv:+.2f} (win minus loss vs the next opponent)"
    return None


def finding(d, a, kind, rule, detail=""):
    return {"kind": kind, "rule": rule, "round": (d["turn"] + 1) // 2, "segment": d["segment"],
            "gold": d["state"]["friendly"].get("gold"), "detail": detail,
            "plan": " -> ".join((a or {}).get("plan") or [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="a Power.log (default: the newest Battlegrounds one)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--net", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--k", type=int, default=8)
    a = ap.parse_args()
    import torch
    torch.set_num_threads(4)
    net = Policy(Path(a.net)).get()[0]
    files = [Path(a.log)] if a.log else (library.bg_logs() if a.all else library.bg_logs()[-1:])
    OUT.mkdir(parents=True, exist_ok=True)
    for f in files:
        found = review_log(f, net, a.k)
        (OUT / f"{f.parent.name}.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
        kinds = collections.Counter((x["rule"], x["kind"]) for x in found)
        print(f"\n{f.parent.name}: {len(found)} findings")
        for (rule, kind), n in sorted(kinds.items(), key=lambda kv: (not kv[0][0], -kv[1])):
            print(f"  {'RULE ' if rule else 'signal'} {kind}: {n}")
            for x in [x for x in found if x["kind"] == kind][:2]:
                print(f"      round {x['round']}, {x['gold']} Gold: {x['detail']} | {x['plan'][:220]}")


if __name__ == "__main__":
    main()
