"""TavernGym's combats against Bob's Buddy's (HDT's combat simulator, kept up with every patch;
tools/bbdiff, built against the installed HDT's DLLs, local only). Random warbands from the
current pool (every in-pool minion; a Tavern Tier per side, minions of that Tier or lower,
some golden, stats grown as a midgame's are), each fight simulated by both; then per card: how
much more TavernGym favours the side that has it than Bob's Buddy does. A card whose combat
script differs (a Deathrattle, Avenge, Start of Combat, an aura) stands out over many fights;
plain-stat minions don't. Results are appended to `--out` as they come (resumable by --seed).

    python -X utf8 -m advisor.bb_diff --fights 3000 --n 300
"""

import argparse
import collections
import json
import math
import random
import subprocess
from pathlib import Path

from advisor.state import CAT, debug, recruit_game

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "tools" / "bbdiff" / "bin" / "Release" / "net472" / "BbDiff.exe"


def pool():
    by_tier = collections.defaultdict(list)
    for k, c in CAT.items():
        if c.get("kind") == "minion" and c.get("in_pool") and not c.get("normal_id") and c.get("tier"):
            by_tier[c["tier"]].append(k)
    return by_tier


def board(rng, by_tier, tier):
    out = []
    for _ in range(rng.randint(max(1, tier - 1), 7)):
        t = rng.randint(1, tier)
        cid = rng.choice(by_tier[t])
        golden = rng.random() < 0.15 and CAT[cid].get("golden_id")
        card = CAT[cid]["golden_id"] if golden else cid
        base = CAT[card]
        grow = 1 + rng.random() * (tier - 1) * 0.8  # a midgame's buffs, more at higher Tiers
        # (Bob's Buddy's factory makes a golden card id a plain minion unless told: HDT sets it)
        out.append({"card": card, "golden": bool(golden), "atk": max(1, round(base["atk"] * grow + rng.randint(0, tier))),
                    "hp": max(1, round(base["hp"] * grow + rng.randint(0, tier)))})
    return out


def combat_trinkets():
    """Reachable trinkets whose text acts in combat (Start of Combat, Avenge, Deathrattles,
    attacks, summons, "in combat")."""
    import re
    rx = re.compile(r"Start of Combat|in combat|this combat|Avenge|Deathrattle|attacks?\b|summon", re.I)
    return sorted(k for k, c in CAT.items() if (c.get("kind") or "").startswith("trinket")
                  and c.get("reachable") and rx.search(c.get("text") or ""))


# Hero Powers that act in combat by themselves (passive: no activation, no choice)
COMBAT_POWERS = ("BG20_HERO_282p", "BG22_HERO_002p", "BG22_HERO_003p", "BG22_HERO_305p", "BG23_HERO_201p",
                 "TB_BaconShop_HP_037a", "TB_BaconShop_HP_061", "TB_BaconShop_HP_069", "TB_BaconShop_HP_086",
                 # (Nov 4: the other two passive ones of pool heroes: Glory of Combat, summoned +1/+2 Taunt)
                 "BG20_HERO_100p", "TB_BaconShop_HP_107")


# A Hero Power's script data in the client (your logs): Wax Warband's buff size (1 fresh: its
# improvements are not modelled here), Drek'Thar's and Vanndar's "unlocked" (Turn 7). Without
# it Bob's Buddy gave a fresh Wax Warband nothing (TavernGym +0.079, z +9)
POWER_DATA = {"TB_BaconShop_HP_037a": lambda t: 1, "BG22_HERO_002p": lambda t: int(t >= 7),
              "BG22_HERO_003p": lambda t: int(t >= 7)}


def fight(rng, by_tier, k, trinkets=(), powers=()):
    tier = rng.randint(2, 6)
    t2 = min(6, max(2, tier + rng.choice((-1, 0, 0, 1))))
    sides = []
    for t in (tier, t2):
        side = {"tier": t, "health": 30, "minions": board(rng, by_tier, t)}
        if trinkets and rng.random() < 0.6:
            side["trinkets"] = rng.sample(trinkets, rng.randint(1, 2))
        if powers and rng.random() < 0.6:
            side["hero_powers"] = [{"card": rng.choice(powers)}]
        sides.append(side)
    turn = 2 * tier + rng.randint(0, 2)
    for side in sides:  # the data HDT passes (the client's script data, as your logs show it)
        for h in side.get("hero_powers", []):
            h["data"] = POWER_DATA.get(h["card"], lambda t: 0)(turn)
    return {"id": k, "turn": turn, "player": sides[0], "opponent": sides[1]}


def taverngym(f, n, seed):
    """(win, tie, loss) of seat 0 over `n` simulations."""
    g = recruit_game(seed)
    debug(g, cmd="set_turn", turn=f["turn"])
    for p, side in ((0, f["player"]), (1, f["opponent"])):
        debug(g, cmd="set_player", p=p, tier=side["tier"], health=side["health"])
        for t in side.get("trinkets", []):
            debug(g, cmd="give_trinket", p=p, card=t)
        for i, h in enumerate(side.get("hero_powers", [])):
            debug(g, cmd="set_hero_power", p=p, slot=i, card=h["card"])
        debug(g, cmd="clear_zone", p=p, zone="board")
        for m in side["minions"]:
            debug(g, cmd="add_minion", p=p, zone="board", card=m["card"], no_triple=True)
            idx = len(json.loads(g.state_json())["players"][p]["board"]) - 1
            debug(g, cmd="edit_minion", p=p, zone="board", index=idx, atk=m["atk"], hp=m["hp"])
    r = json.loads(g.debug(json.dumps({"cmd": "combat_preview", "a": 0, "b": 1, "n": n})))
    return r["win_a"], r["tie"], r["win_b"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fights", type=int, default=3000)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "data" / "progress" / "bb_diff.jsonl"))
    ap.add_argument("--trinkets", action="store_true", help="each side 0-2 combat trinkets (combat_trinkets)")
    ap.add_argument("--powers", action="store_true", help="each side maybe a combat Hero Power (COMBAT_POWERS)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    by_tier = pool()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out.exists():
        for line in open(out, encoding="utf-8"):
            r = json.loads(line)
            if r.get("seed") == a.seed:
                done[r["id"]] = r
    trinkets = combat_trinkets() if a.trinkets else ()
    fights = [fight(rng, by_tier, k, trinkets, COMBAT_POWERS if a.powers else ()) for k in range(a.fights)]
    todo = [f for f in fights if f["id"] not in done]
    if todo:
        bb = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                              encoding="utf-8")
        with open(out, "a", encoding="utf-8") as fh:
            from advisor.train import pause_if_playing
            for f in todo:
                pause_if_playing()  # (home: never while you play)
                bb.stdin.write(json.dumps({**f, "n": a.n}) + "\n")
                bb.stdin.flush()
                b = json.loads(bb.stdout.readline())
                try:
                    tw, tt, tl = taverngym(f, a.n, a.seed * 100_000 + f["id"])
                except ValueError as e:
                    tw = tt = tl = None
                    b["error"] = b.get("error") or f"TavernGym: {e}"
                r = {"seed": a.seed, "id": f["id"], "fight": f, "bb": [b.get("win"), b.get("tie"), b.get("loss")],
                     "tg": [tw, tt, tl], "error": b.get("error")}
                done[f["id"]] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                if len(done) % 200 == 0:
                    print(len(done), "fights", flush=True)
        bb.stdin.close()
        bb.wait()
    report(list(done.values()), a.n)


def report(rows, n):
    ok = [r for r in rows if not r["error"] and None not in r["bb"] and None not in r["tg"]]
    print(f"{len(ok)} fights compared ({len(rows) - len(ok)} with an error)")
    # Win minus loss: TavernGym's against Bob's Buddy's
    d = [(r["tg"][0] - r["tg"][2]) - (r["bb"][0] - r["bb"][2]) for r in ok]
    print(f"mean difference in (win - loss): {sum(d) / len(d):+.3f}; mean |difference| {sum(map(abs, d)) / len(d):.3f}; "
          f"fights differing by > 0.3: {sum(abs(x) > 0.3 for x in d)}")
    # Per card: the difference signed toward the side that has it
    cards = collections.defaultdict(list)
    for r, x in zip(ok, d):
        for sign, side in ((1, "player"), (-1, "opponent")):
            for c in ({m["card"] for m in r["fight"][side]["minions"]} | set(r["fight"][side].get("trinkets", []))
                      | {h["card"] for h in r["fight"][side].get("hero_powers", [])}):
                cards[c].append(sign * x)
    rows_ = []
    for c, xs in cards.items():
        if len(xs) < 8:
            continue
        mean = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))
        rows_.append((mean / (sd / math.sqrt(len(xs)) + 1e-9), mean, len(xs), c))
    rows_.sort(key=lambda t: -abs(t[0]))
    Path(ROOT / "data" / "progress" / "bb_cards.json").write_text(
        json.dumps({c: {"n": k, "mean": round(mean, 4), "z": round(z, 2)} for z, mean, k, c in rows_}, indent=1),
        encoding="utf-8")
    print("cards TavernGym favours (+) or disfavours (-) against Bob's Buddy, by z:")
    for z, mean, k, c in rows_[:30]:
        print(f"  {CAT[c]['name']:30s} {c:16s} n={k:4d} mean {mean:+.3f}  z {z:+.1f}")
    errors = collections.Counter((r["error"] or "")[:80] for r in rows if r["error"])
    if errors:
        print("errors:", errors.most_common(5))


if __name__ == "__main__":
    main()
