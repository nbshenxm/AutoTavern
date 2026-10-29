"""Extract combats and shop offers from Battlegrounds Power.logs.

For every combat the friendly player fought, records both warbands twice: when combat
starts (before Start of Combat effects) and just before the first attack (with the side that
attacks first), plus heroes, Hero Powers, trinkets, enchantments and the outcome (winner and
the damage the winner's hero dealt, before armor). For every game, records the minions and
spells Bob offered, with their stats, as evidence for the pool and stat checks.

Run:    python -X utf8 tools/bg_logs.py LOG_OR_DIR... --cards CLIENT_DIR --out data/replay
Writes OUT/combats.jsonl and OUT/offers.jsonl (one JSON object per combat / per offer).
Logs hold player names: keep the output out of the repository (data/ is ignored).
"""

import argparse
import io
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from hearthstone.entities import Player
from hearthstone.enums import BlockType, CardType, GameTag, Zone
from hslog import LogParser, packets
from hslog.export import EntityTreeExporter

T = GameTag
KEYWORD_TAGS = {
    "TAUNT": T.TAUNT, "DIVINE_SHIELD": T.DIVINE_SHIELD, "REBORN": T.REBORN,
    "VENOMOUS": T.VENOMOUS, "POISONOUS": T.POISONOUS, "STEALTH": T.STEALTH,
    "WINDFURY": T.WINDFURY, "MEGA_WINDFURY": T.MEGA_WINDFURY,
}
SCRIPT_TAGS = (T.TAG_SCRIPT_DATA_NUM_1, T.TAG_SCRIPT_DATA_NUM_2)
TRINKET = 44  # CardType.BATTLEGROUND_TRINKET
TRINKET_PLACEHOLDERS = re.compile(r"^BG30_Trinket_(1st|2nd)$")


def skin_parents(client_dir):
    """Skin card id -> base hero card id (BACON_SKIN_PARENT_ID), from CardDefs.xml."""
    dbf_to_id, parent = {}, {}
    for _, el in ET.iterparse(Path(client_dir) / "CardDefs.xml", events=("end",)):
        if el.tag != "Entity":
            continue
        cid = el.get("CardID")
        dbf_to_id[int(el.get("ID"))] = cid
        for t in el.findall("Tag"):
            if t.get("name") == "BACON_SKIN_PARENT_ID":
                parent[cid] = int(t.get("value"))
        el.clear()
    return {cid: dbf_to_id.get(p, cid) for cid, p in parent.items()}


def _type(e):
    return e.tags.get(T.CARDTYPE, 0)


def _hp(e):
    return e.tags.get(T.HEALTH, 0) - e.tags.get(T.DAMAGE, 0)


def _data(e):
    return [e.tags.get(t, 0) for t in SCRIPT_TAGS]


class CombatExporter(EntityTreeExporter):
    def __init__(self, tree, skins, meta):
        super().__init__(tree)
        self.skins = skins
        self.meta = meta
        self.combats, self.offers = [], []
        self.combat = None
        self.friendly = self.bob = None
        self.depth = 0  # nesting of the block being exported

    # ------------------------------------------------------------------ snapshots

    def _sides(self):
        if self.friendly is None:
            for p in self.game.players:
                hero = self.game.find_entity_by_id(p.tags.get(T.HERO_ENTITY, 0))
                if hero is not None and (hero.card_id or "").startswith("TB_BaconShopBob"):
                    self.bob = p.tags.get(T.CONTROLLER)
            others = [p.tags.get(T.CONTROLLER) for p in self.game.players]
            others = [c for c in others if c != self.bob]
            if self.bob is not None and len(others) == 1:
                self.friendly = others[0]
        return self.friendly, self.bob

    def _in_play(self, ctrl, ctype):
        return [e for e in self.game.entities
                if e.zone == Zone.PLAY and _type(e) == ctype and e.tags.get(T.CONTROLLER) == ctrl]

    def _enchantments(self, target_id):
        return [{"card": e.card_id, "data": _data(e)} for e in self.game.entities
                if _type(e) == CardType.ENCHANTMENT and e.zone == Zone.PLAY
                and e.tags.get(T.ATTACHED) == target_id]

    def _minion(self, e):
        t = e.tags
        kws = [k for k, tag in KEYWORD_TAGS.items() if t.get(tag)]
        return {"card": e.card_id, "eid": e.id, "pos": t.get(T.ZONE_POSITION, 0),
                "atk": t.get(T.ATK, 0), "hp": _hp(e), "max_hp": t.get(T.HEALTH, 0),
                "golden": t.get(T.PREMIUM, 0) == 1, "tier": t.get(T.TECH_LEVEL, 0),
                "keywords": kws, "data": _data(e), "ench": self._enchantments(e.id)}

    def _side(self, ctrl):
        heroes = self._in_play(ctrl, CardType.HERO)
        hero = heroes[0] if heroes else None
        board = sorted((self._minion(e) for e in self._in_play(ctrl, CardType.MINION)),
                       key=lambda m: m["pos"])
        hand = [self._minion(e) for e in self.game.entities
                if e.zone == Zone.HAND and _type(e) == CardType.MINION
                and e.tags.get(T.CONTROLLER) == ctrl and getattr(e, "card_id", None)]
        side = {"board": board, "hand": sorted(hand, key=lambda m: m["pos"]),
                "hero_powers": [{"card": e.card_id, "data": _data(e)}
                                for e in self._in_play(ctrl, CardType.HERO_POWER)],
                "trinkets": [{"card": e.card_id, "data": _data(e)}
                             for e in self._in_play(ctrl, TRINKET)
                             if not TRINKET_PLACEHOLDERS.match(e.card_id or "")],
                "other": sorted({e.card_id for e in self.game.entities
                                 if e.zone == Zone.PLAY and e.tags.get(T.CONTROLLER) == ctrl
                                 and _type(e) not in (CardType.MINION, CardType.HERO,
                                                      CardType.HERO_POWER, CardType.ENCHANTMENT,
                                                      TRINKET)
                                 and getattr(e, "card_id", None)})}
        # Player-level state ("your Beetles have +X/+X this game", improved Tasty Lobsters...)
        player = next((p for p in self.game.players if p.tags.get(T.CONTROLLER) == ctrl), None)
        if player is not None:
            side["player_ench"] = self._enchantments(player.id)
        if hero is not None:
            side.update(hero=self.skins.get(hero.card_id, hero.card_id), hero_skin=hero.card_id,
                        health=_hp(hero), armor=hero.tags.get(T.ARMOR, 0),
                        tier=hero.tags.get(T.PLAYER_TECH_LEVEL, 0),
                        hero_ench=self._enchantments(hero.id))
        return side

    def _snapshot(self):
        f, b = self._sides()
        return {"friendly": self._side(f), "opponent": self._side(b)}

    # ------------------------------------------------------------------ packet hooks

    def export(self):
        super().export()
        # The game (or the segment) ended during a combat: the last fight still counts
        if self.combat and self.combat["start"] is not None:
            self.combats.append(self.combat)
        self.combat = None
        return self

    def handle_tag_change(self, packet):
        super().handle_tag_change(packet)
        g = self.game
        if packet.entity != g.id:
            return
        if packet.tag == T.BOARD_VISUAL_STATE and packet.value == 2:
            self.combat = {**self.meta, "turn": g.tags.get(T.TURN, 0), "start": None,
                           "first_attack": None, "first_attacker": None,
                           "winner": "tie", "damage": 0, "alive": None,
                           "opponent_created": False}
        elif packet.tag == T.BOARD_VISUAL_STATE and packet.value == 1 and self.combat:
            if self.combat["start"] is not None:
                self.combats.append(self.combat)
            self.combat = None

    def _effect_source(self, ref):
        """A block from a card (Hero Power, minion, hand card, trinket, hidden effect), not
        from the game, a player, a cosmetic, or the system entity that sets combat up."""
        if not isinstance(ref, int) or ref == self.game.id:
            return False
        e = self.game.find_entity_by_id(ref)
        return (e is not None and not isinstance(e, Player) and e.zone != Zone.COSMETIC
                and not (getattr(e, "card_id", None) or "").startswith("TB_BaconShop_8P_PlayerE"))

    def _alive(self):
        """Players still in the lobby: the latest hero entity of each PLAYER_ID with health."""
        latest = {}
        for e in self.game.entities:
            pid = e.tags.get(T.PLAYER_ID)
            if _type(e) == CardType.HERO and pid and e.tags.get(T.PLAYER_LEADERBOARD_PLACE):
                if pid not in latest or e.id > latest[pid].id:
                    latest[pid] = e
        return sum(1 for e in latest.values() if _hp(e) > 0) or None

    def handle_block(self, block):
        c = self.combat
        attacker = None
        # Before Start of Combat: the first top-level effect after this combat's opponent hero
        # was created and Bob's warband entered play (the client sets the warbands up before
        # or after STEP=MAIN_START depending on the build), or else the first attack
        if (c is not None and c["start"] is None and c["opponent_created"] and self.depth == 0
                and (block.type == BlockType.ATTACK
                     or (self._effect_source(block.entity)
                         and self._in_play(self._sides()[1], CardType.MINION)))):
            c["start"] = self._snapshot()
            c["alive"] = self._alive()
        if c is not None and block.type == BlockType.ATTACK and c["start"] is not None:
            attacker = self.game.find_entity_by_id(int(block.entity)) if block.entity else None
            if attacker is not None and _type(attacker) == CardType.MINION and not c["first_attack"]:
                c["first_attack"] = self._snapshot()
                f, _ = self._sides()
                c["first_attacker"] = "friendly" if attacker.tags.get(T.CONTROLLER) == f else "opponent"
        self.depth += 1
        try:
            super().handle_block(block)
        finally:
            self.depth -= 1
        if attacker is not None and _type(attacker) == CardType.HERO:
            f, _ = self._sides()
            c["winner"] = "friendly" if attacker.tags.get(T.CONTROLLER) == f else "opponent"
            c["damage"] = max([p.value for p in _walk(block) if isinstance(p, packets.TagChange)
                               and p.tag == T.PREDAMAGE] or [0])

    def handle_full_entity(self, packet):
        super().handle_full_entity(packet)
        c = self.combat
        if c is not None and not c["opponent_created"]:
            e = self.game.find_entity_by_id(packet.entity)
            if e is not None and _type(e) == CardType.HERO and \
                    e.tags.get(T.CONTROLLER) == self._sides()[1]:
                c["opponent_created"] = True
        self._offer(packet.entity)

    def handle_show_entity(self, packet):
        super().handle_show_entity(packet)
        self._offer(packet.entity)

    def _offer(self, eid):
        """A minion or spell appearing in Bob's tavern during a recruit phase."""
        if self.combat is not None:
            return
        f, b = self._sides()
        e = self.game.find_entity_by_id(eid)
        if b is None or e is None or not getattr(e, "card_id", None) or e.zone != Zone.PLAY:
            return
        if e.tags.get(T.CONTROLLER) != b or _type(e) not in (CardType.MINION, CardType.BATTLEGROUND_SPELL):
            return
        self.offers.append({**self.meta, "turn": self.game.tags.get(T.TURN, 0), "card": e.card_id,
                            "type": CardType(_type(e)).name, "atk": e.tags.get(T.ATK, 0),
                            "hp": e.tags.get(T.HEALTH, 0), "tier": e.tags.get(T.TECH_LEVEL, 0),
                            "golden": e.tags.get(T.PREMIUM, 0) == 1, "cost": e.tags.get(T.COST, 0)})


def _walk(block):
    for p in block.packets:
        yield p
        if isinstance(p, packets.Block):
            yield from _walk(p)


def build_number(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"BuildNumber=(\d+)", line)
            if m:
                return int(m.group(1))
    return 0


def is_bg(tree):
    return any(isinstance(p, (packets.FullEntity, packets.ShowEntity))
               and (p.card_id or "").startswith("TB_BaconShopBob") for p in tree.packets[:400])


def segments(path):
    """The log split at each CREATE_GAME. A reconnect starts a new segment of the same game
    with the full state; hslog keeps players across segments and fails when the next game
    gives the account another PlayerID, so each segment gets its own parser."""
    seg = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "GameState.DebugPrintPower() - CREATE_GAME" in line and seg:
                yield seg
                seg = []
            seg.append(line)
    if seg:
        yield seg


def friendly_player_id(lines, name_hint="#"):
    """PlayerID of the account (the DebugPrintGame player whose name is a BattleTag)."""
    for line in lines[:6000]:
        m = re.search(r"DebugPrintGame\(\) - PlayerID=(\d+), PlayerName=(.*)$", line)
        if m and name_hint in m.group(2):
            return int(m.group(1))
    return 0


def extract(path, skins):
    logging.disable(logging.WARNING)  # hslog warns about every nesting quirk
    build = build_number(path)
    combats, offers = [], []
    for i, lines in enumerate(segments(path)):
        parser = LogParser()
        try:
            parser.read(io.StringIO("".join(lines)))
        except Exception as e:  # a damaged segment: skip it, keep the rest
            print(f"  {Path(path).parent.name} segment {i}: {type(e).__name__}: {e}")
            continue
        for tree in parser.games:
            if not is_bg(tree):
                continue
            meta = {"log": Path(path).parent.name, "segment": i, "build": build,
                    "player_id": friendly_player_id(lines)}
            ex = CombatExporter(tree, skins, meta)
            ex.export()
            combats += ex.combats
            offers += ex.offers
    return combats, offers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", help="Power.log files or directories holding them")
    ap.add_argument("--cards", required=True, help="client dir with CardDefs.xml (hero skins)")
    ap.add_argument("--out", default="data/replay")
    a = ap.parse_args()
    files = []
    for x in map(Path, a.logs):
        files += sorted(x.rglob("Power.log")) if x.is_dir() else [x]
    skins = skin_parents(a.cards)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n_c = n_o = 0
    with open(out / "combats.jsonl", "w", encoding="utf-8") as fc, \
         open(out / "offers.jsonl", "w", encoding="utf-8") as fo:
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as f:
                if "GameType=GT_BATTLEGROUNDS" not in f.read():
                    continue
            combats, offers = extract(path, skins)
            for c in combats:
                fc.write(json.dumps(c, ensure_ascii=False) + "\n")
            for o in offers:
                fo.write(json.dumps(o, ensure_ascii=False) + "\n")
            n_c, n_o = n_c + len(combats), n_o + len(offers)
            print(f"{path.parent.name}: {len(combats)} combats, {len(offers)} offers", flush=True)
    print(f"wrote {n_c} combats and {n_o} offers to {out}")


if __name__ == "__main__":
    sys.exit(main())
