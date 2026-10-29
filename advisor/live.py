"""Live advisor: follows Hearthstone's Power.log and advises at each recruit decision.

At every Options packet of the player's recruit phase it rebuilds the lobby in TavernGym
(advisor.bridge), asks the policy for the turn's plan, keeps the first step only when the client
offers it too, adds combat odds against the next opponent's last seen warband, and writes the
advice to `advice.json` in the live folder (the HDT plugin shows it). It reads the log only and
never acts in the game.

    python -X utf8 -m advisor.live                      # follow the newest Power.log
    python -X utf8 -m advisor.live --replay PATH        # a recorded log, timed (no waiting)

Policy v0 is TavernGym's scripted bot (docs/ROADMAP.md, M3); a trained network replaces it.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from hslog import LogParser, packets

from advisor import bridge, decisions, logs
from advisor.state import CAT, debug

HS_LOGS = Path(r"D:\Program Files (x86)\Hearthstone\Logs")
CARDS = Path(r"D:\GitHub\Hearthstone_AI_Advisor\data\cards\255790")
LIVE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "TavernAdvisor"
CREATE_GAME = "GameState.DebugPrintPower() - CREATE_GAME"
OPTIONS = "GameState.DebugPrintOptions()"
MAX_PLAN = 20


# ---------------------------------------------------------------------- following the log

class Tracker:
    """Incremental parse of one Power.log: each CREATE_GAME starts a segment with its own
    parser (as advisor.logs.segments); finished top-level packets are exported as they come,
    and a recruit decision is reported once its Options packet is complete."""

    def __init__(self, skins, name="live"):
        self.skins = skins
        self.name = name
        self.segment = -1
        self.parser = None
        self.exporter = None
        self.exported = 0
        self.in_options = False
        self.reported = None
        self.player_id = 0
        self.history = {}  # player_id -> combats of that game so far (across reconnects)

    def feed(self, line):
        """Parse one line; returns a decision ready for advice, or None."""
        out = None
        if CREATE_GAME in line:
            self._close_segment()
            self.segment += 1
            logging.disable(logging.WARNING)
            self.parser = LogParser()
            self.exporter = None
            self.exported = 0
        if self.parser is None:
            return None
        m = re.search(r"DebugPrintGame\(\) - PlayerID=(\d+), PlayerName=(.*)$", line)
        if m and "#" in m.group(2):
            self.player_id = int(m.group(1))
        options = OPTIONS in line
        if self.in_options and not options:
            out = self._advance()
        self.parser.read_line(line)
        self.in_options = options
        return out

    def _advance(self):
        if not self.parser.games:
            return None
        tree = self.parser.games[-1]
        if self.exporter is None:
            if not logs.is_bg(tree):
                return None
            meta = {"log": self.name, "segment": self.segment, "build": 0,
                    "player_id": self.player_id}
            self.exporter = decisions.DecisionExporter(tree, self.skins, meta)
        pk = tree.packets
        while self.exported < len(pk):
            p = pk[self.exported]
            if isinstance(p, packets.Block) and not p.ended:
                break
            self.exporter.export_packet(p)
            self.exported += 1
        d = self.exporter.pending
        if d is None or d["kind"] != "options" or d["turn"] % 2 == 0 or d is self.reported:
            return None
        self.reported = d
        return d

    def combats(self):
        done = self.history.get(self.player_id, [])
        live = self.exporter.combats if self.exporter is not None else []
        return done + live

    def _close_segment(self):
        if self.exporter is not None:
            self.history.setdefault(self.player_id, []).extend(self.exporter.combats)
            self.exporter.combats = []


def newest_log(log_dir):
    sessions = sorted(p for p in Path(log_dir).glob("Hearthstone_*") if p.is_dir())
    return sessions[-1] / "Power.log" if sessions else None


# ---------------------------------------------------------------------- advice

def name_of(card, locale):
    c = CAT.get(card) or {}
    return (c.get("name_zh") if locale == "zhCN" else None) or c.get("name") or card


def describe(view, a, locale):
    """An action in the player's words, from the view it is taken in."""
    me = view["me"]
    n = lambda zone, i: name_of(me[zone][i]["id"], locale) if i < len(me[zone]) else f"#{i}"
    if a == 0:
        return "End turn"
    if a == 1:
        return "Refresh"
    if a == 2:
        return "Freeze"
    if a == 3:
        return "Level up"
    if a in (4, 5):
        return "Hero Power" + (" 2" if a == 5 else "")
    if a == 6:
        return "Dark Gift"
    if 8 <= a <= 15:
        return f"Buy {n('shop', a - 8)}"
    if 16 <= a <= 22:
        return f"Sell {n('board', a - 16)}"
    if 23 <= a <= 29:
        return f"Activate {n('board', a - 23)}"
    if 30 <= a <= 45:
        pending = me.get("pending") or {}
        i = a - 30
        if pending.get("kind") == "target":  # entity ids on the warband or in the Tavern
            eids = pending.get("targets") or []
            where = {m.get("eid"): (zone, m["id"]) for zone in ("board", "shop", "hand")
                     for m in me.get(zone, []) if isinstance(m, dict) and "id" in m}
            if i < len(eids) and eids[i] in where:
                zone, card = where[eids[i]]
                return f"Target {name_of(card, locale)}" + (" in the Tavern" if zone == "shop" else "")
            return f"Target #{i + 1}"
        opts = pending.get("options") or []
        if i < len(opts) and isinstance(opts[i], dict) and "id" in opts[i]:
            return f"Choose {name_of(opts[i]['id'], locale)}"
        return f"Choose option {i + 1}"
    if 46 <= a <= 125:
        h, pos = divmod(a - 46, 8)
        return f"Play {n('hand', h)} at position {pos + 1}"
    if 126 <= a <= 195:
        h, t = divmod(a - 126, 7)
        return f"Magnetize {n('hand', h)} onto {n('board', t)}"
    if 196 <= a <= 244:
        m, pos = divmod(a - 196, 7)
        return f"Move {n('board', m)} to position {pos + 1}"
    return f"action {a}"


def plan_turn(g, locale):
    """The policy's actions on a copy until it ends the turn: [(action, text)]."""
    c = g.copy()
    out = []
    for _ in range(MAX_PLAN):
        if not c.needs_action(0):
            break
        a = c.bot_action(0)
        out.append((a, describe(json.loads(c.view(0)), a, locale)))
        c.step(0, a)
        if a == 0:
            break
    return out, c


def combat_odds(g, n=300):
    """Win / tie / loss against the next opponent's last seen warband, or None."""
    v = json.loads(g.view(0))
    nxt = next((o for o in v["opponents"] if o.get("is_next_opponent")), None)
    if nxt is None or not nxt.get("seen_board"):
        return None
    r = debug(g, cmd="combat_preview", a=0, b=nxt["id"], n=n)
    hero = nxt.get("hero")
    return {"win": r["win_a"], "tie": r["tie"], "loss": r["win_b"],
            "damage_dealt": r["avg_damage_by_a"], "damage_taken": r["avg_damage_by_b"],
            "opponent": (hero or {}).get("id") if isinstance(hero, dict) else hero,
            "seen_turn": nxt.get("seen_turn")}


def advise(d, combats, locale="enUS"):
    t0 = time.perf_counter()
    g, gaps = bridge.build(d, bridge.game_combats(combats, d) if combats else ())
    client = bridge.client_actions(d)
    plan, after = plan_turn(g, locale)
    warnings = sorted(set(gaps))
    first = plan[0] if plan else None
    if first is not None:
        kinds = bridge.tavern_actions([i == first[0] for i in range(len(json.loads(g.view(0))["mask"]))])
        if kinds and not kinds <= client and first[0] < 196:
            warnings.append("the first step is not offered by the client")
    advice = {
        "turn": (d["turn"] + 1) // 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "policy": "scripted bot (v0)",
        "action": first[1] if first else None,
        "plan": [t for _, t in plan],
        "odds_now": combat_odds(g),
        "odds_after_plan": combat_odds(after),
        "gold": d["state"]["friendly"].get("gold"),
        "warnings": warnings,
    }
    advice["ms"] = round((time.perf_counter() - t0) * 1000)
    return advice


def publish(advice, live_dir):
    live_dir.mkdir(parents=True, exist_ok=True)
    tmp = live_dir / "advice.json.tmp"
    tmp.write_text(json.dumps(advice, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, live_dir / "advice.json")


# ---------------------------------------------------------------------- modes

def replay(path, skins, locale, live_dir=None, limit=None):
    """Feed a recorded log as if live; advice at every recruit decision, timed."""
    tr = Tracker(skins, name=Path(path).parent.name)
    times, n = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = tr.feed(line)
            if d is None:
                continue
            a = advise(d, tr.combats(), locale)
            times.append(a["ms"])
            n += 1
            if live_dir:
                publish(a, live_dir)
            if n <= 3 or n % 50 == 0:
                print(f"turn {a['turn']}: {a['action']} | plan {a['plan'][:4]} | odds {a['odds_after_plan']} | {a['ms']} ms {a['warnings'][:2]}", flush=True)
            if limit and n >= limit:
                break
    times.sort()
    if times:
        print(f"{n} decisions advised; ms median {times[len(times) // 2]}, 95% {times[int(len(times) * 0.95)]}, max {times[-1]}")
    return n, times


def follow(log_dir, skins, locale, live_dir, poll=0.1):
    path, tr, offset, rest = None, None, 0, b""
    while True:
        newest = newest_log(log_dir)
        if newest != path and newest is not None:
            path, tr, offset, rest = newest, Tracker(skins, name=newest.parent.name), 0, b""
            print(f"following {path}", flush=True)
        if path is None or not path.exists():
            time.sleep(1.0)
            continue
        try:
            with open(path, "rb") as f:  # opened per read: Hearthstone must be able to rename it
                f.seek(offset)
                data = f.read()
        except OSError:
            data = b""
        if len(data) == 0:
            time.sleep(poll)
            continue
        offset += len(data)
        *lines, rest = (rest + data).split(b"\n")
        latest = None
        for raw in lines:
            d = tr.feed(raw.decode("utf-8", errors="replace") + "\n")
            if d is not None:
                latest = d
        if latest is not None:  # only the newest decision matters after a burst of lines
            try:
                publish(advise(latest, tr.combats(), locale), live_dir)
            except Exception as e:  # keep following; the next decision tries again
                print(f"advice failed: {type(e).__name__}: {e}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", help="a recorded Power.log instead of following the live one")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--log-dir", default=str(HS_LOGS))
    ap.add_argument("--cards", default=str(CARDS), help="client dir with CardDefs.xml")
    ap.add_argument("--live-dir", default=str(LIVE_DIR))
    ap.add_argument("--locale", default="enUS", choices=["enUS", "zhCN"])
    a = ap.parse_args()
    skins = logs.skin_parents(a.cards)
    if a.replay:
        replay(a.replay, skins, a.locale, Path(a.live_dir) if a.limit else None, a.limit)
    else:
        follow(a.log_dir, skins, a.locale, Path(a.live_dir))


if __name__ == "__main__":
    sys.exit(main())
