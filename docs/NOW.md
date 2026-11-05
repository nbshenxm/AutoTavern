# Now

Short and current: the progress page shows the first three "Next up" items at the top. Goal: 14k+
MMR (master play). Releases: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31); training:
[TRAINING_PLAN.md](TRAINING_PLAN.md); simulator: [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: main1, the mainline (R3's setup on the Nov 4 simulator); its 4 h gate **passed** against R3 (-0.086 ± 0.031)
- [ ] Cluster: main1 at iteration 949 against R3 (3 seeds); the opening rules in realistic lobbies (your positions, the library)

## Next up

- [ ] Speed: `--overlap` made training unstable (dropped); `--chunk 512 --amp-collect` on the cluster's GPU first, then main1 (now 81 s an iteration)
- [ ] main1 at 12 h: still improving? (the cluster gate, about 13:30)
- [ ] The opening: forced Upgrades lose in R3-only lobbies (13 health down by round 7, where nobody levels); a gain in your lobbies would make it a training target

## Later

- [ ] Late-game gap: made in rounds 5-9 ([CASE_LATE_GAME.md](CASE_LATE_GAME.md)); type commitment (on-type buys 35%, you 62-69%)
- [ ] Training speed: observe only the slots that act (about 4 s of a 72 s iteration)
- [ ] Bob's Buddy disagreements: 8 combat Hero Powers and 2 trinkets (none in your logs)
- [ ] A Hero Power exam; a rating ladder and league; the full 18M network

## Done (Nov 5)

- [x] main1 4 h: the first gate pass since R3; act1 at 4 seeds: -0.051 ± 0.017, also better than R3
- [x] The tempo diagnostic: the forced opening loses on early health in R3-only lobbies, later play is fine

## Done (Nov 4)

- [x] Simulator: legality 100% of your decisions, early carry 0.69x -> 0.87x, combats attack by attack 54.9% -> 57.7% (AUDIT.md: about 15 fixes, among them the reconnect, Volumizers, Winner's Bread, Warcry Totem, Drek'Thar's copy, Tavern spells cast)
- [x] Overlay: says when the lineup's stats are after the plan (your Roaring Recruiter note)
- [x] Opening rules forced on R3: 0.7-0.8 places worse (cancelled after round 1)
- [x] act1 end: even with R3 (-0.05 ± 0.03), late1: worse (+0.19); neither ships
- [x] Training plan: one mainline plus one experiment, the champion ladder on the progress page
