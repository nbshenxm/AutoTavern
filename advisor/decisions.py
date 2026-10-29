"""Extract the friendly player's recruit-phase decisions from Battlegrounds Power.logs.

At every Options packet outside combat: the state (advisor.logs snapshot plus gold, costs,
the Tavern, the leaderboard), the options the client offered with their targets (legal ones
have no error), and the option the player sent. Choices (Discover, hero and trinket picks) are
recorded the same way. This is the input of the live bridge (docs/ROADMAP.md, M2) and of the
recruit-rule checks (M1).

Run:    python -X utf8 -m advisor.decisions LOG_OR_DIR... --cards CLIENT_DIR --out data/replay
Writes OUT/decisions.jsonl.
"""

import argparse
import io
import json
import logging
import sys
from pathlib import Path

from hearthstone.entities import Player
from hearthstone.enums import CardType, GameTag, Zone
from hslog import LogParser, packets

from advisor import logs as bg_logs

T = GameTag
LEGAL_ERRORS = (None, "INVALID")  # END_TURN reports INVALID and is still allowed


class DecisionExporter(bg_logs.CombatExporter):
    def __init__(self, tree, skins, meta):
        super().__init__(tree, skins, meta)
        self.decisions = []
        self.pending = None  # the decision waiting for the player's answer

    def _entity_view(self, eid):
        """Who an option or target refers to, in the player's terms."""
        e = self.game.find_entity_by_id(eid) if isinstance(eid, int) else None
        if e is None or isinstance(e, Player):
            return {"eid": eid, "kind": "player" if e is not None else None}
        f, b = self._sides()
        ctrl = e.tags.get(T.CONTROLLER)
        return {"eid": e.id, "card": getattr(e, "card_id", None) or None,
                "type": _name(CardType, e.tags.get(T.CARDTYPE, 0)), "zone": _name(Zone, e.zone),
                "pos": e.tags.get(T.ZONE_POSITION, 0),
                "owner": "friendly" if ctrl == f else "bob" if ctrl == b else ctrl}

    def _recruit_state(self):
        f, b = self._sides()
        g = self.game
        player = next((p for p in g.players if p.tags.get(T.CONTROLLER) == f), None)
        s = self._snapshot()
        me = s["friendly"]
        pt = player.tags if player is not None else {}
        me["gold"] = (pt.get(T.RESOURCES, 0) + pt.get(T.TEMP_RESOURCES, 0)
                      - pt.get(T.RESOURCES_USED, 0))
        me["max_gold"] = pt.get(T.RESOURCES, 0)
        me["hand_all"] = [self._entity_view(e.id) | {"data": bg_logs._data(e)}
                          for e in sorted((e for e in g.entities if e.zone == Zone.HAND
                                           and e.tags.get(T.CONTROLLER) == f),
                                          key=lambda e: e.tags.get(T.ZONE_POSITION, 0))]
        buttons = {}
        for e in g.entities:
            cid = getattr(e, "card_id", None) or ""
            if e.zone == Zone.PLAY and e.tags.get(T.CONTROLLER) == f and cid.startswith("TB_BaconShop"):
                if "TechUp" in cid:
                    buttons["upgrade"] = e.tags.get(T.COST, 0)
                elif "Reroll" in cid:
                    buttons["refresh"] = e.tags.get(T.COST, 0)
        me["costs"] = buttons
        shop = []
        for e in sorted(self._in_play(b, CardType.MINION) + self._in_play(b, CardType.BATTLEGROUND_SPELL),
                        key=lambda e: e.tags.get(T.ZONE_POSITION, 0)):
            item = self._minion(e) if _type(e) == CardType.MINION else \
                {"card": e.card_id, "eid": e.id, "pos": e.tags.get(T.ZONE_POSITION, 0),
                 "data": bg_logs._data(e)}
            item.update(kind="minion" if _type(e) == CardType.MINION else "spell",
                        frozen=bool(e.tags.get(T.FROZEN)), cost=e.tags.get(T.COST, 0))
            shop.append(item)
        s["shop"] = shop
        s["leaderboard"] = self._leaderboard()
        return s

    def _leaderboard(self):
        """Every player's latest hero: health, armor, tier, place (PLAYER_ID keyed)."""
        latest = {}
        for e in self.game.entities:
            pid = e.tags.get(T.PLAYER_ID)
            if _type(e) == CardType.HERO and pid and e.tags.get(T.PLAYER_LEADERBOARD_PLACE):
                if pid not in latest or e.id > latest[pid].id:
                    latest[pid] = e
        return {str(pid): {"hero": self.skins.get(e.card_id, e.card_id), "health": bg_logs._hp(e),
                           "armor": e.tags.get(T.ARMOR, 0), "tier": e.tags.get(T.PLAYER_TECH_LEVEL, 0),
                           "place": e.tags.get(T.PLAYER_LEADERBOARD_PLACE, 0)}
                for pid, e in latest.items()}

    # ------------------------------------------------------------------ packets

    def handle_options(self, packet):
        super().handle_options(packet)
        if self.combat is not None:
            return
        options = []
        for o in packet.options:
            options.append({
                "id": o.id, "type": _name_opt(o.type), "error": o.error,
                "legal": o.error in LEGAL_ERRORS,
                "entity": self._entity_view(o.entity) if o.entity else None,
                "targets": [{"id": t.id, "legal": t.error in LEGAL_ERRORS,
                             "entity": self._entity_view(t.entity)}
                            for t in o.options if t.optype == "target"],
                "subs": [{"id": t.id, "legal": t.error in LEGAL_ERRORS,
                          "entity": self._entity_view(t.entity)}
                         for t in o.options if t.optype == "subOption"],
            })
        self._close_pending()
        self.pending = {**self.meta, "kind": "options", "turn": self.game.tags.get(T.TURN, 0),
                        "state": self._recruit_state(), "options": options, "chosen": None}

    def handle_send_option(self, packet):
        super().handle_send_option(packet)
        if self.pending is not None and self.pending["kind"] == "options":
            self.pending["chosen"] = {"option": packet.option, "suboption": packet.suboption,
                                      "target": self._entity_view(packet.target) if packet.target else None,
                                      "position": packet.position}
            self._close_pending()

    def handle_choices(self, packet):
        super().handle_choices(packet)
        f, _ = self._sides()
        player = self.game.find_entity_by_id(packet.entity) if isinstance(packet.entity, int) else None
        if self.combat is not None or (player is not None and player.tags.get(T.CONTROLLER) != f):
            return
        self._close_pending()
        self.pending = {**self.meta, "kind": "choices", "turn": self.game.tags.get(T.TURN, 0),
                        "choice_type": _name_opt(packet.type),
                        "source": self._entity_view(packet.source) if getattr(packet, "source", None) else None,
                        "options": [self._entity_view(c) for c in packet.choices],
                        "state": self._recruit_state(), "chosen": None}

    def handle_send_choices(self, packet):
        super().handle_send_choices(packet)
        if self.pending is not None and self.pending["kind"] == "choices":
            self.pending["chosen"] = [self._entity_view(c) for c in packet.choices]
            self._close_pending()

    def handle_chosen_entities(self, packet):
        super().handle_chosen_entities(packet)
        # Discover and trinket picks are answered here rather than by SendChoices
        if self.pending is not None and self.pending["kind"] == "choices" and not self.pending["chosen"]:
            self.pending["chosen"] = [self._entity_view(c) for c in packet.choices]
            self._close_pending()

    def _close_pending(self):
        if self.pending is not None:
            self.decisions.append(self.pending)
            self.pending = None

    def export(self):
        super().export()
        self._close_pending()
        return self


def _type(e):
    return e.tags.get(T.CARDTYPE, 0)


def _name(enum, v):
    try:
        return enum(v).name
    except ValueError:
        return v


def _name_opt(v):
    return getattr(v, "name", v)


def extract(path, skins):
    logging.disable(logging.WARNING)
    build = bg_logs.build_number(path)
    out = []
    for i, lines in enumerate(bg_logs.segments(path)):
        parser = LogParser()
        try:
            parser.read(io.StringIO("".join(lines)))
        except Exception as e:  # a damaged segment: skip it, keep the rest
            print(f"  {Path(path).parent.name} segment {i}: {type(e).__name__}: {e}")
            continue
        for tree in parser.games:
            if not bg_logs.is_bg(tree):
                continue
            meta = {"log": Path(path).parent.name, "segment": i, "build": build,
                    "player_id": bg_logs.friendly_player_id(lines)}
            out += DecisionExporter(tree, skins, meta).export().decisions
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--cards", required=True)
    ap.add_argument("--out", default="data/replay")
    a = ap.parse_args()
    files = []
    for x in map(Path, a.logs):
        files += sorted(x.rglob("Power.log")) if x.is_dir() else [x]
    skins = bg_logs.skin_parents(a.cards)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out / "decisions.jsonl", "w", encoding="utf-8") as f:
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if "GameType=GT_BATTLEGROUNDS" not in fh.read():
                    continue
            ds = extract(path, skins)
            for d in ds:
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
            n += len(ds)
            print(f"{path.parent.name}: {len(ds)} decisions", flush=True)
    print(f"wrote {n} decisions to {out / 'decisions.jsonl'}")


if __name__ == "__main__":
    sys.exit(main())
