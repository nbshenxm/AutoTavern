# Making the advisor robust in real games

So far most bad advice was found by you, one game at a time: Activate twice, sell-and-replay,
a Flighty Scout played, a random Volumizer used as if known. That doesn't scale. This plan turns
every class of problem into a check that runs by itself, on every game you play and every network
before it reaches the overlay, and reports what it finds.

## 1. Every piece of advice is reviewed automatically (`advisor.review`)

After each session (the home sync), every advice the overlay showed (history.jsonl, with what you
held) is re-checked against rules that never have exceptions:

- every step legal at that point (TavernGym), the first one offered by the client;
- only cards you have or that are certain (no random draws used as known);
- Gold never below zero along the plan; no card lost to a full hand by the plan's own order;
- no no-op detours (sell a minion and play the same card, Activate twice);

and against signals that are *usually* wrong, reported but never banned (your rule: no hard
rules on moves that can be right):

- the plan ends the turn with 3+ Gold it could spend;
- the plan lowers the warband's odds against the next opponent's last seen warband;
- the plan sells a minion worth more than what replaces it;
- the advice disagrees with what you did, and in the simulator your choice did clearly better
  (regret mining: the cases where you were right and the network wasn't, found for you).

Output: a review page per session (grouped by pattern, worst examples first) and the rates per
game on the progress page. Ctrl+Shift+B marks still go to the top of it.

## 2. The simulator is checked against every new game (`advisor.fidelity`)

The audits that found most bugs today run after every session on all logs, against a stored
baseline: legal actions vs the client (95.9%), one action at a time (94.5%), whole turns (84.6%),
turn transitions, combat replay (0.88). A drop, or a card that newly mismatches, is listed by
card with an example: the to-fix list. Cards seen in your games but never matched are listed
apart (untested content).

## 3. Each fixed bug becomes a regression test

Every reported or found bug gets a test with its position (from your logs) and the property that
was violated (tests/test_live.py, tests/test_bridge.py): Activate once a turn, Faelin's held
minions, Baller bonus, free trinket offers, maximum Gold, detours, random cards. They run before
every commit and on the office before a rebuild.

## 4. Promotion asks real-game questions, not only training numbers

A network reaches the overlay only after the training gates *and* the play audit (advice at your
real positions, complete games, against the current best), now extended with the review's rules
(section 1) on your logged positions: any no-exception rule broken fails it; the usually-wrong
signals must not be clearly worse than the best's.

## 5. Watching for reward hacks in training

The action mix in training (moves, Freeze presses, Refreshes, sells right after buys, Gold left
at End, cards lost) is logged per iteration; a share that drifts away from your own games' mix
(advisor.human_data's held-out set) is flagged on the progress page. A cost the network learns
to dodge (as Freeze dodged the wasted-Gold cost) shows here first.

## 6. Usefulness is measured in your games

Per game: how often you followed the advice's first step, the review's rates, your placement,
Ctrl+Shift+B marks. Over games this says whether the advisor helps, beyond what the simulator
says.

## Order of work

1. `advisor.review` (section 1): done, run by the home sync after every game.
2. `advisor.fidelity` with a stored baseline (section 2): done, same; history on the progress page.
3. Regression tests for the fixes (section 3): done for all of Oct 30's.
4. The review's no-exception rules in the play audit (section 4): done Oct 31 (crashes, the
   first step, exact-id detours; the signals: Gold left, cards lost, weaker warband, worse odds).
   Checking the audit itself found the Gold-left signal dead: it was read after End Turn, when
   nothing is legal; the live test now fails if no plan in a game ever ends with spendable Gold.
5. Action-mix drift in training logs (section 5); usefulness per game (section 6): next.
6. Your habits as a reference (`advisor.compare_play`, on the progress page): done.
