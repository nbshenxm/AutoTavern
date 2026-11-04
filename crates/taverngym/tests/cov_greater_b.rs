//! Card-text tests of Greater Trinkets that had no coverage (never checked against game logs):
//! each test pins one trinket's behaviour to its card text.

mod common;
use common::*;

use taverngym::cards::CardKind;
use taverngym::debug::{DebugCmd, run_debug};
use taverngym::state::{DeityState, ShopSlot};
use taverngym::types::Mech;

const PRISONGUARD: &str = "BG36_345"; // Suspicious Prisonguard 3/3, no type
const BANDIT: &str = "BG33_822"; // Bigwig Bandit 4/6 Pirate, Rally: get a random Bounty
const BANANA: &str = "BG28_897"; // Tavern Dish Banana: Tavern spell, give a minion +2/+2
const BLOOD_GEM: &str = "BG20_GEM"; // not a Tavern spell: give a minion +1/+1
const GEOMANCER: &str = "BG20_100"; // Razorfen Geomancer: Battlecry: get 2 Blood Gems
const ZOATROID: &str = "BG36_098"; // 3/2 Aberration
const TAD: &str = "BG22_202"; // 2/2 Murloc, no Battlecry
const SELLEMENTAL: &str = "BGS_115"; // 3/3 Elemental, no Battlecry
const ACCORD: &str = "BG26_147"; // Accord-o-Tron, a Mech
const BELLRINGER: &str = "BG36_511"; // Dead Bellringer 3/6 Undead, no Deathrattle
const PLAGUERUNNER: &str = "BG34_690";
const WEAVER: &str = "BGS_004"; // Wrath Weaver 1/3

/// Give player 0 the trinket `id` (its `on_attach` runs); open choices are dropped.
fn trinket(g: &mut Game, id: &str) -> CardId {
    let card = id.to_string();
    run_debug(g, DebugCmd::GiveTrinket { p: 0, card }).unwrap();
    g.players[0].pending.clear();
    cid(id)
}

fn hand_cards(g: &Game) -> Vec<CardId> {
    g.players[0].hand.iter().map(|h| h.item.card()).collect()
}

fn count_in_hand(g: &Game, id: &str) -> usize {
    hand_cards(g).into_iter().filter(|c| *c == cid(id)).count()
}

fn start_of_turn(g: &mut Game) {
    g.with_recruit(0, |c| {
        c.run_player_hook(0, |s| s.start_of_turn, "start of turn")
    });
}

fn end_of_turn(g: &mut Game) {
    g.with_recruit(0, |c| c.run_player_hook(0, |s| s.end_of_turn, "end of turn"));
}

fn put_shop_minion(g: &mut Game, id: &str) -> (usize, u32) {
    let m = minion(g, 0, id);
    let sid = m.eid;
    g.players[0].shop.push(ShopSlot::new(sid, Item::Minion(m)));
    (g.players[0].shop.len() - 1, sid)
}

fn put_shop_spell(g: &mut Game, id: &str) -> usize {
    let sid = 900_000 + g.players[0].shop.len() as u32;
    g.players[0]
        .shop
        .push(ShopSlot::new(sid, Item::spell(cid(id))));
    g.players[0].shop.len() - 1
}

/// Give `id` and play it at the right end of the warband.
fn give_and_play(g: &mut Game, id: &str) {
    give(g, 0, id);
    play_last(g, 0);
    while g.players[0].pending.last().is_some() {
        g.apply(0, Action::Choose(0)).unwrap();
    }
}

fn set_deity(g: &mut Game, atk: i32, hp: i32) {
    g.players[0].deity = Some(DeityState {
        card: cid("BGFYM_000"),
        atk,
        hp,
        golden: false,
        reborn: false,
    });
}

// BG35_MagicItem_710 Miniature Ship: "After you cast a Tavern spell, give your Pirates +4/+4."
#[test]
fn miniature_ship() {
    let mut g = game(1);
    trinket(&mut g, "BG35_MagicItem_710");
    set_board(&mut g, 0, &[BANDIT, PRISONGUARD]);
    give(&mut g, 0, BANANA);
    cast_on(&mut g, 0, 1);
    assert_eq!(stats(&g, 0), vec![(4 + 4, 6 + 4), (3 + 2, 3 + 2)]);
    // A spell that is not a Tavern spell (Blood Gem) does nothing.
    give(&mut g, 0, BLOOD_GEM);
    cast_on(&mut g, 0, 1);
    assert_eq!(stats(&g, 0), vec![(8, 10), (6, 6)]);
}

// BG35_MagicItem_712 Privateer Portrait: "Get a Proud Privateer and 2 random Bounties. At the
// start of each turn, get another 2 Bounties."
#[test]
fn privateer_portrait() {
    let mut g = game(2);
    trinket(&mut g, "BG35_MagicItem_712");
    let bounties = |g: &Game| {
        hand_cards(g)
            .into_iter()
            .filter(|c| taverngym::content::is_bounty(*c))
            .count()
    };
    assert_eq!(count_in_hand(&g, "BG33_825"), 1, "a Proud Privateer");
    assert_eq!(bounties(&g), 2);
    assert_eq!(g.players[0].hand.len(), 3);
    start_of_turn(&mut g);
    assert_eq!(bounties(&g), 4, "2 more at the start of the turn");
    assert_eq!(count_in_hand(&g, "BG33_825"), 1, "only one Privateer");
}

// BG35_MagicItem_713 Trusty Crowbar: "Whenever you get a Pirate, give your left-most minion
// +20/+20."
#[test]
fn trusty_crowbar() {
    let mut g = game(3);
    trinket(&mut g, "BG35_MagicItem_713");
    set_board(&mut g, 0, &[PRISONGUARD, WEAVER]);
    give(&mut g, 0, BANDIT);
    assert_eq!(stats(&g, 0), vec![(3 + 20, 3 + 20), (1, 3)]);
    // Getting a non-Pirate does nothing.
    give(&mut g, 0, PRISONGUARD);
    assert_eq!(stats(&g, 0), vec![(23, 23), (1, 3)]);
}

// BG35_MagicItem_733 Jailer Sticker: "Spellcraft: Destroy a friendly Undead to get 2 random
// Undead."
#[test]
fn jailer_sticker() {
    let mut g = game(4);
    g.players[0].tier = 6;
    trinket(&mut g, "BG35_MagicItem_733");
    assert_eq!(hand_cards(&g), vec![cid("BG35_MagicItem_733t")], "the Spellcraft spell");
    set_board(&mut g, 0, &[BELLRINGER]);
    cast_on(&mut g, 0, 0);
    assert!(g.players[0].board.is_empty(), "the Undead is destroyed");
    let hand = hand_cards(&g);
    assert_eq!(hand.len(), 2);
    for c in hand {
        let d = db().get(c);
        assert!(d.is_minion() && d.races.intersects(Races::UNDEAD), "{}", d.name);
    }
    // Spellcraft: a new copy each turn.
    g.players[0].hand.clear();
    start_of_turn(&mut g);
    assert_eq!(hand_cards(&g), vec![cid("BG35_MagicItem_733t")]);
}

// BG35_MagicItem_750 Magicfin Sticker: "After you buy a Tavern spell, get a 1/1 Murloc and teach
// it that spell. (2 times per turn.)"
#[test]
fn magicfin_sticker() {
    let mut g = game(5);
    trinket(&mut g, "BG35_MagicItem_750");
    g.players[0].shop.clear();
    for _ in 0..3 {
        put_shop_spell(&mut g, BANANA);
    }
    g.players[0].gold = 10;
    for _ in 0..3 {
        g.apply(0, Action::Buy(0)).unwrap();
    }
    assert_eq!(count_in_hand(&g, BANANA), 3);
    let fins: Vec<&Minion> = g.players[0]
        .hand
        .iter()
        .filter_map(|h| h.item.as_minion())
        .collect();
    assert_eq!(fins.len(), 2, "2 times per turn");
    for m in fins {
        assert!(m.is(Races::MURLOC));
        assert_eq!((m.atk, m.hp), (1, 1));
        assert_eq!(m.counter, cid(BANANA).0 as i32 + 1, "taught the bought spell");
    }
    // Buying a minion gives nothing.
    let mut g = game(5);
    trinket(&mut g, "BG35_MagicItem_750");
    g.players[0].shop.clear();
    put_shop_minion(&mut g, PRISONGUARD);
    g.players[0].gold = 10;
    g.apply(0, Action::Buy(0)).unwrap();
    assert_eq!(hand_cards(&g), vec![cid(PRISONGUARD)]);
}

// BG35_MagicItem_752 Young Murk-Eye Sticker: "At the end of your turn, trigger your left and
// right- most minions' Battlecries."
#[test]
fn young_murk_eye_sticker() {
    let mut g = game(6);
    trinket(&mut g, "BG35_MagicItem_752");
    set_board(&mut g, 0, &[GEOMANCER, GEOMANCER, PRISONGUARD, GEOMANCER]);
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(
        count_in_hand(&g, BLOOD_GEM),
        4,
        "two Battlecries (left- and right-most) of 2 Blood Gems each"
    );
    // A single minion is both: its Battlecry triggers once.
    let mut g = game(6);
    trinket(&mut g, "BG35_MagicItem_752");
    set_board(&mut g, 0, &[GEOMANCER]);
    end_of_turn(&mut g);
    assert_eq!(count_in_hand(&g, BLOOD_GEM), 2);
}

// BG35_MagicItem_816t Orb of the Unknown: "Get a random Greater Trinket and 4 Gold."
#[test]
fn orb_of_the_unknown() {
    for seed in 7..12 {
        let mut g = game(seed);
        g.players[0].trinkets.clear();
        g.players[0].gold = 3;
        trinket(&mut g, "BG35_MagicItem_816t");
        let t = &g.players[0].trinkets;
        assert_eq!(t.len(), 2, "the Orb and the new trinket");
        assert_eq!(db().get(t[1]).kind, CardKind::TrinketGreater, "{}", db().get(t[1]).name);
        assert_ne!(t[1], cid("BG35_MagicItem_816t"));
        assert!(g.players[0].gold >= 3 + 4, "4 Gold");
    }
}

// BG35_MagicItem_861 Baller Portrait: "Get a Temperature Shift. After you play 11 Elementals,
// repeat this. (11 left!)"
#[test]
fn baller_portrait() {
    let mut g = game(13);
    trinket(&mut g, "BG35_MagicItem_861");
    assert_eq!(hand_cards(&g), vec![cid("BG31_819")]);
    for i in 0..11 {
        if g.players[0].board.len() >= 6 {
            g.players[0].board.clear();
        }
        give_and_play(&mut g, SELLEMENTAL);
        let want = if i < 10 { 1 } else { 2 };
        assert_eq!(count_in_hand(&g, "BG31_819"), want, "after {} Elementals", i + 1);
    }
    // Non-Elementals don't count.
    for _ in 0..11 {
        g.players[0].board.clear();
        give_and_play(&mut g, PRISONGUARD);
    }
    assert_eq!(count_in_hand(&g, "BG31_819"), 2);
}

// BG35_MagicItem_862 Upstart Embers: "After you Refresh, double the stats of the highest- Health
// minion in the Tavern."
#[test]
fn upstart_embers() {
    let shop = |g: &Game| -> Vec<(CardId, i32, i32)> {
        g.players[0]
            .shop
            .iter()
            .filter_map(|s| s.item.as_minion())
            .map(|m| (m.card, m.atk, m.hp))
            .collect()
    };
    let mut plain = game(14);
    let mut g = game(14);
    trinket(&mut g, "BG35_MagicItem_862");
    for x in [&mut plain, &mut g] {
        x.players[0].gold = 10;
        x.apply(0, Action::Refresh).unwrap();
    }
    let (base, got) = (shop(&plain), shop(&g));
    assert_eq!(base.len(), got.len());
    let max_hp = base.iter().map(|m| m.2).max().unwrap();
    let diff: Vec<usize> = (0..base.len()).filter(|i| base[*i] != got[*i]).collect();
    assert_eq!(diff.len(), 1, "one minion changed: {base:?} -> {got:?}");
    let i = diff[0];
    assert_eq!(got[i].0, base[i].0);
    assert_eq!(base[i].2, max_hp, "the highest-Health one");
    assert_eq!((got[i].1, got[i].2), (base[i].1 * 2, base[i].2 * 2), "doubled");
}

// BG36_MagicItem_204 Plaguerunner Portrait: "Get a Plaguerunner. After you destroy a
// Plaguerunner outside combat, get a plain copy."
#[test]
fn plaguerunner_portrait() {
    let mut g = game(15);
    trinket(&mut g, "BG36_MagicItem_204");
    assert_eq!(hand_cards(&g), vec![cid(PLAGUERUNNER)]);
    // A golden one on the board, destroyed in the recruit phase: a plain copy.
    set_board(&mut g, 0, &["BG34_690_G"]);
    g.with_recruit(0, |c| {
        let e = c.boards[0][0].eid;
        c.destroy(e);
        c.resolve_deaths();
    });
    assert!(g.players[0].board.is_empty());
    assert_eq!(count_in_hand(&g, PLAGUERUNNER), 2, "a plain copy");
    // In combat: nothing.
    set_board(&mut g, 0, &[PLAGUERUNNER]);
    set_board(&mut g, 1, &[PRISONGUARD]);
    let mut c = combat_ctx(&mut g);
    let e = c.boards[0][0].eid;
    c.destroy(e);
    c.resolve_deaths();
    drop(c);
    assert_eq!(count_in_hand(&g, PLAGUERUNNER), 2, "not in combat");
}

// BG36_MagicItem_214 Insurrectionist's Blade: "At the end of your turn, trigger all friendly
// Rallies."
#[test]
fn insurrectionists_blade() {
    let bounties = |g: &Game| {
        hand_cards(g)
            .into_iter()
            .filter(|c| taverngym::content::is_bounty(*c))
            .count()
    };
    let mut g = game(16);
    trinket(&mut g, "BG36_MagicItem_214");
    set_board(&mut g, 0, &[BANDIT, PRISONGUARD, BANDIT, BANDIT]);
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(bounties(&g), 3, "each Bandit's Rally: a Bounty");
    // Without the trinket: nothing.
    let mut g = game(16);
    set_board(&mut g, 0, &[BANDIT, PRISONGUARD, BANDIT, BANDIT]);
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(bounties(&g), 0);
}

// BG36_MagicItem_217 Funeral Wreath: "After a friendly minion is Reborn, get a plain copy of it.
// (3 times per combat.)"
#[test]
fn funeral_wreath() {
    let mut g = game(17);
    trinket(&mut g, "BG36_MagicItem_217");
    set_board(&mut g, 0, &["BG36_345_G", PRISONGUARD, PRISONGUARD, PRISONGUARD]);
    for m in g.players[0].board.iter_mut() {
        m.give(Kw::REBORN);
    }
    set_board(&mut g, 1, &[WEAVER]);
    let mut c = combat_ctx(&mut g);
    for _ in 0..4 {
        let e = c.boards[0].iter().find(|m| m.has(Kw::REBORN)).unwrap().eid;
        c.destroy(e);
        c.resolve_deaths();
    }
    assert_eq!(c.boards[0].len(), 4, "all four came back");
    drop(c);
    assert_eq!(
        hand_cards(&g),
        vec![cid(PRISONGUARD); 3],
        "plain copies, 3 times per combat"
    );
    // A new combat: 3 more.
    g.players[0].hand.clear();
    let mut c = combat_ctx(&mut g);
    let e = c.boards[0][0].eid;
    c.destroy(e);
    c.resolve_deaths();
    drop(c);
    assert_eq!(hand_cards(&g), vec![cid(PRISONGUARD)]);
}

// BG36_MagicItem_303t Glass of Perspective: "Get 2 random Choose One cards. At the start of each
// turn, get 2 more."
#[test]
fn glass_of_perspective() {
    let mut g = game(18);
    g.players[0].tier = 6;
    trinket(&mut g, "BG36_MagicItem_303t");
    let choose_one = |g: &Game| {
        let h = hand_cards(g);
        assert!(
            h.iter().all(|c| db().get(*c).mech.has(Mech::CHOOSE_ONE)),
            "{h:?}"
        );
        h.len()
    };
    assert_eq!(choose_one(&g), 2);
    start_of_turn(&mut g);
    assert_eq!(choose_one(&g), 4);
}

// BG36_MagicItem_404t Corrupted Baton: "After you cast a Tavern spell, give your Deity +10/+10."
#[test]
fn corrupted_baton() {
    let mut g = game(19);
    set_deity(&mut g, 5, 6);
    trinket(&mut g, "BG36_MagicItem_404t");
    set_board(&mut g, 0, &[PRISONGUARD]);
    give(&mut g, 0, BANANA);
    cast_on(&mut g, 0, 0);
    let d = g.players[0].deity.as_ref().unwrap();
    assert_eq!((d.atk, d.hp), (15, 16));
    // Not a Tavern spell: nothing.
    give(&mut g, 0, BLOOD_GEM);
    cast_on(&mut g, 0, 0);
    let d = g.players[0].deity.as_ref().unwrap();
    assert_eq!((d.atk, d.hp), (15, 16));
}

// BG36_MagicItem_406 Shath'Yar Shrine: "After you discard a spell, get a random Aberration."
#[test]
fn shathyar_shrine() {
    let mut g = game(20);
    trinket(&mut g, "BG36_MagicItem_406");
    let spell = give(&mut g, 0, BANANA);
    g.with_recruit(0, |c| taverngym::recruit::discard_card(c, 0, spell))
        .unwrap();
    let hand = hand_cards(&g);
    assert_eq!(hand.len(), 1);
    let d = db().get(hand[0]);
    assert!(d.is_minion() && d.races.intersects(Races::ABERRATION), "{}", d.name);
    // Discarding a minion gives nothing.
    g.players[0].hand.clear();
    let m = give(&mut g, 0, PRISONGUARD);
    g.with_recruit(0, |c| taverngym::recruit::discard_card(c, 0, m))
        .unwrap();
    assert!(g.players[0].hand.is_empty());
}

// BG36_MagicItem_416 Evil Experiment: "After your Deity awakens, give it Reborn."
#[test]
fn evil_experiment() {
    for with in [true, false] {
        let mut g = game(21);
        set_deity(&mut g, 7, 7);
        if with {
            trinket(&mut g, "BG36_MagicItem_416");
        }
        set_board(&mut g, 0, &[ZOATROID, ZOATROID, ZOATROID, ZOATROID]);
        set_board(&mut g, 1, &[PRISONGUARD]);
        let mut c = combat_ctx(&mut g);
        for _ in 0..4 {
            let e = c.boards[0]
                .iter()
                .find(|m| m.is_card(ZOATROID))
                .unwrap()
                .eid;
            c.destroy(e);
            c.resolve_deaths();
        }
        let e = c.cs[0].deity_eid;
        assert_ne!(e, 0, "the Deity awakened");
        let deity = c.boards[0].iter().find(|m| m.eid == e).unwrap();
        assert_eq!(deity.has(Kw::REBORN), with, "Reborn with the trinket only");
    }
}

// BG36_MagicItem_418 Tome of the Ancients: "After you discard 3 cards, your Tavern spells give an
// extra +1/+1 this game. (3 left!)"
#[test]
fn tome_of_the_ancients() {
    let mut g = game(22);
    trinket(&mut g, "BG36_MagicItem_418");
    let discard = |g: &mut Game| {
        let h = give(g, 0, PRISONGUARD);
        g.with_recruit(0, |c| taverngym::recruit::discard_card(c, 0, h))
            .unwrap();
    };
    let extra = |g: &mut Game| g.with_recruit(0, |c| c.spell_extra(0));
    discard(&mut g);
    discard(&mut g);
    assert_eq!(extra(&mut g), (0, 0));
    discard(&mut g);
    assert_eq!(extra(&mut g), (1, 1));
    set_board(&mut g, 0, &[PRISONGUARD]);
    give(&mut g, 0, BANANA);
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0), vec![(3 + 2 + 1, 3 + 2 + 1)]);
    // The next 3 discards: another +1/+1.
    for _ in 0..3 {
        discard(&mut g);
    }
    assert_eq!(extra(&mut g), (2, 2));
}

// BG36_MagicItem_423t Volumizer Portrait: "Get 2 random Magnetic Volumizers. At the start of each
// turn, repeat this."
#[test]
fn volumizer_portrait() {
    let mut g = game(23);
    trinket(&mut g, "BG36_MagicItem_423t");
    let volumizers = |g: &Game| {
        let h = hand_cards(g);
        assert!(
            h.iter()
                .all(|c| taverngym::content::VOLUMIZERS.contains(&db().get(*c).id.as_str())),
            "{h:?}"
        );
        assert!(h.iter().all(|c| db().get(*c).mech.has(Mech::MAGNETIC)));
        h.len()
    };
    assert_eq!(volumizers(&g), 2);
    start_of_turn(&mut g);
    assert_eq!(volumizers(&g), 4);
}

// BG36_MagicItem_830 Bloodfury Shield: "Whenever you cast a Tavern spell, add a Fodder to your
// next Refresh."
#[test]
fn bloodfury_shield() {
    let mut g = game(24);
    trinket(&mut g, "BG36_MagicItem_830");
    set_board(&mut g, 0, &[PRISONGUARD]); // not a Demon: the Fodders wait in the Tavern
    for _ in 0..2 {
        give(&mut g, 0, BANANA);
        cast_on(&mut g, 0, 0);
    }
    give(&mut g, 0, BLOOD_GEM); // not a Tavern spell
    cast_on(&mut g, 0, 0);
    assert_eq!(g.players[0].fodder_queue, vec![2]);
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    let fodders = g.players[0]
        .shop
        .iter()
        .filter_map(|s| s.item.as_minion())
        .filter(|m| m.is_card("BG35_150t"))
        .count();
    assert_eq!(fodders, 2, "both in the next Refresh");
    assert!(g.players[0].fodder_queue.iter().all(|n| *n == 0));
}

// BG36_MagicItem_831 Felsteel Cleaver: "After you cast a spell on a Tavern minion, a random
// friendly minion consumes it to gain its stats."
#[test]
fn felsteel_cleaver() {
    let mut g = game(25);
    trinket(&mut g, "BG36_MagicItem_831");
    set_board(&mut g, 0, &[WEAVER]);
    let (_, sid) = put_shop_minion(&mut g, ZOATROID); // 3/2
    give(&mut g, 0, BLOOD_GEM);
    let hand = g.players[0].hand.len() - 1;
    g.apply(0, Action::Play { hand, pos: 0 }).unwrap();
    let Some(Pending::Target { options, .. }) = g.players[0].pending.last() else {
        panic!("expected a target choice")
    };
    let i = options.iter().position(|e| *e == sid).expect("a Tavern target");
    g.apply(0, Action::Choose(i)).unwrap();
    assert!(
        g.players[0].shop.iter().all(|s| s.sid != sid),
        "the Tavern minion is consumed"
    );
    assert_eq!(stats(&g, 0), vec![(1 + 3 + 1, 3 + 2 + 1)], "its stats, gem included");
    // A spell on a friendly minion: nothing is consumed.
    let shop_len = g.players[0].shop.len();
    give(&mut g, 0, BLOOD_GEM);
    cast_on(&mut g, 0, 0);
    assert_eq!(g.players[0].shop.len(), shop_len);
    assert_eq!(stats(&g, 0), vec![(6, 7)]);
}

// BG36_MagicItem_840 Secret Schematic: "After you buy a Mech, get a random Tavern spell that costs
// (2) or more."
#[test]
fn secret_schematic() {
    let mut g = game(26);
    g.players[0].tier = 6;
    trinket(&mut g, "BG36_MagicItem_840");
    g.players[0].shop.clear();
    put_shop_minion(&mut g, PRISONGUARD);
    put_shop_minion(&mut g, ACCORD);
    g.players[0].gold = 10;
    g.apply(0, Action::Buy(0)).unwrap();
    assert_eq!(hand_cards(&g), vec![cid(PRISONGUARD)], "not a Mech: nothing");
    g.apply(0, Action::Buy(0)).unwrap();
    let hand = hand_cards(&g);
    assert_eq!(hand.len(), 3);
    assert_eq!(hand[1], cid(ACCORD));
    let s = db().get(hand[2]);
    assert!(taverngym::content::is_tavern_spell(hand[2]), "{}", s.name);
    assert!(s.cost >= 2, "{} costs {}", s.name, s.cost);
}

// BG36_MagicItem_850 Cookie's Stirring Rod: "After you play 5 Murlocs, get two random Tavern
// spells. (5 left!)"
#[test]
fn cookies_stirring_rod() {
    let mut g = game(27);
    trinket(&mut g, "BG36_MagicItem_850");
    for _ in 0..4 {
        give_and_play(&mut g, TAD);
    }
    give_and_play(&mut g, PRISONGUARD); // not a Murloc
    assert!(g.players[0].hand.is_empty(), "4 Murlocs: nothing yet");
    give_and_play(&mut g, TAD);
    let hand = hand_cards(&g);
    assert_eq!(hand.len(), 2);
    for c in hand {
        assert!(taverngym::content::is_tavern_spell(c), "{}", db().get(c).name);
    }
}
