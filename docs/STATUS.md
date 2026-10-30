# Status

A running note, in plain words: what changed, what is wrong, what comes next. The progress page
(`data/report.html`, `advisor.report`) shows it with the numbers. The plan is
[ROADMAP.md](ROADMAP.md); measurements go to [EXPERIMENTS.md](EXPERIMENTS.md).

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

- PPO from the hot start (`teach1`, ends about 00:50), in generations too, held near the teacher
  at first; it then races `gen1` head to head.
- When generations stop gaining (the Hearthstone advisor's stalled near even): train on the plan
  search's choices, since the search already plays 0.48 places better than the network.
- Opponents from real boards: your logged opponents' warbands by turn.
- A stronger teacher where it helps: positioning, freezing, when to stop leveling at low Health.
