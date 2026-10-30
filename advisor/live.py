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

import numpy as np
from hearthstone.enums import CardType, GameTag as T
from hslog import LogParser, packets

from advisor import bridge, decisions, display, logs, meta
from advisor.state import CAT, debug

HS_LOGS = Path(r"D:\Program Files (x86)\Hearthstone\Logs")
CARDS = Path(r"D:\GitHub\Hearthstone_AI_Advisor\data\cards\255790")
LIVE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "TavernAdvisor"
MODEL = Path(__file__).resolve().parents[1] / "data" / "models" / "best.pt"
CREATE_GAME = "GameState.DebugPrintPower() - CREATE_GAME"
OPTIONS = "GameState.DebugPrintOptions()"
CHOICES = "GameState.DebugPrintEntityChoices()"
MAX_PLAN = 80  # above the largest turn action cap (GAME_CONFIG), so a plan reaches End Turn
A_MOVE = 196  # taverngym.layout(): the first move action


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
        self.combat = False  # the combat phase is on (the overlay hides the advice)
        self.reported_choice = None  # (segment, choice id) of the last open choice advised
        self.tavern_seen = set()  # Tavern cards seen this game: the lobby's types (bridge)

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
            self.tavern_seen = set()
        if self.parser is None:
            return None
        m = re.search(r"DebugPrintGame\(\) - PlayerID=(\d+), PlayerName=(.*)$", line)
        if m and "#" in m.group(2):
            self.player_id = int(m.group(1))
        if "GameState.DebugPrintPower()" in line and "GameEntity tag=BOARD_VISUAL_STATE value=" in line:
            self.combat = line.rstrip().endswith("value=2")
        options = OPTIONS in line or CHOICES in line  # a block of either ends with the next line
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
        if self.exported < len(pk):  # a Discover waits inside the block of what caused it
            d = self.open_choice(pk[self.exported])
            if d is not None:
                return self._seen(d)
        d = self.exporter.pending
        if d is None or d["turn"] % 2 == 0 or d is self.reported:
            return None
        # Recruit Options, or a Discover between minions (Dark Discovery...): both get advice
        if d["kind"] != "options" and not bridge.discover_options(d):
            return None
        self.reported = d
        return self._seen(d)

    def _seen(self, d):
        """Note the Tavern's cards (the lobby's types) and attach all seen so far."""
        self.tavern_seen.update(x["card"] for x in d["state"].get("shop", []) if x.get("card"))
        d["tavern_seen"] = sorted(self.tavern_seen)
        return d

    def open_choice(self, block):
        """The player's unanswered choice between minions inside an unfinished block (Dark
        Discovery, a Discover card), as a choice decision: the options as the block created
        them, the state as it was before the block. None when there is none."""
        if self.exporter.combat is not None:
            return None
        info, choice = {}, None
        for p in _walk(block):
            if isinstance(p, (packets.FullEntity, packets.ShowEntity)):
                e = info.setdefault(p.entity, {})
                e["card"] = p.card_id or e.get("card")
                e.update({int(t): v for t, v in (p.tags or [])})
            elif isinstance(p, packets.TagChange) and isinstance(p.entity, int):
                info.setdefault(p.entity, {})[int(p.tag)] = p.value
            elif isinstance(p, packets.Choices):
                choice = p
            elif isinstance(p, (packets.SendChoices, packets.ChosenEntities)) and choice is not None \
                    and getattr(p, "id", None) == choice.id:
                choice = None  # answered
        if choice is None or (self.reported_choice == (self.segment, choice.id)):
            return None
        options = []
        for eid in choice.choices:
            e = info.get(eid, {})
            if not e.get("card") or e.get(int(T.CARDTYPE)) != int(CardType.MINION):
                return None  # not a choice between minions (trinkets, heroes...)
            ench = [{"card": x["card"], "data": [x.get(int(t), 0) for t in logs.SCRIPT_TAGS]}
                    for x in info.values() if x.get(int(T.ATTACHED)) == eid and x.get("card")]
            options.append({"card": e["card"], "minion": {
                "card": e["card"], "eid": eid, "pos": 0, "atk": e.get(int(T.ATK), 0),
                "hp": e.get(int(T.HEALTH), 0) - e.get(int(T.DAMAGE), 0), "max_hp": e.get(int(T.HEALTH), 0),
                "golden": e.get(int(T.PREMIUM), 0) == 1, "tier": e.get(int(T.TECH_LEVEL), 0),
                "keywords": [k for k, tag in logs.KEYWORD_TAGS.items() if e.get(int(tag))],
                "data": [e.get(int(t), 0) for t in logs.SCRIPT_TAGS], "ench": ench}})
        self.reported_choice = (self.segment, choice.id)
        g = self.exporter.game
        return {**self.exporter.meta, "kind": "choices", "turn": g.tags.get(T.TURN, 0),
                "choice_type": getattr(choice.type, "name", choice.type), "options": options,
                "state": self.exporter._recruit_state(), "chosen": None}

    def combats(self):
        done = self.history.get(self.player_id, [])
        live = self.exporter.combats if self.exporter is not None else []
        return done + live

    def _close_segment(self):
        if self.exporter is not None:
            self.history.setdefault(self.player_id, []).extend(self.exporter.combats)
            self.exporter.combats = []


def _walk(block):
    for p in block.packets:
        yield p
        if isinstance(p, packets.Block):
            yield from _walk(p)


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


def plan_turn(g, locale, net=None, allowed=None, script=None):
    """The policy's actions on a copy until it ends the turn: ([(action, text)], rows, the copy
    at the end). With a network, its most likely action at each step; the first step only among
    `allowed` (what the client offers too). Without one, TavernGym's scripted bot. `rows` are
    the overlay's (advisor.display): a target joins the step that asked for it, and a run of
    moves is one "Arrange" step with the warband's order after it. `script`: these actions
    instead (a plan the search chose), then the plan ends."""
    c = g.copy()
    out, rows = [], []
    after = json.loads(c.view(0))
    for step in range(MAX_PLAN):
        if not c.needs_action(0):
            break
        if script is not None and step < len(script) and not after["mask"][script[step]]:
            # The search planned on a copy with what's hidden re-rolled: where its plan asks
            # for something this game doesn't offer, the network goes on from here
            script = None
        if script is not None:
            if step >= len(script):
                break
            a = script[step]
        elif net is None:
            a = c.bot_action(0)
        else:
            from advisor.policy import act
            a, _, _ = act(net, c, 0, np.array(allowed) if step == 0 and allowed is not None else None)
        view = after  # one view per step: the last step's result is this one's start
        text = describe(view, a, locale)
        row = display.row_for(view, a, locale, name_of)
        if row is None:
            display.merge_target(rows, view, a, locale, name_of)
        c.step(0, a)
        after = json.loads(c.view(0))
        chance = random_outcome(view, a, after)
        if chance:
            # What comes next is the simulator's own roll (a new Tavern, offered cards), not
            # what the game will offer: the plan stops here and the advice updates then
            out.append((a, text))
            if row is not None:
                rows.append(row)
            rows.append(display.chance_row(chance, locale))
            break
        if a >= A_MOVE:
            text = "Arrange: " + ", ".join(name_of(m["id"], locale) for m in after["me"]["board"])
            row = display.arrange_row(after, locale, name_of)
            if out and out[-1][0] >= A_MOVE:
                out[-1] = (a, text)
                rows[-1] = row
                continue
        out.append((a, text))
        if row is not None:
            rows.append(row)
        if a == 0:
            break
    return out, display.collapse(rows, locale), c


def random_outcome(before, a, after):
    """Whether action `a` leads to something random the plan can't know: "tavern" (a Refresh),
    "choice" (it opened an offer: Dark Discovery, a Discover card, trinkets), else None."""
    if a == 1:
        return "tavern"
    pending = after["me"].get("pending") or {}
    if pending and pending.get("kind") != "target" and not (30 <= a <= 45 and before["me"].get("pending")):
        return "choice"
    return None


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


COMPS = []  # meta comps (advisor.meta), loaded by main
SEARCH = {"k": 0, "temperature": 1.0}  # plan search (advisor.search): k sampled plans, 0 = off


def advise(d, combats, locale="enUS", net=None, policy_name="scripted bot (v0)"):
    t0 = time.perf_counter()
    g, gaps = bridge.build(d, bridge.game_combats(combats, d) if combats else ())
    mask = json.loads(g.view(0))["mask"]
    if d["kind"] == "choices":  # a Discover: the real options are the pending choice
        client, allowed = set(), [bool(x) for x in mask]
    else:
        client = bridge.client_actions(d)
        allowed = bridge.allowed_mask(mask, d)
    script = None
    if net is not None and SEARCH["k"] > 0:
        from advisor import search
        script, _, _ = search.best_plan(g, net, 0, allowed, SEARCH["k"], SEARCH["temperature"])
        policy_name += f", plan search over {SEARCH['k'] + 1}"
    plan, rows, after = plan_turn(g, locale, net, allowed, script)
    warnings = sorted(set(gaps))
    first = plan[0] if plan else None
    if first is not None and net is None:
        k = bridge.action_kind(first[0])
        if k is not None and k not in client:
            warnings.append("the first step is not offered by the client")
    odds_now, odds_after = combat_odds(g), combat_odds(after)
    turn = (d["turn"] + 1) // 2
    me = d["state"]["friendly"]
    owned = [m["card"] for m in me["board"]] + [h.get("card") for h in bridge.hand_cards(me)]
    comp = meta.closest([c for c in owned if c], COMPS)
    notes = [x for x in (display.odds_note("now", odds_now, locale, turn),
                         display.odds_note("after", odds_after, locale, turn),
                         display.comp_note(comp, locale, name_of)) if x]
    advice = {
        "display": {"title": display.t(locale, "title", turn=turn), "subtitle": policy_name,
                    "style": "normal", "rows": rows, "notes": notes, "warnings": warnings},
        "turn": turn,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "recruit",
        "policy": policy_name,
        "action": first[1] if first else None,
        "plan": [t for _, t in plan],
        "odds_now": odds_now,
        "odds_after_plan": odds_after,
        "comp": comp,
        "gold": d["state"]["friendly"].get("gold"),
        "warnings": warnings,
    }
    advice["ms"] = round((time.perf_counter() - t0) * 1000)
    return advice


def record(advice, d, live_dir):
    """Append the advice with what it was based on (the slots as the log showed them) to
    history.jsonl, so a reported problem ("turn 6, row 2 said H3") can be traced."""
    me = d["state"]["friendly"]
    seen = {"log": d.get("log"), "segment": d.get("segment"), "game_turn": d.get("turn"),
            "kind": d.get("kind"), "gold": me.get("gold"),
            "tavern": [x["card"] for x in d["state"].get("shop", [])],
            "hand": [h.get("card") for h in bridge.hand_cards(me)],
            "board": [m["card"] for m in me["board"]],
            "offer": [o.get("card") for o in d.get("options", [])] if d.get("kind") == "choices" else None}
    try:
        with open(live_dir / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"advice": advice, "seen": seen}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the history is for diagnosis only


def publish(advice, live_dir):
    live_dir.mkdir(parents=True, exist_ok=True)
    tmp = live_dir / "advice.json.tmp"
    tmp.write_text(json.dumps(advice, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, live_dir / "advice.json")


# ---------------------------------------------------------------------- modes

def replay(path, skins, locale, live_dir=None, limit=None, policy=(None, "scripted bot (v0)")):
    """Feed a recorded log as if live; advice at every recruit decision, timed."""
    tr = Tracker(skins, name=Path(path).parent.name)
    times, n = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = tr.feed(line)
            if d is None:
                continue
            a = advise(d, tr.combats(), locale, *policy)
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


def follow(log_dir, skins, locale, live_dir, poll=0.1, policy=(None, "scripted bot (v0)")):
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
        latest, was_combat = None, tr.combat
        for raw in lines:
            d = tr.feed(raw.decode("utf-8", errors="replace") + "\n")
            if d is not None:
                latest = d
        if tr.combat and not was_combat:
            publish({"phase": "combat", "generated_at": datetime.now().isoformat(timespec="seconds")},
                    live_dir)
        if latest is not None and not tr.combat:  # only the newest decision matters after a burst
            try:
                current = policy.get() if isinstance(policy, Policy) else policy
                advice = advise(latest, tr.combats(), locale, *current)
                publish(advice, live_dir)
                record(advice, latest, live_dir)
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
    ap.add_argument("--log-file", help="write output here (the plugin runs pythonw, no console)")
    ap.add_argument("--search", type=int, default=8, metavar="K",
                    help="plan search over the greedy plan and K sampled ones (0: off; at 8 it "
                    "places 0.48 better than the network alone, docs/EXPERIMENTS.md)")
    ap.add_argument("--model", default=str(MODEL),
                    help="policy network (advisor.train checkpoint); the scripted bot without one")
    a = ap.parse_args()
    if a.log_file:
        Path(a.log_file).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(a.log_file, "a", encoding="utf-8", buffering=1)
    skins = logs.skin_parents(a.cards)
    SEARCH["k"] = a.search
    meta.fetch()
    COMPS[:] = meta.comps()
    policy = Policy(a.model)
    if a.replay:
        replay(a.replay, skins, a.locale, Path(a.live_dir) if a.limit else None, a.limit,
               policy.get())
    else:
        follow(a.log_dir, skins, a.locale, Path(a.live_dir), policy=policy)


class Policy:
    """The network at `path`, reloaded when the file changes (the model sync replaces it while
    the advisor runs); the scripted bot while there is none."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.version = None
        self.current = (None, "scripted bot (v0)")

    def get(self):
        try:
            version = self.path.stat().st_mtime_ns if self.path else None
        except OSError:
            version = None
        if version != self.version:
            self.version = version
            try:
                self.current = load_policy(self.path)
            except Exception as e:  # a half-copied file: keep the previous network, retry later
                print(f"could not load {self.path}: {type(e).__name__}: {e}", flush=True)
                self.version = None
        return self.current


def load_policy(path):
    """(network, name) from a checkpoint, or (None, the scripted bot's name)."""
    if not path or not Path(path).is_file():
        return None, "scripted bot (v0)"
    from advisor.policy import load
    net, ck = load(path)
    ev = ck.get("gate") or ck.get("eval") or {}
    name = f"early network, it {ck.get('iteration', '?')}"
    if ev:
        name += f" (place {ev.get('mean_place')} vs bots, {ev.get('n')} games)"
    print(f"policy: {name}", flush=True)
    return net, name


if __name__ == "__main__":
    sys.exit(main())
