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
| office1 | office, RTX 4080 (shared), 8 threads | 6 h from 16:45, league from iteration 600 | running | about 4.0 vs bots and 4.3-4.4 in the league by iteration 800 |
| entity1 | home, `--arch entity` | 30 min, 160 iterations | about 5M | best at iteration 70: **3.30 ± 0.05 on 1,000 unseen games** (top 4 in 76%) after 10 minutes; then worse (4.9 at 30 min) while the entropy rose 2.4 → 3.0 |
| entity2 | home, `--arch entity --lr 1e-4 --ent 0.0025` | 30 min | running | |

The entity network learns far faster for the time: at equal minutes the MLP was at 5.8 (10
min), 4.8 (15), 4.4 (20) and 3.8 (30). Its update costs more (3.8 s against 0.6 s per
iteration), its collection the same.

**Promoted** (2026-10-29): first smoke1 iteration 1170 (MLP, 3.53), then entity1 iteration 70
(entity network, 3.30; live advice 109 ms median) as `data/models/best.pt`; the MLP is kept as
`best_mlp_smoke1_it1170.pt`. Both beat the scripted bots, which is all they have been measured
against: early networks, not yet advice to rely on.

Throughput at home: about 22,000-34,000 decisions per second collecting, 2.8 s per iteration
of 33,000 decisions.

## Keeping the overlay's network current

1. **Office, hourly at :10** (user crontab): `scripts/office/promote.sh` runs `advisor.promote`
   on every run's `best.pt`. Each candidate plays the bot gate on the same 1,000 unseen seeds as
   the current network and replaces `data/models/best.pt` only when its mean placement is lower
   by more than twice the combined standard error (about 0.15 at present). Replaced networks go
   to `data/models/archive/`; every decision is in `data/models/promotions.jsonl`
   (`promote.log` holds the output); a checkpoint is judged once per version.
2. **Home, hourly at :20** (scheduled task "TavernAdvisor Model Sync"): `scripts/sync_model.ps1`
   copies the office's `best.pt` and `promotions.jsonl` into this repository's `data/models`
   when they changed (the old network archived). Log: `%LOCALAPPDATA%\TavernAdvisor\sync.log`.
   Remove: `Unregister-ScheduledTask -TaskName "TavernAdvisor Model Sync" -Confirm:$false`.
3. **The advisor** reloads `data/models/best.pt` whenever the file changes, mid-session too.
