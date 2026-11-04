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
| rebuild | Easterly Winds (Pocket Cyclone, Air Revenant: "after the Tavern is Refreshed this game, a random minion +9/+9", cast again and again) never rebuilt: the log keeps its per-Refresh total | a rebuilt position's Refreshes buffed nothing where the log had +110/+110 or +337/+337 | the total as TavernGym's stacks |
| rebuild | each rebuilt Volumizer raised the player's Volumizer bonus again (its "when Magnetized" part ran), and a later re-sync took 2/2 off rebuilt Volumizers | Robot Magnetized oversized Volumizers; one action exact fell to 88.9% while fixing | counters and minions' stats set last: 93.6% |
| rebuild | Volumizer stacks and Polarizing Beatboxer's echo enchantment counted as one Magnetization (the log sums them) | Beatboxer 581 of 5,008 real over the turn change | estimated counts: Robot 24.7k / 25.8k, Beatboxer 5.9k / 5.0k, Reveille 2.4k / 2.4k |
| rebuild | an armed Living Prison and Lock and Load's owed minion are only in the turn's earlier decisions | a Kelp Keeper buy: Prison 215 rebuilt, 503 real | the rebuild (and the live advisor, recruit_diff) read the turn's decisions: 503 |
| rebuild | "improve this" counters unread (Spark Snapper, Ultraviolet Ascendant, Sacrificial Wrathguard, Lurking Leviathan; Patient Scout, Sky Admiral Rogers) | every rebuilt one started at 0: a Snapper with 16 improvements gave a 4/6 Satellite (Gatekeeper Amalgam played 10/12, real 42/60) | read from the amount the log shows |
| log parse + rebuild | Hero Power improvements (TAG_SCRIPT_DATA_NUM_3, never parsed): Wax Warband rebuilt unimproved | your Start of Combat gains +8...+40 came out +4/+6 | read: 8 of 9 logged combats exact |
| rebuild | Blood Gem stats rebuilt as plain stats | Gem Confiscation stole nothing | kept apart: 7 of 7 exact |
| rebuild | next-combat Tavern spells cast earlier in the turn (Brood of Nozdormu, Upper Hand, Sharing is Caring) are in no log field once cast | a round-13 golden Tarecgosa lost Brood: kept 149k where the log had 248k (the whole rounds 10+ gap: 0.87x) | read from the turn's earlier decisions (5 casts in your logs) |
| TavernGym | Brood of Nozdormu doubled the Attack as a gain, which golden Tarecgosa doubles again (the client: "Attack set to") | that Tarecgosa kept 296k (real 197k Attack) once Brood was carried | a raise that isn't doubled (`Ctx::raise_as_set`): exact; rounds 10+ 1.00x |
| rebuild + TavernGym | Jim Raynor's Battlecruiser Upgrades: the client keeps each family as one enchantment with its total (Yamato Cannon 6 ... 87); the rebuild read none of them, and TavernGym fired each Yamato upgrade as its own shot (each re-picking the highest-Health enemy) | a round-3 tie at p 0.00 (a 6-damage Yamato missing: Lionfish 8/9 instead of 8/3) | upgrades rebuilt from the totals; Yamato one shot of the sum: p 0.77 |
| TavernGym | a summon's listeners fired in board order: an "After you summon" (Banana Slamma) left of a "Whenever you summon" (Lurking Leviathan) doubled before the +3 | the summoned Beast's Attack (x+3)x2 vs 2x+3 | "whenever" before "after" for summons, as for casts and plays |
| replay | the combat replay never set minions' logged counters (improve-this cards, COUNTER_FROM_DATA); only the Recruit rebuild did | a Leviathan at +15 fought at +3: a fight you won at p 0.03 (Bob's Buddy 0.70) | `bridge.set_counter` in both: p 0.55; calibration +2.70 → +2.55 SD |
| TavernGym + library | the library seats fought as bare warbands: no hero, Hero Power, trinket or player counter in combat (the recorded stats hold their buffs, not what acts in combat) | training fights easier than real ones | a library board carries its player as the combat showed them (config::LibraryPlayer; 469 boards: 0-3 trinkets, 1-2 Hero Powers, counters on 235); R3's training-lobby place 5.08 → 5.16 (data/library/boards_players.json, not yet the training default) |
| log parse + rebuild | the lobby's Deity and its size (player tags BACON_OLD_GOD_ATTACK/HEALTH) never read: rebuilt lobbies drew a random Deity at printed size | a Y'Shaarj where your lobby had a 7/4 C'Thun: a won fight at p 0.14 (Bob's Buddy 1.00) | the logged Deity and size |

## Results so far

- One action: 93.6% of 2,278 logged actions exact (93.4% before this round); the big scalers within 0.1-3% in total stats
  (Methodical Madness 308,908 real / 308,944).
- Combat and the turn change (Nov 3, 37.0.2 build, 543 turn pairs x 3): rounds 1-6 0.73x (small
  numbers: 507 real, 370 TavernGym), rounds 7-9 1.06x, rounds 10+ 1.00x (0.87x before the Brood fixes).
- Combat outcome by round (Nov 3, start mode): rounds 1-6 +1.2 SD, 7-9 +2.0 SD, 10+ +1.0 SD: the
  late fights are calibrated; what's left of the bias is mid-game.
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

- Bob's Buddy with combat trinkets (6,000 fights, 46 combat trinkets, 0-2 a side): mean |difference|
  0.043. Leaning beyond chance, unresolved (not in your logs): Faerie Dragon Scale (z +4.0), All-Purpose
  Kibble (+3.2), Reinforced Shield (+2.8); Wildfire Elemental (+3.2: TavernGym deals the excess even
  when it dies in the exchange). All four match their text in TavernGym.
- Bob's Buddy with combat Hero Powers (3,000 fights, 9 passive combat powers, script data as HDT passes it):
  mean |difference| 0.050; leaning: Wax Warband (z +6: TavernGym's fresh one; your logs agree with
  TavernGym once its size is read), Broodmother (+4.6), Swatting Insects (-3.8), Tentacular (+3.5),
  Frostwolf Fervor (-3.1): the last four not in your logs (their data unknown to the harness).
- The standing check (advisor.fidelity, baseline Nov 2): legal 96.8%, one action 93.8%, whole turns
  86.3%, transitions 99.4%, combats 88.6% (calibration +2.8 SD), carry 0.70x / 1.06x / 0.88x,
  Bob's Buddy sample 0.047; any drop past its tolerance exits 1 (the home sync logs it).
- No seat bias: your combats with you in seat 0 and seat 1 give 98.8 and 99.3 predicted wins.
- The remaining +2.9 SD is spread (Beasts +1.2, Mechs +1.3, the rest +2.4 SD); ties are calibrated.

## Coverage of the current pool (Nov 4, `advisor.coverage`)

| Kind | Checked (your logs or Bob's Buddy) | Tested only (a unit test pins it to its text) | Suspect | Changed in 37.0.2 | Unchecked |
| --- | ---: | ---: | ---: | ---: | ---: |
| Shop minions (245) | 235 | 1 | 9 | 0 | 0 |
| Tavern spells (70) | 51 | 19 | 0 | 0 | 0 |
| Lesser Trinkets (112) | 33 | 76 | 1 | 2 | 0 |
| Greater Trinkets (120) | 29 | 86 | 2 | 3 | 0 |
| Hero Powers (116) | 4 | 104 | 8 | 0 | 0 |

The 109 cards that had neither got a test each on Nov 4 (113 tests: tests/cov_*.rs); none
contradicted its text. "Tested only" is weaker than "checked": a test pins what the script does to
what the text says, a log shows what the game does. Your games on 37.0.2 move cards up.

## Suspects in the coverage report, checked (Nov 4)

| Card | Flag | What it is |
| --- | --- | --- |
| Air Revenant | recruit 1,246 vs 521 | the patch: playing it (an Elemental) triggers Unbound Tempest, 3 Elementals in 37.0.2 (4 when logged) |
| Flighty Scout, Red Volumizer | recruit | the Volumizers next to them: the player's Volumizer bonus is an estimate in a rebuild (known) |
| Relentless Deflector | carry 0 vs 26 | a rebuild gap: Incubation's turns left (fixed: `bridge.set_schedules`, now exact) |
| Titus Rivendare | carry 212 vs 184 | Death's Embrace on it grows with the combat's deaths: random (+84/+60/+48 vs +60/+64/+60) |
| Snarky Shark | recruit 3% | random targets (Lobster Deathrattles, Gryphon's Beasts) |
| Misplaced Tea Set, Natural Blessing... | recruit | changed in 37.0.2; your logs predate it |
| 8 combat Hero Powers, Faerie Dragon Scale, Boom-in-a-Box | Bob's Buddy z 3-11 | open: none appears in your logs to settle which simulator is right (Wax Warband's earlier lean was the harness's input) |

## Open

- The +3.1 SD combat bias: 8 fights you won from < 45% (Pocket Cyclone, the Deathstrider-Lobster
  Beasts, an Undead board under Expedition Plans, ...)
- Rebuild gaps: Blood Gem Barrage's stacks (the log keeps the Gem size, not the count); Blood Gems
  that Gem Confiscation steals (rebuilt minions hold Gem stats as plain stats); Volumizer counts
  are estimates (+-15% per card); trinkets' take effects run again in a rebuild (cards in hand are
  cleared; persistent effects other than Easterly Winds would double)
- Card-text edge cases (likely): Guiding Candle's Tier 6 Refreshes skip other "when Refreshed" effects; Bob-blehead still offers
  Tier 1-2 spells; Ruby Tusk counts a doubled Gem twice
- Card-text readings to confirm (unsure): Snake Eyes' lockout length; Galakrond / Token of the
  Old Gods at Tier 6; Glambot on Tavern Mechs; Devilish Distractor and effect-cast spells; Deft
  Deserter's keyword per minion; powers gained mid-game starting improved (C'Thun, Kragg); Dead
  Bellringer onto another Bellringer ("a different friendly Undead": usually just "another")
- Not covered by your logs: two thirds of spells and trinkets, most heroes (advisor.coverage)
