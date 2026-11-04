//! Card-text coverage of Hero Powers that had no focused test: one test per power pins its
//! behaviour to its text.

mod common;
use common::*;
use taverngym::actions::A_HERO_POWER;
use taverngym::content;
use taverngym::state::ShopSlot;

/// `game(seed)` with player 0 on Hero Power `id` (no `on_attach`) and plenty of Gold.
fn with_hp(seed: u64, id: &str) -> Game {
    let mut g = game(seed);
    g.players[0].set_hero_power(0, cid(id));
    g.players[0].gold = 50;
    g
}

/// The first seed from `seed` whose lobby has minion type `r`.
fn seed_with(seed: u64, r: Races) -> u64 {
    (seed..seed + 200)
        .find(|s| game(*s).lobby_races.intersects(r))
        .expect("a lobby with that type")
}

/// Player 0's Tavern holds just these minions.
fn shop(g: &mut Game, ids: &[&str]) {
    g.players[0].shop.clear();
    for id in ids {
        let m = minion(g, 0, id);
        g.players[0].shop.push(ShopSlot::new(m.eid, Item::Minion(m)));
    }
}

/// Stock one minion and buy it.
fn buy(g: &mut Game, id: &str) {
    shop(g, &[id]);
    g.apply(0, Action::Buy(0)).unwrap();
}

fn count_hand(g: &Game, id: &str) -> usize {
    g.players[0]
        .hand
        .iter()
        .filter(|h| h.item.card() == cid(id))
        .count()
}

/// The open Discover's options (cards).
fn discover_cards(g: &Game) -> Vec<CardId> {
    match g.players[0].pending.last() {
        Some(Pending::Discover { options, .. }) => options.iter().map(|i| i.card()).collect(),
        other => panic!("expected a Discover, got {other:?}"),
    }
}

/// Use Hero Power slot 0 on player 0's minion `eid` (answering the target menu if any).
fn hp_on(g: &mut Game, eid: u32) {
    g.apply(0, Action::HeroPower(0)).unwrap();
    if let Some(Pending::Target { options, .. }) = g.players[0].pending.last() {
        let i = options.iter().position(|e| *e == eid).expect("a legal target");
        g.apply(0, Action::Choose(i)).unwrap();
    }
}

fn hp_price(g: &Game) -> i32 {
    g.hero_power_price(0, 0).unwrap()
}

// ---------------------------------------------------------------------------- Rokara

#[test]
fn glory_of_combat() {
    // "After a friendly minion kills an enemy, give it +1 Attack permanently."
    let mut g = with_hp(100, "BG20_HERO_100p");
    set_board(&mut g, 0, &["BG36_345"]); // 3/3
    set_board(&mut g, 1, &["BG24_715"]); // 1/1
    {
        let mut c = combat_ctx(&mut g);
        let a = c.boards[0][0].eid;
        taverngym::combat::attack_now(&mut c, 0, a);
        assert!(c.boards[1].iter().all(|m| !m.alive()), "the enemy died");
        assert_eq!(c.minion(a).unwrap().atk, 4, "+1 Attack in combat");
    }
    assert_eq!(stats(&g, 0), vec![(4, 3)], "and permanently (Attack only)");
    // An enemy that kills a friendly minion gets nothing (it is not friendly).
    let mut g = with_hp(101, "BG20_HERO_100p");
    set_board(&mut g, 0, &["BG24_715"]);
    set_board(&mut g, 1, &["BG36_345"]);
    {
        let mut c = combat_ctx(&mut g);
        let a = c.boards[0][0].eid;
        let enemy = c.boards[1][0].eid;
        taverngym::combat::attack_now(&mut c, 0, a);
        assert_eq!(c.minion(enemy).unwrap().atk, 3);
    }
}

// ---------------------------------------------------------------------------- Blackthorn

#[test]
fn bloodbound() {
    // "Get 2 Blood Gems. (Twice per turn.)"
    let mut g = with_hp(102, "BG20_HERO_103p");
    g.players[0].gold = 10;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(count_hand(&g, "BG20_GEM"), 2);
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(count_hand(&g, "BG20_GEM"), 4);
    assert_eq!(g.players[0].gold, 10 - 2, "costs (1) each");
    assert!(!g.can_hero_power(0, 0), "twice per turn");
    assert!(g.apply(0, Action::HeroPower(0)).is_err());
}

// ---------------------------------------------------------------------------- Scabbs

#[test]
fn i_spy() {
    // "Discover a plain copy of a minion from your next opponent's warband."
    let mut g = with_hp(103, "BG21_HERO_010p");
    let mut big = minion(&mut g, 1, "BG36_345_G");
    big.set_stats(20, 20);
    big.give(Kw::TAUNT);
    let other = minion(&mut g, 1, "BG36_098");
    g.players[1].seen_board = vec![big, other];
    g.players[0].next_opponent = Some(1);
    g.players[0].next_is_ghost = false;
    g.apply(0, Action::HeroPower(0)).unwrap();
    let mut cards = discover_cards(&g);
    cards.sort();
    let mut want = vec![cid("BG36_345"), cid("BG36_098")];
    want.sort();
    assert_eq!(cards, want, "plain (non-Golden) copies of the opponent's minions");
    let Some(Pending::Discover { options, .. }) = g.players[0].pending.last() else {
        unreachable!()
    };
    let i = options
        .iter()
        .position(|o| o.card() == cid("BG36_345"))
        .unwrap();
    g.apply(0, Action::Choose(i)).unwrap();
    let m = g.players[0].hand[0].item.as_minion().unwrap();
    assert_eq!((m.card, m.atk, m.hp, m.golden), (cid("BG36_345"), 3, 3, false));
    assert!(!m.has(Kw::TAUNT), "a plain copy has no enchantments");
}

// ---------------------------------------------------------------------------- Ini Stormcoil

#[test]
fn mechgyver() {
    // "After 9 friendly minions die, get a random Mech."
    let seed = seed_with(104, Races::MECH);
    let mut g = with_hp(seed, "BG22_HERO_200p");
    let mechs = |g: &Game| {
        g.players[0]
            .hand
            .iter()
            .filter(|h| h.item.as_minion().is_some_and(|m| m.races.intersects(Races::MECH)))
            .count()
    };
    let kill = |g: &mut Game, n: usize| {
        let ids = vec!["BG36_345"; n];
        set_board(g, 0, &ids);
        let mut c = combat_ctx(g);
        for e in c.boards[0].iter().map(|m| m.eid).collect::<Vec<_>>() {
            c.destroy(e);
        }
        c.resolve_deaths();
    };
    kill(&mut g, 7);
    kill(&mut g, 1);
    assert_eq!(mechs(&g), 0, "8 deaths: not yet");
    kill(&mut g, 1);
    assert_eq!(mechs(&g), 1, "the 9th death gives a Mech");
    assert_eq!(g.players[0].hand.len(), 1);
}

// ---------------------------------------------------------------------------- Togwaggle

#[test]
fn the_perfect_crime() {
    // "Steal all cards from the Tavern. Each turn, your next Hero Power costs (1) less."
    let mut g = with_hp(105, "BG23_HERO_305p");
    assert_eq!(hp_price(&g), 11);
    g.start_turn();
    assert_eq!(hp_price(&g), 10, "(1) less after a turn");
    g.start_turn();
    assert_eq!(hp_price(&g), 9, "and (1) less again");
    g.players[0].pending.clear();
    shop(&mut g, &["BG36_345", "BG36_098", "BGS_119"]);
    let stolen: Vec<CardId> = g.players[0].shop.iter().map(|s| s.item.card()).collect();
    g.players[0].gold = 20;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 20 - 9);
    assert!(g.players[0].shop.is_empty(), "the Tavern is emptied");
    let hand: Vec<CardId> = g.players[0].hand.iter().map(|h| h.item.card()).collect();
    assert_eq!(hand, stolen, "every Tavern card goes to the hand");
    assert_eq!(hp_price(&g), 11, "the discount was for the next Hero Power only");
}

// ---------------------------------------------------------------------------- Enhance-o Mechano

#[test]
fn enhancification() {
    // "After the Tavern is Refreshed, give a random minion in it a random Bonus Keyword, twice."
    for seed in 106..112 {
        let mut g = with_hp(seed, "BG24_HERO_204p");
        g.players[0].gold = 10;
        g.apply(0, Action::Refresh).unwrap();
        let gained: usize = g.players[0]
            .shop
            .iter()
            .filter_map(|s| s.item.as_minion())
            .map(|m| m.kw.count_bonus() - db().get(m.card).kw.count_bonus())
            .sum();
        assert_eq!(gained, 2, "seed {seed}: two Bonus Keywords in the new Tavern");
    }
}

// ---------------------------------------------------------------------------- Cap'n Hoggarr

#[test]
fn im_the_capn_now() {
    // "After you buy a Pirate, gain 1 Gold."
    let mut g = with_hp(107, "BG26_HERO_101p");
    g.players[0].gold = 10;
    buy(&mut g, "BG26_135"); // Southsea Busker (Pirate)
    assert_eq!(g.players[0].gold, 10 - 3 + 1);
    buy(&mut g, "BG36_345"); // not a Pirate
    assert_eq!(g.players[0].gold, 8 - 3);
}

// ---------------------------------------------------------------------------- Doctor Holli'dae

#[test]
fn blessing_of_the_nine_frogs() {
    // "Get a random Tavern spell."
    let mut g = with_hp(108, "BG28_HERO_801p");
    g.players[0].gold = 10;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 9);
    assert_eq!(g.players[0].hand.len(), 1);
    assert!(content::is_tavern_spell(g.players[0].hand[0].item.card()));
}

// ---------------------------------------------------------------------------- Cenarius

#[test]
fn wisdom_of_ancients() {
    // "Increase your maximum Gold by 1."
    let mut g = with_hp(109, "BG32_HERO_001p");
    g.players[0].gold = 10;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 7, "costs (3)");
    assert_eq!(g.players[0].max_gold_bonus, 1);
    g.start_turn();
    assert_eq!(
        g.players[0].gold,
        g.players[2].gold + 1,
        "one more Gold each turn than a player without it"
    );
}

// ---------------------------------------------------------------------------- Chromie

#[test]
fn mana_per_minute() {
    // "Refresh the Tavern with Tavern spells."
    let mut g = with_hp(110, "BG34_HERO_001p");
    let before: Vec<u32> = g.players[0].shop.iter().map(|s| s.sid).collect();
    let n = g.players[0].shop.len();
    assert!(n > 0);
    g.apply(0, Action::HeroPower(0)).unwrap();
    let shop = &g.players[0].shop;
    assert_eq!(shop.len(), n, "a full Refresh");
    assert!(
        shop.iter().all(|s| content::is_tavern_spell(s.item.card())),
        "only Tavern spells: {:?}",
        shop.iter().map(|s| db().get(s.item.card()).name.clone()).collect::<Vec<_>>()
    );
    assert!(shop.iter().all(|s| !before.contains(&s.sid)), "new cards");
}

// ---------------------------------------------------------------------------- Kith'ix

#[test]
fn dark_ritual() {
    // "Get 2 random minions. When you play one, discard the other."
    let mut g = with_hp(111, "BG36_HERO_002p");
    g.players[0].gold = 10;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 8, "costs (2)");
    let hand = &g.players[0].hand;
    assert_eq!(hand.len(), 2);
    assert!(hand.iter().all(|h| h.item.as_minion().is_some()));
    let (a, b) = (hand[0].hid, hand[1].hid);
    g.apply(0, Action::Play { hand: 0, pos: 0 }).unwrap();
    while g.players[0].pending.last().is_some() {
        g.apply(0, Action::Choose(0)).unwrap();
    }
    assert_eq!(g.players[0].board.len(), 1, "the played one");
    assert!(
        g.players[0].hand.iter().all(|h| h.hid != a && h.hid != b),
        "the other one is discarded"
    );
}

// ---------------------------------------------------------------------------- Gallywix

#[test]
fn smart_savings() {
    // "After you sell a minion, gain 1 Gold next turn."
    let mut g = with_hp(112, "TB_BaconShop_HP_008");
    set_board(&mut g, 0, &["BG36_345", "BG36_345"]);
    g.players[0].gold = 0;
    g.players[0].gold_next_turn = 0;
    g.apply(0, Action::Sell(0)).unwrap();
    assert_eq!(g.players[0].gold_next_turn, 1);
    g.apply(0, Action::Sell(0)).unwrap();
    assert_eq!(g.players[0].gold_next_turn, 2);
    assert_eq!(g.players[0].gold, 2, "only the sale price now");
    g.players[2].gold_next_turn = 0;
    g.start_turn();
    assert_eq!(g.players[0].gold, g.players[2].gold + 2, "next turn");
}

// ---------------------------------------------------------------------------- Millificent

#[test]
fn tinker() {
    // "Discover a Magnetic Mech. (Unlocks at Tier 4.)"
    let seed = seed_with(113, Races::MECH);
    let mut g = with_hp(seed, "TB_BaconShop_HP_015");
    g.players[0].tier = 3;
    assert!(!g.legal_mask(0)[A_HERO_POWER], "locked below Tier 4");
    assert!(g.apply(0, Action::HeroPower(0)).is_err());
    g.players[0].tier = 4;
    assert!(g.legal_mask(0)[A_HERO_POWER]);
    g.apply(0, Action::HeroPower(0)).unwrap();
    let cards = discover_cards(&g);
    assert!(!cards.is_empty());
    for c in &cards {
        let d = db().get(*c);
        assert!(
            d.races.intersects(Races::MECH) && d.kw.has(Kw::MAGNETIC) && d.tier <= 4,
            "{} is a Magnetic Mech of Tier <= 4",
            d.name
        );
    }
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(g.players[0].hand[0].item.card(), cards[0]);
}

// ---------------------------------------------------------------------------- The Curator

#[test]
fn menagerist() {
    // "Start the game with a 2/2 Amalgam with Venomous and all minion types."
    let mut g = game(114);
    g.set_hero_power(0, 0, cid("TB_BaconShop_HP_033"));
    let b = &g.players[0].board;
    assert_eq!(b.len(), 1);
    let m = &b[0];
    assert_eq!(m.card, cid("TB_BaconShop_HP_033t"));
    assert_eq!((m.atk, m.hp), (2, 2));
    assert!(m.has(Kw::VENOMOUS));
    assert_eq!(m.races, Races::ALL, "all minion types");
}

// ---------------------------------------------------------------------------- Yogg-Saron

#[test]
fn puzzle_box() {
    // "At the start of your turn, cast a random Tavern spell. (Unlocks on Turn 3.)"
    let mut g = with_hp(115, "TB_BaconShop_HP_039t");
    set_board(&mut g, 0, &["BG36_345"]);
    assert_eq!(g.turn, 1);
    g.start_turn();
    assert_eq!(g.turn, 2);
    assert_eq!(g.players[0].stats.tavern_spells_cast, 0, "locked on Turn 2");
    g.players[0].pending.clear();
    g.start_turn();
    assert_eq!(g.turn, 3);
    assert_eq!(g.players[0].stats.tavern_spells_cast, 1, "one cast on Turn 3");
    assert!(g.players[0].stats.last_spell_cast.is_some_and(content::is_tavern_spell));
    g.players[0].pending.clear();
    g.start_turn();
    assert_eq!(g.players[0].stats.tavern_spells_cast, 2, "and every turn after");
}

// ---------------------------------------------------------------------------- The Rat King

#[test]
fn a_tale_of_kings() {
    // "Discover a minion of a specific minion type. Swaps type each turn."
    let mut g = with_hp(116, "TB_BaconShop_HP_041");
    g.players[0].gold = 10;
    let r = g.rat_king_type().unwrap();
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 8, "costs (2)");
    let cards = discover_cards(&g);
    assert!(!cards.is_empty());
    for c in &cards {
        assert!(db().get(*c).races.intersects(r), "{} has this turn's type", db().get(*c).name);
    }
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(g.players[0].hand.len(), 1);
    g.start_turn();
    assert_ne!(g.rat_king_type().unwrap(), r, "the type swaps each turn");
}

// ---------------------------------------------------------------------------- Reno Jackson

#[test]
fn gonna_be_rich() {
    // "Once per game, make a friendly minion Golden."
    let mut g = with_hp(117, "TB_BaconShop_HP_046");
    set_board(&mut g, 0, &["BG36_345", "BG36_098"]);
    let eid = g.players[0].board[0].eid;
    hp_on(&mut g, eid);
    let m = &g.players[0].board[0];
    assert!(m.golden);
    assert_eq!(m.card, cid("BG36_345_G"));
    assert_eq!((m.atk, m.hp), (6, 6));
    // Once per game: not on later turns either.
    g.start_turn();
    g.players[0].pending.clear();
    assert!(!g.can_hero_power(0, 0));
}

// ---------------------------------------------------------------------------- Elise

#[test]
fn lead_explorer() {
    // "Discover a minion from your Tier. Costs (1) more after each use."
    let mut g = with_hp(118, "TB_BaconShop_HP_047");
    g.players[0].tier = 3;
    g.players[0].gold = 10;
    assert_eq!(hp_price(&g), 1);
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 9);
    let cards = discover_cards(&g);
    assert!(!cards.is_empty());
    assert!(cards.iter().all(|c| db().get(*c).tier == 3), "from your Tier");
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(hp_price(&g), 2, "(1) more");
    g.start_turn();
    g.players[0].pending.clear();
    g.players[0].gold = 10;
    g.apply(0, Action::HeroPower(0)).unwrap();
    assert_eq!(g.players[0].gold, 8);
    assert_eq!(hp_price(&g), 3, "(1) more after each use");
}

// ---------------------------------------------------------------------------- Dinotamer Brann

#[test]
fn battle_brand() {
    // "After you buy 4 Battlecry minions, get a Brann Bronzebeard. (Once per game.)"
    let mut g = with_hp(119, "TB_BaconShop_HP_048");
    for _ in 0..3 {
        buy(&mut g, "BG20_100"); // Razorfen Geomancer (Battlecry)
    }
    buy(&mut g, "BG36_345"); // no Battlecry: doesn't count
    assert_eq!(count_hand(&g, "BG_LOE_077"), 0);
    buy(&mut g, "BG20_100");
    assert_eq!(count_hand(&g, "BG_LOE_077"), 1, "the 4th Battlecry minion");
    for _ in 0..4 {
        buy(&mut g, "BG20_100");
    }
    assert_eq!(count_hand(&g, "BG_LOE_077"), 1, "once per game");
}

// ---------------------------------------------------------------------------- Millhouse

#[test]
fn manastorm() {
    // "Minions and Refreshes cost 2 Gold. Upgrading the Tavern costs (1) more."
    let mut g = with_hp(120, "TB_BaconShop_HP_054");
    g.players[0].gold = 20;
    buy(&mut g, "BG36_345");
    assert_eq!(g.players[0].gold, 18, "a minion costs 2");
    g.apply(0, Action::Refresh).unwrap();
    assert_eq!(g.players[0].gold, 16, "a Refresh costs 2");
    g.players[0].upgrade_cost = 5;
    assert_eq!(g.upgrade_price(0), 6);
    g.apply(0, Action::Upgrade).unwrap();
    assert_eq!(g.players[0].gold, 10, "upgrading costs (1) more");
}

// ---------------------------------------------------------------------------- Kael'thas

#[test]
fn verdant_spheres() {
    // "After you buy 3 minions, get a Tavern Coin."
    let mut g = with_hp(121, "TB_BaconShop_HP_066");
    buy(&mut g, "BG36_345");
    buy(&mut g, "BG36_345");
    assert_eq!(count_hand(&g, "BG28_810"), 0);
    buy(&mut g, "BG36_345");
    assert_eq!(count_hand(&g, "BG28_810"), 1);
    for _ in 0..3 {
        buy(&mut g, "BG36_345");
    }
    assert_eq!(count_hand(&g, "BG28_810"), 2, "every 3 minions");
}

// ---------------------------------------------------------------------------- Hooktusk

#[test]
fn trash_for_treasure() {
    // "Remove a friendly minion. Discover one from a Tier lower to get."
    let mut g = with_hp(122, "TB_BaconShop_HP_075");
    set_board(&mut g, 0, &["BG36_346", "BG36_345"]); // Fruit Vendor (Tier 3), a Tier 1
    let eid = g.players[0].board[0].eid;
    hp_on(&mut g, eid);
    assert_eq!(g.players[0].board.len(), 1);
    assert_eq!(g.players[0].board[0].card, cid("BG36_345"), "the Vendor is removed");
    let cards = discover_cards(&g);
    assert!(!cards.is_empty());
    assert!(cards.iter().all(|c| db().get(*c).tier == 2), "a Tier lower");
    g.apply(0, Action::Choose(0)).unwrap();
    assert_eq!(g.players[0].hand[0].item.card(), cards[0], "to get");
}

// ---------------------------------------------------------------------------- Mr. Bigglesworth

#[test]
fn kelthuzads_kitty() {
    // "After another hero dies, Discover a minion from their warband. It keeps enchantments."
    let mut g = with_hp(123, "TB_BaconShop_HP_080");
    let mut m = minion(&mut g, 1, "BG36_345");
    m.set_stats(13, 14);
    m.give(Kw::TAUNT);
    content::on_eliminated(&mut g, 1, vec![m]);
    assert_eq!(discover_cards(&g), vec![cid("BG36_345")]);
    g.apply(0, Action::Choose(0)).unwrap();
    let h = g.players[0].hand[0].item.as_minion().unwrap();
    assert_eq!((h.atk, h.hp), (13, 14), "keeps its stats");
    assert!(h.has(Kw::TAUNT), "and gained keywords");
}

// ---------------------------------------------------------------------------- Omu

#[test]
fn everbloom() {
    // "After you upgrade the Tavern, gain 2 Gold."
    let mut g = with_hp(124, "TB_BaconShop_HP_082");
    g.players[0].gold = 10;
    let price = g.upgrade_price(0);
    g.apply(0, Action::Upgrade).unwrap();
    assert_eq!(g.players[0].tier, 2);
    assert_eq!(g.players[0].gold, 10 - price + 2);
}

// ---------------------------------------------------------------------------- Chenvaala

#[test]
fn avalanche() {
    // "After you play 3 Elementals, reduce the Cost of upgrading the Tavern by (3)."
    let mut g = with_hp(125, "TB_BaconShop_HP_088");
    g.players[0].upgrade_cost = 7;
    for id in ["BGS_119", "BG36_345", "BGS_119"] {
        give(&mut g, 0, id);
        play_last(&mut g, 0);
    }
    assert_eq!(g.players[0].upgrade_cost, 7, "2 Elementals (the other doesn't count)");
    give(&mut g, 0, "BGS_119");
    play_last(&mut g, 0);
    assert_eq!(g.players[0].upgrade_cost, 4, "the 3rd Elemental: (3) less");
    assert_eq!(g.upgrade_price(0), 4);
}

// ---------------------------------------------------------------------------- Greybough

#[test]
fn sprout_it_out() {
    // "Give +1/+2 and Taunt to minions you summon during combat."
    let mut g = with_hp(126, "TB_BaconShop_HP_107");
    set_board(&mut g, 0, &["BG28_300"]); // Deathrattle: summon two 1/1 Skeletons
    set_board(&mut g, 1, &["BG28_300"]);
    {
        let mut c = combat_ctx(&mut g);
        let (mine, theirs) = (c.boards[0][0].eid, c.boards[1][0].eid);
        c.destroy(mine);
        c.destroy(theirs);
        c.resolve_deaths();
        let s: Vec<_> = c.boards[0].iter().filter(|m| m.alive()).collect();
        assert_eq!(s.len(), 2);
        for m in s {
            assert_eq!((m.atk, m.hp), (2, 3), "1/1 Skeleton +1/+2");
            assert!(m.has(Kw::TAUNT));
        }
        for m in c.boards[1].iter().filter(|m| m.alive()) {
            assert_eq!((m.atk, m.hp), (1, 1), "the enemy's summons get nothing");
            assert!(!m.has(Kw::TAUNT));
        }
    }
    // Outside combat a summon gets nothing.
    set_board(&mut g, 0, &["BG28_300"]);
    let e = g.players[0].board[0].eid;
    g.with_recruit(0, |c| {
        c.destroy(e);
        c.resolve_deaths();
    });
    assert_eq!(stats(&g, 0), vec![(1, 1), (1, 1)]);
    assert!(g.players[0].board.iter().all(|m| !m.has(Kw::TAUNT)));
}

// ---------------------------------------------------------------------------- The Jailer

#[test]
fn rune_of_damnation() {
    // "Destroy a friendly Undead to get a random Undead. (Unlocks at Tier 2.)"
    let seed = seed_with(127, Races::UNDEAD);
    let mut g = with_hp(seed, "TB_BaconShop_HP_702t");
    set_board(&mut g, 0, &["BG25_013", "BG36_345"]); // Rot Hide Gnoll (Undead), a non-Undead
    g.players[0].tier = 1;
    assert!(!g.can_hero_power(0, 0), "locked at Tier 1");
    g.players[0].tier = 2;
    assert!(g.can_hero_power(0, 0));
    let undead = g.players[0].board[0].eid;
    g.apply(0, Action::HeroPower(0)).unwrap();
    if let Some(Pending::Target { options, .. }) = g.players[0].pending.last() {
        assert_eq!(options, &vec![undead], "only friendly Undead are targets");
        g.apply(0, Action::Choose(0)).unwrap();
    }
    assert_eq!(g.players[0].board.len(), 1);
    assert_eq!(g.players[0].board[0].card, cid("BG36_345"), "the Undead is destroyed");
    assert_eq!(g.players[0].hand.len(), 1);
    let d = db().get(g.players[0].hand[0].item.card());
    assert!(d.races.intersects(Races::UNDEAD), "{} is an Undead", d.name);
}
