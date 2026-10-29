# Training

```bash
python -X utf8 -m advisor.train --run NAME --minutes 10          # home: short runs only
ssh office 'bash -s' < scripts/office/setup.sh                          # office: pull + build
ssh office "RUN=NAME HOURS=6 THREADS=8 bash -s" < scripts/office/train.sh  # office: run, detached
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

**League.** Every 50 iterations a frozen snapshot joins a pool (the newest 6, kept in
`data/train/NAME/pool`). In training, seats 6 and 7 of every game are played by pool snapshots
(not learned from), so the network keeps meeting its past versions, not only itself; the gate
adds the network on seat 0 against seven pool snapshots (`league` in the log: under 4.5 beats its
past versions). `python -m advisor.train --evaluate CKPT --eval-episodes 1000` runs the bot gate
alone on seeds no training gate uses.

The rules are `advisor.state.GAME_CONFIG`, shared with the live advisor (a network planning
without the cap it learned with would move minions for ever). Two rules keep the games moving: a per-turn action cap a little above the most the player
took in a logged turn (`turn_action_caps`: 8, 8, 12, 12, 20, 40, 40, then 60), and
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
| smoke1 (resumed) | home | +50 min, to iteration 1535 | 50.7M in all (about 21,700 games) | best at iteration 1170: **3.53 ± 0.06 on 1,000 unseen games** (top 4 in 71%); flat around 3.5-3.7 after iteration 800 |
| office1 | office, RTX 4080 (shared), 8 threads | 6 h from 16:45, league from iteration 600 | running | |

**Promoted** (2026-10-29): smoke1 iteration 1170 as `data/models/best.pt`, the first network the
overlay shows ("early network ... place 3.529 vs bots, 1000 games"). It beats the scripted
bots, which is all it has been measured against: an early network, not yet advice to rely on.

Throughput at home: about 22,000-34,000 decisions per second collecting, 2.8 s per iteration
of 33,000 decisions.
