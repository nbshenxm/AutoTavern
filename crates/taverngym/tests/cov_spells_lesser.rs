//! Card-text coverage: Murcules, eight Tavern spells and 28 Lesser Trinkets that had no test
//! (one test per card, more for cards with distinct parts). Each test quotes the card text and
//! asserts its concrete effect.
mod common;
use common::*;

use taverngym::cards::CardKind;
use taverngym::combat::attack_now;
use taverngym::content;
use taverngym::script::{Me, script};
use taverngym::state::ShopSlot;
use taverngym::types::Mech;

// ------------------------------------------------------------------------------- fixtures

/// `common::game` with some minion types forced into the lobby.
fn game_with(seed: u64, types: &[&str]) -> Game {
    let cfg = RulesConfig {
        aberration_forced: true,
        lobby_types: types.iter().map(|t| t.to_string()).collect(),
        ..RulesConfig::default()
    };
    let mut g = Game::new(seed, cfg);
    for p in 0..8 {
        g.apply(p, Action::Choose(0)).unwrap();
    }
    for p in 0..8 {
        g.players[p].hero = Some(cid("TB_BaconShop_HERO_34"));
        g.players[p].pending.clear();
        g.players[p].hand.clear();
        g.players[p].stats = Default::default();
        g.players[p].effects.clear();
        g.players[p].quests.clear();
        g.players[p].counters.clear();
        g.players[p].max_gold_bonus = 0;
        g.players[p].skipping = false;
        g.players[p].board.clear();
        g.players[p].powers.clear();
        g.players[p].set_hero_power(0, cid("TB_BaconShop_HP_035"));
    }
    g.cfg.triple_copies = 99;
    for t in types {
        let r = Races::NAMES.iter().position(|n| n == t).expect("a type name");
        assert!(g.lobby_races.intersects(Races(1 << r)), "{t} in the lobby");
    }
    g
}

/// Player 0 buys trinket `id` from a trinket offer (the real path: cost paid, `on_attach` runs).
fn buy_trinket(g: &mut Game, id: &str) {
    g.players[0].gold = g.players[0].gold.max(db().get(cid(id)).cost);
    g.players[0].pending.push(Pending::Trinket {
        options: vec![cid(id)],
        free: false,
        replace: None,
    });
    g.apply(0, Action::Choose(0)).unwrap();
    assert!(g.players[0].has_trinket(id));
}

/// Player 0 gets trinket `id` for free (`on_attach` runs).
fn grant(g: &mut Game, id: &str) {
    g.with_recruit(0, |c| content::grant_trinket(c, 0, cid(id)));
}

fn me(card: CardId) -> Me {
    Me {
        side: 0,
        eid: 0,
        card,
        golden: false,
        opt: 0,
        pos: 0,
        data: 0,
    }
}

/// Card ids in player 0's hand, left to right.
fn hand(g: &Game) -> Vec<String> {
    g.players[0]
        .hand
        .iter()
        .map(|h| db().get(h.item.card()).id.clone())
        .collect()
}

/// (attack, health) of the hand card at `i` (a minion).
fn hand_stats(g: &Game, i: usize) -> (i32, i32) {
    let m = g.players[0].hand[i].item.as_minion().unwrap();
    (m.atk, m.hp)
}

/// Player 0's Tavern minions: (card, attack, health).
fn shop(g: &Game) -> Vec<(CardId, i32, i32)> {
    g.players[0]
        .shop
        .iter()
        .filter_map(|s| s.item.as_minion().map(|m| (m.card, m.atk, m.hp)))
        .collect()
}

fn put_shop(g: &mut Game, id: &str) {
    let m = minion(g, 0, id);
    let sid = m.eid;
    g.players[0].shop.push(ShopSlot::new(sid, Item::Minion(m)));
}

fn base(card: CardId) -> (i32, i32) {
    let d = db().get(card);
    (d.atk, d.hp)
}

/// The open Discover of player 0: (source, offered cards).
fn discover(g: &Game) -> (CardId, Vec<CardId>) {
    match g.players[0].pending.last() {
        Some(Pending::Discover { source, options }) => {
            (*source, options.iter().map(|o| o.card()).collect())
        }
        other => panic!("expected a Discover, got {other:?}"),
    }
}

/// Play the last hand card at board position `pos`.
fn play_at(g: &mut Game, pos: usize) {
    let hand = g.players[0].hand.len() - 1;
    g.apply(0, Action::Play { hand, pos }).unwrap();
}

/// Board of side `s` right after Start of Combat (needs `record_log`).
fn after_soc(g: &Game, s: usize) -> Vec<(i32, i32)> {
    g.last_frames[1].boards[s]
        .iter()
        .map(|m| (m.atk, m.hp))
        .collect()
}

const VANILLA: &str = "BG36_345"; // Suspicious Prisonguard, 3/3, no type
const PIRATE: &str = "BG26_135"; // Southsea Busker, 3/1 Pirate, Battlecry: 1 Gold next turn
const SELLEMENTAL: &str = "BGS_115"; // 3/3 Elemental
const THEM_APPLES: &str = "BG28_966"; // Tavern spell, no target
const CORRUPTED_COIN: &str = "BG36_303"; // Tavern spell: gain 2 Gold
const SACRED_GIFT: &str = "BG28_507"; // Tavern spell on a minion: Divine Shield

// ------------------------------------------------------------------------------- minion

/// Murcules: "Whenever this kills a minion, give a minion in your hand +3/+3." (golden +6/+6)
#[test]
fn murcules_buffs_a_hand_minion_when_it_kills() {
    for (id, k) in [("BG27_023", 3), ("BG27_023_G", 6)] {
        let mut g = game(101);
        set_board(&mut g, 0, &[id]);
        set_board(&mut g, 1, &[VANILLA]);
        g.players[1].board[0].hp = 1;
        g.players[1].board[0].max_hp = 1;
        give(&mut g, 0, "BGS_004"); // Wrath Weaver 1/3
        let before = hand_stats(&g, 0);
        let mut c = combat_ctx(&mut g);
        let murcules = c.boards[0][0].eid;
        attack_now(&mut c, 0, murcules);
        drop(c);
        assert_eq!(hand_stats(&g, 0), (before.0 + k, before.1 + k), "{id}");
    }
}

/// Murcules: no kill, no buff.
#[test]
fn murcules_without_a_kill_gives_nothing() {
    let mut g = game(102);
    set_board(&mut g, 0, &["BG27_023"]);
    set_board(&mut g, 1, &[VANILLA]);
    g.players[1].board[0].hp = 50;
    g.players[1].board[0].max_hp = 50;
    give(&mut g, 0, "BGS_004");
    let before = hand_stats(&g, 0);
    let mut c = combat_ctx(&mut g);
    let murcules = c.boards[0][0].eid;
    attack_now(&mut c, 0, murcules);
    drop(c);
    assert_eq!(hand_stats(&g, 0), before);
}

// ------------------------------------------------------------------------------- spells

/// Staff of Enrichment: "Give minions in the Tavern +2/+2 this game."
#[test]
fn staff_of_enrichment_buffs_the_tavern_for_the_game() {
    let mut g = game(201);
    let before = shop(&g);
    assert!(!before.is_empty());
    give(&mut g, 0, "BG28_886");
    play_last(&mut g, 0);
    let after = shop(&g);
    assert_eq!(after.len(), before.len());
    for (b, a) in before.iter().zip(&after) {
        assert_eq!((a.1, a.2), (b.1 + 2, b.2 + 2), "current Tavern minions");
    }
    // "this game": the next Tavern's minions have it too.
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    for (card, a, h) in shop(&g) {
        let (ba, bh) = base(card);
        assert_eq!((a, h), (ba + 2, bh + 2), "refreshed {}", db().get(card).name);
    }
}

/// Hired Headhunter: "Discover a Battlecry minion."
#[test]
fn hired_headhunter_discovers_a_battlecry_minion() {
    let mut g = game(202);
    g.players[0].tier = 3;
    give(&mut g, 0, "BG28_GIL_836");
    play_last(&mut g, 0);
    let (_, options) = discover(&g);
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!(d.kind, CardKind::Minion);
        assert!(d.mech.has(Mech::BATTLECRY), "{} has no Battlecry", d.name);
        assert!(d.tier <= 3, "{} above your Tier", d.name);
    }
    g.apply(0, Action::Choose(1)).unwrap();
    assert_eq!(hand(&g), vec![db().get(options[1]).id.clone()]);
}

/// Time Management: "Choose One - Give your minions +2/+2; ..."
#[test]
fn time_management_now_gives_two_two() {
    let mut g = game(203);
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    give(&mut g, 0, "BG31_881");
    play_last(&mut g, 0);
    assert!(matches!(
        g.players[0].pending.last(),
        Some(Pending::ChooseOne { .. })
    ));
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(stats(&g, 0), vec![(5, 5), (5, 5)]);
}

/// Time Management: "...; or At the start of your next turn, give your minions +2/+2 twice."
#[test]
fn time_management_later_gives_two_two_twice_next_turn() {
    let mut g = game(204);
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    give(&mut g, 0, "BG31_881");
    play_last(&mut g, 0);
    g.apply(0, Action::Choose(1)).unwrap();
    assert_eq!(stats(&g, 0), vec![(3, 3), (3, 3)], "nothing this turn");
    end_turn_all(&mut g);
    assert_eq!(stats(&g, 0), vec![(7, 7), (7, 7)]);
}

/// Sharing is Caring: "Start of Combat: Your left-most minion gains stats equal to the nearest
/// enemy minion's."
#[test]
fn sharing_is_caring_copies_the_facing_enemy_stats_at_start_of_combat() {
    let mut g = game(205);
    g.cfg.record_log = true;
    give(&mut g, 0, "BG31_889");
    play_last(&mut g, 0);
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    set_board(&mut g, 1, &[VANILLA, VANILLA]);
    g.players[1].board[0].atk = 6;
    g.players[1].board[0].hp = 8;
    g.players[1].board[0].max_hp = 8;
    fight(&mut g);
    assert_eq!(after_soc(&g, 0), vec![(9, 11), (3, 3)]);
    // A "Start of Combat:" spell is for the next combat only.
    assert!(
        !g.players[0]
            .effects
            .iter()
            .any(|e| e.card == cid("BG31_889"))
    );
}

/// Sharing is Caring with uneven boards: the boards are centred, so a lone minion faces the
/// middle of three enemies, and one of two minions faces the second of four.
#[test]
fn sharing_is_caring_faces_the_centred_enemy_on_uneven_boards() {
    for (ours, theirs, facing) in [(1usize, 3usize, 1usize), (2, 4, 1), (3, 2, 0)] {
        let mut g = game(208);
        g.cfg.record_log = true;
        give(&mut g, 0, "BG31_889");
        play_last(&mut g, 0);
        set_board(&mut g, 0, &vec![VANILLA; ours]);
        set_board(&mut g, 1, &vec![VANILLA; theirs]);
        g.players[1].board[facing].atk = 6;
        g.players[1].board[facing].hp = 8;
        g.players[1].board[facing].max_hp = 8;
        fight(&mut g);
        assert_eq!(after_soc(&g, 0)[0], (9, 11), "{ours} vs {theirs}");
    }
}

/// Hallowed Ritual: "Discover a Tier 7 minion."
#[test]
fn hallowed_ritual_discovers_a_tier_seven_minion() {
    let mut g = game(206);
    give(&mut g, 0, "BG31_896");
    play_last(&mut g, 0);
    let (_, options) = discover(&g);
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!((d.kind, d.tier), (CardKind::Minion, 7), "{}", d.name);
    }
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(hand(&g), vec![db().get(options[0]).id.clone()]);
}

/// A New Sprout: "Discover a Tier 1 minion."
#[test]
fn a_new_sprout_discovers_a_tier_one_minion() {
    let mut g = game(207);
    g.players[0].tier = 4;
    give(&mut g, 0, "BG33_101");
    play_last(&mut g, 0);
    let (_, options) = discover(&g);
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!((d.kind, d.tier), (CardKind::Minion, 1), "{}", d.name);
    }
    g.apply(0, Action::Choose(2)).unwrap();
    assert_eq!(hand(&g), vec![db().get(options[2]).id.clone()]);
}

/// Search Through Time: "Discover a minion of your Tier. Lock it in your hand for 1 turn."
#[test]
fn search_through_time_discovers_your_tier_and_locks_it_for_a_turn() {
    let mut g = game(208);
    g.players[0].tier = 3;
    give(&mut g, 0, "BG34_330");
    play_last(&mut g, 0);
    let (_, options) = discover(&g);
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!((d.kind, d.tier), (CardKind::Minion, 3), "{}", d.name);
    }
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(hand(&g), vec![db().get(options[0]).id.clone()]);
    let hid = g.players[0].hand[0].hid;
    assert_eq!(g.players[0].hand[0].locked, 1);
    assert!(
        g.apply(0, Action::Play { hand: 0, pos: 0 }).is_err(),
        "locked this turn"
    );
    end_turn_all(&mut g);
    let h = g.players[0].hand.iter().find(|h| h.hid == hid).unwrap();
    assert_eq!(h.locked, 0, "playable next turn");
}

/// Brood of Nozdormu: "Start of Combat: Double your left-most minion's Attack."
#[test]
fn brood_of_nozdormu_doubles_the_left_most_attack() {
    let mut g = game(209);
    g.cfg.record_log = true;
    give(&mut g, 0, "BG34_889");
    play_last(&mut g, 0);
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    g.players[0].board[0].atk = 5;
    g.players[0].board[0].hp = 4;
    g.players[0].board[0].max_hp = 4;
    set_board(&mut g, 1, &[VANILLA]);
    fight(&mut g);
    assert_eq!(after_soc(&g, 0), vec![(10, 4), (3, 3)]);
}

// ------------------------------------------------------------------------------- trinkets

/// Book of Medivh: "Discover a Tavern spell. At the start of each turn, Discover another."
#[test]
fn book_of_medivh_discovers_a_tavern_spell_now_and_each_turn() {
    let mut g = game(301);
    g.players[0].tier = 2;
    buy_trinket(&mut g, "BG30_MagicItem_420");
    let (source, options) = discover(&g);
    assert_eq!(source, cid("BG30_MagicItem_420"));
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!(d.kind, CardKind::TavernSpell, "{}", d.name);
        assert!(d.tier <= 2, "{} above your Tier", d.name);
    }
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(hand(&g), vec![db().get(options[0]).id.clone()]);
    end_turn_all(&mut g);
    let (source, options) = discover(&g);
    assert_eq!(source, cid("BG30_MagicItem_420"));
    assert!(
        options
            .iter()
            .all(|o| db().get(*o).kind == CardKind::TavernSpell)
    );
}

/// Azeroth Model Globe: "At the start of every two turns, gain 2 Gold and Discover a Tier 6
/// minion. (2 turns left!)"
#[test]
fn azeroth_model_globe_pays_and_discovers_every_two_turns() {
    let mut g = game(302);
    let mut ctrl = game(302);
    buy_trinket(&mut g, "BG30_MagicItem_425");
    assert!(g.players[0].pending.is_empty(), "nothing on purchase");
    end_turn_all(&mut g);
    end_turn_all(&mut ctrl);
    assert!(g.players[0].pending.is_empty(), "1 turn left");
    assert_eq!(g.players[0].gold, ctrl.players[0].gold);
    end_turn_all(&mut g);
    end_turn_all(&mut ctrl);
    assert_eq!(g.players[0].gold, ctrl.players[0].gold + 2);
    let (source, options) = discover(&g);
    assert_eq!(source, cid("BG30_MagicItem_425"));
    assert_eq!(options.len(), 3);
    for o in &options {
        let d = db().get(*o);
        assert_eq!((d.kind, d.tier), (CardKind::Minion, 6), "{}", d.name);
    }
}

/// Rockin' Music Box: "Get a random Battlecry minion. At the start of each turn, get another."
#[test]
fn rockin_music_box_gives_a_battlecry_minion_each_turn() {
    let mut g = game(303);
    buy_trinket(&mut g, "BG30_MagicItem_430");
    let check = |g: &Game, n: usize| {
        assert_eq!(g.players[0].hand.len(), n);
        for h in &g.players[0].hand {
            let d = db().get(h.item.card());
            assert_eq!(d.kind, CardKind::Minion);
            assert!(d.mech.has(Mech::BATTLECRY), "{} has no Battlecry", d.name);
        }
    };
    check(&g, 1);
    end_turn_all(&mut g);
    check(&g, 2);
}

/// Nomi Sticker: "After you play an Elemental, give Elementals in the Tavern +3/+2 this game."
#[test]
fn nomi_sticker_buffs_tavern_elementals_after_an_elemental_is_played() {
    let mut g = game(304);
    buy_trinket(&mut g, "BG30_MagicItem_544");
    put_shop(&mut g, SELLEMENTAL);
    let before = shop(&g);
    give(&mut g, 0, VANILLA);
    play_last(&mut g, 0);
    assert_eq!(shop(&g), before, "not an Elemental");
    give(&mut g, 0, SELLEMENTAL);
    play_last(&mut g, 0);
    let after = shop(&g);
    for (b, a) in before.iter().zip(&after) {
        let elemental = db().get(b.0).races.intersects(Races::ELEMENTAL);
        let (da, dh) = if elemental { (3, 2) } else { (0, 0) };
        assert_eq!((a.1, a.2), (b.1 + da, b.2 + dh), "{}", db().get(b.0).name);
    }
    let st = &g.players[0].stats;
    assert_eq!((st.tavern_elemental_atk, st.tavern_elemental_hp), (3, 2), "this game");
}

/// Fish Portrait: "Get a Fish of N'Zoth."
#[test]
fn fish_portrait_gives_a_fish_of_nzoth() {
    let mut g = game(305);
    buy_trinket(&mut g, "BG30_MagicItem_821");
    assert_eq!(hand(&g), vec!["TB_BaconShop_HP_105t".to_string()]);
}

/// Nerglish Phrasebook: "After you play a minion, give the left-most minion in your hand +5/+5."
#[test]
fn nerglish_phrasebook_buffs_the_left_most_hand_minion() {
    let mut g = game(306);
    buy_trinket(&mut g, "BG30_MagicItem_914");
    give(&mut g, 0, "BGS_004"); // Wrath Weaver 1/3
    give(&mut g, 0, VANILLA);
    give(&mut g, 0, VANILLA); // the one played
    play_last(&mut g, 0);
    assert_eq!(hand_stats(&g, 0), (6, 8));
    assert_eq!(hand_stats(&g, 1), (3, 3));
}

/// Booty Bay Brew: "Whenever you spend Gold, give two friendly Pirates +3/+3."
#[test]
fn booty_bay_brew_buffs_two_pirates_when_gold_is_spent() {
    let mut g = game(307);
    buy_trinket(&mut g, "BG30_MagicItem_924");
    set_board(&mut g, 0, &[PIRATE, PIRATE, PIRATE, VANILLA]);
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    let b = stats(&g, 0);
    let buffed = b[..3].iter().filter(|s| **s == (6, 4)).count();
    let plain = b[..3].iter().filter(|s| **s == (3, 1)).count();
    assert_eq!((buffed, plain), (2, 1), "{b:?}");
    assert_eq!(b[3], (3, 3), "not a Pirate");
}

/// Yogg-Tastic Pastry: "Spin the Wheel of Yogg-Saron. At the start of each turn, spin it again."
/// Every wheel outcome changes the hand, warband, Tavern or Gold (but Rod of Roasting may stop
/// at once): the state changes nearly every time it spins.
#[test]
fn yogg_tastic_pastry_spins_the_wheel_now_and_each_turn() {
    let snap = |g: &Game| {
        let p = &g.players[0];
        serde_json::to_string(&(&p.hand, &p.board, &p.shop, p.gold, &p.effects)).unwrap()
    };
    let card = cid("BG30_MagicItem_994");
    let (mut on_attach, mut on_turn) = (0, 0);
    for seed in 0..20 {
        let mut g = game(3080 + seed);
        set_board(&mut g, 0, &[VANILLA, VANILLA]);
        let s0 = snap(&g);
        grant(&mut g, "BG30_MagicItem_994");
        let s1 = snap(&g);
        on_attach += usize::from(s1 != s0);
        let sot = script(card).unwrap().start_of_turn.unwrap();
        g.with_recruit(0, |c| sot(c, me(card)));
        on_turn += usize::from(snap(&g) != s1);
    }
    assert!(on_attach >= 17, "spun on taking it: {on_attach}/20");
    assert!(on_turn >= 17, "spun at turn start: {on_turn}/20");
}

/// Sellemental Portrait: "Get a Sellemental. At the start of each turn, get another."
#[test]
fn sellemental_portrait_gives_a_sellemental_each_turn() {
    let mut g = game(309);
    buy_trinket(&mut g, "BG32_MagicItem_831");
    assert_eq!(hand(&g), vec![SELLEMENTAL.to_string()]);
    end_turn_all(&mut g);
    assert_eq!(hand(&g), vec![SELLEMENTAL.to_string(), SELLEMENTAL.to_string()]);
}

/// Explorer's Binoculars: "Get three random Tier 4 minions."
#[test]
fn explorers_binoculars_gives_three_tier_four_minions() {
    let mut g = game(310);
    buy_trinket(&mut g, "BG32_MagicItem_858");
    assert_eq!(g.players[0].hand.len(), 3);
    for h in &g.players[0].hand {
        let d = db().get(h.item.card());
        assert_eq!((d.kind, d.tier), (CardKind::Minion, 4), "{}", d.name);
    }
}

/// Vibrant Bubble: "Spellcraft: Give a Murloc a random Bonus Keyword."
#[test]
fn vibrant_bubble_gives_a_murloc_a_bonus_keyword_each_turn() {
    let mut g = game(311);
    buy_trinket(&mut g, "BG32_MagicItem_892");
    assert_eq!(hand(&g), vec!["BG32_MagicItem_892t".to_string()]);
    assert!(g.players[0].hand[0].temporary, "a Spellcraft spell");
    set_board(&mut g, 0, &[VANILLA, "BG32_330"]); // Flighty Scout, a Murloc
    let murloc = g.players[0].board[1].eid;
    play_last(&mut g, 0);
    let Some(Pending::Target { options, .. }) = g.players[0].pending.last() else {
        panic!("expected a target choice")
    };
    assert_eq!(options, &vec![murloc], "Murlocs only");
    g.apply(0, Action::Choose(0)).unwrap();
    let got = content::BONUS_KWS
        .iter()
        .filter(|k| g.players[0].board[1].has(**k))
        .count();
    assert_eq!(got, 1);
    end_turn_all(&mut g);
    assert_eq!(hand(&g), vec!["BG32_MagicItem_892t".to_string()], "a new one");
}

/// Bluegill Flippers: "Whenever you cast a Tavern spell, give the left-most minion in your hand
/// and warband +3/+3."
#[test]
fn bluegill_flippers_buff_left_most_hand_and_board_minions() {
    let mut g = game(312);
    buy_trinket(&mut g, "BG32_MagicItem_893");
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    give(&mut g, 0, "BGS_004");
    give(&mut g, 0, VANILLA);
    give(&mut g, 0, THEM_APPLES);
    play_last(&mut g, 0);
    assert_eq!(hand_stats(&g, 0), (4, 6));
    assert_eq!(hand_stats(&g, 1), (3, 3));
    assert_eq!(stats(&g, 0), vec![(6, 6), (3, 3)]);
}

/// Cursed Crystal: "After the Tavern is Refreshed, give its minions +2/+2 this turn."
#[test]
fn cursed_crystal_buffs_the_refreshed_tavern_for_this_turn() {
    let mut g = game(313);
    let before = shop(&g);
    buy_trinket(&mut g, "BG35_MagicItem_150");
    assert_eq!(shop(&g), before, "only after a Refresh");
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    let slots: Vec<&Minion> = g.players[0]
        .shop
        .iter()
        .filter_map(|s| s.item.as_minion())
        .collect();
    assert!(!slots.is_empty());
    for m in slots {
        let (ba, bh) = base(m.card);
        assert_eq!((m.atk, m.hp), (ba + 2, bh + 2), "{}", m.name());
        assert_eq!((m.temp_atk, m.temp_hp), (2, 2), "this turn only");
    }
}

/// Scraper Sticker: "Get a random Magnetic Mech. At the start of each turn, get another."
#[test]
fn scraper_sticker_gives_a_magnetic_mech_each_turn() {
    let mut g = game_with(314, &["MECHANICAL"]);
    g.players[0].tier = 3;
    buy_trinket(&mut g, "BG35_MagicItem_301");
    let check = |g: &Game, n: usize| {
        assert_eq!(g.players[0].hand.len(), n);
        for h in &g.players[0].hand {
            let d = db().get(h.item.card());
            assert!(d.races.intersects(Races::MECH), "{} not a Mech", d.name);
            assert!(d.mech.has(Mech::MAGNETIC), "{} not Magnetic", d.name);
        }
    };
    check(&g, 1);
    end_turn_all(&mut g);
    check(&g, 2);
}

/// Stormcoil Sticker: "After 5 friendly minions die, get a random Mech. (5 left!)"
#[test]
fn stormcoil_sticker_gives_a_mech_after_five_friendly_deaths() {
    let mut g = game_with(315, &["MECHANICAL"]);
    buy_trinket(&mut g, "BG35_MagicItem_302");
    set_board(&mut g, 0, &[VANILLA; 5]);
    let kill = |g: &mut Game, n: usize| {
        let mut c = combat_ctx(g);
        let eids: Vec<u32> = c.boards[0].iter().take(n).map(|m| m.eid).collect();
        for e in eids {
            c.destroy(e);
            c.resolve_deaths();
        }
    };
    kill(&mut g, 4);
    assert!(g.players[0].hand.is_empty(), "1 left");
    kill(&mut g, 5);
    assert_eq!(g.players[0].hand.len(), 1);
    let d = db().get(g.players[0].hand[0].item.card());
    assert!(d.races.intersects(Races::MECH), "{} not a Mech", d.name);
    assert_eq!(d.kind, CardKind::Minion);
}

/// Jailer Sticker: "Spellcraft: Destroy a friendly Undead to get a random Undead."
#[test]
fn jailer_sticker_trades_a_friendly_undead_for_a_random_one() {
    let mut g = game_with(316, &["UNDEAD"]);
    g.players[0].tier = 2;
    buy_trinket(&mut g, "BG35_MagicItem_306");
    assert_eq!(hand(&g), vec!["BG35_MagicItem_306t".to_string()]);
    set_board(&mut g, 0, &[VANILLA, "BG25_008"]); // Eternal Knight, an Undead
    let undead = g.players[0].board[1].eid;
    play_last(&mut g, 0);
    let Some(Pending::Target { options, .. }) = g.players[0].pending.last() else {
        panic!("expected a target choice")
    };
    assert_eq!(options, &vec![undead], "friendly Undead only");
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(g.players[0].board.len(), 1, "the Undead is destroyed");
    assert_eq!(g.players[0].board[0].card, cid(VANILLA));
    assert_eq!(g.players[0].hand.len(), 1);
    let d = db().get(g.players[0].hand[0].item.card());
    assert!(d.races.intersects(Races::UNDEAD), "{} not Undead", d.name);
    assert_eq!(d.kind, CardKind::Minion);
}

/// Magician's Top Hat: "Get two minions each from Tiers 1, 2, and 3."
#[test]
fn magicians_top_hat_gives_two_minions_of_tiers_one_to_three() {
    let mut g = game(317);
    buy_trinket(&mut g, "BG35_MagicItem_815");
    let mut tiers: Vec<u8> = g.players[0]
        .hand
        .iter()
        .map(|h| {
            let d = db().get(h.item.card());
            assert_eq!(d.kind, CardKind::Minion);
            d.tier
        })
        .collect();
    tiers.sort();
    assert_eq!(tiers, vec![1, 1, 2, 2, 3, 3]);
}

/// Lens Case: "Get a Duplicating Lens. At the start of every 2 turns, repeat this. (2 turns
/// left!)"
#[test]
fn lens_case_gives_a_duplicating_lens_every_two_turns() {
    let lens = "BG35_MagicItem_817t";
    let mut g = game(318);
    buy_trinket(&mut g, "BG35_MagicItem_817");
    assert_eq!(hand(&g), vec![lens.to_string()]);
    end_turn_all(&mut g);
    assert_eq!(hand(&g), vec![lens.to_string()], "1 turn left");
    end_turn_all(&mut g);
    assert_eq!(hand(&g), vec![lens.to_string(), lens.to_string()]);
    // The Lens: "Choose a minion from Tier 3 or below. Get a plain copy of it."
    set_board(&mut g, 0, &[VANILLA]);
    cast_on(&mut g, 0, 0);
    assert_eq!(hand(&g), vec![lens.to_string(), VANILLA.to_string()]);
}

/// Chromatic Tear: "Get a random Chromadrake. At the start of each turn, repeat this."
#[test]
fn chromatic_tear_gives_a_chromadrake_each_turn() {
    let mut g = game(319);
    buy_trinket(&mut g, "BG35_MagicItem_840");
    let check = |g: &Game, n: usize| {
        let h = hand(g);
        assert_eq!(h.len(), n);
        assert!(h.iter().all(|x| content::CHROMADRAKES.contains(&x.as_str())), "{h:?}");
    };
    check(&g, 1);
    end_turn_all(&mut g);
    check(&g, 2);
}

/// Pocket Cyclone: "Cast Easterly Winds. At the start of each turn, cast it again." (Easterly
/// Winds: "After the Tavern is Refreshed this game, give a random minion in it +9/+9.")
#[test]
fn pocket_cyclone_casts_easterly_winds_now_and_each_turn() {
    let winds = cid("BG34_444");
    let stacks = |g: &Game| {
        g.players[0]
            .effects
            .iter()
            .find(|e| e.card == winds)
            .map_or(0, |e| e.stacks)
    };
    let extra = |g: &Game| {
        shop(g).iter().fold((0, 0), |(sa, sh), (card, a, h)| {
            let (ba, bh) = base(*card);
            (sa + a - ba, sh + h - bh)
        })
    };
    let mut g = game(320);
    buy_trinket(&mut g, "BG35_MagicItem_850");
    assert_eq!(stacks(&g), 1);
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    assert_eq!(extra(&g), (9, 9));
    end_turn_all(&mut g);
    assert_eq!(stacks(&g), 2, "cast again");
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    assert_eq!(extra(&g), (18, 18));
}

/// Sunken Anchor: "Get 2 random Bounties. At the start of each turn, repeat this."
#[test]
fn sunken_anchor_gives_two_bounties_each_turn() {
    let mut g = game(321);
    buy_trinket(&mut g, "BG35_MagicItem_890");
    let check = |g: &Game, n: usize| {
        let h = hand(g);
        assert_eq!(h.len(), n);
        assert!(h.iter().all(|x| content::BOUNTIES.contains(&x.as_str())), "{h:?}");
    };
    check(&g, 2);
    end_turn_all(&mut g);
    check(&g, 4);
}

/// Dragon Skull: "Whenever you trigger a Battlecry, give your left- and right-most minions
/// +5/+5."
#[test]
fn dragon_skull_buffs_the_end_minions_on_a_battlecry() {
    let mut g = game(322);
    buy_trinket(&mut g, "BG36_MagicItem_203");
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    give(&mut g, 0, VANILLA); // no Battlecry
    play_at(&mut g, 1);
    assert_eq!(stats(&g, 0), vec![(3, 3), (3, 3), (3, 3)]);
    give(&mut g, 0, PIRATE); // Southsea Busker, Battlecry
    play_at(&mut g, 1);
    assert_eq!(stats(&g, 0), vec![(8, 8), (3, 1), (3, 3), (8, 8)]);
}

/// Gold Mallet: "At the end of your turn, give your minions +1/+1."
#[test]
fn gold_mallet_buffs_your_minions_at_end_of_turn() {
    let mut g = game(323);
    buy_trinket(&mut g, "BG36_MagicItem_302");
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(stats(&g, 0), vec![(4, 4), (4, 4)]);
}

/// Gold Mallet: "(Improved by Golden minions you've played this game!)"
#[test]
fn gold_mallet_is_improved_by_golden_minions_played() {
    let mut g = game(324);
    buy_trinket(&mut g, "BG36_MagicItem_302");
    set_board(&mut g, 0, &[VANILLA]);
    give(&mut g, 0, "BG36_345_G"); // a Golden 6/6
    play_last(&mut g, 0);
    assert_eq!(g.players[0].stats.golden_played, 1);
    g.players[0].pending.clear();
    g.players[0].hand.clear(); // the Triple Reward
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(stats(&g, 0), vec![(5, 5), (8, 8)], "+2/+2 after one Golden");
}

/// Wand of Divination: "After you cast 2 spells on minions, gain 1 Gold. (2 left!)"
#[test]
fn wand_of_divination_gains_gold_every_second_spell_on_a_minion() {
    let mut g = game(325);
    buy_trinket(&mut g, "BG36_MagicItem_307");
    set_board(&mut g, 0, &[VANILLA, VANILLA]);
    g.players[0].gold = 5;
    give(&mut g, 0, THEM_APPLES); // not on a minion
    play_last(&mut g, 0);
    give(&mut g, 0, SACRED_GIFT);
    cast_on(&mut g, 0, 0);
    assert_eq!(g.players[0].gold, 5, "1 left");
    give(&mut g, 0, SACRED_GIFT);
    cast_on(&mut g, 0, 1);
    assert_eq!(g.players[0].gold, 6);
}

/// Mindslasher Portrait: "Get a Vicious Mindslasher. Your Vicious Mindslashers also give stats
/// to adjacent minions." (Mindslasher: "Whenever you cast a Tavern spell, give this and your
/// Deity +1/+2.")
#[test]
fn mindslasher_portrait_makes_mindslashers_buff_their_neighbours() {
    let mut g = game(326);
    buy_trinket(&mut g, "BG36_MagicItem_402");
    assert_eq!(hand(&g), vec!["BG36_108".to_string()]);
    set_board(&mut g, 0, &[VANILLA, VANILLA, VANILLA]);
    play_at(&mut g, 1); // [Prisonguard, Mindslasher, Prisonguard, Prisonguard]
    give(&mut g, 0, THEM_APPLES);
    play_last(&mut g, 0);
    assert_eq!(stats(&g, 0), vec![(4, 5), (2, 4), (4, 5), (3, 3)]);
}

/// Rascal Sticker: "Gain 1 Gold for each friendly Golden minion. At the start of your turn,
/// repeat this."
#[test]
fn rascal_sticker_pays_per_golden_minion_now_and_each_turn() {
    let mut g = game(327);
    let mut ctrl = game(327);
    for x in [&mut g, &mut ctrl] {
        set_board(x, 0, &["BG36_345_G", VANILLA, "BG36_345_G"]);
    }
    g.players[0].gold = db().get(cid("BG36_MagicItem_424")).cost;
    buy_trinket(&mut g, "BG36_MagicItem_424");
    assert_eq!(g.players[0].gold, 2);
    end_turn_all(&mut g);
    end_turn_all(&mut ctrl);
    assert_eq!(g.players[0].gold, ctrl.players[0].gold + 2);
}

/// Demonic Bloodletter: "Whenever you cast a Tavern spell, give minions in the Tavern +1/+1 this
/// game."
#[test]
fn demonic_bloodletter_buffs_the_tavern_on_each_tavern_spell() {
    let mut g = game(328);
    buy_trinket(&mut g, "BG36_MagicItem_800");
    let before = shop(&g);
    give(&mut g, 0, CORRUPTED_COIN);
    play_last(&mut g, 0);
    for (b, a) in before.iter().zip(&shop(&g)) {
        assert_eq!((a.1, a.2), (b.1 + 1, b.2 + 1), "{}", db().get(b.0).name);
    }
    let st = &g.players[0].stats;
    assert_eq!((st.tavern_atk, st.tavern_hp), (1, 1));
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    for (card, a, h) in shop(&g) {
        let (ba, bh) = base(card);
        assert_eq!((a, h), (ba + 1, bh + 1), "this game: {}", db().get(card).name);
    }
}

/// Flighty Portrait: "Get a Flighty Scout. After you cast a Tavern spell, give Flighty Scouts in
/// your hand and warband +3/+3."
#[test]
fn flighty_portrait_buffs_flighty_scouts_in_hand_and_warband() {
    let mut g = game(329);
    buy_trinket(&mut g, "BG36_MagicItem_820");
    assert_eq!(hand(&g), vec!["BG32_330".to_string()]);
    set_board(&mut g, 0, &["BG32_330", VANILLA]);
    give(&mut g, 0, VANILLA);
    give(&mut g, 0, THEM_APPLES);
    play_last(&mut g, 0);
    assert_eq!(hand_stats(&g, 0), (6, 6), "Scout in hand");
    assert_eq!(hand_stats(&g, 1), (3, 3), "not a Scout");
    assert_eq!(stats(&g, 0), vec![(6, 6), (3, 3)]);
}
