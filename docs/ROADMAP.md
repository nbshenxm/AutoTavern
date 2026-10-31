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
| M2 | done: the whole lobby is built from the log, its minion types inferred from what the Tavern shows; the player's legal actions match the client's in 95.8% of 2,603 logged decisions ([REPLAY.md](REPLAY.md#live-bridge)) |
| M3 | done: advice at every recruit decision, Discover (minions, Tavern spells, Dark Discovery), trinket offer and hero offer; the trained network with plan search and an Arrange step, about 0.1-1.3 s |
| M4 | done: in use in the user's games (constructed-advisor rows with card tiles, middle of the screen, Ctrl+Shift+B flags bad advice); the network synced hourly |
| M5 | in progress ([TRAINING.md](TRAINING.md)): 1.49 against the bots; generations against the frozen best with promotions hourly; hot start, real-warband opponents, search-guided training (the current best), a larger network being distilled. The gap: late-game scaling against real lobbies (the progress page's strength curve) |
| M6 | not started |

## Releases (from 2026-10-31)

Improvement doesn't get an open-ended budget: a release goes out **every day at 20:00** with
whatever is best then, and strength has dated targets. A release is a git tag (`bg-rN`), the
overlay build installed, the network it runs, and a short note in [RELEASES.md](RELEASES.md):
what changed, the numbers below, the known faults. A day where no network beat the last one
still ships (advice and overlay fixes) and says so.

Every training idea gets one office window (8-12 hours) and a bar fixed before it starts; it
clears the bar or is stopped, no extensions. A missed target means a change of approach, not
another round of the same: first in line is what the network learns from (self-play opponents
that scale like real lobbies all game, not only stronger library seats).

The numbers (all on the progress page): **late** = the network's late-game warband (rounds
10-13) against your lobbies' (curve, median ratio); **real** = mean placement from your logged
positions (vs_best_real); **Gold left** = rounds 13+ (compare_play); **on-type** = minion buys
of the warband's main type, rounds 10+; **your games** = placement and how often you followed
the advice (advisor.usefulness).

| Release | Date | Target | State |
| --- | --- | --- | --- |
| R1 | Oct 31 | next-step display, trinket offers and picks, audit fixed; the 18:21 network (late 0.19, real 2.56, Gold left 9.2, on-type 40%) | |
| R2 | Nov 1 | late >= 0.25, real < 2.50 | |
| R3 | Nov 2 | late >= 0.30, real < 2.45, Gold left <= 6 | |
| R4 | Nov 3 | late >= 0.40, on-type >= 50% | |
| R5 | Nov 4 | late >= 0.50; your games: 5+ played with it, measured | |
