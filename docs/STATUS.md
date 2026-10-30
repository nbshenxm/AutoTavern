# Status

A running note, in plain words: what changed, what is wrong, what comes next. The progress page
(`data/report.html`, `advisor.report`) shows it with the numbers. The plan is
[ROADMAP.md](ROADMAP.md); measurements go to [EXPERIMENTS.md](EXPERIMENTS.md).

## Latest

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

- PPO from the hot start (`teach1`), held near the teacher at first; compare it with `office3`
  head to head.
- Opponents from real boards: your logged opponents' warbands by turn.
- A stronger teacher where it helps: positioning, freezing, when to stop leveling at low Health.
