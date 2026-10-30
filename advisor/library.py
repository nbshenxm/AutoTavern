"""Real warbands for library seats (TavernGym `RulesConfig.library`, AutoTavern's library seats):
both sides of every combat in the user's logs (data/replay/combats.jsonl, advisor.logs), each made
into TavernGym minions the way the bridge makes them (advisor.state.add_minion: logged stats,
keywords and attachments), with the round and its owner's Tavern Tier. Training then puts real
lobbies' strength, by round, in front of the network instead of only its own copies.

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
BOARDS = ROOT / "data" / "library" / "boards.json"
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


def refresh_combats(out=COMBATS):
    """Re-extract every Battlegrounds log's combats into `out` when a log is newer than it.
    True when it did."""
    from advisor import logs
    from advisor.live import CARDS
    files = bg_logs()
    if out.exists() and all(f.stat().st_mtime <= out.stat().st_mtime for f in files):
        return False
    skins = logs.skin_parents(CARDS)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fc:
        for f in files:
            combats, _ = logs.extract(f, skins)
            for c in combats:
                fc.write(json.dumps(c, ensure_ascii=False) + "\n")
    tmp.replace(out)
    return True


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
            out.append({"round": rnd, "tier": int(s["tier"] or 1), "minions": minions,
                        "source": f"{c['log']}#{c['segment']} turn {c['turn']} {side}"})
    return out, skipped


def library(seats, path=BOARDS):
    """The `library` entry of a RulesConfig: `seats` fight with the boards in `path`."""
    boards = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"seats": list(seats), "boards": [{k: b[k] for k in ("round", "tier", "minions")} for b in boards]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combats", default=str(COMBATS))
    ap.add_argument("--out", default=str(BOARDS))
    ap.add_argument("--refresh", action="store_true", help="re-read the logs first if one is newer")
    a = ap.parse_args()
    if a.refresh and not refresh_combats(Path(a.combats)) and Path(a.out).exists():
        print("library up to date")
        return
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    boards, skipped = build(combats)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(boards), encoding="utf-8")
    by_round = collections.Counter(b["round"] for b in boards)
    print(f"{len(boards)} warbands from {len(combats)} combats (skipped: {dict(skipped)})")
    print("by round:", dict(sorted(by_round.items())))


if __name__ == "__main__":
    main()
