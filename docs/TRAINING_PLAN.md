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

**After every verdict, the audit (your rule, Nov 5): why it won or didn't.** `scripts/hpc/post_audit.sh
CAND CONTROL NAME` (advisor.post_audit, cluster CPUs, data/audit/NAME): the gate's games, candidate against its
control from the same seeds; where the place difference is made (the first round seat 0's health differs
between the two); round by round health, Tier, warband, the main tribe's share, Gold left and actions; the mid
and engine exams paired; Refreshes, buys, Upgrades and Freezes next to yours (compare_play, early and late).
Also: did the change do what it was meant to (comp2: more engine games: do its comp-start games end with the
engine, and does that carry to fresh games?). The cause found goes into EXPERIMENTS.md with the verdict and
picks the next queue item; a result without a cause is a reason to investigate before the next run, not to
guess.

**An experiment wins** when it passes its bar *and* isn't worse on the gate. Its change then goes into
the mainline's setup, and the mainline continues from its own latest checkpoint with it.

**A network ships** (a release) only after a gate pass against the champion and the fresh-seed
recheck. A day without one ships advice and simulator fixes on the same network.

## The queue

Ordered by the evidence (docs/CASE_LATE_GAME.md: the late gap is made in the mid-game, where the value
head can't see what an engine is worth). Written before running; reordered only by a result.

| # | Change (one) | Why | Bar (set first) | State |
| --- | --- | --- | --- | --- |
| 1 | your round 5-8 turns as an imitation target (mid1) | the root cause: R3's own games never build engines | mid exam: engine held >= 40% (R3 29%) at +3, held-out agreement up; gate not worse | the cluster's slot after late1 (Nov 4 ~20:00), from R3 = the mainline's start; prior low after late1 (below) |
| 2 | library seats with their players (hero, Hero Powers, trinkets in combat) | training fights as real ones | gate not worse; R3's training-lobby place no longer the easy one | in main1 since Nov 5 08:20 (the rebuilt boards.json) |
| 3 | starts from the curated comps' mid-game boards, more of them | more games where an engine exists | mid exam engine held up; gate not worse | comp2: `--comp-starts 0.66`, cluster, Nov 5 |
| 4 | a deeper turn search (MCTS) as a teacher, once the value head sees the mid-game | expert iteration, as the constructed advisor | search beats the network on the gate first | later |

Results that are already in (Nov 4): act1 (forced Activates) and late1 (your better late turns) run
to their ends tonight; a winner joins the mainline's setup, a loser leaves the queue.

**Changed Nov 4, 14:30, on a result.** late1 at 4 h: the gate *worse* than R3 (+0.191 ± 0.052;
from your positions +0.30), while its agreement with your held-out late turns rose 4x (7.6% →
33%): imitating a few hundred of your decisions pulls the policy toward your moves and away from
what wins. act1 at 4 h: even on the gate, the engine exam and the mid exam. So (1) the mainline
starts tonight at 19:40 on the office instead of a 12-hour mid1 there: R3's fixed setup on the
rebuilt simulator (the day's fixes), nothing having beaten R3; (2) mid1, the same imitation recipe
on your round 5-8 turns, keeps its place at the head of the queue but runs as the one experiment
on the cluster after late1, with its bar unchanged; if it fails the gate like late1, imitation at
this scale leaves the queue.

*Nov 4, 18:30 (no change to a running run):* the cluster's staged update (applied after late1, before
mid1) re-staged at 7163c1d with this evening's simulator fixes, so mid1 and main1 start on the same rules
(Drek'Thar's copy position, the rebuild fixes; docs/AUDIT.md).

**Changed Nov 4, 19:40, on a result.** Since R3 (Nov 2) 8 candidates went through the gate, none better;
imitating your turns made it worse (late1). mid1 is the same imitation recipe: cancelled. The experiment
slot goes to the biggest measured flaw, the opening (R3: 0 Upgrades a turn in rounds 2-6, you 0.55; Freezes
0.6-0.7, you 0.1; your Busker note): first, without training, opening lines on R3 at decision time through the
gate (`advisor.gate --rules busker,level,nofreeze`, rounds 1-4 only). A pass ships at once and becomes a
training target; a fail says R3's value can't plan tempo, which then goes to what training rewards. Releases
only on a gate pass from now on (you, Nov 4). main1 runs as planned.

*Nov 4, 23:10 (your OK; no change to what it learns):* main1 restarted from its own last.pt (iteration 596)
with `--eval-every 100`. The in-run evaluation (200-game checks every 10 iterations) stalled the GPU 460 s each
time, 37% of the run (126 s an iteration for 80 s of training); the cluster gates judge it instead. Next for
speed: the update overlapping the next collection (36 s of the 80), tested apart from the run first.

*Nov 5, 08:20-08:45 (your OK):* main1 ran 16 iterations with `--chunk 512 --amp-collect --overlap`: 57.7 s an
iteration (80.7 before), but the KL between the collecting copy and the learner grew every iteration (0.001 to 0.05;
before, 0.0003). Rewound to its iteration-949 checkpoint (the one being gated) on the previous settings; the
drifted checkpoint is kept (data/train/main1/last_overlap_it972.pt). At home each flag alone, and all three at
small batches, show no growth. Traced at full size (Nov 5): the copy is exact and reproduces the stored
log-probabilities, but each update moves the policy further (KL per update 0.001 to 0.1 in 12 iterations), the
same when collection and update are kept apart in time: the one-update lag itself is unstable here. `--overlap`
is dropped; `--chunk 512 --amp-collect` (same math; bfloat16 collection) is being tested at full size on the
cluster's GPU before main1 gets it.

*Nov 5, 11:00:* the full-size test (cluster GPU, 40 iterations from main1's it 949, `--chunk 512 --amp-collect`):
KL flat, mean |KL| 0.0008 (main1's own last 40: 0.00075), no growth from the first half to the second; 25 s an
update (office, chunk 128: 37 s), collection about 40 s. Same training, faster: main1 to get both flags at a
checkpoint (needs your OK to stop it).

*Nov 5, 11:20-11:45 (your OK; same training):* main1 restarted from its own last.pt (it 1078) with `--chunk 512
--amp-collect`: collection 44 → 31 s, but the update 37 → 41.5 s on the office's GPU (faster on the cluster's).
Restarted again at it 1086 with `--chunk 128 --amp-collect`: **68 s an iteration** (81 before), KL as before.

**Nov 5, 12:30: the mainline is the model (your call), experiments beside it.** main1's steady line is the
first gain since R3 (-0.097 ± 0.020 at 12 h); it keeps running and every experiment branches from its latest
checkpoint and is judged against *main1 at the same iteration* (not R3): the same hours of training, one change.
Found while choosing: queue item 2 (library seats with their players) is already in main1 since its 08:20
restart today: data/library/boards.json was rebuilt with the players on Nov 4 at 23:22 (530 boards, all with a
player; 469 before) and main1 reads it at each start. Not planned, not harmful (the realistic library); written
in the setup table. So item 3 is next:

**comp2** (cluster GPU, from main1 it ~1095, 12 h): `--comp-starts 0.66` (0.33 in main1): a third of all new
games start from a curated comp's midgame instead of a sixth, so the network spends more of its games where an
engine exists (the late gap is made in rounds 5-9 because its own games never build one). Everything else
main1's (`--chunk 128 --amp-collect`, the same library and simulator build). **Bar, set first:** a gate pass
against main1 at the same iteration wins outright; not worse on the gate with the mid exam's engine held up
(main1's own measured at the same time) wins too; worse on the gate leaves the queue.

## The mainline's setup

| From | Setup | Checkpoint |
| --- | --- | --- |
| Nov 4 19:40 (main1, office, until Nov 8 20:00 then on) | R3's (big3: --solo, the top-1% library, real starts 0.5, comp starts 0.33, lr 1e-5, 1 epoch), on TavernGym with the Nov 4 fixes; a winning experiment's change joins at a checkpoint | R3 (big3 it 510): neither act1 nor late1 beat it at 4 h |
| Nov 5 08:20 (main1's restart) | + library seats with their players (the rebuilt boards.json: hero, Hero Powers, trinkets, counters) | main1's own (it 949) |
| Nov 5 11:45 | + `--amp-collect` (bfloat16 collection; same training, 81 → 68 s an iteration) | main1's own (it 1086) |

## Rules

- The plan isn't fixed ahead of the evidence: the queue, the budgets and the setup change when a
  result (or a finding about the simulator or the game) says so, with the reason written here at
  that moment. What it rules out is changing course without one.
- One mainline, one experiment at a time; no third run beside them.
- No flag changed in a running run; a change is a new experiment.
- A result is written in docs/EXPERIMENTS.md before the next step is chosen.
- The simulator's fixes go into the mainline at its next checkpoint (a rebuild), noted here.
