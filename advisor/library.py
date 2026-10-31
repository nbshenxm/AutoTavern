"""Real warbands for library seats (TavernGym `RulesConfig.library`, AutoTavern's library seats):
both sides of every combat in the user's logs (data/replay/combats.jsonl, advisor.logs), each made
into TavernGym minions the way the bridge makes them (advisor.state.add_minion: logged stats,
keywords and attachments), with the round and its owner's Tavern Tier. Training then puts real
lobbies' strength, by round, in front of the network instead of only its own copies.

Also the player's own position at the start of each round (data/library/starts.jsonl):
training games that start from them (advisor.train --real-starts) play real midgames.

    python -X utf8 -m advisor.library        # writes data/library/boards.json, counts by round
    python -X utf8 -m advisor.library --refresh   # first re-reads the logs if any is newer
"""

import argparse
import collections
import json
from pathlib import Path

from advisor.state import GAME_CONFIG, add_minion, debug, recruit_game

ROOT = Path(__file__).resolve().parents[1]
COMBATS = ROOT / "data" / "replay" / "combats.jsonl"
DECISIONS = ROOT / "data" / "replay" / "decisions.jsonl"
BOARDS = ROOT / "data" / "library" / "boards.json"
STARTS = ROOT / "data" / "library" / "starts.jsonl"
# Where the Power.logs are: the game's own folder and the constructed project's archive
LOG_DIRS = [Path(r"D:\Program Files (x86)\Hearthstone\Logs"),
            Path(r"D:\GitHub\Hearthstone_AI_Advisor\data\logs")]


def bg_logs(dirs=LOG_DIRS):
    """Every Battlegrounds Power.log, one per game session (a session copied to both places
    counts once: the larger copy)."""
    by_session = {}
    for d in dirs:
        for f in sorted(Path(d).glob("*/Power.log")) if Path(d).is_dir() else []:
            if f.stat().st_size < by_session.get(f.parent.name, (0, None))[0]:
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                if "GameType=GT_BATTLEGROUNDS" not in fh.read():
                    continue
            by_session[f.parent.name] = (f.stat().st_size, f)
    return [f for _, f in sorted(by_session.values(), key=lambda x: x[1].parent.name)]


def refresh_combats(out=COMBATS, decisions_out=DECISIONS):
    """Re-extract every Battlegrounds log's combats into `out` (and its decisions into
    `decisions_out`, advisor.decisions) when a log is newer than them. True when it did."""
    from advisor import decisions, logs
    from advisor.live import CARDS
    files = bg_logs()
    outs = [out, decisions_out]
    if all(o.exists() for o in outs) and all(f.stat().st_mtime <= o.stat().st_mtime
                                             for f in files for o in outs):
        return False
    skins = logs.skin_parents(CARDS)
    tmp, tmp_d = out.with_suffix(".tmp"), decisions_out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fc, open(tmp_d, "w", encoding="utf-8") as fd:
        for f in files:
            combats, _ = logs.extract(f, skins)
            for c in combats:
                fc.write(json.dumps(c, ensure_ascii=False) + "\n")
            for d in decisions.extract(f, skins):
                fd.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
    tmp.replace(out)
    tmp_d.replace(decisions_out)
    return True


def starts(decisions, combats):
    """[{d, combats}]: the player's position at the start of every recruit round of every
    logged game (its first Options), with the game's combats before it (advisor.bridge.build's
    input). Training games start from them (advisor.train --real-starts)."""
    from advisor import bridge
    out, seen = [], set()
    for d in decisions:
        key = (d["log"], d["segment"], d["turn"])
        if d["kind"] != "options" or d["turn"] % 2 == 0 or d["turn"] < 3 or key in seen:
            continue
        seen.add(key)
        out.append({"d": d, "combats": bridge.game_combats(combats, d)})
    return out


def build(combats):
    """[{round, tier, minions, source}]: the warbands whose every minion TavernGym has."""
    g = recruit_game(1, GAME_CONFIG)
    out, skipped = [], collections.Counter()
    for c in combats:
        rnd = (c["turn"] + 1) // 2
        for side in ("friendly", "opponent"):
            s = c["start"][side]
            debug(g, cmd="clear_zone", p=1, zone="board")
            gaps = []
            for m in s["board"][:7]:
                add_minion(g, 1, "board", m, gaps, side)
            minions = json.loads(g.state_json())["players"][1]["board"]
            if not s["board"] or gaps or len(minions) != len(s["board"][:7]):
                skipped["empty" if not s["board"] else "missing card"] += 1
                continue
            who = "me" if side == "friendly" else f"p{s.get('player_id')}"
            out.append({"round": rnd, "tier": int(s["tier"] or 1), "minions": minions,
                        "source": f"{c['log']}#{c['segment']} turn {c['turn']} {side}",
                        "track": f"{c['log']}#{c['segment']} {who}"})
    return out, skipped


# Library warbands are scaled toward the top 1% of players' warband strength by round (Firestone):
# the user's lobbies (6-7k MMR) are about average through round 8, the top 1% up to 1.7x stronger
# by then. STRENGTH 1 = that target, 0 = the boards as logged; never below the logged stats
STRENGTH, MAX_SCALE = 1.0, 3.0


def scale_factors(boards, strength=STRENGTH, curve=None):
    """round -> the factor this round's boards' stats are multiplied by: toward `curve` (the top
    1%'s average by round), from the median of the boards of that round."""
    import statistics
    if curve is None:
        from advisor import meta
        curve = meta.warband_curve()
    by_round = collections.defaultdict(list)
    for b in boards:
        by_round[b["round"]].append(sum(m["atk"] + m["hp"] for m in b["minions"]))
    out = {}
    for r, xs in by_round.items():
        mine, top = statistics.median(xs), curve.get(r)
        if not top or mine <= 0:
            out[r] = 1.0
            continue
        target = mine + strength * (top - mine)
        out[r] = min(MAX_SCALE, max(1.0, target / mine))
    return out


def _scaled(m, f):
    if f <= 1.0:
        return m
    m = dict(m)
    for k in ("atk", "hp", "max_hp"):
        m[k] = round(m[k] * f)
    m["peak_atk"], m["peak_hp"] = max(m["peak_atk"], m["atk"]), max(m["peak_hp"], m["hp"])
    return m


# A comp seat's Tavern Tier by round (a quick top player's curve; Tier 6 from round 10)
COMP_TIERS = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5}


def comp_boards(path=None, curve=None, rounds=range(2, 17)):
    """[{round, tier, minions, track, source, synthetic}]: a warband per round for each curated
    comp in Tavern Link's catalog (advisor.meta.TAVERN_LINK): its early cards first, then its
    midgame ones, from round 9 its final board, filled with its tribe's minions of the Tier, at
    the top 1%'s Attack+Health for the round (shared by the cards' printed stats). A library seat
    then plays one comp all game: poison Murlocs, Divine Shield Dragons, Undead... to read and
    answer."""
    from advisor import meta
    from advisor.state import CAT, normal_form
    path = Path(path or meta.TAVERN_LINK)
    if not path.exists():
        return []
    if curve is None:
        curve = meta.warband_curve()
    cat = json.loads(path.read_text(encoding="utf-8"))
    by_name = {m["name"]: m for m in cat.get("minions", [])}

    def cid(m):  # a catalog minion -> TavernGym's card id (by its database id)
        c = meta._DBF.get(m["id"])
        x = normal_form(c["id"])[0] if c else None
        return x if x in CAT and CAT[x]["kind"] == "minion" else None

    g = recruit_game(1, GAME_CONFIG)
    out = []
    for comp in cat.get("comps", []):
        stages = [st.get("cards", []) for st in comp.get("stages", [])] + [[], [], []]
        final = [sl["choices"][0] for sl in comp.get("finalBoard", []) if sl.get("choices")]
        tribes = set(comp.get("tribes") or [])
        fill = sorted((m for m in cat.get("minions", []) if not m.get("duosOnly")
                       and (set(m.get("racesZh") or []) & tribes if tribes else m.get("neutral"))),
                      key=lambda m: (-m["tier"], m["id"]))
        for r in rounds:
            tier = COMP_TIERS.get(r, 6)
            want = (stages[0] if r <= 4 else stages[1] + stages[0] if r <= 8
                    else final + stages[2] + stages[1])
            names = list(dict.fromkeys(want))
            picked = [by_name[x] for x in names if x in by_name and by_name[x]["tier"] <= tier and cid(by_name[x])]
            for m in fill:
                if len(picked) >= min(7, r + 1):
                    break
                if m["tier"] <= tier and cid(m) and m not in picked:
                    picked.append(m)
            picked = picked[:min(7, r + 1)]
            total = curve.get(r)
            if not picked or not total:
                continue
            base = sum(m["attack"] + m["health"] for m in picked)
            debug(g, cmd="clear_zone", p=1, zone="board")
            for m in picked:
                share = total * (m["attack"] + m["health"]) / base
                a = max(m["attack"], round(share * m["attack"] / (m["attack"] + m["health"])))
                h = max(m["health"], round(share - a), 1)
                debug(g, cmd="add_minion", p=1, zone="board", card=cid(m), no_triple=True)
                debug(g, cmd="edit_minion", p=1, zone="board", index=len(zone_of(g)) - 1, atk=a, hp=h)
            out.append({"round": r, "tier": tier, "minions": json.loads(g.state_json())["players"][1]["board"],
                        "source": f"comp {comp['name']} round {r}", "track": f"comp:{comp['id']}",
                        "synthetic": True})
    return out


def zone_of(g, p=1):
    return json.loads(g.state_json())["players"][p]["board"]


def library(seats, path=BOARDS, strength=STRENGTH, curve=None, comps=False):
    """The `library` entry of a RulesConfig: `seats` fight with the boards in `path`, each seat
    following one real player (track) all game, the stats scaled toward the top 1% by round
    (`strength`; 0 = as logged), and grown along that curve between the rounds a player was seen.
    `comps`: the curated comps' warbands too (comp_boards), each a player to follow."""
    if curve is None:
        from advisor import meta
        curve = meta.warband_curve()
    boards = json.loads(Path(path).read_text(encoding="utf-8"))
    factors = scale_factors(boards, strength, curve) if strength else {}
    if comps:  # curated comps' warbands, already at the top 1%'s strength (not scaled again)
        boards += comp_boards(curve=curve)
    ids = {t: i + 1 for i, t in enumerate(sorted({b["track"] for b in boards if b.get("track")}))}
    out = [{"round": b["round"], "tier": b["tier"], "track": ids.get(b.get("track"), 0),
            "minions": [m if b.get("synthetic") else _scaled(m, factors.get(b["round"], 1.0))
                        for m in b["minions"]]}
           for b in boards]
    growth = [float(curve.get(r, 0.0)) for r in range(max(curve, default=0) + 1)] if curve else []
    return {"seats": list(seats), "boards": out, "growth": growth}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combats", default=str(COMBATS))
    ap.add_argument("--decisions", default=str(DECISIONS))
    ap.add_argument("--out", default=str(BOARDS))
    ap.add_argument("--starts", default=str(STARTS))
    ap.add_argument("--refresh", action="store_true", help="re-read the logs first if one is newer")
    a = ap.parse_args()
    if a.refresh and not refresh_combats(Path(a.combats), Path(a.decisions)) \
            and Path(a.out).exists() and Path(a.starts).exists():
        print("library up to date")
        return
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    boards, skipped = build(combats)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(boards), encoding="utf-8")
    by_round = collections.Counter(b["round"] for b in boards)
    print(f"{len(boards)} warbands from {len(combats)} combats (skipped: {dict(skipped)})")
    print("by round:", dict(sorted(by_round.items())))
    rows = starts(map(json.loads, open(a.decisions, encoding="utf-8")), combats)
    tmp = Path(a.starts).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(a.starts)
    print(f"{len(rows)} round starts")


if __name__ == "__main__":
    main()


COMP_START_ROUNDS = range(6, 11)


def comp_starts(rounds=COMP_START_ROUNDS, seed=0):
    """Game states (Game.state_json) where the player's seat (0) plays a curated comp: at each of
    `rounds`, the comp's warband of that round (comp_boards: its stage cards, at the top 1%'s
    strength), its Tavern Tier and the round's Gold, in a lobby with the comp's minion types; the
    other seats have real warbands of that round (the library, scaled the same way). Training
    games start from them (advisor.train RealStarts) to practise each comp's way to scale."""
    import random

    import taverngym

    from advisor.state import CAT, normal_form
    r = random.Random(seed)
    comps = collections.defaultdict(dict)
    for b in comp_boards():
        comps[b["track"]][b["round"]] = b
    real = collections.defaultdict(list)
    for b in library([], strength=STRENGTH)["boards"]:
        real[b["round"]].append(b)
    out = []
    for track, by_round in sorted(comps.items()):
        races = collections.Counter(
            x for b in by_round.values() for m in b["minions"]
            for x in (CAT.get(normal_form(CAT_BY_CID().get(m["card"], ""))[0], {}).get("races") or [])
            if x not in ("ALL", "NEUTRAL"))
        types = [x for x, _ in races.most_common(2)]
        for rnd in rounds:
            b = by_round.get(rnd)
            if b is None or not real.get(rnd):
                continue
            g = recruit_game(r.randrange(1 << 30), {**GAME_CONFIG, "lobby_types": types})
            debug(g, cmd="set_turn", turn=rnd)
            st = json.loads(g.state_json())
            for i, pl in enumerate(st["players"]):
                if i == 0:
                    board, tier = b["minions"], b["tier"]
                else:
                    o = r.choice(real[rnd])
                    board, tier = o["minions"], o["tier"]
                pl["board"] = [dict(m) for m in board[:7]]
                for m in pl["board"]:
                    st["next_eid"] += 1
                    m["eid"] = st["next_eid"]
                pl["tier"] = max(1, tier)
                pl["health"] = max(10, 30 - 2 * max(0, rnd - 4))
            g = taverngym.Game.from_json(json.dumps(st))
            # The round's Gold and the Tavern of the comp's Tier
            debug(g, cmd="set_player", p=0, gold=min(10, rnd + 2), tier=b["tier"])
            debug(g, cmd="refresh_shop", p=0)
            out.append(json.loads(g.state_json()))
    return out


_CAT_BY_CID = None


def CAT_BY_CID():
    """TavernGym card index -> card id."""
    global _CAT_BY_CID
    if _CAT_BY_CID is None:
        from advisor.state import CAT
        _CAT_BY_CID = {c["cid"]: k for k, c in CAT.items()}
    return _CAT_BY_CID
