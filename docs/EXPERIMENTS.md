# Experiments

Every experiment, newest last: what was tried, how it was measured, what it showed and what was
decided (the constructed track's discipline: a row before acting on a result). Mean placements are
against seven scripted bots unless said otherwise (bots against bots: 4.5); ± is one standard
error unless marked.

| Date | What | Result | Decision |
| --- | --- | --- | --- |
| 2026-10-29 | Combat replay of 106 logged combats (`advisor.replay`), before / after carrying player counters (Tasty Lobster, Undead, Beetles, Eternal Knight) | most likely result = logged: 90% / 92.5% (start), 91% / 95% (attack); Brier 0.073 / 0.045, 0.069 / 0.038 | counters carried; the simulator is trusted for combat |
| 2026-10-29 | Recruit rules against 110 logged turns (`advisor.recruit_checks`) | Gold, upgrade and refresh costs, Tavern sizes, Tier mix, trinket timing all agree; exceptions are effects TavernGym models | rules trusted; train with `hero_choices: 4` |
| 2026-10-29 | Live bridge: TavernGym's legal actions vs the client's options at 1,870 logged decisions | identical sets 89% → 94% after carrying Lockbox locks, spent Hero Powers, Dark Discovery use, Malchezaar's and Bazaar Sticker's uses, Spirit Swap mid-use; Methodical Madness fixed in TavernGym | the live advice is masked by the client's options too |
| 2026-10-29 | An untrained policy in TavernGym | chose "move minion" 99.8% of the time; no game ended | per-turn action caps from the player's logged turns; new networks biased away from moves |
| 2026-10-29 | MLP PPO at home, 10 + 50 min (`smoke1`) | 7.97 → 5.52 (10 min) → best 3.53 ± 0.06 on 1,000 unseen games; flat 3.5-3.7 after iteration 800 | promoted (first network in the overlay) |
| 2026-10-29 | Entity network vs MLP at equal minutes (`entity1`, 30 min) | entity 3.3 at 10 min (MLP 5.8); best 3.30 ± 0.05 on 1,000 games; later worse as entropy rose 2.4 → 3.0 | promoted; entropy and learning rate lowered |
| 2026-10-29 | Entity network, lr 1e-4, entropy 0.0025 (`entity2`, 30 min) | steady, entropy flat 2.3-2.5; 3.15-3.24 | the office run's settings |
| 2026-10-29 | BG training beside the constructed PPO on the office (pause A/B) | constructed PPO 384 → 288 games/s (−25%), the same at 4 or 8 threads | user: keep both; then the office became BG's alone |
| 2026-10-29 | `--amp` (bf16 forward in updates) on the RTX 4080 | update 14.5 → 8.9 s per 66k decisions | on |
| 2026-10-29 | A real game: does the network buy an affordable triple? | 1 of 5 chances, never as the first step | Tavern minions now flag pair / triple in the observation; office2 restarted with it |
| 2026-10-29 | `office2` (entity, triple flags, 256 games, 66k batches), first 2 hours | 2.62 at iteration 100, 2.32 at 280; league (vs its past snapshots) 3.6-4.0 | promoted at iteration 150 (2.49 ± 0.05 on 1,000 games) |
| 2026-10-29 | Plan search at advice time vs the network's own choice (`advisor.search_eval`, 200 paired games, k = 8) | running | |
| 2026-10-29 | Scripted bots steered to HSReplay meta comps (buy/keep/discover bonus for a comp's core and add-on cards; then also freeze and refresh for them), 400 bot games, half the seats with a comp | 4.51 vs 4.49 without a comp; with freeze/refresh 4.59 vs 4.42; comp seats end with 11-12% of their core cards (they're tier 4-6) | dropped; the comp guides only feed the overlay's "closest meta comp" note |
| 2026-10-29 | Why the advice rarely refreshes: the promoted network on seat 0 vs bots, 30 games | moves are over half its actions (turn 8: 568 of ~1,000); 45-70% of its turn ends on turns 2-8 are forced by the action cap; from turn 10 it ends turns with 3-9 gold while Refresh is legal (refreshes per turn 1.5 at turn 6, 0.06 at turn 15; bots 5) | `moves_per_turn` 7 outside the action budget; reward −0.003 per gold left when Refresh was legal and the Tavern unfrozen; `office3` resumes `office2` under them |
