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
| 3 | starts from the curated comps' mid-game boards, more of them | more games where an engine exists | mid exam engine held up; gate not worse | comp2: `--comp-starts 0.66`, cluster, Nov 5: **failed** at 4 h (+0.133 ± 0.043 vs main1); scaling unchanged; stopped at it 1415 (your OK) |
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

**Nov 5, 16:30: the next step, written before the evidence that picks it.** main1 never levels (Upgrade
probability 1e-6..1e-13 at your positions) and one Upgrade there is worth nothing to it in the training lobby
(+0.075 ± 0.048). The same test is running in two lobbies where the late game is within reach (the library
seats at your lobbies' logged strength; main1 alone):
- **A. An Upgrade pays there** (paired gain, 2.5 SE): the top-1% lobby is what teaches tempo over investment.
  Experiment lobby1 from main1: the library seats at your lobbies' logged strength (`--library-strength 0`),
  everything else main1's. Bar: not worse than main1 at the same iteration on the gate's realistic suite (your
  positions), and it starts to level (Upgrades from your round 4-9 positions >= 0.1 a turn; now 0.00).
- **B. It pays nowhere** (the result, Nov 5 18:00: top 1% +0.075 ± 0.048, logged +0.14 ± 0.047, alone +0.054 ± 0.052; A is out): the cause is what it does with a Tier (buys off-tribe, breaks the engine), not the
  lobby. Search can only teach that if the value head sees the mid-game (55% on your round 5-8 turns, Nov 4;
  main1's measured tonight). If it still can't: teach the value head from outcomes of your positions (many
  rollouts each) before any search teacher; if it can: the plan search with that value as the teacher.

**Nov 5, 19:00: the next candidate, after comp2 (your OK, 19:30: queued as job 108385, from main1's it 1400 snapshot widened, starts when comp2's array ends; judged against main1 at the same iteration as always).** Every probe today puts the gap
in main1's own mid-game play, and AutoTavern's agent, whose recipe differs from ours mainly in scale, scales
from turn 11 where ours doesn't. The one difference we can test at our size: the network. Our trunk is
theirs (d 384, 8 layers, 8 heads) but with feed-forward layers 2 x d (11.0M); theirs is the usual 4 x d (18M;
their 18M beat 8M and 3.5M). advisor.widen grows main1's checkpoint to 4 x d (15.7M) playing exactly as it
did (zero output weights on the new units: logit difference 0 over 266 decisions); 1.18x the forward time.
**wide1**: main1's checkpoint at comp2's end, widened; main1's setup otherwise; KL anchor 0.1 to its start for
the first 100 iterations (their stage rule); 12 h. **Bar, set first:** a gate pass against main1 at the same
iteration; or not worse with the audit's scaling share (warband 1.8x+ a round from round 8 to 12) up from
main1's 2.6% (fresh) / 10% (your positions).
**Result (Nov 6): a tie** (audit -0.008 ± 0.075, 841 pairs; scaling share 1.0% vs 2.4% fresh, 8.1% vs 7.7% yours; the exams the same). Twice the feed-forward width learns the same play in the same time: capacity is not what holds the mid-game back. Lesson added: no more width/size variants without new evidence.

**Nov 5, 23:30: the direction (your call): learn with less, not by brute force.** The day's probes agree:
no habit of yours forced on main1 pays (Upgrade, tribe, comp starts), its value head is right about its own
play, and the gap is the scaling it rarely reaches (1.8x+ a round in 2.6% of fresh games, which then place
2.1). AutoTavern got there with ~60x our decisions; main1 is still climbing (-0.189 ± 0.024 at it 1400), so
time helps, but the methods made for rare, long-delayed success come first:
1. **sil1: self-imitation of its own high games** (`--sil-games`, GameSil): the transitions of games that
   ended 1st or 2nd, where they beat the value, replayed every minibatch. Bar: not worse on the gate than
   main1 at the same iteration, and the audit's scaling share up.
2. **A reverse curriculum from your scaling games:** starts from your board a few rounds before you scaled,
   moved earlier as the network finishes them (building, not playing a built engine: comp2's failure).
3. **Turn search at advice time** (MCTS on the shop turn), later a teacher.
One at a time on the cluster's GPU after wide1; main1 keeps running. Fewer probes: a diagnostic only
where a decision waits on it.

**Nov 6, 00:30: the lessons from every run so far (your question: don't loop), and the three ideas above
withdrawn as variants of what failed.** Gains the gate confirms came from (1) one fixed setup trained long (R1 ->
R3 on big3's setup; main1 -0.189 ± 0.024 at it 1400), (2) the simulator made more faithful (big3's own line on
the old rules flattened at -0.013 after 276 iterations; the same setup on the Nov 4 rules passed at -0.086 after
115), (3) early network and observation changes. Nothing that put one part of your play into the policy ever
did (forced rules and steps, exploration + self-imitation: big3sil, act1; imitation: human-data, late1; starts:
comp2; lobby tweaks: big3ad/open; lr3; big3hero; search as a teacher once the network outgrew it; width: wide1, 4 x d feed-forward, tied Nov 6): its style is a
consistent whole, one habit alone is worse for it (measured Nov 5), and RL pushes it back. **Rule:** a new
experiment is checked against this list first; a variant of a failed idea runs only with new evidence for why it
would work now. A change of setup is judged by a long run (days) against main1 at the same iteration, not 4-12 h.
**Next:** simulator fidelity as a training lever (the combat bias: you win +2.7 SD more of your fights than it
predicts, rounds 1-10: split by board type); wide1 runs out; calibrated opponents only as a long run.

**Nov 6, 09:30: what we optimise changes (your doubt, the evidence agrees), and the next experiment (your OK).**
main1's gain since it 949 is 72% in rounds 1-5; its share of fresh games that scale fell 4.7% -> 1.2%; against R3
the gain from your positions (0.09 ± 0.03) is a third of the fresh games' (~0.25); the mid and engine exams are
flat. The full gate rewards the opening, which the advice needs least. **From now on the advisor's measures lead:**
your positions (held out), the mid exam, the engine exam, the scaling share; the full gate only as a not-worse check.
**spec1, the mid/late specialist:** from main1's latest checkpoint (wide1 tied: narrow), every new game starts
from one of your positions in rounds 6+ of your *training* games (`--real-starts 1.0 --real-rounds 6 19
--real-split train --comp-starts 0`: 148 positions, 13 games); everything else main1's. At advice time main1 plays
rounds 1-5 and the specialist from round 6 (AutoTavern's merged specialists). Judged only on the 8 held-out games
(`BG_SPLIT=test`: 84 positions) against main1 at the same iteration. **Bar, set first:** mid exam (warband vs yours
at +3) and engine exam better than main1's, the scaling share from your positions up, the gate's held-out real
suite not worse. Also watched: the mid-game value probe (your rounds 5-8 End Turn rated above its own; main1 it 2200 on the held-out games: 62% of 32, +0.013 ± 0.025, so only a large change shows). Days, checked every 12 h (started Nov 6 10:00 from main1 it 2200, narrow, your OK: the GPU was idle until wide1's verdict; widened and restarted only if wide1 wins). If it doesn't scale either, more mid-game practice isn't the limit:
the network's ability to learn it is. **Result: no gain at 8 h or 24 h** (gate +0.103 ± 0.066 on the held-out
games at it 3317; exams level; the value probe 61% as main1's): stopped Nov 7 at it 3431 (your OK).

**Nov 7: the diagnosis, and plan1 (your OK).** One decision at a time, R6's choices are as good as yours under its
own follow-through (disagreement audit: -0.021 ± 0.021 over 581); its value head doesn't track scaling at all (its
correlation with the warband's growth 2-4 rounds on, in its own games: 0.07 / 0.01; aux_probe). The gap is a
**local optimum**: your committed-engine style is many coordinated choices whose payoff comes rounds later, and
every single step toward it from main1's tempo style is worse (each habit forced alone lost), so PPO's small
steps never cross. AutoTavern's end-to-end PPO gets across by scale; we can't.

**plan1: plan-conditioned training.** The network gets a plan input (EntityNet `plans=`: none, or a tribe the
game commits to), zero at first so every plan plays as main1 (advisor.plan_init: 0.00 difference). In training a
learner seat's game is committed with probability 0.5 to a tribe (among those on its warband and in its Tavern) from
a random round in 3-6; a potential-based shaping (`--plan-shaping 0.3`: the plan tribe's minions on the warband / 7,
rewarded as its change, zero over a game) credits each step toward it without changing what is best. So each
committed style is practised and improved as its own mode (it needn't beat tempo while still clumsy), and the
choice between styles is one decision with clean feedback: the value under each plan. At advice and in the gate,
PlanPicker plays the plan with the highest value (`BG_PLAN_PICK=1`). Everything else main1's setup, from main1's
it 3600 snapshot; judged against main1 at the same iteration. **Bar, set first:** with the picker, on your
held-out games: the scaling share (1.8x+ a round, rounds 8-12) up, mid and engine exams better, the mid-game value
probe up, the gate's real suite not worse. **Checks that the plans are real:** the value spread across plans in
mid-game positions grows; under a tribe plan the network buys that tribe when offered (main1 34-46%, you 72%) and
those games scale. Days; checked every 12 h. Not a repeat of the failed list: forced tribe buys gave a network that
didn't know the plan trajectories it couldn't learn from; here the plan is its input, its follow-through is what
it trains, and the value picks the plan.

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
