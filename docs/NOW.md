# Now

Short and current: the progress page shows the first three "Next up" items at the top. Goal: 14k+
MMR (master play). Releases: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31); training:
[TRAINING_PLAN.md](TRAINING_PLAN.md); simulator: [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: main1, the mainline, since 19:54 (R3's setup on tonight's simulator); since 23:10 about 1.6x faster (evaluation moved out)
- [ ] Cluster: act1 against R3 at 4x the pairs (it was -0.05 ± 0.03, too close to call); the tempo diagnostic

## Next up (Nov 5 morning; overnight everything runs on the office and the cluster)

- [ ] Speed, on the office: a 15-minute test of `--chunk 512 --amp-collect --overlap` (home: update 40 s -> 27 s at chunk 512, bfloat16 collection 1.5x, its policy within KL 0.00003 of fp32), then main1 restarted from its last.pt with them
- [ ] Read the night's results: act1 at 4x the pairs (cluster, ~04:30); main1's 4 h gate and engine exam (office, from 23:54); the tempo diagnostic (early health or later play decides the opening's fix)
- [ ] Releases only for a major breakthrough, with a complete check (you, Nov 4)

## Later

- [ ] Late-game gap: made in rounds 5-9 ([CASE_LATE_GAME.md](CASE_LATE_GAME.md)); type commitment (on-type buys 35%, you 62-69%)
- [ ] Training speed: observe only the slots that act (about 4 s of a 72 s iteration)
- [ ] Bob's Buddy disagreements: 8 combat Hero Powers and 2 trinkets (none in your logs)
- [ ] A Hero Power exam; a rating ladder and league; the full 18M network

## Done today (Nov 4)

- [x] Simulator: legality 100% of your decisions, early carry 0.69x -> 0.87x, combats attack by attack 54.9% -> 57.7% (AUDIT.md: about 15 fixes, among them the reconnect, Volumizers, Winner's Bread, Warcry Totem, Drek'Thar's copy, Tavern spells cast)
- [x] Overlay: says when the lineup's stats are after the plan (your Roaring Recruiter note)
- [x] Opening rules forced on R3: 0.7-0.8 places worse (cancelled after round 1)
- [x] act1 end: even with R3 (-0.05 ± 0.03), late1: worse (+0.19); neither ships
- [x] Training plan: one mainline plus one experiment, the champion ladder on the progress page
