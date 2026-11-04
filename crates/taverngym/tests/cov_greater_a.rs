//! Card-behaviour tests for Greater Trinkets (coverage batch A): each test pins one trinket
//! to its card text.

mod common;
use common::*;

/// Buy trinket `id` through the offer flow (gold is topped up to cover it).
fn buy_trinket(g: &mut Game, p: PlayerId, id: &str) {
    g.players[p].gold = g.players[p].gold.max(db().get(cid(id)).cost);
    g.players[p].pending.push(Pending::Trinket {
        options: vec![cid(id)],
        free: false,
        replace: None,
    });
    g.apply(p, Action::Choose(0)).unwrap();
    assert!(g.players[p].has_trinket(id));
}

/// Put a fresh minion of card `id` into player `p`'s Tavern; returns its slot.
fn put_shop(g: &mut Game, p: PlayerId, id: &str) -> usize {
    let m = minion(g, p, id);
    let sid = m.eid;
    g.players[p]
        .shop
        .push(taverngym::state::ShopSlot::new(sid, Item::Minion(m)));
    g.players[p].shop.len() - 1
}

/// Cards in player `p`'s hand, left to right.
fn hand_cards(g: &Game, p: PlayerId) -> Vec<CardId> {
    g.players[p].hand.iter().map(|h| h.item.card()).collect()
}

/// How many cards of `id` (normal or golden) player `p` holds.
fn count_in_hand(g: &Game, p: PlayerId, id: &str) -> usize {
    let n = cid(id);
    g.players[p]
        .hand
        .iter()
        .filter(|h| {
            let c = h.item.card();
            c == n || db().get(c).normal == Some(n)
        })
        .count()
}

/// The hand minion of card `id` (first one).
fn hand_minion<'a>(g: &'a Game, p: PlayerId, id: &str) -> &'a Minion {
    g.players[p]
        .hand
        .iter()
        .filter_map(|h| h.item.as_minion())
        .find(|m| m.is_card(id))
        .unwrap_or_else(|| panic!("{id} in hand"))
}

/// Answer every pending choice of player `p` with option 0; the cards picked from Discovers
/// whose source is `source`.
fn answer_all(g: &mut Game, p: PlayerId, source: &str) -> Vec<CardId> {
    let src = cid(source);
    let mut picked = vec![];
    for _ in 0..50 {
        let Some(top) = g.players[p].pending.last().cloned() else {
            break;
        };
        if let Pending::Discover { source, options } = &top
            && *source == src
        {
            picked.push(options[0].card());
        }
        g.apply(p, Action::Choose(0)).unwrap();
    }
    assert!(g.players[p].pending.is_empty());
    picked
}

/// Shop minions' (attack, health), left to right.
fn shop_stats(g: &Game, p: PlayerId) -> Vec<(i32, i32)> {
    g.players[p]
        .shop
        .iter()
        .filter_map(|s| s.item.as_minion())
        .map(|m| (m.atk, m.hp))
        .collect()
}

/// Play the last hand card (a minion) and, if its Battlecry asks, target board entity `eid`.
fn play_last_on(g: &mut Game, p: PlayerId, eid: u32) {
    play_last(g, p);
    if let Some(Pending::Target { options, .. }) = g.players[p].pending.last().cloned() {
        let i = options.iter().position(|e| *e == eid).expect("target offered");
        g.apply(p, Action::Choose(i)).unwrap();
    }
}

// Book of Medivh: "Discover 2 Tavern spells. At the start of each turn, Discover 2 more."
#[test]
fn book_of_medivh_discovers_two_spells_now_and_each_turn() {
    let id = "BG30_MagicItem_420t";
    let mut g = game(500);
    buy_trinket(&mut g, 0, id);
    let picked = answer_all(&mut g, 0, id);
    assert_eq!(picked.len(), 2, "two Discovers on purchase");
    for c in &picked {
        assert_eq!(db().get(*c).kind, taverngym::cards::CardKind::TavernSpell);
    }
    let hand = hand_cards(&g, 0);
    for c in &picked {
        assert!(hand.contains(c));
    }
    g.players[0].hand.clear();
    end_turn_all(&mut g);
    let picked = answer_all(&mut g, 0, id);
    assert_eq!(picked.len(), 2, "two more at the start of the turn");
    for c in &picked {
        assert_eq!(db().get(*c).kind, taverngym::cards::CardKind::TavernSpell);
    }
}

// Azerite Portrait: "Get a Living Azerite. Your Living Azerites also give stats to friendly
// Elementals."
#[test]
fn azerite_portrait_gets_living_azerite_and_buffs_friendly_elementals() {
    let mut g = game(501);
    buy_trinket(&mut g, 0, "BG30_MagicItem_431");
    assert_eq!(count_in_hand(&g, 0, "BG28_707"), 1);
    g.players[0].hand.clear();
    // Living Azerite 6/6, Sellemental 3/3 (Elemental), Suspicious Prisonguard 3/3.
    set_board(&mut g, 0, &["BG28_707", "BGS_115", "BG36_345"]);
    g.players[0].shop.clear();
    put_shop(&mut g, 0, "BGS_115");
    give(&mut g, 0, "BG28_810"); // Tavern Coin
    play_last(&mut g, 0);
    assert_eq!(shop_stats(&g, 0), vec![(6, 6)], "Tavern Elementals +3/+3");
    assert_eq!(
        stats(&g, 0),
        vec![(9, 9), (6, 6), (3, 3)],
        "friendly Elementals get the stats too, other minions don't"
    );
}

// Living Azerite without the Portrait: friendly Elementals are not buffed (control).
#[test]
fn azerite_portrait_control_living_azerite_alone_skips_friendly_elementals() {
    let mut g = game(501);
    set_board(&mut g, 0, &["BG28_707", "BGS_115"]);
    g.players[0].shop.clear();
    put_shop(&mut g, 0, "BGS_115");
    give(&mut g, 0, "BG28_810");
    play_last(&mut g, 0);
    assert_eq!(shop_stats(&g, 0), vec![(6, 6)]);
    assert_eq!(stats(&g, 0), vec![(6, 6), (3, 3)]);
}

// Designer Eyepatch: "You only need 2 copies of a Pirate to make it Golden."
#[test]
fn designer_eyepatch_pirates_triple_with_two_copies() {
    let mut g = game(502);
    // A pair held when the trinket arrives merges; a pair of non-Pirates does not.
    give(&mut g, 0, "BG36_342"); // Clever Castaway (Pirate)
    give(&mut g, 0, "BG36_342");
    give(&mut g, 0, "BG36_345"); // Suspicious Prisonguard (no type)
    give(&mut g, 0, "BG36_345");
    buy_trinket(&mut g, 0, "BG30_MagicItem_439");
    let hand = hand_cards(&g, 0);
    assert_eq!(
        hand.iter().filter(|c| **c == cid("BG36_342_G")).count(),
        1,
        "two Castaways became a Golden one: {hand:?}"
    );
    assert_eq!(hand.iter().filter(|c| **c == cid("BG36_342")).count(), 0);
    assert_eq!(hand.iter().filter(|c| **c == cid("BG36_345")).count(), 2);
    // Buying a second copy of a held Pirate makes it Golden.
    g.players[0].hand.clear();
    set_board(&mut g, 0, &["BG36_342"]);
    g.players[0].shop.clear();
    put_shop(&mut g, 0, "BG36_342");
    g.players[0].gold = 10;
    g.apply(0, Action::Buy(0)).unwrap();
    let golden = g.players[0].board.iter().any(|m| m.card == cid("BG36_342_G"))
        || hand_cards(&g, 0).contains(&cid("BG36_342_G"));
    assert!(golden, "board + bought copy = Golden");
    assert!(!g.players[0].board.iter().any(|m| m.card == cid("BG36_342")));
}

// Nether Pendant: "Minions in the Tavern have +2/+2. Improves every 3 times your hero takes
// damage outside combat. (3 left!)"
#[test]
fn nether_pendant_buffs_the_tavern_and_improves_every_three_hero_hits() {
    let mut g = game(503);
    let before = shop_stats(&g, 0);
    assert!(!before.is_empty());
    buy_trinket(&mut g, 0, "BG30_MagicItem_541");
    let plus = |v: &[(i32, i32)], k: i32| v.iter().map(|(a, h)| (a + k, h + k)).collect::<Vec<_>>();
    assert_eq!(shop_stats(&g, 0), plus(&before, 2), "Tavern minions +2/+2");
    assert_eq!(
        (g.players[0].stats.tavern_atk, g.players[0].stats.tavern_hp),
        (2, 2)
    );
    for _ in 0..2 {
        g.with_recruit(0, |c| c.hero_damage(0, 1));
    }
    assert_eq!(shop_stats(&g, 0), plus(&before, 2), "not yet: 1 left");
    g.with_recruit(0, |c| c.hero_damage(0, 1));
    assert_eq!(shop_stats(&g, 0), plus(&before, 4), "improved to +4/+4");
    assert_eq!(
        (g.players[0].stats.tavern_atk, g.players[0].stats.tavern_hp),
        (4, 4)
    );
    // Combat damage does not count.
    let mut c = combat_ctx(&mut g);
    for _ in 0..3 {
        c.hero_damage(0, 1);
    }
    drop(c);
    assert_eq!(g.players[0].stats.tavern_atk, 4, "combat damage ignored");
    // A Refresh shows the improved aura.
    g.players[0].gold = 10;
    g.apply(0, Action::Refresh).unwrap();
    for m in g.players[0].shop.iter().filter_map(|s| s.item.as_minion()) {
        let d = db().get(m.card);
        assert_eq!((m.atk, m.hp), (d.atk + 4, d.hp + 4), "{}", d.name);
    }
}

// Nomi Sticker: "After you play an Elemental, give Elementals in the Tavern +5/+5 this game."
#[test]
fn nomi_sticker_greater_buffs_tavern_elementals_by_five() {
    let mut g = game(504);
    buy_trinket(&mut g, 0, "BG30_MagicItem_544t");
    g.players[0].shop.clear();
    put_shop(&mut g, 0, "BGS_115"); // Sellemental 3/3 (Elemental)
    put_shop(&mut g, 0, "BG36_345"); // Prisonguard 3/3
    give(&mut g, 0, "BG36_345");
    play_last(&mut g, 0);
    assert_eq!(shop_stats(&g, 0), vec![(3, 3), (3, 3)], "a non-Elemental: nothing");
    give(&mut g, 0, "BGS_115");
    play_last(&mut g, 0);
    assert_eq!(shop_stats(&g, 0), vec![(8, 8), (3, 3)], "Tavern Elementals +5/+5");
    // "this game": future Tavern Elementals get it too.
    let p = &g.players[0];
    assert_eq!(
        (p.stats.tavern_elemental_atk, p.stats.tavern_elemental_hp),
        (5, 5)
    );
    let fresh = g.with_recruit(0, |c| {
        let mut m = c.new_minion(0, cid("BGS_115"));
        c.apply_tavern_buffs(0, &mut m);
        (m.atk, m.hp)
    });
    assert_eq!(fresh, (8, 8));
}

// Manipulator Portrait: "Get a Faceless Manipulator."
#[test]
fn manipulator_portrait_gets_a_faceless_manipulator() {
    let mut g = game(505);
    buy_trinket(&mut g, 0, "BG30_MagicItem_876");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG_EX1_564")]);
}

// Nerglish Phrasebook: "After you play a minion, give the left-most minion in your hand
// +10/+10."
#[test]
fn nerglish_phrasebook_greater_gives_leftmost_hand_minion_ten_ten() {
    let mut g = game(506);
    buy_trinket(&mut g, 0, "BG30_MagicItem_914t");
    give(&mut g, 0, "BG36_345");
    give(&mut g, 0, "BGS_115");
    give(&mut g, 0, "BG36_342");
    play_last(&mut g, 0);
    let hand: Vec<(i32, i32)> = g.players[0]
        .hand
        .iter()
        .filter_map(|h| h.item.as_minion())
        .map(|m| (m.atk, m.hp))
        .collect();
    assert_eq!(hand, vec![(13, 13), (3, 3)], "only the left-most +10/+10");
    // A spell is not a minion: nothing.
    give(&mut g, 0, "BG28_810");
    play_last(&mut g, 0);
    let m = &g.players[0].hand[0].item.as_minion().unwrap();
    assert_eq!((m.atk, m.hp), (13, 13), "casting a spell does not trigger it");
}

// Booty Bay Brew: "Whenever you spend Gold, give two friendly Pirates +8/+8."
#[test]
fn booty_bay_brew_greater_buffs_two_pirates_per_spend() {
    let mut g = game(507);
    buy_trinket(&mut g, 0, "BG30_MagicItem_924t");
    // Three Clever Castaways (Pirates, 2/3) and a Prisonguard.
    set_board(&mut g, 0, &["BG36_342", "BG36_342", "BG36_342", "BG36_345"]);
    g.players[0].gold = 10;
    g.with_recruit(0, |c| c.spend_gold(0, 1));
    let s = stats(&g, 0);
    let buffed = s[..3].iter().filter(|x| **x == (10, 11)).count();
    let plain = s[..3].iter().filter(|x| **x == (2, 3)).count();
    assert_eq!((buffed, plain), (2, 1), "exactly two Pirates +8/+8: {s:?}");
    assert_eq!(s[3], (3, 3), "not a Pirate");
    g.with_recruit(0, |c| c.spend_gold(0, 1));
    let total: i32 = stats(&g, 0)[..3].iter().map(|x| x.0).sum();
    assert_eq!(total, 3 * 2 + 4 * 8, "another spend: two more +8/+8");
}

// Mecha-Jaraxxus Sticker: "Get 2 random Magnetic Mecha-Demons. At the start of each turn,
// get 2 more."
#[test]
fn mecha_jaraxxus_sticker_gets_two_mecha_demons_now_and_each_turn() {
    let demons = ["BG25_807t", "BG25_807t2", "BG25_807t3", "BG25_807t4"];
    let count = |g: &Game| {
        g.players[0]
            .hand
            .iter()
            .filter_map(|h| h.item.as_minion())
            .filter(|m| demons.iter().any(|d| m.is_card(d)))
            .inspect(|m| {
                let d = db().get(m.card);
                assert!(d.mech.has(taverngym::types::Mech::MAGNETIC));
                assert!(m.is(Races::MECH) && m.is(Races::DEMON));
            })
            .count()
    };
    let mut g = game(508);
    buy_trinket(&mut g, 0, "BG30_MagicItem_942");
    assert_eq!(count(&g), 2);
    assert_eq!(g.players[0].hand.len(), 2);
    end_turn_all(&mut g);
    answer_all(&mut g, 0, "BG30_MagicItem_942");
    assert_eq!(count(&g), 4, "two more at the start of the turn");
}

// Great Boar Sticker: "Get 5 Blood Gems. Your Blood Gems give an extra +3/+3."
#[test]
fn great_boar_sticker_gets_five_gems_that_give_four_four() {
    let mut g = game(509);
    buy_trinket(&mut g, 0, "BG30_MagicItem_988t");
    assert_eq!(count_in_hand(&g, 0, "BG20_GEM"), 5);
    assert_eq!(g.players[0].hand.len(), 5);
    set_board(&mut g, 0, &["BG36_345"]);
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0), vec![(3 + 4, 3 + 4)], "+1/+1 and an extra +3/+3");
    assert_eq!(count_in_hand(&g, 0, "BG20_GEM"), 4);
}

// Pagle's Fishing Rod: "Get a random Tier 7 minion. At the start of each turn, get another."
#[test]
fn pagles_fishing_rod_gets_a_tier_7_minion_now_and_each_turn() {
    let tier7 = |g: &Game| {
        g.players[0]
            .hand
            .iter()
            .filter_map(|h| h.item.as_minion())
            .filter(|m| db().get(m.card).tier == 7)
            .count()
    };
    let mut g = game(510);
    buy_trinket(&mut g, 0, "BG30_MagicItem_993");
    assert_eq!(tier7(&g), 1);
    assert_eq!(g.players[0].hand.len(), 1);
    end_turn_all(&mut g);
    answer_all(&mut g, 0, "BG30_MagicItem_993");
    assert_eq!(tier7(&g), 2, "another at the start of the turn");
}

// Wisdomball Supply: "Get a Knockoff Wisdomball. At the start of each turn, repeat this."
#[test]
fn wisdomball_supply_gets_a_wisdomball_now_and_each_turn() {
    let mut g = game(511);
    buy_trinket(&mut g, 0, "BG31_MagicItem_903");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG30_802")]);
    end_turn_all(&mut g);
    answer_all(&mut g, 0, "BG31_MagicItem_903");
    assert_eq!(count_in_hand(&g, 0, "BG30_802"), 2);
}

// Boom's Monster Portrait: "Get a Dr. Boom's Monster. At the start of every turn, get
// another."
#[test]
fn booms_monster_portrait_gets_a_monster_now_and_each_turn() {
    let mut g = game(512);
    buy_trinket(&mut g, 0, "BG32_MagicItem_172");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG31_176")]);
    end_turn_all(&mut g);
    answer_all(&mut g, 0, "BG32_MagicItem_172");
    assert_eq!(count_in_hand(&g, 0, "BG31_176"), 2);
}

// Maw Caster Portrait: "Get a Maw Caster. Whenever you destroy a minion outside combat, gain
// 1 Gold."
#[test]
fn maw_caster_portrait_gold_for_destroying_outside_combat() {
    let mut g = game(513);
    buy_trinket(&mut g, 0, "BG32_MagicItem_205");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG32_340")]);
    // Maw Caster's Battlecry destroys a friendly Undead: +1 Gold.
    set_board(&mut g, 0, &["BG34_690"]); // Plaguerunner (Undead)
    let undead = g.players[0].board[0].eid;
    g.players[0].gold = 5;
    play_last_on(&mut g, 0, undead);
    assert!(!g.players[0].board.iter().any(|m| m.is_card("BG34_690")));
    assert_eq!(g.players[0].gold, 6, "one minion destroyed: 1 Gold");
    answer_all(&mut g, 0, "BG32_340");
    // Selling is not destroying.
    let gold = g.players[0].gold;
    g.apply(0, Action::Sell(0)).unwrap();
    assert_eq!(g.players[0].gold, gold + 1, "only the sale's Gold");
    // Deaths in combat don't count.
    set_board(&mut g, 0, &["BG36_345", "BG36_345"]);
    let gold = g.players[0].gold;
    let mut c = combat_ctx(&mut g);
    let e = c.boards[0][0].eid;
    c.destroy(e);
    c.resolve_deaths();
    drop(c);
    assert_eq!(g.players[0].gold, gold, "not in combat");
}

// Czarina Portrait: "Get a Charging Czarina. Your Charging Czarinas also give Health."
#[test]
fn czarina_portrait_czarinas_also_give_health() {
    let mut g = game(514);
    buy_trinket(&mut g, 0, "BG32_MagicItem_283");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG28_741")]);
    g.players[0].hand.clear();
    // Charging Czarina 4/1 DS, Crackling Cyclone 2/1 DS, Prisonguard 3/3.
    set_board(&mut g, 0, &["BG28_741", "BGS_119", "BG36_345"]);
    give(&mut g, 0, "BG28_810"); // Tavern Coin
    play_last(&mut g, 0);
    assert_eq!(
        stats(&g, 0),
        vec![(8, 5), (6, 5), (3, 3)],
        "Divine Shield minions +4/+4 (Attack and Health)"
    );
}

// Portable Factory: "Discover a Tier 6 minion with a type. At the start of each turn, get
// another copy of it."
#[test]
fn portable_factory_greater_discovers_typed_tier_6_and_copies_it() {
    let id = "BG32_MagicItem_361t";
    let mut g = game(515);
    buy_trinket(&mut g, 0, id);
    let Some(Pending::Discover { options, .. }) = g.players[0].pending.last().cloned() else {
        panic!("a Discover")
    };
    for o in &options {
        let d = db().get(o.card());
        assert_eq!(d.tier, 6, "{}", d.name);
        assert!(!d.races.is_none(), "{} has a type", d.name);
    }
    let picked = answer_all(&mut g, 0, id);
    assert_eq!(picked.len(), 1);
    let pick = picked[0];
    assert_eq!(hand_cards(&g, 0), vec![pick]);
    g.players[0].hand.clear();
    end_turn_all(&mut g);
    answer_all(&mut g, 0, id);
    assert!(hand_cards(&g, 0).contains(&pick), "a copy at the start of the turn");
    let n = hand_cards(&g, 0).iter().filter(|c| **c == pick).count();
    assert_eq!(n, 1);
}

// Poet Portrait: "Get a Timewarped Poet."
#[test]
fn poet_portrait_gets_a_timewarped_poet() {
    let mut g = game(516);
    buy_trinket(&mut g, 0, "BG32_MagicItem_364");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG34_Giant_314")]);
}

// Curator Sticker: "Get a Golden Mishmash and a 10/10 Amalgam with Venomous."
#[test]
fn curator_sticker_gets_golden_mishmash_and_venomous_10_10_amalgam() {
    let mut g = game(517);
    buy_trinket(&mut g, 0, "BG32_MagicItem_807");
    assert_eq!(g.players[0].hand.len(), 2);
    let mish = hand_minion(&g, 0, "TB_BaconShop_HERO_33_Buddy");
    assert!(mish.golden, "Golden Mishmash");
    assert_eq!(mish.card, cid("TB_BaconShop_HERO_33_Buddy_G"));
    let amalgam = hand_minion(&g, 0, "TB_BaconShop_HP_033t");
    assert!(!amalgam.golden);
    assert_eq!((amalgam.atk, amalgam.hp), (10, 10));
    assert!(amalgam.has(Kw::VENOMOUS));
}

// Bloodbound Earrings: "After you cast 5 spells, this plays two Blood Gems on all your
// minions. (5 left!)"
#[test]
fn bloodbound_earrings_greater_two_gems_on_all_after_five_spells() {
    let mut g = game(518);
    buy_trinket(&mut g, 0, "BG32_MagicItem_808t");
    set_board(&mut g, 0, &["BG36_345", "BG36_342"]);
    for _ in 0..4 {
        give(&mut g, 0, "BG28_810");
        play_last(&mut g, 0);
    }
    assert_eq!(stats(&g, 0), vec![(3, 3), (2, 3)], "4 spells: nothing yet");
    give(&mut g, 0, "BG28_810");
    play_last(&mut g, 0);
    assert_eq!(stats(&g, 0), vec![(5, 5), (4, 5)], "5th spell: two gems on each");
    assert!(g.players[0].board.iter().all(|m| m.gems == 2));
    for _ in 0..5 {
        give(&mut g, 0, "BG28_810");
        play_last(&mut g, 0);
    }
    assert_eq!(stats(&g, 0), vec![(7, 7), (6, 7)], "and again after 5 more");
}

// Recycling Sticker: "After you play an Elemental, gain a free Refresh."
#[test]
fn recycling_sticker_free_refresh_after_an_elemental() {
    let mut g = game(519);
    buy_trinket(&mut g, 0, "BG32_MagicItem_888");
    let before = g.players[0].free_refreshes;
    give(&mut g, 0, "BG36_345");
    play_last(&mut g, 0);
    assert_eq!(g.players[0].free_refreshes, before, "not an Elemental");
    give(&mut g, 0, "BGS_115");
    play_last(&mut g, 0);
    assert_eq!(g.players[0].free_refreshes, before + 1);
    // The free Refresh costs no Gold.
    g.players[0].gold = 0;
    g.apply(0, Action::Refresh).unwrap();
    assert_eq!(g.players[0].free_refreshes, before);
    assert_eq!(g.players[0].gold, 0);
}

// Hackerfin Portrait: "Get a Hackerfin. At the end of each turn, trigger your Hackerfins'
// Battlecries."
#[test]
fn hackerfin_portrait_triggers_hackerfin_battlecries_at_end_of_turn() {
    let mut g = game(520);
    buy_trinket(&mut g, 0, "BG32_MagicItem_925");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG31_148")]);
    g.players[0].hand.clear();
    // Hackerfin 5/3, Prisonguard 3/3 (no Bonus Keywords in the warband).
    set_board(&mut g, 0, &["BG31_148", "BG36_345"]);
    g.apply(0, Action::EndTurn).unwrap();
    assert_eq!(
        stats(&g, 0),
        vec![(5, 3), (6, 5)],
        "Battlecry: other minions +3/+2"
    );
}

// Morgl Portrait: "Get a Tide Oracle Morgl."
#[test]
fn morgl_portrait_gets_tide_oracle_morgl() {
    let mut g = game(521);
    buy_trinket(&mut g, 0, "BG32_MagicItem_926");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG27_513")]);
}

// Behemoth Portrait: "Get an Arcane Behemoth."
#[test]
fn behemoth_portrait_gets_an_arcane_behemoth() {
    let mut g = game(522);
    buy_trinket(&mut g, 0, "BG32_MagicItem_998");
    assert_eq!(hand_cards(&g, 0), vec![cid("BG31_360")]);
}
