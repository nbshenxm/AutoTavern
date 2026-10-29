# Training

```bash
python -X utf8 -m advisor.train --run NAME --minutes 10          # home: short runs only
python -X utf8 -m advisor.train --run NAME --hours 4 --resume data/train/NAME/last.pt
bash scripts/office/setup.sh && bash scripts/office/train.sh   # the office machine
```

`advisor.train` is PPO self-play: TavernGym's batched environment with all eight seats
played by the current network (`advisor.policy.PolicyNet`: an embedding per card slot plus the
observation floats through a signed log, an MLP, a policy head over the 245 actions with
illegal ones masked, a value head; 8.1M parameters). A seat's episode ends with the placement
reward (1st = 1, 8th = -1); seats act asynchronously, so each keeps its own trajectory (GAE,
gamma 0.995, lambda 0.95). Every 10 iterations the greedy network plays seat 0 against seven
scripted bots on fresh seeds: mean placement over 200 games (bots against bots: 4.5).
Checkpoints: `data/train/NAME/last.pt` (resumable) and `best.pt` (best gate result). It waits
while Hearthstone runs.

Two rules keep the games moving: a per-turn action cap a little above the most the player
took in a logged turn (`CONFIG["turn_action_caps"]`: 8, 8, 12, 12, 20, 40, 40, then 60), and
a new network starting unlikely to move minions (49 of the 245 actions are moves, which never
advance the game: an untrained policy chose them 99.8% of the time and no game ended).
`hero_choices` is 4, the player's offer.

**Promotion.** The live advisor uses `data/models/best.pt` when it exists and the scripted
bot otherwise. Copy a network there only when its gate result beats the bots (mean placement
clearly under 4.5; the first target is under 3.0) on 1,000 fresh games.

## Runs

| Run | Where | Length | Decisions | Gate (mean placement vs bots) |
| --- | --- | --- | ---: | --- |
| smoke1 | home, RTX 5090, 8 threads | 10 min, 211 iterations | 7.0M (about 4,100 games) | 7.97 untrained → 5.52, top 4 in 27.5%; still falling |

Throughput at home: about 22,000-34,000 decisions per second collecting, 2.8 s per iteration
of 33,000 decisions.
