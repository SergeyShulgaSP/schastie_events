"""Количественный анализ сделок: воронка, отказы, источники, скорость реакции, менеджеры, товары.
Результат: data/metrics.json + таблица lead_features в data/amo.sqlite."""
import collections, json, os, re, sqlite3, statistics as st
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "..", "data", "amo.sqlite")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "metrics.json")
WON, LOST = 142, 143
CHAT = {"chat.apps.telegram": "Telegram", "telegram": "Telegram", "newamo.chatapp.waweb": "WhatsApp",
        "online.chatapp.max": "MAX", "onlinechat": "Онлайн-чат сайта", "ru.teletype": "Teletype"}


def main():
    db = sqlite3.connect(DB, timeout=120)
    q = lambda s, *a: db.execute(s, a).fetchall()
    users = dict(q("SELECT id,name FROM users"))
    reasons = dict(q("SELECT id,name FROM loss_reasons"))
    leads = {r[0]: dict(zip(["id", "status", "pipeline", "resp", "reason", "created", "closed", "price", "tags", "cf"], r))
             for r in q("SELECT id,status_id,pipeline_id,responsible_user_id,loss_reason_id,created_at,closed_at,price,tags,custom_fields FROM leads")}
    notes = collections.defaultdict(list)
    import link_notes; link_notes.build(db)
    for eid, nt, by, at, text, prm in q("SELECT lead_id,note_type,created_by,created_at,text,params FROM lead_notes ORDER BY created_at"):
        notes[eid].append((nt, by, at, text or "", json.loads(prm or "{}")))
    chats = collections.defaultdict(list)
    for eid, tp, by, at, raw in q("SELECT entity_id,type,created_by,created_at,raw FROM chat_events WHERE entity_type='lead' ORDER BY created_at"):
        origin = json.loads(raw)["value_after"][0]["message"].get("origin")
        chats[eid].append((tp, by, at, origin))
    tasks = collections.defaultdict(list)
    for eid, comp, till, ca in q("SELECT entity_id,is_completed,complete_till,created_at FROM tasks WHERE entity_type='leads'"):
        tasks[eid].append((comp, till, ca))
    order = dict(q("SELECT id,sort FROM statuses"))
    sname = dict(q("SELECT id,name FROM statuses"))
    hist = collections.defaultdict(list)
    for lid, at, fr, to in q("SELECT lead_id,created_at,from_status,to_status FROM status_events ORDER BY created_at"):
        hist[lid].append((at, fr, to))

    feats = []
    for l in leads.values():
        lid = l["id"]; ns = notes[lid]; cs = chats[lid]
        tags = json.loads(l["tags"] or "[]"); text = "\n".join(n[3] for n in ns if n[0] == "common")
        # источник
        if any("Телфин" in t or t == "Calltracking" for t in tags): src = "Звонок на номер"
        elif "квиз" in tags: src = "Квиз catalog.k-truck.ru"
        elif any("k-truck.ru" == t or "сайт K-TRUCK" == t for t in tags): src = "Заявка с сайта (форма)"
        elif re.search(r"^Выбер[еи]те категорию|^whatsapp:.*\n+Выбер", text, re.M): src = "Telegram-бот (квиз)"
        elif "SKU" in text or "Shipping:" in text: src = "Заказ через корзину сайта"
        elif "Additional information about the sender" in text: src = "Форма обратной связи сайта"
        elif any(n[0] == "amomail_message" for n in ns): src = "Email"
        elif cs and cs[0][3] in CHAT: src = "Входящий чат: " + CHAT[cs[0][3]]
        elif any(n[0] == "call_in" for n in ns): src = "Звонок на номер"
        else: src = "Не определён"
        cfv = {f["field_name"]: f["values"][0]["value"] for f in json.loads(l["cf"] or "null") or []}
        utm = cfv.get("utm_source") or ""
        # категория и модель
        m = re.search(r"Выбер[еи]те категорию\n(.+)", text) or re.search(r"Категория: (.+)", text)
        cat = m.group(1).strip() if m else None
        mm = re.search(r"Выбер[еи]те модель[^\n]*\n(.+)", text) or re.search(r"Модель: (.+)", text) or re.search(r"^(Мини[^/\n]+?) / SKU", text, re.M)
        model = mm.group(1).strip() if mm else None
        if not cat:
            for n in ns:
                if n[0] == "link_followed":
                    u = n[4].get("url", "")
                    k = re.search(r"/product(?:-category)?/([^/]+)", u)
                    if k:
                        slug = k.group(1)
                        cat = ("Мини-экскаваторы" if "ekskavator" in slug else "Мини-погрузчики" if "pogruzchik" in slug
                               else "Мини-думпер" if "dumper" in slug or "dumper" in u else "Мини-тракторы" if "traktor" in slug
                               else "Прочее"); break
        if cat and "кскават" in cat: cat = "Мини-экскаваторы"
        elif cat and "огрузчик" in cat: cat = "Мини-погрузчики"
        elif cat and "думпер" in cat.lower(): cat = "Мини-думперы"
        elif cat and "трактор" in cat.lower(): cat = "Мини-тракторы"
        g = re.search(r"Местоположение: Россия, ([^\n|]+)", text) or re.search(r"Город: ([^\n|]+)", text)
        city = g.group(1).strip() if g else None
        d = re.search(r"Выбер[еи]те способ доставки\n(.+)", text)
        delivery = d.group(1).strip() if d else None
        # касания менеджера
        out_calls = [n for n in ns if n[0] == "call_out"]
        talk_calls = [n for n in ns if n[0].startswith("call") and (n[4].get("duration") or 0) > 0]
        in_missed = [n for n in ns if n[0] == "call_in" and n[4].get("call_result") == "Пропущенный звонок"]
        human_msgs = [c for c in cs if c[0] == "outgoing_chat_message" and (c[1] != 0 or c[3] in ("newamo.chatapp.waweb", "online.chatapp.max"))]
        in_msgs = [c for c in cs if c[0] == "incoming_chat_message"]
        touches = sorted([n[2] for n in out_calls] + [c[2] for c in human_msgs])
        first = next((t for t in touches if t >= l["created"]), None)
        react_min = (first - l["created"]) / 60 if first else None
        manual_notes = [n for n in ns if n[0] == "common" and n[1] != 0]
        tk = tasks[lid]
        overdue = sum(1 for c, till, ca in tk if not c and till and till < 1795200000)
        # стадия
        maxs = max([order.get(to, 0) for _, _, to in hist[lid] if to not in (WON, LOST)] + [order.get(l["status"], 0) if l["status"] not in (WON, LOST) else 0])
        closed_from = next((sname.get(fr) for at, fr, to in reversed(hist[lid]) if to == LOST), None)
        outcome = "won" if l["status"] == WON else "lost" if l["status"] == LOST else "open"
        won_at = next((at for at, fr, to in hist[lid] if to == WON), l["closed"])
        feats.append(dict(
            lead_id=lid, outcome=outcome, created=l["created"], month=datetime.fromtimestamp(l["created"]).strftime("%Y-%m"),
            manager=users.get(l["resp"], str(l["resp"])), reason=reasons.get(l["reason"]) if outcome == "lost" else None,
            source=src, utm_source=utm, category=cat, model=model, city=city, delivery=delivery, price=l["price"] or 0,
            max_stage=maxs, closed_from=closed_from, react_min=react_min, out_calls=len(out_calls), talks=len(talk_calls),
            talk_sec=sum(n[4].get("duration") or 0 for n in talk_calls), missed_in=len(in_missed),
            msgs_out=len(human_msgs), msgs_in=len(in_msgs), manual_notes=len(manual_notes), tasks=len(tk), overdue=overdue,
            days_to_win=(won_at - l["created"]) / 86400 if outcome == "won" and won_at else None,
            channel=CHAT.get(cs[0][3]) if cs else None))

    db.execute("DROP TABLE IF EXISTS lead_features")
    cols = list(feats[0])
    db.execute(f"CREATE TABLE lead_features({','.join(cols)})")
    db.executemany(f"INSERT INTO lead_features VALUES({','.join('?' * len(cols))})", [tuple(f[c] for c in cols) for f in feats])
    db.commit()

    def conv(rows):
        w = sum(r["outcome"] == "won" for r in rows); lo = sum(r["outcome"] == "lost" for r in rows)
        return dict(n=len(rows), won=w, lost=lo, open=len(rows) - w - lo, conv=round(100 * w / len(rows), 2) if rows else 0)

    def by(key, rows=feats, minn=0):
        g = collections.defaultdict(list)
        for r in rows: g[r[key] if r[key] is not None else "—"].append(r)
        return {k: conv(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])) if len(v) >= minn}

    nospam = [r for r in feats if r["reason"] != "Спам"]
    stage_names = [(s, n) for i, n, s in q("SELECT id,name,sort FROM statuses WHERE pipeline_id=8016678 AND id NOT IN (142,143) ORDER BY sort")]
    funnel = [(n, sum(1 for r in nospam if r["max_stage"] >= s or r["outcome"] == "won")) for s, n in stage_names]
    funnel.append(("Груз выдан", sum(r["outcome"] == "won" for r in nospam)))

    def bucket(m):
        if m is None: return "6. Не было исходящего касания"
        return ("1. до 5 мин" if m <= 5 else "2. 5–30 мин" if m <= 30 else "3. 30 мин–2 ч" if m <= 120
                else "4. 2–24 ч" if m <= 1440 else "5. больше суток")

    for r in feats: r["react_bucket"] = bucket(r["react_min"])
    lost = [r for r in feats if r["outcome"] == "lost"]
    won = [r for r in feats if r["outcome"] == "won"]
    med = lambda xs: round(st.median(xs), 1) if xs else None
    mgr = {}
    for m, rows in collections.Counter(r["manager"] for r in feats).items():
        rs = [r for r in feats if r["manager"] == m]; ls = [r for r in rs if r["outcome"] == "lost"]
        mgr[m] = dict(conv(rs), no_reason_pct=round(100 * sum(r["reason"] is None for r in ls) / max(1, len(ls)), 1),
                      react_median_min=med([r["react_min"] for r in rs if r["react_min"] is not None]),
                      no_touch_pct=round(100 * sum(r["react_min"] is None for r in rs) / len(rs), 1),
                      overdue_tasks=sum(r["overdue"] for r in rs))
    year = lambda r: r["month"][:4]
    metrics = dict(
        generated=datetime.now().isoformat(timespec="minutes"),
        period=[min(r["month"] for r in feats), max(r["month"] for r in feats)],
        total=conv(feats), total_no_spam=conv(nospam),
        revenue_won=sum(r["price"] for r in won), avg_check_won=round(st.mean([r["price"] for r in won if r["price"]]) if won else 0),
        monthly=by("month"), by_year={y: conv([r for r in feats if year(r) == y]) for y in sorted({year(r) for r in feats})},
        funnel=funnel,
        loss_reasons=collections.Counter(r["reason"] or "Не указана" for r in lost).most_common(),
        loss_reason_by_year={y: collections.Counter(r["reason"] or "Не указана" for r in lost if year(r) == y).most_common() for y in sorted({year(r) for r in lost})},
        closed_from=collections.Counter(r["closed_from"] or "нет данных" for r in lost).most_common(),
        reason_x_stage={rs: collections.Counter(r["closed_from"] or "нет данных" for r in lost if (r["reason"] or "Не указана") == rs).most_common()
                        for rs in {r["reason"] or "Не указана" for r in lost}},
        sources=by("source", nospam), utm=by("utm_source", nospam, 20), channel=by("channel", nospam, 10),
        categories=by("category", nospam, 5), models=by("model", nospam, 30), cities=by("city", nospam, 40),
        delivery=by("delivery", nospam, 10),
        reaction=by("react_bucket", nospam),
        reaction_median_min=med([r["react_min"] for r in nospam if r["react_min"] is not None]),
        managers=mgr,
        won_vs_lost={k: dict(won=med([r[k] for r in won]), lost=med([r[k] for r in lost if r["reason"] != "Спам"]))
                     for k in ("out_calls", "talks", "talk_sec", "msgs_out", "msgs_in", "manual_notes", "tasks", "missed_in")},
        lost_without_talk=sum(1 for r in lost if r["talks"] == 0 and r["msgs_out"] == 0 and r["reason"] != "Спам"),
        lost_single_touch=sum(1 for r in lost if r["out_calls"] + r["msgs_out"] <= 1 and r["reason"] != "Спам"),
        lost_no_note=sum(1 for r in lost if r["manual_notes"] == 0 and r["reason"] is None),
        days_to_win=dict(median=med([r["days_to_win"] for r in won if r["days_to_win"] is not None]),
                         p75=round(sorted(r["days_to_win"] for r in won if r["days_to_win"])[int(len(won) * .75)], 1) if won else None),
        missed_in_total=sum(r["missed_in"] for r in feats),
        open_leads=[dict(id=r["lead_id"], manager=r["manager"], stage_sort=r["max_stage"]) for r in feats if r["outcome"] == "open"],
    )
    with open(OUT, "w") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    print(f"OK → {OUT}")


if __name__ == "__main__":
    main()
