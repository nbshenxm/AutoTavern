# Simulator audit

Is TavernGym right, and is what we feed it (positions rebuilt from your Power.logs) right? Each
check below says what it covers, what it found, and what is still open. Started 2026-11-02 after
the late game failed to improve: a card that scales wrongly makes an engine look worthless (or
worth too much) whatever the network decides.

## The checks

| Check | Tool | Covers | Reference |
|---|---|---|---|
| One action | `advisor.recruit_diff` | each of your logged Recruit actions from a rebuilt state: the warband after it | your log |
| A whole turn | `advisor.turn_replay` | a turn replayed from its start: what builds up within it | your log |
| Combat and the turn change | `advisor.carry_test` | end of turn, the combat you really had, the next turn's start: what a warband keeps | your log |
| Combat outcome | `advisor.replay` (calibration) | the logged result's chance per combat; predicted vs actual wins by bucket | your log |
| Combat rules | `advisor.bb_diff` + `tools/bbdiff` | random current-pool warbands, every minion: TavernGym against Bob's Buddy (HDT's simulator, local only) | Bob's Buddy |
| Card text | 6 reviewers, Nov 2 | every current-pool script (~700: minions, spells, Dark Gifts, trinkets, Hero Powers) read against its text | the card text |
| Coverage | `advisor.coverage` | per card: played in your logs, which checks saw it, a status | all of the above |

## Found and fixed

| Where | What | Effect | Fixed |
|---|---|---|---|
| rebuild | a minion's Satellites are one enchantment in the log; rebuilt as one Magnetization | Utility Drone engines grew 0.42x the real amount over the turn change (rounds 7-9) | each Satellite (stack / 4): 1.03x |
| log parse + rebuild | "Your Volumizers have +X this game" (player tags 4468/4469) never read | Resourceful Robot / Auto Reveille Magnetized printed-size Volumizers (13.7k of 25.8k real) | read: 21.7k |
| rebuild | Vol'jin's Spirit Swap ("until next turn") rebuilt as permanent Attack | swapped minions kept thousands of Attack (Dark Paradox 2,319 instead of 337) | temporary (edit_minion temp_atk) |
| rebuild, replay | Hero Powers used in Recruit for the next combat not armed (Y'Shaarj, Rafaam) | logged wins at p 0.00 | armed: 0.54 / 0.11 / 0.04 (the summon is random) |
| replay | Lock and Load's taken minion never owed to the combat | a minion short: p 0.43, 0.65 for logged wins | owed: 0.88, 0.84 |
| TavernGym | Offensive / Defensive Sacrifice (Dark Gifts) could give the stats to the host itself when its Deathrattle was triggered while it lived (Deathstrider, Herald Sticker) | the host buffed itself | another friendly minion |
| log parse + rebuild | the lobby's Deity and its size (player tags BACON_OLD_GOD_ATTACK/HEALTH) never read: rebuilt lobbies drew a random Deity at printed size | a Y'Shaarj where your lobby had a 7/4 C'Thun: a won fight at p 0.14 (Bob's Buddy 1.00) | the logged Deity and size |

## Results so far

- One action: 93.4% of 2,278 logged actions exact; the big scalers within 0.1-3% in total stats
  (Methodical Madness 308,908 real / 308,944).
- Combat and the turn change: 0.92-1.05x the real growth through round 9, 0.86x from round 10
  (left: the Volumizer stack count, Tarecgosa's combat).
- Combat outcome: predicted 100.6 wins of 212, actual 109 (+2.9 SD; +3.1 before the Deity fix):
  TavernGym still underrates your side in close fights.
- Card text: ~700 scripts, no number or scaling contradiction; edge cases listed below.
- Bob's Buddy, random warbands (6,000 fights, every in-pool minion, after fixing the harness: golden flags,
  shield hit counts): mean |difference| in (win - loss) 0.038. The two cards that still lean far
  (Dark Paradox z +6.4, golden Scarlet Survivor z +5.4) were settled by your logs in TavernGym's
  favour (Dark Paradox's shield takes 3 hits; Survivors at 6+ Attack have Divine Shield, 18 of 18);
  the rest are at chance level (z <= 2.7 over ~400 cards).
- Bob's Buddy, your 212 combats (plain inputs only, no enchantment effects): +4.6 SD, worse than
  TavernGym's +2.9: the bias left is mostly in what neither gets from the log, not TavernGym's rules.

## Open

- The +3.1 SD combat bias: 8 fights you won from < 45% (Pocket Cyclone, the Deathstrider-Lobster
  Beasts, an Undead board under Expedition Plans, ...)
- Rebuild gaps: the Volumizer stack's Magnetization count (Beatboxer); Living Prison armed earlier
  in the turn; Blood Gems that Gem Confiscation steals; Gatekeeper Amalgam played as printed
  stats; Lock and Load in the live advice (needs the turn's decisions)
- Card-text edge cases (likely): Guiding Candle's Tier 6 Refreshes skip other "when Refreshed" effects; Bob-blehead still offers
  Tier 1-2 spells; Ruby Tusk counts a doubled Gem twice
- Card-text readings to confirm (unsure): Snake Eyes' lockout length; Galakrond / Token of the
  Old Gods at Tier 6; Glambot on Tavern Mechs; Devilish Distractor and effect-cast spells; Deft
  Deserter's keyword per minion; powers gained mid-game starting improved (C'Thun, Kragg); Dead
  Bellringer onto another Bellringer ("a different friendly Undead": usually just "another")
- Not covered by your logs: two thirds of spells and trinkets, most heroes (advisor.coverage)
