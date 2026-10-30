# Training

```bash
python -X utf8 -m advisor.train --run NAME --minutes 10          # home: short runs only
ssh office 'bash -s' < scripts/office/setup.sh                          # office: pull + build
ssh office "RUN=NAME HOURS=6 THREADS=10 EXTRA='...' bash -s" < scripts/office/train.sh   # detached
```

Results of every experiment are in [EXPERIMENTS.md](EXPERIMENTS.md); the plain-words state of
things in [STATUS.md](STATUS.md); the numbers over time on the progress page
(`data/report.html`, `advisor.report`).

## The network

`advisor.policy.EntityNet` (0.86M parameters): a token per card slot (its learned card embedding
plus the card table, with that slot's floats: stats, keywords, types, counters, prices) and a
global token, a 3-layer transformer, and pointer heads: an action on a Tavern, hand or warband
slot is scored from that slot's token; a value head.

- **The card table** (`card_table`): what each card is, from TavernGym's card data, rebuilt at
  every load: kind, minion types, printed mechanics (Battlecry, Deathrattle, Avenge, Rally...),
  keywords, Tier, cost, stats, the types a trinket or hero goes with, and a trinket's public
  average placement and pick rate (Firestone, `advisor.meta`). It is added to the embedding
  through zero-initialized weights.
- **Observation layout** (`taverngym.layout()`, obs.rs). Version 2 (2026-10-30) added a minion's
  counter, the turn's actions and moves left, the damage cap, streak and last damage, and how
  old each opponent's last seen warband is. A network saved for an older layout or a narrower
  card table is adapted at load (`policy.adapt`: zero weights for what is new): it computes
  exactly what it did, then learns to use the rest.

## PPO

`advisor.train`: TavernGym's batched environment, every seat's decisions in trajectories (GAE,
gamma 0.995, lambda 0.95), the placement reward (1st = 1, 8th = -1), updates in chunks of 1,024
rows (same step, less GPU memory), bf16 with `--amp`. A non-finite step is skipped. The rules
are `advisor.state.GAME_CONFIG`, shared with the live advisor: `turn_action_caps` (8, 8, 12, 12,
20, 40, 40, then 60 actions a turn), moves outside that budget at most 7 a turn
(`moves_per_turn`), `hero_choices` 4. Ending a turn with gold while a Refresh is possible and
the Tavern unfrozen costs 0.003 reward per gold. It waits while Hearthstone runs (home).

Opponents and extras, by option:

- **`--generations`**: seats 4-6 of every game are the frozen current best (`data/models/best.pt`,
  reloaded when a promotion replaces it), seat 7 an archived earlier best, the learner the other
  four. The run's `best.pt` is the network that placed best against the current best.
- **`--library 6 7`**: those seats fight with real warbands from the logs (library seats,
  `advisor.library`: both sides of every logged combat as TavernGym minions, the round and Tier
  kept; the home sync rebuilds them after new games and the run takes them up). Tested each
  time against the best plus two library seats (`vs_library`).
- **`--search-data DIR...`**: also learn the plan search's choices: 0.2 x the cross-entropy to the
  newest 200,000 searched decisions (`advisor.search_games` makes them on the office's CPUs).
- **`--anchor CKPT`, `--anchor-best COEF`, `--critic-warmup N`**: stay near a checkpoint (KL,
  fading) or near the current best; train only the value first (after a hot start).
- **`--trinket-prior COEF`**: pull trinket picks toward the public preference. Off: the
  public averages lose to the network's own picks in the simulator (EXPERIMENTS.md).

**Hot start.** `advisor.pretrain` trains a network to copy the teacher bot (`teacher.rs`, the
player's strategy: leveling curve, Dark Gifts, triples, spending all gold, meta comps) before
PPO; `teachppo1`, PPO from it in generations, made the best networks of Oct 30.

## Promotion

Hourly on the office (`scripts/office/promote.sh` → `advisor.promote`), every run's `best.pt`:

1. against seven plain bots on 1,000 unseen seeds: not clearly worse than the current network
   (measured again whenever the rules or the simulator build change);
2. one seat against seven copies of the current network, 1,000 games: clearly under 4.5, then
   again on 1,000 fresh seeds (a winner of many judged candidates is partly luck); **or**
3. in lobbies with two library seats: clearly better than the current network on the same
   seeds, twice, and not clearly worse head to head (the bots' floor with 0.1 places to spare).

The replaced network goes to `data/models/archive/`; every decision is in
`data/models/promotions.jsonl`.

## Keeping things going

- **Office supervisor** (cron, every 20 minutes, `scripts/office/supervise.sh`): the runs in
  `data/overnight.conf` (`RUN|END|THREADS|EXTRA`) are restarted from their `last.pt` when they
  crashed or logged nothing for 30 minutes before their end.
- **Training processes** take at most 40% of the GPU each (`--gpu-memory`); the promotion uses
  the CPU when the GPU is full. Two training runs fit the office's 30 GB of RAM, not three.
- **Home sync** (scheduled task "TavernAdvisor Model Sync", hourly at :20,
  `scripts/sync_model.ps1`): the promoted network, the training logs for the progress page,
  and, while Hearthstone is closed, the library rebuilt from new logs and sent to the office.
  Log: `%LOCALAPPDATA%\TavernAdvisor\sync.log`.
- **The live advisor** reloads `data/models/best.pt` when it changes.

## History

Day one (2026-10-29): the MLP (smoke1, 3.53 against the bots), the entity network (3.30 in 10
minutes), `office2` (self-play, 2.49 → 2.08). Day two: generations, the hot start (`teach1` →
`teachppo1`, promoted at 05:23, 09:25 and 10:21: 1.52 against the bots), library seats (`lib1`),
search-guided training (`search2`). Every row with numbers is in EXPERIMENTS.md.
