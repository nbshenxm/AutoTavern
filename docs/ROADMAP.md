# Battlegrounds advisor: plan

Goal: advice in HDT during the recruit phase of a Battlegrounds game: what to buy, sell, play,
when to level and refresh, and how to order the warband, from a policy trained in TavernGym.

"Usable" means: within about a second of each recruit decision, the overlay shows a recommended
action (and the next few). It reads only Power.log. It never acts for the player.

## Architecture

Like the constructed advisor (D:\GitHub\Hearthstone_AI_Advisor):

- **HDT plugin** (C#, net472, WPF overlay): starts the advisor process, polls its advice file,
  draws the overlay. It is its own plugin (`TavernAdvisor`), separate from the constructed one.
- **Advisor process** (Python, `taverngym` conda env): follows the newest Power.log. At each
  recruit decision it rebuilds the state in TavernGym, asks the policy, and writes the advice.
- **Policy**: the scripted bot first (v0), then the trained network (PPO).

## Milestones

**M0. Simulator and checks (done 2026-10-29).** TavernGym builds at home. The 37.0 client diff
shows no Battlegrounds changes. Logged combats replay with 92.5-95% agreement
([REPLAY.md](REPLAY.md)).

**M1. Recruit-phase fidelity.** Check the logged recruit phases against TavernGym's rules: shop
size and Tier odds per Tavern Tier, gold per turn, upgrade costs and discounts, refresh cost,
tavern spells offered, triple rewards. The source is the logged offers and the players' gold and
tags. Done when every rule is either confirmed or fixed, or the gap is written down.

**M2. Live bridge.** Power.log → TavernGym game at each friendly recruit decision: hero, health,
armor, tier, gold, upgrade cost, board, hand, shop (frozen or not), trinkets, quests, the
counters from M0, opponents' heroes, health, tiers and last seen warbands. The rest of the
lobby is unseen, so the bridge fills it with consistent stand-ins.
Test: at every logged decision, the actions the client offered (the Options packets) match
TavernGym's legal mask. Report the agreement rate and the mismatches by kind.

**M3. Advisor v0, end to end.** Advisor process with the scripted bot as its policy, plus
combat odds from TavernGym. Weak advice, but it exercises the whole path: Power.log → state →
policy → advice file. Done when a recorded game, replayed through the advisor, produces advice
at every decision, under a second each.

**M4. HDT plugin.** Overlay, settings file, install script, restart-on-crash, a hotkey to flag
bad advice. Done when it runs through a real game with the user. This is the first usable
version.

**M5. Training.** PPO self-play in TavernGym: an entity network over the card indices plus the
global features, trained against the scripted bots first, then against itself and earlier
versions. The gate: mean placement against seven bots and against the previous best, on fresh
seeds. Runs longer than an hour go to the office machine (shared with the constructed PPO) or to
the cluster (1 GPU job for this track). Each promoted network replaces the advisor's policy. The
first goal is to clearly beat the bots (mean placement under 3.0); after that, the user's own
games are the test.

**M6. Patch pipeline.** For each patch: `tools/client_diff.py`, new cards into `cards.json`
(the 36.6.1 resource bundle can't take them, so they come from HearthstoneJSON directly),
scripts for new cards, the replay test, retraining or a fine-tune.

Order: M1 → M2 → M3 → M4, the first usable version. M5 starts once M2's parity holds, since
the live inputs must match what training sees. It runs in the background while M3 and M4 are
built. M6 runs at every patch.

## Status

| Milestone | State |
| --- | --- |
| M0 | done |
| M1 | done: every recruit rule checked agrees ([REPLAY.md](REPLAY.md#recruit-rules)); train with `hero_choices: 4` for the player's seat |
| M2 | done: the whole lobby is built from the log; the player's legal actions match the client's in 89% of decisions ([REPLAY.md](REPLAY.md#live-bridge)) |
| M3 | done: `advisor.live` advises at every recruit decision of a replayed log, under 160 ms ([REPLAY.md](REPLAY.md#live-advisor)); policy = scripted bot |
| M4 | in progress |
| M5-M6 | not started |
