"""Replay logged combats in TavernGym and compare with what happened in the game.

Each combat from tools/bg_logs.py is rebuilt with the debug commands (heroes, Hero Powers,
trinkets, tiers, health, warbands with logged stats and keywords, attached Dark Gifts and
magnetized minions) and simulated N times. A combat agrees when the logged result is a likely
outcome of the simulation; a logged winner the simulator gives under 2% points at a rules or
content gap (or at state the log shows but the setup can't carry, listed per combat).

Two modes: "start" simulates from the boards before Start of Combat; "attack" from the boards
just before the first attack, with the logged first attacker (isolates the attack phase).

Run:    python -X utf8 tools/combat_replay.py data/replay/combats.jsonl [-n 500] [--out FILE]
"""

import argparse
import collections
import json
import sys
from pathlib import Path

import taverngym

SURPRISE = 0.02
SIDES = ("friendly", "opponent")


def catalog():
    return {c["id"]: c for c in json.loads(taverngym._core.catalog_json())}


CAT = None
CARDS = Path(__file__).resolve().parents[1] / "crates" / "taverngym" / "data" / "cards.json"
KEYWORDS = {c["id"]: c["keywords"]
            for c in json.loads(CARDS.read_text(encoding="utf-8"))["cards"]}


RULES = json.loads(taverngym._core.default_config_json())


def damage_cap(turn, alive):
    """RulesConfig::damage_cap."""
    if alive <= RULES["damage_cap_until_alive"]:
        return None
    cap = None
    for first, c in RULES["damage_caps"]:
        if turn >= first:
            cap = c
    return cap


def recruit_game(seed):
    """A game in its first recruit turn with every hero chosen (tests/test_debug.py)."""
    g = taverngym.Game(seed)
    for p in range(8):
        g.step(p, json.loads(g.view(p))["actions"]["CHOOSE"])
    for p in range(8):
        for _ in range(4):
            v = json.loads(g.view(p))
            if v["me"]["pending"] is None:
                break
            g.step(p, v["actions"]["CHOOSE"])
    return g


def normal_form(cid):
    c = CAT.get(cid)
    if c and c.get("normal_id"):
        return c["normal_id"], True
    return cid, False


def attachment(ench):
    """The TavernGym card an enchantment stands for, if it carries behaviour: a Dark Gift or
    a magnetized minion ("<card>e"). Stat-only enchantments are in the logged stats."""
    base = ench[:-1] if ench.endswith("e") else None
    c = CAT.get(base) if base else None
    if c is None:
        return None
    if c["kind"] == "dark_gift" or (c["kind"] == "minion" and "MAGNETIC" in KEYWORDS.get(base, ())):
        return base
    return None


# "This game" counters the log shows on player enchantments: card -> PlayerStats fields
# filled from the enchantment's TAG_SCRIPT_DATA_NUM_1 and _2
PLAYER_ENCHANTMENTS = {
    "BG25_011pe": ("undead_atk", None),  # Nerubian Deathswarmer
    "BG25_008pe": ("eternal_knight_deaths", None),  # Eternal Knight
    "BG31_808pe": ("beetle_atk", "beetle_hp"),  # Runed Progenitor and other Beetle buffs
}
TASTY_LOBSTER = "BG36_202"


def player_stats(s):
    """PlayerStats fields recoverable from a logged side."""
    out = {}
    for e in s.get("player_ench", []):
        fields = PLAYER_ENCHANTMENTS.get(e["card"])
        if fields:
            for f, v in zip(fields, e["data"]):
                if f:
                    out[f] = v
    # A Tasty Lobster shows the buff its Deathrattle gives: (2, 1) x (1 + improvements),
    # doubled when golden
    for m in s["board"] + s.get("hand", []):
        cid, golden = normal_form(m["card"])
        if cid == TASTY_LOBSTER and m["data"][0] > 0:
            g = 2 if golden or m["golden"] else 1
            out["lobster_bonus"] = max(out.get("lobster_bonus", 0), m["data"][0] // (2 * g) - 1)
    return out


def setup(c, snap, seed):
    """A TavernGym game holding the logged combat on seats 0 (friendly) and 1 (opponent).
    Returns (game, gaps): gaps are the logged parts the setup could not carry."""
    g = recruit_game(seed)
    dbg = lambda **kw: json.loads(g.debug(json.dumps(kw)))
    gaps = []
    g.debug(json.dumps({"cmd": "set_turn", "turn": max(1, c["turn"] // 2)}))
    for p, side in enumerate(SIDES):
        s = snap[side]
        hero = s.get("hero")
        if hero in CAT and CAT[hero]["kind"] == "hero":
            dbg(cmd="set_hero", p=p, hero=hero)
        else:
            gaps.append(f"{side} hero {hero}")
        for i, hp in enumerate(s["hero_powers"]):
            if hp["card"] in CAT and CAT[hp["card"]]["kind"] == "hero_power":
                dbg(cmd="set_hero_power", p=p, slot=i, card=hp["card"])
            else:
                gaps.append(f"{side} hero power {hp['card']}")
        dbg(cmd="clear_zone", p=p, zone="board")
        dbg(cmd="clear_zone", p=p, zone="hand")
        # Trinkets before the warband: an on-attach buff must not hit the logged stats
        for t in s["trinkets"]:
            if t["card"] in CAT and CAT[t["card"]]["kind"].startswith("trinket"):
                dbg(cmd="give_trinket", p=p, card=t["card"])
            else:
                gaps.append(f"{side} trinket {t['card']}")
        dbg(cmd="set_player", p=p, tier=max(1, s.get("tier", 1)), health=s.get("health", 30),
            armor=s.get("armor", 0))
        # Before the warband: minions created afterwards carry the player-level bonuses
        stats = player_stats(s)
        if stats:
            dbg(cmd="set_stats", p=p, stats=stats)
        for zone, minions in (("board", s["board"][:7]), ("hand", s.get("hand", [])[:10])):
            for m in minions:
                cid, golden = normal_form(m["card"])
                if cid not in CAT or CAT[cid]["kind"] != "minion":
                    gaps.append(f"{side} minion {m['card']}")
                    continue
                dbg(cmd="add_minion", p=p, zone=zone, card=cid, golden=golden or m["golden"])
                idx = len(_zone(g, p, zone)) - 1
                for e in m["ench"]:
                    a = attachment(e["card"])
                    if a:
                        dbg(cmd="edit_minion", p=p, zone=zone, index=idx, attach=a)
                # The log carries the current keywords except printed ones it has no tag for
                kept = [k for k in _zone(g, p, zone)[idx].get("keywords", []) if k not in LOGGED_KW]
                dbg(cmd="edit_minion", p=p, zone=zone, index=idx, atk=m["atk"],
                    hp=max(1, m["hp"]), keywords=sorted(set(m["keywords"]) | set(kept)))
                if not CAT[cid]["implemented"]:
                    gaps.append(f"{side} unscripted {cid}")
    return g, gaps


LOGGED_KW = {"TAUNT", "DIVINE_SHIELD", "REBORN", "VENOMOUS", "POISONOUS", "STEALTH",
             "WINDFURY", "MEGA_WINDFURY"}  # tools/bg_logs.py KEYWORD_TAGS


def _zone(g, p, zone):
    return json.loads(g.view(p))["me"][zone]


def replay(c, n, mode, seed):
    snap = c["start"] if mode == "start" else c["first_attack"]
    if snap is None:
        return None
    g, gaps = setup(c, snap, seed)
    cmd = {"cmd": "combat_preview", "a": 0, "b": 1, "n": n, "details": True,
           "ghost_b": snap["opponent"].get("health", 1) <= 0}
    if mode == "attack":
        cmd.update(after_start=True, first_attacker=0 if c["first_attacker"] == "friendly" else 1)
    r = json.loads(g.debug(json.dumps(cmd)))
    want = {"friendly": 0, "opponent": 1, "tie": 2}[c["winner"]]
    # The logged damage is after the cap, which depends on how many players are left; the
    # setup lobby always has eight, so the cap is applied here from the logged count.
    cap = damage_cap(max(1, c["turn"] // 2), c.get("alive") or 8)
    outcomes = collections.Counter()
    for t in r["trials"]:
        dmg = 0 if t["winner"] == 2 else t["damage"] if cap is None else min(t["damage"], cap)
        outcomes[(t["winner"], dmg)] += 1
    p_win = sum(v for (w, _), v in outcomes.items() if w == want) / n
    p_exact = outcomes[(want, c["damage"] if want < 2 else 0)] / n
    return {"log": c["log"], "segment": c["segment"], "build": c["build"], "turn": c["turn"],
            "mode": mode, "winner": c["winner"], "damage": c["damage"],
            "p_win": round(p_win, 4), "p_exact": round(p_exact, 4),
            "sim": {"win": r["win_a"], "loss": r["win_b"], "tie": r["tie"]},
            # Simulated damage when the logged winner wins: {damage: share of those wins}
            "sim_damage": {d: round(v / max(1, p_win * n), 3) for (w, d), v in
                           sorted(outcomes.items()) if w == want and want < 2},
            "gaps": sorted(set(gaps)), "surprise": p_win < SURPRISE}


def summarize(rows):
    out = {}
    for key in sorted({(r["build"], r["mode"]) for r in rows}):
        rs = [r for r in rows if (r["build"], r["mode"]) == key]
        clean = [r for r in rs if not r["gaps"]]
        def stats(x):
            if not x:
                return {"n": 0}
            return {"n": len(x),
                    "mean_p_win": round(sum(r["p_win"] for r in x) / len(x), 3),
                    "mean_p_exact": round(sum(r["p_exact"] for r in x) / len(x), 3),
                    "surprises": sum(r["surprise"] for r in x)}
        out[f"{key[0]}/{key[1]}"] = {"all": stats(rs), "no_gaps": stats(clean)}
    return out


def main():
    global CAT
    ap = argparse.ArgumentParser()
    ap.add_argument("combats")
    ap.add_argument("-n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--modes", default="start,attack")
    ap.add_argument("--out", help="JSON report (default: next to the combats file)")
    a = ap.parse_args()
    CAT = catalog()
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    rows = []
    for c in combats:
        for mode in a.modes.split(","):
            r = replay(c, a.n, mode, a.seed)
            if r is not None:
                rows.append(r)
    summary = summarize(rows)
    out = Path(a.out or Path(a.combats).with_name("replay_report.json"))
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    for k, v in summary.items():
        print(k, json.dumps(v))
    gaps = collections.Counter(x for r in rows if r["mode"] == "start" for x in r["gaps"])
    if gaps:
        print("setup gaps:", gaps.most_common(15))
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
