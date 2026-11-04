# Training plan

Since R3 (Nov 2) nine runs have each trained 4-12 hours from R3 under new flags and been dropped
(big3 on, big3ad, big3open, big3hero, lr3, p37, act1, late1, mid1). Each was a fair experiment;
together nothing trained long enough to compound. From Nov 5 the training follows this plan.

## Two kinds of run

**The mainline** (office GPU, always running). One lineage, one fixed setup, trained continuously
for days, like one of AutoTavern's stages. Its setup changes only when an experiment has won (below),
and then once, at a checkpoint, written in the table here. It is never restarted from R3, and its
flags are never changed for a test.

**The experiment slot** (cluster GPU, one at a time). Each experiment tests exactly one change
against the mainline's setup, from the mainline's current checkpoint, for a fixed budget (12 hours),
with its bar written here before it starts. It isn't stopped early except for a crash or a collapse
(the gate more than 0.3 places worse at 4 hours).

## Judging

Automatic at +4 h and at the end (scripts/office/run_checks.sh, and the same on the cluster's
checkpoints):
- advisor.gate against the champion (paired, about 2,700 pairs; pass: mean < 0 and 2.5 SE);
- advisor.engine_exam (late turns from your positions) and advisor.mid_exam (rounds 6-9 three rounds
  on), paired against the champion;
- for imitation runs, agreement on your held-out games.

**An experiment wins** when it passes its bar *and* isn't worse on the gate. Its change then goes into
the mainline's setup, and the mainline continues from its own latest checkpoint with it.

**A network ships** (a release) only after a gate pass against the champion and the fresh-seed
recheck. A day without one ships advice and simulator fixes on the same network.

## The queue

Ordered by the evidence (docs/CASE_LATE_GAME.md: the late gap is made in the mid-game, where the value
head can't see what an engine is worth). Written before running; reordered only by a result.

| # | Change (one) | Why | Bar (set first) | State |
| --- | --- | --- | --- | --- |
| 1 | your round 5-8 turns as an imitation target (mid1) | the root cause: R3's own games never build engines | mid exam: engine held >= 40% (R3 29%) at +3, held-out agreement up; gate not worse | runs Nov 4 19:40 on the office (the last parallel one) |
| 2 | library seats with their players (hero, Hero Powers, trinkets in combat) | training fights as real ones | gate not worse; R3's training-lobby place no longer the easy one | ready (data/library/boards_players.json) |
| 3 | starts from the curated comps' mid-game boards, more of them | more games where an engine exists | mid exam engine held up; gate not worse | to build |
| 4 | a deeper turn search (MCTS) as a teacher, once the value head sees the mid-game | expert iteration, as the constructed advisor | search beats the network on the gate first | later |

Results that are already in (Nov 4): act1 (forced Activates) and late1 (your better late turns) run
to their ends tonight; a winner joins the mainline's setup, a loser leaves the queue.

## The mainline's setup

| From | Setup | Checkpoint |
| --- | --- | --- |
| Nov 5 | R3's (big3: --solo, the top-1% library, real starts 0.5, comp starts 0.33, lr 1e-5, 1 epoch) + the winners of act1 / late1 / mid1 | the best of tonight's verdicts, else R3 |

## Rules

- One mainline, one experiment at a time; no third run beside them.
- No flag changed in a running run; a change is a new experiment.
- A result is written in docs/EXPERIMENTS.md before the next step is chosen.
- The simulator's fixes go into the mainline at its next checkpoint (a rebuild), noted here.
