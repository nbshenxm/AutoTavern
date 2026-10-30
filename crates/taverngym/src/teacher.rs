//! A scripted strategy written from a player's advice (`RulesConfig::teacher`): level on a
//! curve, take economy cards and the right Dark Gifts early, complete triples (their Discover
//! reaches a higher Tier, where the key cards are), spend every Gold, and from the mid game
//! build toward the comp the warband is closest to. A stronger opponent than the plain bot
//! (`bot.rs`) and a policy for the network to learn from before PPO.

use crate::actions::{Action, N_BOARD, N_HAND, N_POWERS};
use crate::bot::{item_value, minion_value, pick_option};
use crate::cards::{CardId, db};
use crate::config::TeacherConfig;
use crate::engine::{Game, Phase};
use crate::state::{Item, Minion, Pending};
use crate::types::{Kw, PlayerId};

/// Value added to a minion that would be the second copy, or the third (a golden minion and a
/// Discover from a higher Tier).
const PAIR: i32 = 8;
const TRIPLE: i32 = 25;
/// Value added to a card of the comp the bot builds toward.
const CORE: i32 = 15;
const ADDON: i32 = 6;
/// A Tavern card is worth a Freeze when it adds this much over its stats.
const KEEP: i32 = PAIR;

fn plan(g: &Game) -> &TeacherConfig {
    g.cfg.teacher.as_ref().expect("teacher config")
}

fn name_of(c: CardId) -> &'static str {
    db().get(c).id.as_str()
}

/// Non-golden copies of `card` (by normal form) on `p`'s warband and in hand.
fn copies(g: &Game, p: PlayerId, card: CardId) -> usize {
    let d = db();
    let normal = d.normal_of(card);
    let pl = &g.players[p];
    pl.board
        .iter()
        .filter(|m| !m.golden && d.normal_of(m.card) == normal)
        .count()
        + pl.hand
            .iter()
            .filter(|h| matches!(&h.item, Item::Minion(m) if !m.golden && d.normal_of(m.card) == normal))
            .count()
}

/// The comp `p` builds toward (an index into `TeacherConfig::comps`): from `commit_turn`, the
/// one its cards are closest to, core cards counting twice, with at least one core card.
fn target_comp(g: &Game, p: PlayerId) -> Option<usize> {
    let t = plan(g);
    if g.turn < t.commit_turn {
        return None;
    }
    let d = db();
    let pl = &g.players[p];
    let owned: Vec<CardId> = pl
        .board
        .iter()
        .map(|m| d.normal_of(m.card))
        .chain(pl.hand.iter().map(|h| d.normal_of(h.item.card())))
        .collect();
    let has = |s: &String| d.find(s).is_some_and(|c| owned.contains(&d.normal_of(c)));
    let mut best: Option<(f64, usize)> = None;
    for (i, c) in t.comps.iter().enumerate() {
        let core = c.core.iter().filter(|s| has(s)).count();
        if core == 0 {
            continue;
        }
        let addon = c.addon.iter().filter(|s| has(s)).count();
        let score = (2 * core + addon) as f64 / (2 * c.core.len() + c.addon.len()) as f64;
        if best.is_none_or(|(b, _)| score > b) {
            best = Some((score, i));
        }
    }
    best.map(|(_, i)| i)
}

fn comp_bonus(g: &Game, comp: Option<usize>, card: CardId) -> i32 {
    let Some(i) = comp else { return 0 };
    let c = &plan(g).comps[i];
    let id = name_of(db().normal_of(card));
    if c.core.iter().any(|s| s == id) {
        CORE
    } else if c.addon.iter().any(|s| s == id) {
        ADDON
    } else {
        0
    }
}

/// What `item` (in the Tavern or offered) is worth to `p` over its stats.
fn bonus(g: &Game, p: PlayerId, comp: Option<usize>, item: &Item) -> i32 {
    let t = plan(g);
    let early = g.turn <= t.early_turns;
    let card = item.card();
    let mut v = comp_bonus(g, comp, card);
    if early {
        v += t.economy.get(name_of(card)).copied().unwrap_or(0);
    }
    if let Item::Minion(m) = item {
        if early {
            v += m
                .attached
                .iter()
                .map(|a| t.gifts.get(name_of(*a)).copied().unwrap_or(0))
                .sum::<i32>();
        }
        if !m.golden {
            v += match copies(g, p, card) {
                0 => 0,
                1 => PAIR,
                _ => TRIPLE,
            };
        }
    }
    v
}

/// What a warband minion is worth keeping.
fn kept(g: &Game, p: PlayerId, comp: Option<usize>, m: &Minion) -> i32 {
    let pair = if !m.golden && copies(g, p, m.card) >= 2 { PAIR } else { 0 };
    minion_value(m) + comp_bonus(g, comp, m.card) + pair
}

/// Choose one action for `p` (always legal when `game.needs_action(p)`).
pub fn choose_action(g: &mut Game, p: PlayerId) -> Action {
    let comp = target_comp(g, p);
    if let Some(top) = g.players[p].pending.last().cloned() {
        // A Discover (a triple's reward, a Dark Gift...): the most valuable option.
        if let Pending::Discover { options, .. } = &top {
            let i = (0..options.len())
                .filter(|i| g.option_legal(p, *i))
                .max_by_key(|i| item_value(&options[*i]) + bonus(g, p, comp, &options[*i]));
            if let Some(i) = i {
                return Action::Choose(i);
            }
        }
        return Action::Choose(pick_option(g, p, &top));
    }
    if g.phase != Phase::Recruit {
        return Action::EndTurn;
    }
    let pl = &g.players[p];
    let mask = g.legal_mask(p);
    let legal = |a: Action| mask[a.encode()];
    if pl.actions_this_turn > 60 {
        return Action::EndTurn;
    }
    // 1. Play cards from hand (the plain bot's way).
    for (h, card) in pl.hand.iter().enumerate().take(N_HAND) {
        match &card.item {
            Item::Minion(m) => {
                if m.has(Kw::MAGNETIC)
                    && let Some(b) = (0..pl.board.len().min(N_BOARD))
                        .find(|b| legal(Action::Magnetize { hand: h, board: *b }))
                {
                    return Action::Magnetize { hand: h, board: b };
                }
                let pos = pl.board.len();
                if pos < 8 && legal(Action::Play { hand: h, pos }) {
                    return Action::Play { hand: h, pos };
                }
            }
            Item::Spell { .. } => {
                if legal(Action::Play { hand: h, pos: 0 }) {
                    return Action::Play { hand: h, pos: 0 };
                }
            }
        }
    }
    // 2. Level on the curve, unless low Health asks for warband first.
    let t = plan(g);
    let curve_tier = 1 + t.level_turns.iter().filter(|x| g.turn >= **x).count() as u8;
    let low = pl.health <= 10 && pl.tier >= 4;
    if pl.tier < curve_tier && !low && legal(Action::Upgrade) {
        return Action::Upgrade;
    }
    // 3. The best Tavern card.
    let worth = |s: &Item| item_value(s) + bonus(g, p, comp, s);
    let best = pl
        .shop
        .iter()
        .enumerate()
        .filter(|(i, _)| legal(Action::Buy(*i)))
        .max_by_key(|(_, s)| worth(&s.item));
    let minions_owned = pl.board.len()
        + pl.hand.iter().filter(|h| matches!(h.item, Item::Minion(_))).count();
    let room = minions_owned < g.cfg.board_size;
    // Early, a Dark Gift beats a card with nothing beyond its stats.
    let plain = best.is_none_or(|(_, s)| bonus(g, p, comp, &s.item) <= 0);
    if legal(Action::DarkGift) && room && plain && g.turn <= t.early_turns {
        return Action::DarkGift;
    }
    // 4. Full warband: sell the least kept for a clearly better card.
    if pl.board.len() >= g.cfg.board_size
        && let Some((_, s)) = best
        && let Some((wi, wm)) = pl
            .board
            .iter()
            .enumerate()
            .min_by_key(|(_, m)| kept(g, p, comp, m))
        && worth(&s.item) > kept(g, p, comp, wm) + 4
        && pl.gold >= g.minion_price(p)
        && legal(Action::Sell(wi))
    {
        return Action::Sell(wi);
    }
    // 5. Buy (a minion when there is room or it pairs up).
    if let Some((i, s)) = best {
        let pairs = matches!(&s.item, Item::Minion(m) if !m.golden && copies(g, p, m.card) >= 1);
        if !matches!(s.item, Item::Minion(_)) || room || pairs {
            return Action::Buy(i);
        }
    }
    // 6. Dark Gift, Hero Power, Activate.
    if legal(Action::DarkGift) && room {
        return Action::DarkGift;
    }
    for slot in 0..N_POWERS {
        if legal(Action::HeroPower(slot)) {
            return Action::HeroPower(slot);
        }
    }
    for i in 0..pl.board.len().min(N_BOARD) {
        if legal(Action::Activate(i)) {
            return Action::Activate(i);
        }
    }
    // 7. A cheap level off the curve.
    if legal(Action::Upgrade) && g.upgrade_price(p) <= 3 {
        return Action::Upgrade;
    }
    // 8. Keep a card worth having for next turn; otherwise spend the Gold on Refreshes.
    let keep = pl.shop.iter().any(|s| bonus(g, p, comp, &s.item) >= KEEP);
    if keep && !pl.is_frozen() && legal(Action::Freeze) {
        return Action::Freeze;
    }
    if legal(Action::Refresh)
        && !(keep && pl.is_frozen())
        && pl.stats.refreshes < 30 * g.turn as i32
        && pl.actions_this_turn < 50
    {
        return Action::Refresh;
    }
    Action::EndTurn
}
