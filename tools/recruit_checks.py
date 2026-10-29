"""Check TavernGym's recruit rules against logged recruit phases (docs/ROADMAP.md, M1).

From tools/bg_decisions.py output, at the first decision of each recruit turn: maximum Gold,
the upgrade cost (base cost minus the per-turn discount since the last upgrade), the refresh
cost, and the size of a fresh (unfrozen) Tavern; and the Tier mix of the minions offered at
each Tavern Tier, against TavernGym's own Taverns (sampled with the debug command
`refresh_shop` over many lobbies). Effects (Goblin Wallet, hero powers, discounts) move single
values; a rule error shows as a systematic difference.

Run:    python -X utf8 tools/recruit_checks.py data/replay/decisions.jsonl
"""

import argparse
import collections
import json
import sys

import taverngym

RULES = json.loads(taverngym._core.default_config_json())
CAT = {c["id"]: c for c in json.loads(taverngym._core.catalog_json())}


def recruit_turn(game_turn):
    return (game_turn + 1) // 2


def turn_starts(decisions):
    """The first option decision of each (game, recruit turn), in log order, and the full
    per-game sequence (for upgrade history)."""
    games = collections.defaultdict(list)
    for d in decisions:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            games[(d["log"], d["player_id"], d["state"]["friendly"].get("hero"))].append(d)
    starts = {}
    for key, ds in games.items():
        seen = set()
        for d in ds:
            t = recruit_turn(d["turn"])
            if t not in seen:
                seen.add(t)
                starts.setdefault(key, []).append(d)
    return starts


def check_gold(starts):
    diffs = collections.Counter()
    for ds in starts.values():
        for d in ds:
            t = recruit_turn(d["turn"])
            want = min(RULES["start_gold"] + (t - 1) * RULES["gold_increment"],
                       RULES["gold_refill_cap"])
            diffs[d["state"]["friendly"]["max_gold"] - want] += 1
    return diffs


def check_upgrade(starts):
    """Logged upgrade cost - TavernGym's: base for the next Tier minus 1 per turn since the
    player reached the current Tier (first turn of the game counts from turn 1)."""
    diffs = collections.Counter()
    examples = []
    for ds in starts.values():
        reached = {1: 1}
        prev_tier = 1
        for d in ds:
            me = d["state"]["friendly"]
            t, tier = recruit_turn(d["turn"]), me.get("tier", 1)
            if tier != prev_tier:
                # The upgrade happened during the previous turn: its discount starts now
                reached[tier] = t - 1
                prev_tier = tier
            if tier >= RULES["max_regular_tier"] or "upgrade" not in me["costs"]:
                continue
            base = RULES["upgrade_costs"][tier - 1]
            want = max(0, base - RULES["upgrade_discount_per_turn"] * (t - reached.get(tier, t)))
            diff = me["costs"]["upgrade"] - want
            diffs[diff] += 1
            if diff and len(examples) < 12:
                examples.append((d["log"][-8:], d["segment"], t, tier, me["costs"]["upgrade"], want,
                                 me.get("hero")))
    return diffs, examples


def check_refresh(starts):
    return collections.Counter(d["state"]["friendly"]["costs"].get("refresh")
                               for ds in starts.values() for d in ds)


def check_shop_size(starts):
    """(tier, minions, spells) of fresh Taverns at turn start (none frozen)."""
    out = collections.Counter()
    for ds in starts.values():
        for d in ds:
            shop = d["state"]["shop"]
            if any(x["frozen"] for x in shop):
                continue
            tier = d["state"]["friendly"].get("tier", 1)
            out[(tier, sum(x["kind"] == "minion" for x in shop),
                 sum(x["kind"] == "spell" for x in shop))] += 1
    return out


def logged_tier_mix(decisions):
    """Tier of each minion offered, by the player's Tavern Tier, counting every Tavern
    once: the shop at each decision whose shop differs from the previous decision's."""
    mix = collections.defaultdict(collections.Counter)
    last = None
    for d in decisions:
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        shop = tuple(x["eid"] for x in d["state"]["shop"] if x["kind"] == "minion")
        key = (d["log"], d["segment"], d["turn"], shop)
        if not shop or key == last:
            continue
        new = [x for x in d["state"]["shop"] if x["kind"] == "minion" and not x["frozen"]
               and (last is None or x["eid"] not in last[3])]
        last = key
        tier = d["state"]["friendly"].get("tier", 1)
        for x in new:
            c = CAT.get(x["card"])
            if c and c.get("in_pool"):
                mix[tier][c["tier"]] += 1
    return mix


def simulated_tier_mix(n_lobbies=40, refreshes=50):
    mix = collections.defaultdict(collections.Counter)
    for seed in range(n_lobbies):
        g = taverngym.Game(seed)
        for p in range(8):
            g.step(p, json.loads(g.view(p))["actions"]["CHOOSE"])
        for tier in range(1, 7):
            g.debug(json.dumps({"cmd": "set_player", "p": 0, "tier": tier}))
            for _ in range(refreshes):
                g.debug(json.dumps({"cmd": "refresh_shop", "p": 0}))
                for x in json.loads(g.view(0))["me"]["shop"]:
                    c = CAT.get(x["id"])
                    if c and c["kind"] == "minion":
                        mix[tier][c["tier"]] += 1
    return mix


def shares(counter):
    n = sum(counter.values())
    return {k: round(v / n, 3) for k, v in sorted(counter.items())} if n else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decisions")
    a = ap.parse_args()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    starts = turn_starts(decisions)
    print(f"{len(starts)} games, {sum(map(len, starts.values()))} recruit turns")
    print("max Gold, logged - TavernGym:", dict(sorted(check_gold(starts).items())))
    up, ex = check_upgrade(starts)
    print("upgrade cost, logged - TavernGym:", dict(sorted(up.items())))
    for e in ex:
        print("   ", e)
    print("refresh cost at turn start:", dict(check_refresh(starts)))
    print("fresh Tavern (tier, minions, spells): count")
    for k, v in sorted(check_shop_size(starts).items()):
        want = RULES["shop_minion_slots"][k[0] - 1], RULES["shop_spell_slots"]
        print(f"    {k}: {v}" + ("" if k[1:] == want else f"   (TavernGym {want})"))
    logged, sim = logged_tier_mix(decisions), simulated_tier_mix()
    print("Tier mix of offered minions by Tavern Tier (logged n | logged shares | TavernGym shares)")
    for tier in sorted(logged):
        print(f"    tier {tier}: n={sum(logged[tier].values()):4d} {shares(logged[tier])} | {shares(sim[tier])}")


if __name__ == "__main__":
    sys.exit(main())
