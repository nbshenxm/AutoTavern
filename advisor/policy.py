"""The policy networks over TavernGym observations, shared by training (advisor.train) and the
live advisor. Both take the 3,227 observation floats (signed log) and the 124 card indices
(taverngym.layout) and give logits over the 245 actions (illegal ones masked out) and a value
(expected placement reward, -1..1).

- "mlp" (PolicyNet): every card slot's embedding concatenated with the floats, an MLP.
- "entity" (EntityNet): a token per card slot (its card embedding with its own stats) and a
  global token, a transformer over them, and pointer heads: an action on a Tavern, hand or
  warband slot is scored from that slot's token.
"""

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

class EntityNet(nn.Module):
    """Tokens: global (the global, Quest and pending-kind floats), the card-only slots (hero,
    Hero Powers, Deity, pending source, Quests, Secrets, trinkets), warband, hand, Tavern,
    choices, opponents (hero + leaderboard floats) and their last seen warbands."""

    def __init__(self, card_dim=64, d=128, layers=3, heads=4, arch="entity"):
        super().__init__()
        self.config = {"arch": "entity", "card_dim": card_dim, "d": d, "layers": layers,
                       "heads": heads}
        self.cards = nn.Embedding(N_CARDS + 1, card_dim, padding_idx=0)
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
        emb = self.cards(cards)
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
    torch.save({"config": net.config, "state": net.state_dict(), **(extra or {})}, path)


def load(path, device="cpu"):
    ck = torch.load(path, map_location=device, weights_only=False)
    net = make(ck["config"]).to(device)
    net.load_state_dict(ck["state"])
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
