"""The policy networks over TavernGym observations, shared by training (advisor.train) and the
live advisor. Both take the 3,227 observation floats (signed log) and the 124 card indices
(taverngym.layout) and give logits over the 245 actions (illegal ones masked out) and a value
(expected placement reward, -1..1).

- "mlp" (PolicyNet): every card slot's embedding concatenated with the floats, an MLP.
- "entity" (EntityNet): a token per card slot (its card embedding with its own stats) and a
  global token, a transformer over them, and pointer heads: an action on a Tavern, hand or
  warband slot is scored from that slot's token.
"""

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

import taverngym
from taverngym import N_ACTIONS, N_CARDS, OBS_CARDS, OBS_FLOATS

A_MOVE = 196  # taverngym.layout()


class PolicyNet(nn.Module):
    def __init__(self, card_dim=32, hidden=1024, arch="mlp"):
        super().__init__()
        self.config = {"arch": "mlp", "card_dim": card_dim, "hidden": hidden}
        self.cards = nn.Embedding(N_CARDS + 1, card_dim, padding_idx=0)
        self.body = nn.Sequential(
            nn.Linear(OBS_FLOATS + OBS_CARDS * card_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden // 2), nn.ReLU(),
        )
        self.pi = nn.Linear(hidden // 2, N_ACTIONS)
        self.v = nn.Linear(hidden // 2, 1)
        # A new network starts unlikely to move minions: 49 of the 245 actions are moves, which
        # never advance the game, and an untrained policy would spend its turns on them
        with torch.no_grad():
            self.pi.bias[A_MOVE:] = -3.0

    def forward(self, features, cards, mask):
        # Signed log: late-game stats run into the tens of thousands (a Tasty Lobster build's
        # minions), which raw would swamp the network
        features = torch.sign(features) * torch.log1p(features.abs())
        e = self.cards(cards.clamp(0, N_CARDS)).flatten(1)
        h = self.body(torch.cat([features, e], dim=1))
        logits = self.pi(h).masked_fill(~mask, -1e9)
        return logits, self.v(h).squeeze(1)


L = dict(taverngym.layout())
MINION_F, ITEM_F, OPP_F = L["MINION_F"], L["ITEM_F"], L["OPP_F"]
N_BOARD, N_HAND, N_SHOP, N_CHOICE, N_OPP = (L["N_BOARD"], L["N_HAND"], L["N_SHOP"],
                                            L["N_CHOICE"], L["N_OPP"])
GLOBAL_ALL = L["GLOBAL_F"] + L["N_QUESTS"] * L["QUEST_F"] + L["PENDING_KINDS"]
# Card slots before the warband: hero, Hero Powers, Deity, the pending choice's source, Quests
# (card, Reward, owned Reward each), Secrets (crates/taverngym/src/obs.rs)
N_MISC = 1 + L["N_POWERS"] + 2 + 3 * L["N_QUESTS"] + L["N_SECRETS"]
N_TRINKETS = 8
# Float blocks in observation order: (name, slots, floats each)
FLOAT_BLOCKS = [("board", N_BOARD, MINION_F), ("hand", N_HAND, ITEM_F), ("shop", N_SHOP, ITEM_F),
                ("choice", N_CHOICE, ITEM_F), ("opp", N_OPP, OPP_F),
                ("oppb", N_OPP * N_BOARD, MINION_F)]
assert GLOBAL_ALL + sum(n * k for _, n, k in FLOAT_BLOCKS) == OBS_FLOATS
assert N_MISC + N_TRINKETS + sum(n for _, n, _ in FLOAT_BLOCKS) == OBS_CARDS

# The observation layout a network is built for (saved with it): a network saved for an older
# one is adapted at load time (`adapt`). Version 1 is everything before 2026-10-30.
OBS_LAYOUT = {k: L[k] for k in ("OBS_VERSION", "MINION_F", "ITEM_F", "GLOBAL_F", "OPP_F")}
V1_LAYOUT = {"OBS_VERSION": 1, "MINION_F": 31, "ITEM_F": 40, "GLOBAL_F": 53, "OPP_F": 9}

# The card table: what each card is, from TavernGym's card data (rebuilt at every load, so a
# patched card reads as it is now and a new one doesn't start from nothing). Fixed width.
CARD_KINDS = ["minion", "tavern_spell", "spell", "hero", "hero_power", "trinket_lesser",
              "trinket_greater", "dark_gift", "quest", "quest_reward"]
CARD_RACES = ["BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC", "PIRATE",
              "QUILBOAR", "UNDEAD", "ABERRATION", "NAGA", "ALL"]
CARD_MECH = ["BATTLECRY", "DEATHRATTLE", "START_OF_COMBAT", "END_OF_TURN", "AVENGE", "RALLY",
             "CHOOSE_ONE", "DISCOVER", "AURA", "MAGNETIC", "ACTIVATE"]
CARD_KW = ["TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS", "STEALTH",
           "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE", "IMMUNE_ATTACKING"]  # Kw::NAMES
CARD_F = len(CARD_KINDS) + 2 * len(CARD_RACES) + len(CARD_MECH) + len(CARD_KW) + 6 + 3


def card_table():
    """(N_CARDS + 1, CARD_F) float32: row 1 + cid is that card (row 0: no card)."""
    t = np.zeros((N_CARDS + 1, CARD_F), np.float32)
    from advisor import meta
    public = {**meta.trinket_stats(), **meta.hero_stats()}
    for c in json.loads(taverngym.catalog_json()):
        row = t[c["cid"] + 1]
        i = 0
        for names, have in ((CARD_KINDS, [c["kind"]]), (CARD_RACES, c.get("races") or []),
                            (CARD_MECH, c.get("mech") or []), (CARD_KW, c.get("keywords") or [])):
            for j, n in enumerate(names):
                row[i + j] = n in have
            i += len(names)
        row[i:i + 6] = [(c.get("tier") or 0) / 7, (c.get("cost") or 0) / 10,
                        np.log1p(max(0, c.get("atk") or 0)) / 4, np.log1p(max(0, c.get("hp") or 0)) / 4,
                        bool(c.get("normal_id")), bool(c.get("in_pool"))]
        i += 6
        # Added later, at the end (`adapt` widens older networks there): the minion types a
        # trinket, hero or spell goes with
        for j, n in enumerate(CARD_RACES):
            row[i + j] = n in (c.get("assoc") or [])
        i += len(CARD_RACES)
        # Public play data (advisor.meta, Firestone): a trinket's or hero's average placement
        # (4.5 = average) and how often it's picked when offered; known or not
        s = public.get(c["id"])
        if s:
            row[i:i + 3] = [(4.5 - s["place"]) / 0.5, s.get("pick") or 0.0, 1.0]
    return t


class EntityNet(nn.Module):
    """Tokens: global (the global, Quest and pending-kind floats), the card-only slots (hero,
    Hero Powers, Deity, pending source, Quests, Secrets, trinkets), warband, hand, Tavern,
    choices, opponents (hero + leaderboard floats) and their last seen warbands."""

    def __init__(self, card_dim=64, d=128, layers=3, heads=4, arch="entity"):
        super().__init__()
        self.config = {"arch": "entity", "card_dim": card_dim, "d": d, "layers": layers,
                       "heads": heads}
        self.cards = nn.Embedding(N_CARDS + 1, card_dim, padding_idx=0)
        # What the card is (the card table), added to its learned embedding; zero at first, so
        # a network from before the table plays exactly as it did
        self.register_buffer("card_table", torch.from_numpy(card_table()), persistent=False)
        self.card_proj = nn.Linear(CARD_F, card_dim)
        nn.init.zeros_(self.card_proj.weight)
        nn.init.zeros_(self.card_proj.bias)
        self.glob = nn.Linear(GLOBAL_ALL, d)
        self.misc = nn.Linear(card_dim, d)
        self.proj = nn.ModuleDict({n: nn.Linear(card_dim + k, d) for n, _, k in FLOAT_BLOCKS})
        self.n_tokens = 1 + N_MISC + N_TRINKETS + sum(n for _, n, _ in FLOAT_BLOCKS)
        self.pos = nn.Parameter(torch.randn(self.n_tokens, d) * 0.02)
        layer = nn.TransformerEncoderLayer(d, heads, 2 * d, dropout=0.0, batch_first=True,
                                           norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.out_norm = nn.LayerNorm(d)
        self.trunk = nn.Sequential(nn.Linear(2 * d, 2 * d), nn.ReLU())
        self.global_head = nn.Linear(2 * d, 6)  # end, refresh, freeze, upgrade, Dark Gift, cancel
        self.v = nn.Linear(2 * d, 1)
        self.power_head = nn.Linear(d, 1)
        self.buy_head = nn.Linear(d, 1)
        self.sell_head = nn.Linear(d, 1)
        self.activate_head = nn.Linear(d, 1)
        self.choose_head = nn.Linear(d, 1)
        self.play_head = nn.Linear(d, L["N_POS"])
        self.mag_q = nn.Linear(d, d)
        self.mag_k = nn.Linear(d, d)
        self.move_head = nn.Linear(d, N_BOARD)
        with torch.no_grad():  # as PolicyNet: a new network starts unlikely to move minions
            self.move_head.bias.fill_(-3.0)
        # Token ranges: global at 0, then the card-only slots, then the float blocks
        self.at = {}
        i = 1
        for name, n in (("misc", N_MISC), ("trinkets", N_TRINKETS)):
            self.at[name] = (i, i + n)
            i += n
        for name, n, _ in FLOAT_BLOCKS:
            self.at[name] = (i, i + n)
            i += n

    def forward(self, features, cards, mask):
        features = torch.sign(features) * torch.log1p(features.abs())
        cards = cards.clamp(0, N_CARDS)
        emb = self.cards(cards) + self.card_proj(self.card_table[cards])
        b = features.shape[0]
        # Card slots in observation order: misc, warband, hand, Tavern, choices, trinkets,
        # opponent heroes, opponent warbands
        spans, c = {}, 0
        for name, n in [("misc", N_MISC)] + [(n, k) for n, k, _ in FLOAT_BLOCKS[:4]] + \
                [("trinkets", N_TRINKETS)] + [(n, k) for n, k, _ in FLOAT_BLOCKS[4:]]:
            spans[name] = (emb[:, c:c + n], cards[:, c:c + n])
            c += n
        toks = [self.glob(features[:, :GLOBAL_ALL])[:, None],
                self.misc(spans["misc"][0]), self.misc(spans["trinkets"][0])]
        empties = [torch.zeros(b, 1, dtype=torch.bool, device=features.device),
                   spans["misc"][1] == 0, spans["trinkets"][1] == 0]
        f = GLOBAL_ALL
        for name, n, k in FLOAT_BLOCKS:
            x = features[:, f:f + n * k].reshape(b, n, k)
            f += n * k
            e, cc = spans[name]
            toks.append(self.proj[name](torch.cat([e, x], dim=2)))
            empties.append((cc == 0) & (x.abs().sum(2) == 0))
        h = torch.cat(toks, dim=1) + self.pos
        empty = torch.cat(empties, dim=1)
        h = self.out_norm(self.encoder(h, src_key_padding_mask=empty))
        live = (~empty).float()[..., None]
        pooled = (h * live).sum(1) / live.sum(1).clamp(min=1)
        z = self.trunk(torch.cat([h[:, 0], pooled], dim=1))

        def seg(name):
            a, b_ = self.at[name]
            return h[:, a:b_]

        board, hand = seg("board"), seg("hand")
        g = self.global_head(z)
        powers = seg("misc")[:, 1:1 + L["N_POWERS"]]
        magnetize = torch.einsum("bhd,btd->bht", self.mag_q(hand), self.mag_k(board))
        logits = torch.cat([
            g[:, :4],                                          # 0-3 end, refresh, freeze, upgrade
            self.power_head(powers).squeeze(2),                # 4-5 Hero Powers
            g[:, 4:6],                                         # 6-7 Dark Gift, cancel
            self.buy_head(seg("shop")).squeeze(2),             # 8-15 buy Tavern slot
            self.sell_head(board).squeeze(2),                  # 16-22 sell
            self.activate_head(board).squeeze(2),              # 23-29 Activate
            self.choose_head(seg("choice")).squeeze(2),        # 30-45 choose option
            self.play_head(hand).flatten(1),                   # 46-125 hand card x position
            magnetize.flatten(1) / h.shape[2] ** 0.5,          # 126-195 hand card x warband
            self.move_head(board).flatten(1),                  # 196-244 minion x position
        ], dim=1)
        return logits.masked_fill(~mask, -1e9), self.v(z).squeeze(1)


ARCHS = {"mlp": PolicyNet, "entity": EntityNet}


def make(config=None):
    """A new network from a checkpoint's config (an old one without "arch" is the MLP)."""
    config = dict(config or {"arch": "mlp"})
    return ARCHS[config.get("arch", "mlp")](**config)


def save(net, path, extra=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"config": net.config, "state": net.state_dict(), "obs": OBS_LAYOUT,
                **(extra or {})}, path)


def adapt(state, old, new=OBS_LAYOUT):
    """An entity network's weights for observation layout `old` made to read layout `new`:
    each layout's additions sit at the end of a block (obs.rs), so the input layers get zero
    weights for them there and the network computes exactly what it did. In place; returns
    `state`."""
    def widen(key, cuts):  # cuts: [(position in the old input, columns to insert)]
        w = state[key]
        parts, prev = [], 0
        for at, n in cuts:
            parts += [w[:, prev:at], w.new_zeros(w.shape[0], n)]
            prev = at
        state[key] = torch.cat(parts + [w[:, prev:]], dim=1)
    gm, gi, gg, go = (new[k] - old[k] for k in ("MINION_F", "ITEM_F", "GLOBAL_F", "OPP_F"))
    w = state.get("card_proj.weight")
    if w is not None and w.shape[1] < CARD_F:  # a card table that has grown since (at its end)
        state["card_proj.weight"] = torch.cat([w, w.new_zeros(w.shape[0], CARD_F - w.shape[1])], 1)
    if gg:
        widen("glob.weight", [(old["GLOBAL_F"], gg)])
    for name, extra in (("board", gm), ("oppb", gm), ("hand", gi), ("shop", gi),
                        ("choice", gi), ("opp", go)):
        if extra:
            widen(f"proj.{name}.weight", [(state[f"proj.{name}.weight"].shape[1], extra)])
    return state


def load(path, device="cpu"):
    """A saved network on `device`, adapted when it was built for an older observation layout
    (`ck["adapted"]` then holds the layout it had; its optimizer state no longer fits)."""
    ck = torch.load(path, map_location=device, weights_only=False)
    net = make(ck["config"]).to(device)
    state = ck["state"]
    old = ck.get("obs", V1_LAYOUT)
    grown = "card_proj.weight" in state and state["card_proj.weight"].shape[1] < CARD_F
    if old != OBS_LAYOUT or grown:
        if ck["config"].get("arch") != "entity":
            raise ValueError(f"{path}: an MLP built for observation layout {old} can't be adapted")
        state = adapt(dict(state), old)
        ck["adapted"] = old
    missing, unexpected = net.load_state_dict(state, strict=False)
    if unexpected or any(not k.startswith("card_proj.") for k in missing):
        raise ValueError(f"{path}: weights don't fit ({missing}, {unexpected})")
    net.eval()
    return net, ck


def observe(g, seat):
    """(features, cards, mask) arrays of `seat` in TavernGym game `g`."""
    f, c = g.observe(seat)[:2]
    mask = np.frombuffer(g.legal_mask(seat), dtype=np.uint8).astype(bool)
    return (np.frombuffer(f, dtype="<f4").copy(), np.frombuffer(c, dtype="<i4").copy(), mask)


@torch.no_grad()
def act(net, g, seat=0, allowed=None, device="cpu"):
    """The network's most likely action (restricted to `allowed` when given) and its
    probabilities over the legal actions."""
    f, c, m = observe(g, seat)
    if allowed is not None:
        m = m & allowed
    logits, value = net(torch.from_numpy(f)[None].to(device), torch.from_numpy(c)[None].to(device),
                        torch.from_numpy(m)[None].to(device))
    p = torch.softmax(logits[0], 0).cpu().numpy()
    return int(p.argmax()), p, float(value[0])
