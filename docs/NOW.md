# Now

What's being worked on, kept current (the progress page shows it under "Where we are"). The
release targets are in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31).

## Running

- [ ] Office: big3 (10x larger network) training on alone against 7 library seats, until Nov 2 16:00
- [ ] Cluster: big3ad (big3 it 302 in an adaptive lobby: late strength 1.25x its own, rising with it; + forced Upgrades with self-imitation)

## Next up

- [x] Cards lost to a full hand: a cost in training (card_lost_penalty, tested); big3 restarted with it 17:49
- [ ] Your games with big3: does the advice feel right late (refreshes, Gold spent)? Ctrl+Shift+B marks what doesn't
- [ ] R3 (Nov 2 20:00): late >= 0.30x, from your positions < 2.45, Gold left <= 6 (big3: 0.19x, 2.36, 1.85)
- [x] The late-game curve in the top-1% lobby (study --lobby library): big3 0.18x, the old best 0.17x; early 2.06x, mid 1.21x (old 1.87, 1.05)
- [x] Levelling: big3 is tier 2.8 at round 10 in that lobby (your lobbies 5.3). Made to level on a curve it placed 0.14 +- 0.07 worse; the teacher bot too (fast curve +0.39 worse, tier 3 the same as standard)
- [x] Why: every network gives Upgrade ~0.000 in your round 4-9 positions (inherited from the first self-play; forced exploration trained only the value). Self-imitation of forced Upgrades that pay (--explore-sil) added and tested
- [x] Why: the simulator's rules are right (prices exact, your turns replay 86% exactly); its lobby isn't: real late warbands no simulated player approaches, so the late game is lost whatever one does. Adaptive library added (--library-adaptive), big3sil stopped for it
- [ ] big3ad vs big3: P(Upgrade) in your positions, tier at round 10 and the late game in the top-1% lobby, from your positions
- [ ] big3's entropy rose 0.85 -> 1.3, back to 0.96 at it 240; from your positions 2.20 (best 2.30): watching

## Tomorrow morning (Nov 2)

- [x] big3ad levels now: tier at round 10 in the top-1% lobby 4.4-4.6 (big3 2.9), round 13 5.7-5.9 (4.1); turns with an Upgrade in your rounds 10-11 82-91% (14%). Strength the same as big3 (head to head 4.2-4.6 vs R2, your positions 2.15-2.44)
- [x] big3 iteration 510 promoted automatically 06:53 (head to head 4.28 vs R2, audit clean); on the home advisor and the cluster by hand (the home sync was off overnight)
- [ ] The late game hasn't moved: 0.16-0.20x for both (R3 wants 0.30). Levelling is learned, a scaling engine isn't: genre scorecards running (office)
- [x] Simulator check across turns (carry_test): rebuilt real boards lost Magnetizations (a log keeps all Satellites in one enchantment): rounds 7-9 gained 0.42x the real growth, now 1.03x. Fixed for the live advice (restart the advisor) and training's real starts
- [x] Card-by-card scaling check (within the turn: 93.4% of 2,278 actions exact, big scalers within 3%; over the turn change: per card). Fixed: the Volumizer bonus (Robot 13.7k -> 21.7k of 25.8k real), Vol'jin's swap kept as permanent Attack
- [ ] Open: Volumizer stacks' Magnetization count (Beatboxer), Living Prison, Gatekeeper Amalgam, Bramble Tunneler; Tarecgosa (combat)
- [x] Combats calibrated: fixed Hero Powers armed for the next combat (Y'Shaarj) and Lock and Load's owed minion; TavernGym still underrates your side by ~9 wins of 212 (3.1 SD)
- [ ] The 8 fights you won from < 45%: case by case (Pocket Cyclone, Deathstrider-Lobster, Undead under Expedition Plans...)
- [x] Audit (docs/AUDIT.md): card-text review of ~700 scripts (no scaling contradiction; Sacrifice fixed); Bob's Buddy on 6,000 random warbands (mean |diff| 0.038; both strong outliers decided by your logs for TavernGym); the Deity rebuilt (combats +3.1 -> +2.9 SD)
- [ ] Audit next: the rest of the +2.9 SD (close fights); spells, trinkets and Hero Powers with few log checks
- [x] fidelity: one check for all audits with a baseline (actions 93.6%, turns 86.3%, transitions 99.4%, combats calibrated +3.0 SD, carry 0.70/1.05/0.88x); a regression exits 1 (the home sync logs it)
- [x] Rebuild: Blood Gems kept apart (Gem Confiscation 7 of 7), improve-this counters, Living Prison and Lock and Load from the turn's decisions
- [ ] Your opening (Nov 2): networks Freeze 5-8x as often as you in rounds 2-6, never Upgrade (you 0.55/turn), buy more off-type minions. Rules checked (damage caps 5/10/15, Triple Reward Tier on play): right. Next: a run that learns the opening
- [ ] Rebuild the home module when the advisor is closed (Vol'jin fix needs it); restart the advisor for the Satellite/Volumizer fixes
- [ ] R3 (20:00): big3 it 510 unless big3ad beats it head to head by then

## Later

- [ ] R4 (Nov 3): late >= 0.40x, on-type buys >= 50% (big3: 48.5%)
- [ ] R5 (Nov 4): late >= 0.50x; 5 of your games measured
- [ ] Opponents' trinket counters in the observation (the bridge's live values)
- [ ] The full 18M network AutoTavern used (big3 is d384 x 8 layers)

## Done today (Nov 1)

- [x] R2 shipped (tag bg-r2): big3 iteration 180, the first network to beat the 18:21 one
- [x] The Cancel reward hack found and fixed (solo1, emb1); solo2 restarted from before it
- [x] Teacher test: no search plays better than the network; the advice runs without it (0.3 s)
- [x] A 10x larger network distilled and trained (big3); the play audit made fair
