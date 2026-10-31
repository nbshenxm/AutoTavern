# Status

A running note, in plain words: what changed, what is wrong, what comes next. The progress page
(`data/report.html`, `advisor.report`) shows it with the numbers. The plan is
[ROADMAP.md](ROADMAP.md); measurements go to [EXPERIMENTS.md](EXPERIMENTS.md).

## Morning (Oct 31): the late-game Gold problem, measured and traced

- **The audit had a blind spot, now fixed.** "Ended the turn with spendable Gold" was read after
  the plan's End Turn, when nothing is legal, so it never fired. Fixed: across your 13 games 228
  plans end with 3+ spendable Gold, 218 in rounds 11-15, mostly "Freeze -> End turn" with 8-10
  Gold. Still no rule broken (the 1 crash and 2 detours the rerun first showed were the same
  replay bug: a run of moves was replayed as its last move only). The promotion audit now counts
  it, plus the review's other rules.
- **Spending would help, in the simulator too.** From your round-8+ positions against top-1%
  seats, forcing the network to spend 3+ Gold before ending every turn places it 0.10 +- 0.04
  better. So it's the network that hasn't learned it, not the simulator.
- **Why training didn't fix it:** the runs imitate plan-search data made with the 18:21 best
  (they agree with it 92% of the time), and that data has its habits: 6% Freeze (you 0.6%),
  5.5% Refresh (you 18%), 30% of End Turns with 3+ spendable Gold. Both runs' best checkpoints
  still refresh 0.25-0.3 times a turn in rounds 13+ (you 4.3) and end with 8-9 Gold.
- **Changed at 07:35:** big2 keeps the search data without those idle End Turns
  (`--search-drop-idle`); sig1 drops the search data entirely. No more search data from the old
  best. Watch: rounds-13+ Refreshes and Gold left (advisor.compare_play) and promotions.

## Overnight (Oct 30-31)

- **Where it stands.** Mechanically the advice is clean: re-checked on every logged position of
  your 13 games, no rule is broken. In strength it is weak from round 10 (see the bottom line on
  the progress page); the training below aims there. No network has beaten the 18:21 one yet.
- **Your turns against the network's** (rounds 7+, same positions): it buys more and off-type
  (30-50% of its buys fit the warband, yours 62-73%), levels less mid-game (0.07 vs 0.33 a turn),
  and late it refreshes far less (0.5 vs 4.3 a turn), freezes and ends with 9 Gold (you 4.7).
- **Fixed and sent to training:** freezing no longer dodges the unspent-Gold cost; no second Freeze
  straight after one (a no-op that was most of the network's 7% Freeze presses); half of new games
  start from your positions (rounds 7+ weighted 15x); comp starts weighted to the genres it plays
  worst; per-turn action caps up to 100; forced exploration of Refresh and Upgrade in sig1;
  big2's learning rate halved (its steps were too large).
- **Audit tools now run by themselves after every game:** the advice review, the simulator checks
  against a baseline, your habits against the network's, the genre scorecard; the progress page
  opens with the bottom line and an audit section.
- **Overlay:** lineup panel (one card per line, stats and keywords), genre panel (3 genres, a share
  each, the cards they need), no network name; installed.

## Today (Oct 30), afternoon

- **Why the network falls behind late, found.** Started from your own position at the start
  of round 10, the network fills the board and then stalls: by round 13 it freezes and ends the
  turn with 14 gold and four cards in hand, where you kept scaling (an Unbound Tempest 418 →
  706 → 1,447). From round 6 it keeps up with you for two rounds. The scripted teacher bot
  levels as fast as real players and still has only 590 Attack+Health at round 13. Self-play
  games never reach a real late game, so the network never learned one.
- **Training from your positions.** A share of new training games (30% in `big2`) now start
  where you stood at the start of a logged round (168 positions from your 10 games, more with
  every game: the home sync sends them). A new number, `vs_best_real`, plays the network in your
  seat from every one of them (paired with the best's own result).
- **First result of training from your positions: no change yet, and why.** After ~1.5 hours
  big2 still stalls from your round-10 positions. Its own estimate there is that it's winning
  (1st-2nd): the simulated opponents are copies of it and don't scale either, so ending a turn
  with 10 gold costs nothing. Since 18:00 two seats of big2's games also play real warbands from
  your lobbies at that round (library seats), so a late start now meets real late-game strength.
- **Stronger, readable opponents (your suggestion).** Library seats used to show a random
  warband at every combat, so what the network saw of one told it nothing about the next fight.
  Now each library seat follows one player all game: your own warbands of one game, one of your
  opponents as you met them, or one of 19 curated comps from Tavern Link's catalog (poison
  Murlocs, Divine Shield Dragons, Undead...). Their stats are scaled to the top 1% of players by
  round (Firestone: up to 1.7x your lobbies at rounds 7-10). big2 now trains with 3 of them, so
  reading the next opponent's warband and answering it (Venomous, 火车王, Divine Shield) pays.
- **The live advisor ran over all your games** (2,603 decisions, plan search on): no errors,
  median 0.6 s beside a heavy job. Timed again on a quiet PC: median 0.4 s, 95% under 1.0 s,
  the slowest of 2,818 decisions 8.3 s (a 6-minute one in the first run didn't come back).
- **The larger network** (8.6M parameters, distilled from the best) continues as `big2`
  (PPO, search targets, real starts), in `lib2`'s place: the library seats alone didn't help.

## Today (Oct 30), while you were away

- **Trinkets and heroes are advised.** A trinket offer, a Tavern spell Discover and the hero
  offer at the start now get advice (they had none). The overlay lists the offered trinkets or
  heroes by the public average placement of players who picked them (Firestone, the last 7
  days), and the network's card table knows those numbers too.
- **Public trinket averages are not a rule to follow:** picking the publicly best trinket every
  time does 0.6 places worse than the network's own picks in the simulator (players pick the
  trinket that fits their board, so averages flatter fitting picks). The network's picks are
  worth about a place over random ones.
- **Arrange advice.** When the plan ends the turn and the next opponent's warband has been
  seen, the advisor tries other orders of your warband in simulated combats and adds an Arrange
  step when one clearly does better (the network itself rarely rearranges).
- **Four simulator mistakes fixed,** found by comparing the logged attacks of your combats
  with the simulator's: who attacks first with equal warbands (random, not the higher Tier),
  that it's settled after Start of Combat, Dark Gifts the log numbers differently (an
  Admiration's +153 Attack was lost), and rebuilt hands forming triples that hadn't happened.
- **The simulator checked against your own actions:** each logged action replayed on the
  rebuilt state gives exactly the warband the log shows next in 94.5% of 1,550 cases (90.8% at
  first). Fixed on the way: Blood Gem size, Tavern buffs, the Tavern spell bonus and minions'
  "(N left!)" counters weren't carried from the log (an Unbound Tempest fired at the wrong
  time). What remains is mostly random ("a random minion"). So the late-game gap is the
  network's play, not the simulator's rules.
- **More of your games' data used:** gold next turn and the free Refresh count are now read
  from the log; three sessions the first export had missed are in (95.8% of 2,603 logged
  decisions now match the client's options exactly).
- **Strength curve on the progress page:** the network's warbands by round against your lobbies
  and the public average. It keeps up until round 9, then flattens: the main thing to fix.
- **Search-guided training works:** `search2` (learning the plan search's choices besides PPO)
  was promoted at 12:20 (4.22 head to head against the previous best), the first promotion since
  10:21. A larger network (8.6M parameters, was 0.86M) is learning to copy it (`big1`), to
  continue with PPO.

## Today (Oct 30)

- **Case study: why the advice is weak in real games.** In its own games the network stays on
  Tier 1-2 and stacks stats, ahead of real lobbies early (84 vs 56 Attack+Health at round 5) and
  far behind late (963 vs 16,760 at round 13; Tier 4.2 vs 5.8). Nothing in self-play punishes
  it: every opponent is a copy. Your logs' real warbands, by round, are the calibration.
- **Opponents with real warbands (`lib1`).** Two seats of every training game now fight with a
  real warband from your logs for that round (209 so far; every game you play adds about 26).
  In lobbies of the current network such seats place 3.33 on average, the network's own 4.89.
- **Live bridge fixed:** the lobby's five minion types (read from what your Tavern shows), the
  last combat's result, and a stand-in that could leave you in a skipped turn. The network and
  the plan search now see your real lobby.
- **The network sees more (observation version 2).** What each card is, from the card data
  (mechanics, types, Tier, stats: the Hearthstone advisor's card table), a minion's counter, the
  turn's actions left, the damage cap, streaks, how old each opponent's last warband is. Older
  networks load with zero weights for these and play exactly as before, then learn them.
- **The library grows by itself.** After you play, the hourly home sync rebuilds the real
  warbands from your logs (now 295 from 149 combats) and the office's runs take them up.
- **A second way to promotion:** clearly better in lobbies with real warbands (and not worse
  head to head), twice. Real lobbies are what counts.
- `teachppo1` was promoted again at 09:25 (head to head 4.28): the hot-start line still leads.
  The cautious line (`safe1`) didn't gain and made room for `lib1`.

## Overnight results (Oct 30 morning)

- **Your hot start worked.** The line that started by copying your strategy (`teachppo1`) made
  the best network: promoted at 05:23, it beat the previous best head to head (4.22, again 4.20
  on fresh games; 4.5 is even) and places 1.61 against the plain bots. It is in your overlay.
- `gen1` was promoted once (23:24), then got slightly worse than its own promoted copy as it kept
  training (4.9-5.6 head to head). PPO after a promotion wanders: progress isn't steady.
- The search-guided line (`gensearch1`) never beat the best and then broke: a few stored
  decisions had numbers too large for the storage format, which ruined the network. Fixed; the
  test of search-guided training is still open.
- `teachppo1`'s restart at 07:20 (after a crash) put its pull toward the teacher back at full
  strength, which set it back. Fixed; it continues without it.
- Your PC slept from about 23:20, so the overlay only got the new network this morning.

## Latest

- **Search games started.** 12 office cores play games where two seats follow the plan search;
  every searched decision (about 200,000 an hour) is kept as a target. A run can then learn the
  search's choices alongside PPO, the Hearthstone advisor's search-guided training. Ready for
  when generations stop gaining.
- **The hourly promotion had been failing** since about 22:10: the two training runs held 7.8 GB
  of the GPU each, leaving it none. Training now takes at most 40% each (its updates run in
  smaller pieces, the same result), and the promotion falls back to the CPU if needed.
- **Training in generations (`gen1`), like the Hearthstone advisor.** Three seats of every
  training game play the frozen current best, one an earlier best, the learner the other four.
  When a new network clearly beats the best (on one seat against seven copies of it, and again on
  fresh games) it is promoted, and the run then trains against it. It continues `office3`, whose
  last test was 1.71 against the plain bots.
- **A simulator bug that froze tests, fixed.** After a choice took a player past the turn's action
  limit, the game offered a move and then refused it; a network that always plays its first choice
  repeated it forever. Training wasn't affected (it samples), but the tests and the head-to-head
  promotion test could hang. The random-play check of the simulator now covers this setup.
- **Plan search is on in the overlay.** Before advising, the advisor tries 8 other plans for the
  turn and keeps the best. In 200 test games it placed 0.48 better than the network alone
  (1.99 vs 2.47 against seven bots). Advice takes about half a second, at most 1.3 s.
- **Two training habits found and fixed.** The network spent most of its actions moving minions
  around, so the turn's action limit ran out with gold left, and late in the game it stopped
  refreshing. Moves now have their own limit (7 a turn), and training charges a little for gold
  left when a Refresh was possible. The run `office3` continues training under these rules.
- **Hot start from your strategy.** A new scripted player, the teacher, plays your way: Tier 2
  on turn 2, a Dark Gift when the Tavern has nothing good, triples, every gold spent, then the
  meta comp the warband is closest to. It beats the old bot clearly (3.5 vs 5.1 when four of each
  play). The run `teach1` trains a fresh network to copy it; PPO then continues from there.
  But the network in the overlay already beats it: 2.18 against seven teachers. So the hot start
  is a test of whether starting from your strategy leads further after PPO, not a sure gain.
- **Meta comps in the overlay.** The advice names the HSReplay comp your cards are closest to and
  the core cards you are missing.

## Known problems

- The network in the overlay still learned from self-play only: it may end late turns with gold
  left and refresh too little. Fixed in training; it improves when a newer network is promoted.
- Economy cards and early Dark Gift choices: as written from your advice they cost the teacher a
  little against the plain bots, so they are switched off for now; to test again against
  stronger opponents.
- Training opponents are its own copies, not real lobbies. AutoTavern's biggest gain came from
  opponents calibrated to real games: the boards of the opponents you meet are in your logs.

## Next

- Watch `lib1` against real warbands (its "vs best + library" test) and head to head.
- One observation upgrade: card mechanics from the card data, minion counters and attachments,
  opponents' board age, the turn's action budget (a network conversion, then fine-tuning).

- PPO from the hot start (`teach1`, ends about 00:50), in generations too, held near the teacher
  at first; it then races `gen1` head to head.
- When generations stop gaining (the Hearthstone advisor's stalled near even): train on the plan
  search's choices, since the search already plays 0.48 places better than the network.
- Opponents from real boards: your logged opponents' warbands by turn.
- A stronger teacher where it helps: positioning, freezing, when to stop leveling at low Health.
