# Status

A running note, in plain words: what changed, what is wrong, what comes next. The progress page
(`data/report.html`, `advisor.report`) shows it with the numbers. The plan is
[ROADMAP.md](ROADMAP.md); measurements go to [EXPERIMENTS.md](EXPERIMENTS.md).

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
- **A simulator rule fixed:** with equal warbands, who attacks first is random, not the higher
  Tavern Tier (your logs: the higher Tier went first in only 17 of 29 such combats).
- **More of your games' data used:** gold next turn and the free Refresh count are now read
  from the log; three sessions the first export had missed are in (95.8% of 2,603 logged
  decisions now match the client's options exactly).
- **Strength curve on the progress page:** the network's warbands by round against your lobbies
  and the public average. It keeps up until round 9, then flattens: the main thing to fix.
- **Search-guided training (`search2`)** took `teachppo1`'s place when generations stalled; its
  first tests improve (4.44 → 4.26 against the best).

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
