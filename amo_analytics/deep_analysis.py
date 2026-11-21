"""Углублённый анализ на собранных данных (amoCRM, Telegram, ChatApp, ручная таблица сделок).
10 направлений: сезонность, скорость сделки, скорость ответа по часам, менеджеры, повторные клиенты,
источники, география, модели и комплектации, продажи вне amoCRM, портрет клиента.
Результат: data/deep.json (агрегаты без персональных данных) и печать сводки."""
import collections, datetime as dt, json, os, re, sqlite3, statistics as st

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "data", "amo.sqlite")
MSK = dt.timezone(dt.timedelta(hours=3))
OWN_TG = {"K-truck", "K-TRUCK - доставка из Китая 🇨🇳"}
SKIP_TG = {"Куплю Запчасти", "Запчасти на спецтехнику из Европы и США Chat", "K-TRUCK Задачи", "Сергей Шульга",
           "Техника и запчасти из Китая - k-truck Chat"}
CHINA = 8016678
STAGES = [(65739762, "Менеджер назначен"), (65738814, "Переговор"), (65738818, "КП отправлено"), (66041750, "Договор"),
          (65738822, "Предоплата"), (65899094, "Оплата"), (142, "Груз выдан")]


def ts(t): return dt.datetime.fromtimestamp(t, MSK)
def med(v): return round(st.median(v), 1) if v else None
def pct(a, b): return round(100 * a / b, 1) if b else 0.0


PURPOSE = [("Дача, участок, свой дом", r"(?<![а-яё])дач|участ(ок|ка|ке|ки|ков)|огород|сво(й|его) дом|для себя|частн(ый|ого) дом|загородн"),
           ("Стройка: фундамент, траншеи, септик", r"фундамент|траншe|траншея|траншеи|котлован|септик|канализац|водопровод|коммуникац|ленточн|сва[ий]"),
           ("Работа на заказ, аренда, бизнес", r"аренд|на заказ|подработ|работать на (себя|заказ)|для бизнеса|под бизнес|подряд|оказ\w* услуг|брать заказы"),
           ("Ферма, сельское хозяйство", r"ферм(а|ы|е|ер)|хозяйств|навоз|скот|кфх|сельхоз|теплиц"),
           ("Уборка снега, благоустройство", r"снег|уборк\w* (снега|территор)|благоустр|тротуар|коммунал|жкх"),
           ("Лес, пни, расчистка", r"\bпни\b|пней|корчев|расчист|вырубк|лесн|бревн"),
           ("Демонтаж, внутри помещений", r"демонтаж|подвал|внутри помещ|в помещени"),
           ("Пруд, дренаж, мелиорация", r"пруд|водо[её]м|дренаж|мелиорац|канав|скважин")]
BUYER = [("ИП / ООО / компания", r"\bип\b|\bооо\b|юр\.? ?лиц|юрлиц|организац|компани[ия] (купит|оплатит)|с ндс|безнал|на фирму|на организацию"),
         ("Нужен учёт, ЭПСМ, лизинг", r"эпсм|\bпсм\b|на уч[её]т|госреги|лизинг|гостехнадзор")]
REFERRAL = r"посоветовал|порекомендовал|по рекомендаци|знаком(ый|ому|ые) (купил|брал|взял|заказ)|друг (купил|брал|взял|заказ)|сосед (купил|брал|взял)|уже брал у вас|второй раз|ещ[её] одн(у|ин) (машин|экскаватор|технику)|повторн"
SOURCE_WORDS = [("Авито", r"авито|avito"), ("YouTube", r"ютуб|youtube|ютьюб"), ("Telegram-канал", r"ваш(ем|ему)? канал|в канале|на канале|телеграм[- ]?канал"),
                ("Сайт", r"на сайте|ваш сайт|k-truck\.ru"), ("Рекомендация", r"посоветовал|порекомендовал|по рекомендаци|знакомый|друг купил|сосед"),
                ("Яндекс / поиск", r"яндекс|гугл|google|в поиске|нагуглил"), ("ВКонтакте", r"вконтакт|\bвк\b|vk\.com")]
ATTACH = [("ковш", r"ковш"), ("быстросъём", r"быстр\w*с[ъь]?[её]м|быстроразъ|быстрос"), ("планировочный ковш", r"план\w*\.? ?ковш"),
          ("гидробур", r"бур\b|гидробур|бур "), ("удлинитель стрелы", r"удлин"), ("клык / рыхлитель", r"клык|рыхлит"),
          ("щипцы / захват", r"щипц|захват|грейфер"), ("гидромолот", r"молот"), ("кабина", r"кабин"), ("Kubota", r"кубот|kubota"),
          ("отвал / щётка", r"отвал|щ[её]тк"), ("вилы", r"вил[ыа]")]
CITY_NORM = [(r"санкт|спб|питер|петербург|ленинград|\bло\b|гатчин|всеволожск|колпин|пушкин|кировск|выборг|тосно|сестрорецк|кронштадт|ломоносов", "Санкт-Петербург и ЛО"),
             (r"москв|мск|\bмо\b|подмосков|балаших|подольск|химки|мытищ|дмитров|сергиев|ногинск|коломн|одинцов|красногорск|люберц|раменск|серпухов|чехов|домодедов|наро-фом|истр|звенигор", "Москва и МО")]


def norm_city(c):
    c = (c or "").strip()
    if not c: return None
    low = c.lower()
    for rx, name in CITY_NORM:
        if re.search(rx, low): return name
    return re.split(r"[,(/;]", c)[0].strip().title()[:30] or None


def main():
    db = sqlite3.connect(DB, timeout=120)
    q = lambda s, *a: db.execute(s, a).fetchall()
    R = {}
    leads = {r[0]: dict(zip(["id", "outcome", "created", "manager", "reason", "source", "utm", "category", "model", "city", "price",
                             "closed_from", "react", "days_to_win", "channel"], r))
             for r in q("SELECT lead_id,outcome,created,manager,reason,source,utm_source,category,model,city,price,closed_from,react_min,days_to_win,channel FROM lead_features")}
    real = {l for l, in q("SELECT id FROM leads WHERE pipeline_id=?", CHINA)}
    spam = {i for i, l in leads.items() if (l["reason"] or "").lower().startswith("спам")}
    work = {i: l for i, l in leads.items() if i not in spam}
    hist = [dict(zip(["key", "client", "sheets", "date", "manager", "city", "cargo", "kind", "models", "status", "amount"], r))
            for r in q("SELECT key,client,sheets,date,manager,city,cargo,kind,models,status,amount FROM hist_deals")]

    # ---------- 1. Сезонность ----------
    m_leads, m_won, m_hist = collections.Counter(), collections.Counter(), collections.Counter()
    for l in work.values():
        m = ts(l["created"]).strftime("%Y-%m"); m_leads[m] += 1
        if l["outcome"] == "won": m_won[m] += 1
    for h in hist:
        if h["date"]: m_hist[h["date"][:7]] += 1
    tg_first = {}
    for chat, name, t in q("SELECT chat,chat_name,MIN(time) FROM tg_messages GROUP BY chat"):
        if name not in SKIP_TG: tg_first[chat] = t
    m_tg = collections.Counter(ts(t).strftime("%Y-%m") for t in tg_first.values())
    months = sorted(set(m_leads) | set(m_hist) | set(m_tg))
    R["monthly"] = [{"месяц": m, "заявок amoCRM": m_leads[m], "выиграно amoCRM": m_won[m], "новых диалогов Telegram": m_tg[m],
                     "сделок в таблице": m_hist[m]} for m in months if m >= "2024-04"]
    # средний профиль месяца года (по полным годам 2025 и доле)
    cal = collections.defaultdict(lambda: [0, 0, 0])
    for l in work.values():
        d = ts(l["created"])
        if d.year == 2025: cal[d.month][0] += 1; cal[d.month][1] += l["outcome"] == "won"
    for h in hist:
        if h["date"] and h["date"][:4] in ("2025",): cal[int(h["date"][5:7])][2] += 1
    tot = sum(v[0] for v in cal.values())
    R["calendar_2025"] = [{"месяц": m, "заявок": cal[m][0], "доля заявок года, %": pct(cal[m][0], tot), "выиграно amoCRM": cal[m][1], "сделок в таблице": cal[m][2]} for m in range(1, 13)]
    wd = collections.defaultdict(lambda: [0, 0]); hr = collections.defaultdict(lambda: [0, 0, []])
    for l in work.values():
        d = ts(l["created"]); wd[d.weekday()][0] += 1; wd[d.weekday()][1] += l["outcome"] == "won"
        b = "09–13" if 9 <= d.hour < 13 else "13–18" if 13 <= d.hour < 18 else "18–22" if 18 <= d.hour < 22 else "22–09"
        hr[b][0] += 1; hr[b][1] += l["outcome"] == "won"
        if l["react"] is not None: hr[b][2].append(l["react"])
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    R["weekday"] = [{"день": names[k], "заявок": v[0], "выиграно": v[1], "конверсия, %": pct(v[1], v[0])} for k, v in sorted(wd.items())]

    # ---------- 3. Скорость ответа по времени заявки ----------
    R["hour"] = [{"время заявки (МСК)": k, "заявок": v[0], "доля, %": pct(v[0], len(work)), "медиана первой реакции, мин": med(v[2]),
                  "конверсия, %": pct(v[1], v[0])} for k, v in sorted(hr.items())]
    wk = {"будни": [0, 0, []], "выходные": [0, 0, []]}
    for l in work.values():
        k = "выходные" if ts(l["created"]).weekday() >= 5 else "будни"
        wk[k][0] += 1; wk[k][1] += l["outcome"] == "won"
        if l["react"] is not None: wk[k][2].append(l["react"])
    R["weekend"] = [{"когда": k, "заявок": v[0], "медиана реакции, мин": med(v[2]), "конверсия, %": pct(v[1], v[0])} for k, v in wk.items()]
    # реакция по годам
    ry = collections.defaultdict(list)
    for l in work.values():
        if l["react"] is not None: ry[ts(l["created"]).year].append(l["react"])
    R["react_year"] = {y: {"медиана, мин": med(v), "до 30 мин, %": pct(sum(x <= 30 for x in v), len(v)), "больше суток, %": pct(sum(x > 1440 for x in v), len(v))} for y, v in sorted(ry.items())}
    # Telegram: первый ответ по часу первого сообщения клиента
    tgd = {c: (b, fr) for c, b, fr in q("SELECT chat,bought,first_resp FROM tg_dialogs")}
    tgh = collections.defaultdict(lambda: [0, 0, []])
    for c, (b, fr) in tgd.items():
        if c not in tg_first: continue
        d = ts(tg_first[c]); k = "выходные" if d.weekday() >= 5 else ("рабочее время" if 9 <= d.hour < 19 else "вечер и ночь")
        tgh[k][0] += 1; tgh[k][1] += b
        if fr is not None: tgh[k][2].append(fr / 60)
    R["tg_hour"] = [{"когда написал клиент": k, "диалогов": v[0], "медиана первого ответа, мин": med(v[2]), "дошли до оплаты, %": pct(v[1], v[0])} for k, v in tgh.items()]

    # ---------- 2. Скорость сделки ----------
    first = collections.defaultdict(dict)
    for lid, t, to in q("SELECT lead_id,created_at,to_status FROM status_events WHERE to_status IS NOT NULL ORDER BY created_at"):
        first[lid].setdefault(to, t)
    order = [s for s, _ in STAGES]
    seg = collections.defaultdict(list); total = []
    won_china = [i for i, l in work.items() if l["outcome"] == "won" and i in real]
    for lid in won_china:
        st_ = first.get(lid, {}); prev_t, prev_n = leads[lid]["created"], "Заявка"
        for s, n in STAGES:
            if s in st_ and st_[s] >= prev_t:
                seg[f"{prev_n} → {n}"].append((st_[s] - prev_t) / 86400); prev_t, prev_n = st_[s], n
        if 142 in st_: total.append((st_[142] - leads[lid]["created"]) / 86400)
    R["deal_speed_pairs"] = [{"этап": k, "сделок": len(v), "медиана, дней": med(v), "75% сделок быстрее, дней": round(sorted(v)[int(len(v) * .75)], 1)}
                       for k, v in seg.items() if len(v) >= 10]
    R["deal_total"] = {"выигранных с выдачей": len(total), "медиана от заявки до выдачи, дней": med(total),
                       "от заявки до договора, медиана": med([(first[i][66041750] - leads[i]["created"]) / 86400 for i in won_china if 66041750 in first.get(i, {})]),
                       "от договора до выдачи, медиана": med([(first[i][142] - first[i][66041750]) / 86400 for i in won_china if 66041750 in first.get(i, {}) and 142 in first[i] and first[i][142] > first[i][66041750]])}
    R["milestones"] = []
    for s_id, n in STAGES[2:]:
        v = [(first[i][s_id] - leads[i]["created"]) / 86400 for i in won_china if s_id in first.get(i, {}) and first[i][s_id] >= leads[i]["created"]]
        R["milestones"].append({"этап": n, "сделок дошло": len(v), "медиана дней от заявки": med(v)})
    # быстрые и долгие решения
    to_contract = [(first[i][66041750] - leads[i]["created"]) / 86400 for i in won_china if 66041750 in first.get(i, {})]
    R["decision_buckets"] = [{"от заявки до договора": n, "сделок": sum(lo <= x < hi for x in to_contract), "доля, %": pct(sum(lo <= x < hi for x in to_contract), len(to_contract))}
                             for n, lo, hi in [("до 3 дней", 0, 3), ("3–14 дней", 3, 14), ("2–8 недель", 14, 56), ("2–6 месяцев", 56, 180), ("больше полугода", 180, 9e9)]]
    # сколько живут проигранные на КП
    kp_lost = []
    for i, l in work.items():
        if l["outcome"] == "lost" and 65738818 in first.get(i, {}) and 143 in first[i] and first[i][143] > first[i][65738818]:
            kp_lost.append((first[i][143] - first[i][65738818]) / 86400)
    R["kp_lost"] = {"сделок": len(kp_lost), "медиана от КП до закрытия, дней": med(kp_lost),
                    "закрыто в течение суток после КП, %": pct(sum(x < 1 for x in kp_lost), len(kp_lost)),
                    "закрыто через 30+ дней, %": pct(sum(x >= 30 for x in kp_lost), len(kp_lost))}

    # ---------- 4. Менеджеры ----------
    users = dict(q("SELECT id,name FROM users"))
    touched = collections.defaultdict(set)
    for lid, by, nt in q("SELECT lead_id,created_by,note_type FROM lead_notes WHERE created_by>0"):
        touched[by].add(lid)
    for lid, by in q("SELECT lead_id,created_by FROM status_events WHERE created_by>0"):
        touched[by].add(lid)
    calls = collections.Counter(by for by, in q("SELECT created_by FROM lead_notes WHERE note_type='call_out' AND created_by>0"))
    R["managers_amo"] = []
    for uid, ls in touched.items():
        ls = {x for x in ls if x in work}
        won = sum(work[x]["outcome"] == "won" for x in ls)
        prices = [work[x]["price"] for x in ls if work[x]["outcome"] == "won" and (work[x]["price"] or 0) > 50000]
        yrs = sorted(ts(work[x]["created"]).year for x in ls)
        R["managers_amo"].append({"сотрудник": users.get(uid, uid), "работал со сделками": len(ls), "из них выиграно": won, "конверсия, %": pct(won, len(ls)),
                                  "исходящих звонков": calls[uid], "средний бюджет выигранной, тыс. ₽": round(st.mean(prices) / 1000) if prices else None,
                                  "период": f"{yrs[0]}–{yrs[-1]}" if yrs else ""})
    R["managers_amo"].sort(key=lambda x: -x["работал со сделками"])
    mh = collections.defaultdict(list)
    for h in hist: mh[((h["manager"] or "").split() or ["не указан"])[0].title()].append(h)
    R["managers_hist"] = []
    for m, hs in sorted(mh.items(), key=lambda x: -len(x[1])):
        tech = [h for h in hs if h["kind"] == "Техника"]
        amt = [h["amount"] for h in tech if h["amount"] and h["status"].startswith("Завершена")]
        att = [h for h in tech if any(re.search(rx, h["cargo"] or "", re.I) for n, rx in ATTACH if n not in ("кабина", "Kubota"))]
        R["managers_hist"].append({"менеджер": m, "сделок": len(hs), "завершено": sum(h["status"].startswith("Завершена") for h in hs), "техника": len(tech),
                                   "средний чек техники, тыс. ₽": round(st.mean(amt) / 1000) if amt else None,
                                   "техника с навесным, %": pct(len(att), len(tech)), "Kubota, %": pct(sum(bool(re.search("кубот|kubota", h["cargo"] or "", re.I)) for h in tech), len(tech))})

    # ---------- 5. Повторные клиенты ----------
    by_contact = collections.defaultdict(list)
    for lid, cids in q("SELECT id,contact_ids FROM leads"):
        if lid not in work: continue
        for c in json.loads(cids or "[]")[:1]: by_contact[c].append(lid)
    phone_of = {}
    for cid, raw in q("SELECT id,raw FROM contacts"):
        for f in (json.loads(raw).get("custom_fields_values") or []):
            if f.get("field_code") == "PHONE":
                for v in f["values"]:
                    p = re.sub(r"\D", "", v["value"])[-10:]
                    if len(p) == 10: phone_of[cid] = p; break
    by_person = collections.defaultdict(list)
    for c, ls in by_contact.items(): by_person[phone_of.get(c, f"c{c}")].extend(ls)
    multi = {p: sorted(ls, key=lambda x: work[x]["created"]) for p, ls in by_person.items() if len(ls) > 1}
    rep_won = [p for p, ls in by_person.items() if sum(work[x]["outcome"] == "won" for x in ls) >= 2]
    # конверсия: первая заявка человека vs повторное обращение
    first_l, later_l = [], []
    for p, ls in by_person.items():
        ls = sorted(ls, key=lambda x: work[x]["created"]); first_l.append(ls[0]); later_l += ls[1:]
    # покупатели, вернувшиеся после покупки
    back = 0; won_people = 0
    for p, ls in by_person.items():
        ls = sorted(ls, key=lambda x: work[x]["created"])
        w = [i for i, x in enumerate(ls) if work[x]["outcome"] == "won"]
        if w: won_people += 1; back += any(i > w[0] for i in range(len(ls)))
    tg_ref = collections.Counter(); tg_ref_b = 0
    clientmsgs = collections.defaultdict(list)
    for chat, name, sender, text in q("SELECT chat,chat_name,sender,text FROM tg_messages WHERE text<>''"):
        if name in SKIP_TG or sender in OWN_TG: continue
        clientmsgs[chat].append(text)
    ref_chats = [c for c, ms in clientmsgs.items() if any(re.search(REFERRAL, m, re.I) for m in ms)]
    R["repeat"] = {"людей (по телефону) в amoCRM": len(by_person), "обращались больше одного раза": len(multi), "доля, %": pct(len(multi), len(by_person)),
                   "купили 2+ раза (amoCRM)": len(rep_won), "покупателей": won_people, "покупатели, которые обращались снова после покупки": back,
                   "конверсия первой заявки, %": pct(sum(work[x]["outcome"] == "won" for x in first_l), len(first_l)),
                   "конверсия повторного обращения, %": pct(sum(work[x]["outcome"] == "won" for x in later_l), len(later_l)),
                   "повторных обращений": len(later_l),
                   "отмечено «+1 сделка» в таблице": sum("+1" in (h["client"] or "") or "+1" in (h["cargo"] or "") for h in hist),
                   "Telegram: диалогов с упоминанием рекомендации или повторной покупки": len(ref_chats),
                   "из них дошли до оплаты, %": pct(sum(tgd.get(c, (0, 0))[0] for c in ref_chats), len(ref_chats))}
    gaps = [(work[ls[1]]["created"] - work[ls[0]]["created"]) / 86400 for ls in multi.values()]
    R["repeat"]["медиана между первым и вторым обращением, дней"] = med(gaps)

    # ---------- 6. Источники ----------
    src = collections.defaultdict(lambda: [0, 0, [], []])
    for l in work.values():
        s = l["source"] or "Не определён"
        if s.startswith("Входящий чат") and l["channel"]: s = "Входящий чат: " + l["channel"]
        src[s][0] += 1
        if l["outcome"] == "won":
            src[s][1] += 1
            if (l["price"] or 0) > 50000: src[s][2].append(l["price"])
            if l["days_to_win"]: src[s][3].append(l["days_to_win"])
    R["sources"] = [{"источник": k, "заявок": v[0], "выиграно": v[1], "конверсия, %": pct(v[1], v[0]), "выручка (бюджет), млн ₽": round(sum(v[2]) / 1e6, 2),
                     "средний чек, тыс. ₽": round(st.mean(v[2]) / 1000) if v[2] else None, "доля всех продаж, %": pct(v[1], sum(x[1] for x in src.values())),
                     "медиана до выдачи, дней": med(v[3])} for k, v in sorted(src.items(), key=lambda x: -x[1][0]) if v[0] >= 20]
    sy = collections.defaultdict(lambda: collections.Counter())
    for l in work.values():
        s = l["source"] or "Не определён"
        sy[ts(l["created"]).year][s if not s.startswith("Входящий чат") else "Входящий чат"] += 1
    R["sources_year"] = {y: dict(c.most_common(6)) for y, c in sorted(sy.items())}
    tgsrc = collections.Counter(); tgsrc_b = collections.Counter()
    for c, ms in clientmsgs.items():
        for n, rx in SOURCE_WORDS:
            if any(re.search(rx, m, re.I) for m in ms[:15]):
                tgsrc[n] += 1; tgsrc_b[n] += tgd.get(c, (0, 0))[0]
    R["tg_sources"] = [{"упоминание в первых 15 сообщениях клиента": n, "диалогов": tgsrc[n], "дошли до оплаты": tgsrc_b[n], "доля оплат, %": pct(tgsrc_b[n], tgsrc[n])} for n, _ in SOURCE_WORDS]

    # ---------- 7. География ----------
    geo = collections.defaultdict(lambda: [0, 0, 0])
    for l in work.values():
        c = norm_city(l["city"])
        if c: geo[c][0] += 1; geo[c][1] += l["outcome"] == "won"
    for h in hist:
        c = norm_city(h["city"])
        if c and h["status"].startswith("Завершена"): geo[c][2] += 1
    with_city = sum(v[0] for v in geo.values())
    R["geo"] = [{"город": k, "заявок amoCRM": v[0], "выиграно amoCRM": v[1], "конверсия, %": pct(v[1], v[0]), "завершено по таблице": v[2]}
                for k, v in sorted(geo.items(), key=lambda x: -(x[1][0] + 10 * x[1][2]))[:25]]
    msk = geo["Москва и МО"]; spb = geo["Санкт-Петербург и ЛО"]
    other = [sum(v[i] for k, v in geo.items() if k not in ("Москва и МО", "Санкт-Петербург и ЛО")) for i in range(3)]
    R["geo_groups"] = [{"регион": n, "заявок": v[0], "доля заявок, %": pct(v[0], with_city), "выиграно": v[1], "конверсия, %": pct(v[1], v[0]), "завершено по таблице": v[2],
                        "доля продаж по таблице, %": pct(v[2], sum(x[2] for x in geo.values()))}
                       for n, v in [("Москва и МО", msk), ("Санкт-Петербург и ЛО", spb), ("Остальные регионы", other)]]
    R["geo_city_filled"] = {"заявок с городом": with_city, "всего заявок": len(work)}

    # ---------- 8. Модели и комплектации ----------
    mm = collections.defaultdict(lambda: [0, 0])
    for l in work.values():
        m = l["model"]
        if not m or m.startswith("Нужна"): continue
        m = re.sub(r"&amp;nbsp;|&nbsp;", " ", m); m = re.sub(r"\s+", " ", m).strip()
        mm[m][0] += 1; mm[m][1] += l["outcome"] == "won"
    R["models_amo"] = [{"модель в заявке": k, "заявок": v[0], "выиграно": v[1], "конверсия, %": pct(v[1], v[0])} for k, v in sorted(mm.items(), key=lambda x: -x[1][0])[:15]]
    cat = collections.defaultdict(lambda: [0, 0])
    for l in work.values():
        c = l["category"] or "не указана"; cat[c][0] += 1; cat[c][1] += l["outcome"] == "won"
    R["category_amo"] = [{"категория": k, "заявок": v[0], "выиграно": v[1], "конверсия, %": pct(v[1], v[0])} for k, v in sorted(cat.items(), key=lambda x: -x[1][0])]
    tech = [h for h in hist if h["kind"] == "Техника"]
    hm = collections.Counter(m for h in tech for m in json.loads(h["models"] or "[]"))
    R["models_hist"] = dict(hm.most_common(15))
    ac = collections.Counter(); pairs = collections.Counter(); sizes = []
    for h in tech:
        items = sorted({n for n, rx in ATTACH if re.search(rx, h["cargo"] or "", re.I)})
        ac.update(items); sizes.append(len([i for i in items if i not in ("кабина", "Kubota")]))
        it2 = [i for i in items if i not in ("кабина", "Kubota")]
        pairs.update(f"{a} + {b}" for i, a in enumerate(it2) for b in it2[i + 1:])
    R["bundle"] = {"сделок с техникой": len(tech), "опции": {k: f"{v} ({pct(v, len(tech))}%)" for k, v in ac.most_common()},
                   "без навесного, %": pct(sum(s == 0 for s in sizes), len(tech)), "среднее число видов навесного": round(st.mean(sizes), 1),
                   "3+ вида навесного, %": pct(sum(s >= 3 for s in sizes), len(tech)), "частые пары": dict(pairs.most_common(8))}
    # Kubota и кабина: влияние на чек
    def avg(f):
        v = [h["amount"] for h in tech if h["amount"] and h["status"].startswith("Завершена") and f(h)]
        return (len(v), round(st.median(v) / 1000) if v else None)
    R["check_by_option"] = {"с Kubota (сделок, медиана тыс. ₽)": avg(lambda h: re.search("кубот|kubota", h["cargo"], re.I)),
                            "без Kubota": avg(lambda h: not re.search("кубот|kubota", h["cargo"], re.I)),
                            "с 3+ видами навесного": avg(lambda h: len([n for n, rx in ATTACH if n not in ("кабина", "Kubota") and re.search(rx, h["cargo"], re.I)]) >= 3),
                            "с 0–2 видами навесного": avg(lambda h: len([n for n, rx in ATTACH if n not in ("кабина", "Kubota") and re.search(rx, h["cargo"], re.I)]) < 3)}

    # ---------- 9. Продажи вне amoCRM ----------
    amo_names = collections.defaultdict(list)
    for lid, name, cids in q("SELECT id,name,contact_ids FROM leads"):
        for w in re.findall(r"[а-яё]{4,}", (name or "").lower()): amo_names[w].append(lid)
    cname = dict(q("SELECT id,name FROM contacts"))
    for lid, cids in q("SELECT id,contact_ids FROM leads"):
        for c in json.loads(cids or "[]"):
            for w in re.findall(r"[а-яё]{4,}", (cname.get(c) or "").lower()): amo_names[w].append(lid)
    tg_names = collections.Counter()
    for (n,) in q("SELECT DISTINCT chat_name FROM tg_messages"):
        for w in re.findall(r"[а-яё]{4,}", (n or "").lower()): tg_names[w] += 1
    groups = collections.defaultdict(list)
    for h in hist:
        if not h["status"].startswith("Завершена"): continue
        k = (h["key"] or "").lower(); ls = set(amo_names.get(k, [])) if re.fullmatch(r"[а-яё]{4,}", k) else set()
        outs = {leads[x]["outcome"] for x in ls if x in leads}
        g = "выиграна в amoCRM" if "won" in outs else "открыта в amoCRM" if "open" in outs else "закрыта в amoCRM как проигранная" if "lost" in outs else "нет в amoCRM"
        groups[g].append((h, ls))
    R["outside"] = {}
    for g, items in groups.items():
        yrs = collections.Counter((h["date"] or "без даты")[:4] for h, _ in items)
        mg = collections.Counter(((h["manager"] or "").split() or ["не указан"])[0].title() for h, _ in items)
        kinds = collections.Counter(h["kind"] for h, _ in items)
        amt = [h["amount"] for h, _ in items if h["amount"]]
        sheets = collections.Counter(s for h, _ in items for s in json.loads(h["sheets"]))
        R["outside"][g] = {"сделок": len(items), "по годам": dict(sorted(yrs.items())), "менеджер": dict(mg), "состав": dict(kinds),
                           "сумма, млн ₽": round(sum(amt) / 1e6, 2), "листы таблицы": dict(sheets),
                           "фамилия есть в чатах Telegram": sum(1 for h, _ in items if tg_names[(h["key"] or "").lower()])}
    lost_info = collections.Counter(); lost_cf = collections.Counter(); lost_gap = []
    for h, ls in groups.get("закрыта в amoCRM как проигранная", []):
        for x in ls:
            if x in leads:
                lost_info[leads[x]["reason"] or "не указана"] += 1; lost_cf[leads[x]["closed_from"] or "—"] += 1
                if h["date"]: lost_gap.append((dt.date.fromisoformat(h["date"]) - ts(leads[x]["created"]).date()).days)
    R["outside_lost"] = {"причины в amoCRM": dict(lost_info.most_common()), "закрыта с этапа": dict(lost_cf.most_common()),
                         "медиана дней от заявки в amoCRM до сделки в таблице": med(lost_gap)}

    # ---------- 10. Портрет клиента ----------
    lead_text = collections.defaultdict(list)
    for lid, t in q("SELECT lead_id,text FROM lead_notes WHERE text<>'' AND created_by>0 AND note_type='common'"): lead_text[lid].append(t)
    for lid, t in q("SELECT lead_id,text FROM transcripts"): lead_text[lid].append(t)
    for lid, t, r in q("SELECT entity_id,text,result FROM tasks WHERE entity_type='leads'"): lead_text[lid].append(f"{t or ''} {r or ''}")
    def portrait(texts_by_id, outcome):
        c, cb = collections.Counter(), collections.Counter(); n = 0
        for i, ts_ in texts_by_id.items():
            blob = " ".join(t for t in ts_ if t).lower()
            if len(blob) < 30: continue
            n += 1
            for name, rx in PURPOSE + BUYER:
                if re.search(rx, blob): c[name] += 1; cb[name] += outcome(i)
        return n, c, cb
    n_tg, c_tg, b_tg = portrait(clientmsgs, lambda c: tgd.get(c, (0, 0))[0])
    n_amo, c_amo, b_amo = portrait({k: v for k, v in lead_text.items() if k in work}, lambda i: work[i]["outcome"] == "won")
    R["portrait"] = [{"признак": name, "Telegram: диалогов": c_tg[name], "Telegram: доля, %": pct(c_tg[name], n_tg), "Telegram: дошли до оплаты, %": pct(b_tg[name], c_tg[name]),
                      "amoCRM: сделок": c_amo[name], "amoCRM: доля, %": pct(c_amo[name], n_amo), "amoCRM: конверсия, %": pct(b_amo[name], c_amo[name])}
                     for name, _ in PURPOSE + BUYER]
    R["portrait_base"] = {"диалогов Telegram с текстом": n_tg, "сделок amoCRM с текстом": n_amo,
                          "Telegram: средняя доля оплат, %": pct(sum(tgd.get(c, (0, 0))[0] for c in clientmsgs), len(clientmsgs)),
                          "amoCRM: средняя конверсия сделок с текстом, %": pct(sum(work[i]["outcome"] == "won" for i in lead_text if i in work), sum(1 for i in lead_text if i in work))}
    R["category_hist"] = dict(collections.Counter(h["kind"] for h in hist))

    json.dump(R, open(os.path.join(ROOT, "data", "deep.json"), "w"), ensure_ascii=False, indent=1, default=str)
    for k, v in R.items():
        print("=====", k); print(json.dumps(v, ensure_ascii=False, default=str)[:2500])


if __name__ == "__main__":
    main()
