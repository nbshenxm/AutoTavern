"""The overlay's rows for a plan, in the constructed advisor's format (its HDT plugin draws the
same rows): per step a verb, the acting card by its place (Tavern slot, hand slot, warband slot,
Hero Power) with its tile, the target by its place and tile, and where a played minion goes.
Places are counted from the left as the step begins.
"""

A_MOVE = 196  # taverngym.layout()

TEXT = {
    "enUS": {
        "buy": "Buy", "sell": "Sell", "play": "Play", "magnetize": "Magnetize",
        "hero_power": "Hero Power", "activate": "Activate", "choose": "Choose",
        "target": "Target", "upgrade": "Level up", "refresh": "Refresh", "freeze": "Freeze",
        "end": "End turn", "dark_gift": "Dark Discovery", "arrange": "Arrange", "cancel": "Back",
        "then_choose": "Then choose from what you're offered (the advice updates)",
        "then_tavern": "Then buy from the new Tavern (the advice updates)",
        "badge_tavern": "T{n}", "badge_hand": "H{n}", "badge_board": "B{n}",
        "badge_hero_power": "HP", "badge_choose": "Pick",
        "title": "Turn {turn}", "odds": "{label}: win {win:.0%} · tie {tie:.0%} · lose {loss:.0%}",
        "odds_seen": " (their warband from turn {turn})", "now": "Now", "after": "After the plan",
        "more": "… {n} more",
        "odds_stale": "Next opponent's warband last seen on turn {turn}: no odds",
        "trinket_stats": " · avg {place:.2f} · picked {pick:.0%}",
        "comp": "Closest meta comp: {name} (HSReplay tier {tier}), {have} of {of} core cards",
        "comp_missing": "; missing {cards}",
    },
    "zhCN": {
        "buy": "购买", "sell": "出售", "play": "打出", "magnetize": "磁力吸附",
        "hero_power": "英雄技能", "activate": "激活", "choose": "选择", "target": "目标",
        "upgrade": "升级酒馆", "refresh": "刷新", "freeze": "冻结", "end": "结束回合",
        "dark_gift": "黑暗发现", "arrange": "调整站位", "cancel": "取消",
        "then_choose": "然后从出现的选项中选择（建议会更新）",
        "then_tavern": "然后从刷新后的酒馆中购买（建议会更新）",
        "badge_tavern": "酒馆{n}", "badge_hand": "手{n}", "badge_board": "场{n}",
        "badge_hero_power": "技能", "badge_choose": "选择",
        "title": "第{turn}回合", "odds": "{label}：胜 {win:.0%} · 平 {tie:.0%} · 负 {loss:.0%}",
        "odds_seen": "（对手阵容来自第{turn}回合）", "now": "现在", "after": "按计划之后",
        "more": "… 还有{n}步",
        "odds_stale": "下一个对手的阵容最后见于第{turn}回合：不计算胜率",
        "trinket_stats": " · 平均{place:.2f}名 · 选取率{pick:.0%}",
        "comp": "最接近的流行流派：{name}（HSReplay {tier}级），核心卡 {have}/{of}",
        "comp_missing": "；缺少 {cards}",
    },
}


_TRINKETS = None


def trinket_stats():
    """advisor.meta.trinket_stats(), read once per advisor run."""
    global _TRINKETS
    if _TRINKETS is None:
        from advisor import meta
        _TRINKETS = meta.trinket_stats()
    return _TRINKETS


def t(locale, key, **kw):
    return (TEXT.get(locale) or TEXT["enUS"])[key].format(**kw)


def _card(entry):
    return entry.get("id") if isinstance(entry, dict) else None


def row_for(view, a, locale, name_of):
    """The row of action `a` taken in `view` (the player's TavernGym view), or None for a
    choice that completes the previous row (a target, see `merge_target`)."""
    me = view["me"]
    slot = lambda zone, i: me[zone][i] if i < len(me[zone]) else {}
    row = {"verb": None, "badge": "", "badge_kind": "", "card_id": None, "name": None}

    def card(zone, i, badge_key, kind):
        e = slot(zone, i)
        row.update(badge=t(locale, badge_key, n=i + 1), badge_kind=kind, card_id=_card(e),
                   name=name_of(_card(e), locale) if _card(e) else None)

    if a in (0, 1, 2, 3, 6, 7):
        row["verb"] = t(locale, {0: "end", 1: "refresh", 2: "freeze", 3: "upgrade",
                                 6: "dark_gift", 7: "cancel"}[a])
    elif a in (4, 5):
        powers = me.get("hero_powers") or []
        p = powers[a - 4] if a - 4 < len(powers) else {}
        row.update(verb=t(locale, "hero_power"), badge=t(locale, "badge_hero_power"),
                   badge_kind="power", card_id=_card(p), name=name_of(_card(p), locale) if _card(p) else None)
    elif 8 <= a <= 15:
        row["verb"] = t(locale, "buy")
        card("shop", a - 8, "badge_tavern", "tavern")
    elif 16 <= a <= 22:
        row["verb"] = t(locale, "sell")
        card("board", a - 16, "badge_board", "board")
    elif 23 <= a <= 29:
        row["verb"] = t(locale, "activate")
        card("board", a - 23, "badge_board", "board")
    elif 30 <= a <= 45:
        pending = me.get("pending") or {}
        i = a - 30
        if pending.get("kind") == "target":
            return None
        opts = pending.get("options") or []
        o = opts[i] if i < len(opts) and isinstance(opts[i], dict) else {}
        name = name_of(_card(o), locale) if _card(o) else f"#{i + 1}"
        # A Dark Discovery offer carries its Dark Gift: say which
        gifts = [a for a in o.get("attached") or [] if isinstance(a, dict) and a.get("kind") == "dark_gift"]
        if gifts:
            name += " + " + ", ".join(name_of(g["id"], locale) for g in gifts)
        # A trinket: what the public data says of it (Firestone, the last 7 days)
        stats = trinket_stats().get(_card(o) or "") if str(o.get("kind", "")).startswith("trinket") else None
        if stats:
            name += t(locale, "trinket_stats", place=stats["place"], pick=stats["pick"])
        row.update(verb=t(locale, "choose"), badge=t(locale, "badge_choose"), badge_kind="choose",
                   card_id=_card(o), name=name)
    elif 46 <= a <= 125:
        h, pos = divmod(a - 46, 8)
        row["verb"] = t(locale, "play")
        card("hand", h, "badge_hand", "hand")
        if (slot("hand", h).get("kind") == "minion") and me["board"]:
            row["place"] = t(locale, "badge_board", n=pos + 1)
    elif 126 <= a <= 195:
        h, tgt = divmod(a - 126, 7)
        row["verb"] = t(locale, "magnetize")
        card("hand", h, "badge_hand", "hand")
        e = slot("board", tgt)
        row.update(action="target", target_badge=t(locale, "badge_board", n=tgt + 1),
                   target_badge_kind="board", target_card_id=_card(e),
                   target_name=name_of(_card(e), locale) if _card(e) else None)
    return row


def merge_target(rows, view, a, locale, name_of):
    """A target choice: added to the step that asked for it (or a row of its own)."""
    me = view["me"]
    eids = (me.get("pending") or {}).get("targets") or []
    i = a - 30
    where = {}
    for zone, key, kind in (("board", "badge_board", "board"), ("shop", "badge_tavern", "tavern"),
                            ("hand", "badge_hand", "hand")):
        for j, e in enumerate(me.get(zone) or []):
            if isinstance(e, dict) and "eid" in e:
                where[e["eid"]] = (t(locale, key, n=j + 1), kind, e.get("id"))
    if i >= len(eids) or eids[i] not in where:
        return
    badge, kind, cid = where[eids[i]]
    target = {"action": "target", "target_badge": badge, "target_badge_kind": kind,
              "target_card_id": cid, "target_name": name_of(cid, locale)}
    if rows and "target_card_id" not in rows[-1] and rows[-1]["verb"] != t(locale, "arrange"):
        rows[-1].update(target)
    else:
        rows.append({"verb": t(locale, "target"), "badge": "", "badge_kind": "", "card_id": None,
                     "name": None, **target})


def arrange_row(view, locale, name_of):
    board = view["me"]["board"]
    return {"verb": t(locale, "arrange"), "badge": "", "badge_kind": "", "card_id": None,
            "name": None, "cards": [{"card_id": m["id"], "name": name_of(m["id"], locale)}
                                    for m in board]}


MAX_ODDS_AGE = 3  # turns: odds against an older warband would mislead


def odds_note(label, odds, locale, turn=None):
    if not odds:
        return None
    if turn is not None and odds.get("seen_turn") and turn - odds["seen_turn"] > MAX_ODDS_AGE:
        return t(locale, "odds_stale", turn=odds["seen_turn"]) if label == "now" else None
    s = t(locale, "odds", label=t(locale, label), win=odds["win"], tie=odds["tie"],
          loss=odds["loss"])
    if odds.get("seen_turn"):
        s += t(locale, "odds_seen", turn=odds["seen_turn"])
    return s


def comp_note(comp, locale, name_of):
    """The meta comp the player's cards are closest to (advisor.meta.closest), or None."""
    if not comp:
        return None
    s = t(locale, "comp", name=comp["name"], tier=comp["tier"], have=comp["have"], of=comp["of"])
    if comp["missing"]:
        s += t(locale, "comp_missing", cards=", ".join(name_of(c, locale) for c in comp["missing"]))
    return s


def collapse(rows, locale):
    """Runs of the same button: Refresh x3; Freeze presses toggle, so an even run is nothing."""
    out = []
    for r in rows:
        simple = r["card_id"] is None and "target_card_id" not in r and "cards" not in r
        if simple and out and out[-1].get("verb") == r["verb"] and out[-1].get("_simple"):
            out[-1]["_count"] += 1
            continue
        out.append({**r, "_simple": simple, "_count": 1})
    final = []
    for r in out:
        count = r.pop("_count")
        r.pop("_simple")
        if r["verb"] == t(locale, "freeze"):
            if count % 2 == 0:
                continue
        elif count > 1:
            r["verb"] += f" ×{count}"
        final.append(r)
    for n, r in enumerate(final, 1):
        r["n"] = n
    return final


def chance_row(kind, locale):
    """The last row of a plan that reaches a random step: what to do once it resolves."""
    return {"verb": t(locale, "then_tavern" if kind == "tavern" else "then_choose"), "badge": "",
            "badge_kind": "", "card_id": None, "name": None}
