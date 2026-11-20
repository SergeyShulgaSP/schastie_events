"""Готовит наборы данных для дашборда «Анализ сделок K-truck» (data/report/*.json).
Каждый файл: {rows, meta}; meta содержит код этого скрипта, чтобы цифры можно было проверить и пересчитать.
Входные данные: data/amo.sqlite (export.py → link_notes.py → analyze.py → reasons.py → transcribe.py)."""
import collections, json, os, re, sqlite3, statistics as st
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "report")
WON, LOST, KP = 142, 143, 65738818
CODE = open(os.path.abspath(__file__)).read()


def save(name, rows, note):
    os.makedirs(OUT, exist_ok=True)
    meta = [{"label": "Как посчитано", "value": note},
            {"label": "Источник", "value": "amoCRM gres16 (K-truck), выгрузка API v4 от " + datetime.now().strftime("%d.%m.%Y")},
            {"label": "report_data.py", "value": CODE, "type": "code", "lang": "python"}]
    json.dump({"rows": rows, "meta": meta}, open(os.path.join(OUT, name + ".json"), "w"), ensure_ascii=False)


def main():
    db = sqlite3.connect(os.path.join(DATA, "amo.sqlite"), timeout=120)
    q = lambda s, *a: db.execute(s, a).fetchall()
    m = json.load(open(os.path.join(DATA, "metrics.json")))
    rs = json.load(open(os.path.join(DATA, "reasons.json")))
    F = [dict(zip([d[0] for d in db.execute("SELECT * FROM lead_features LIMIT 0").description], r)) for r in q("SELECT * FROM lead_features")]
    nospam = [r for r in F if r["reason"] != "Спам"]
    lost = [r for r in F if r["outcome"] == "lost"]

    # касания после КП
    kp_at = dict(q("SELECT lead_id,min(created_at) FROM status_events WHERE to_status=? GROUP BY 1", KP))
    touch = collections.defaultdict(list)
    for lid, at in q("SELECT lead_id,created_at FROM lead_notes WHERE note_type='call_out'"):
        touch[lid].append(at)
    for lid, at, by, org in q("""SELECT entity_id,created_at,created_by,json_extract(raw,'$.value_after[0].message.origin')
                                 FROM chat_events WHERE type='outgoing_chat_message' AND entity_type='lead'"""):
        if by != 0 or org in ("newamo.chatapp.waweb", "online.chatapp.max"):
            touch[lid].append(at)
    fu = collections.defaultdict(lambda: collections.Counter())
    for r in nospam:
        if r["lead_id"] in kp_at and r["outcome"] in ("won", "lost"):
            n = sum(1 for t in touch[r["lead_id"]] if t > kp_at[r["lead_id"]] + 3600)
            fu["нет касаний" if n == 0 else "1–2 касания" if n <= 2 else "3 и больше"][r["outcome"]] += 1
    followup = [{"касаний после КП": k, "выиграно": fu[k]["won"], "проиграно": fu[k]["lost"],
                 "конверсия, %": round(100 * fu[k]["won"] / max(1, fu[k]["won"] + fu[k]["lost"]), 1)}
                for k in ("нет касаний", "1–2 касания", "3 и больше")]
    save("followup", followup, "Сделки, дошедшие до этапа «расчёт отправлен/КП» (без спама). Касание — исходящий звонок или сообщение менеджера позже чем через час после перехода на этап КП.")

    # пропущенные входящие
    norm = lambda p: re.sub(r"\D", "", p or "")[-10:]
    outs = collections.defaultdict(list)
    for at, p in q("SELECT created_at,json_extract(params,'$.phone') FROM notes WHERE note_type='call_out'"):
        outs[norm(p)].append(at)
    for v in outs.values(): v.sort()
    import bisect
    cb = collections.Counter()
    for at, p in q("SELECT created_at,json_extract(params,'$.phone') FROM notes WHERE note_type='call_in' AND json_extract(params,'$.call_result')='Пропущенный звонок'"):
        v = outs.get(norm(p), []); i = bisect.bisect_left(v, at)
        if i == len(v): cb["5. не перезвонили"] += 1; continue
        d = (v[i] - at) / 60
        cb["1. до 15 минут" if d <= 15 else "2. 15–60 минут" if d <= 60 else "3. 1–24 часа" if d <= 1440 else "4. позже суток"] += 1
    callbacks = [{"перезвон": k[3:], "звонков": v} for k, v in sorted(cb.items())]
    save("callbacks", callbacks, "Пропущенные входящие звонки Telphin и время до первого исходящего звонка на тот же номер.")

    # пустые результаты задач
    users = dict(q("SELECT id,name FROM users"))
    tc, te = collections.Counter(), collections.Counter()
    for u, r in q("SELECT responsible_user_id,json_extract(result,'$.text') FROM tasks WHERE is_completed=1"):
        n = users.get(u, "?"); tc[n] += 1
        if not r or re.fullmatch(r"[\s+.\-–,]*|\d{1,2}[./]\d{1,2}([./]\d{2,4})?|ок|ok|связал\w*|написал\w*|кс\d|к", r.strip().lower()):
            te[n] += 1

    mg = []
    for name, v in m["managers"].items():
        if v["n"] < 50: continue
        mg.append({"менеджер": name, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"],
                   "медиана реакции, ч": round(v["react_median_min"] / 60, 1) if v["react_median_min"] else None,
                   "без исходящего касания, %": v["no_touch_pct"],
                   "отказов без причины, %": v["no_reason_pct"],
                   "задач закрыто без комментария, %": round(100 * te[name] / tc[name]) if tc[name] else None})
    save("managers", mg, "Ответственный по сделке. Реакция — от создания сделки до первого исходящего звонка или сообщения менеджера. Пустой результат задачи — «+», «.», дата или одно слово.")

    tot = m["total"]; ns = m["total_no_spam"]
    no_reason = sum(1 for r in lost if r["reason"] is None)
    kpi = [{"сделок": tot["n"], "выиграно": tot["won"], "проиграно": tot["lost"], "в работе": tot["open"],
            "конверсия, %": tot["conv"], "конверсия без спама, %": ns["conv"],
            "бюджет выигранных, ₽": m["revenue_won"], "средний бюджет выигранной, ₽": m["avg_check_won"],
            "отказов без причины": no_reason, "отказов без причины, %": round(100 * no_reason / len(lost), 1),
            "медиана реакции, ч": round(m["reaction_median_min"] / 60, 1),
            "дней до выдачи груза (медиана)": m["days_to_win"]["median"],
            "период с": m["period"][0], "период по": m["period"][1]}]
    save("kpi", kpi, "Все сделки аккаунта (воронка «Китай»). Конверсия — доля сделок в статусе «Груз выдан». Бюджет — поле «Бюджет» сделки.")

    monthly = [{"месяц": k, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for k, v in sorted(m["monthly"].items())]
    save("monthly", monthly, "Сделки по месяцу создания и их итог на дату выгрузки. Последние месяцы ещё в работе.")

    save("funnel", [{"этап": n, "дошло сделок": c} for n, c in m["funnel"]],
         "Сколько сделок (без спама) хотя бы раз дошли до этапа — по истории смены статусов.")
    save("loss_crm", [{"причина в CRM": k, "сделок": v} for k, v in m["loss_reasons"]],
         "Поле «Причина отказа» у закрытых нереализованных сделок.")
    save("closed_from", [{"этап": k, "закрыто сделок": v} for k, v in m["closed_from"] if v >= 10],
         "С какого этапа сделка переведена в «Закрыто и не реализовано».")
    real = [{"реальная причина": k, "сделок": v} for k, v in rs["real_reasons"]]
    save("loss_real", real, f"Закрытые нереализованные сделки (без спама), по которым есть комментарии менеджеров, результаты задач или расшифровки звонков: {rs['lost_with_text']} шт. Причины найдены по ключевым словам в тексте; у сделки может быть несколько причин.")
    src = [{"источник": k, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for k, v in m["sources"].items()]
    save("sources", src, "Источник определён по тегам сделки, первой заметке (квиз-бот Telegram, форма сайта, корзина) или первому каналу чата. Без спама.")
    save("reaction", [{"скорость реакции": k[3:], "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for k, v in sorted(m["reaction"].items())],
         "От создания сделки до первого исходящего звонка или сообщения менеджера. Без спама.")
    cats = [{"категория": k, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for k, v in m["categories"].items() if k != "—"]
    save("categories", cats, "Категория техники из квиза или формы сайта. Сделки без указанной категории не показаны.")
    dl = [{"способ доставки": k, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for k, v in m["delivery"].items() if k != "—"]
    save("delivery", dl, "Способ доставки, выбранный клиентом в квиз-боте Telegram.")
    yrs = [{"год": y, "сделок": v["n"], "выиграно": v["won"], "конверсия, %": v["conv"]} for y, v in m["by_year"].items()]
    save("years", yrs, "По году создания сделки. 2026 год неполный, часть сделок ещё в работе.")

    kb = [dict(zip(["тема", "вопрос клиента", "как отвечать", "как часто"], r)) for r in
          q("SELECT category,question,best_answer,frequency FROM kb_questions ORDER BY category,frequency DESC")]
    if kb:
        save("kb", kb, "База вопросов клиентов: собрана по расшифровкам звонков, комментариям менеджеров и результатам задач. Ответы — лучшие формулировки менеджеров K-truck, сведённые в один ответ.")
    mq = [dict(zip(["ситуация", "что сказал менеджер", "оценка", "как лучше"], r)) for r in
          q("SELECT question,answer,score,comment FROM manager_answers ORDER BY score")]
    if mq:
        save("answers", mq, "Разбор ответов менеджеров в расшифрованных звонках: оценка 1–5 и рекомендация.")
    print("ok", os.listdir(OUT))


if __name__ == "__main__":
    main()
