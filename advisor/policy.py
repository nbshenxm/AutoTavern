"""The policy network over TavernGym observations, shared by training (advisor.train) and the
live advisor.

Input: the 3,227 observation floats (signed log) and the 124 card indices (taverngym.layout);
each card slot gets an embedding, concatenated with the floats, then an MLP with a policy head over the
245 actions (illegal ones masked out) and a value head (expected placement reward, -1..1).
"""

from pathlib import Path

import numpy as np
import torch
from torch import nn

from taverngym import N_ACTIONS, N_CARDS, OBS_CARDS, OBS_FLOATS

A_MOVE = 196  # taverngym.layout()


class PolicyNet(nn.Module):
    def __init__(self, card_dim=32, hidden=1024):
        super().__init__()
        self.config = {"card_dim": card_dim, "hidden": hidden}
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


def save(net, path, extra=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"config": net.config, "state": net.state_dict(), **(extra or {})}, path)


def load(path, device="cpu"):
    ck = torch.load(path, map_location=device, weights_only=False)
    net = PolicyNet(**ck["config"]).to(device)
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
