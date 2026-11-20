"""Анализ переписки ChatApp: темы вопросов клиентов, скорость ответа, вопросы без ответа.
Результат: data/report/chat_*.json и data/chat_metrics.json."""
import collections, datetime as dt, json, os, re, sqlite3, statistics as st

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "data", "amo.sqlite")
MSK = dt.timezone(dt.timedelta(hours=3))
# сообщения, которые не являются вопросами клиентов: посты канала, шаблоны менеджеров, внутренние, спам
NOISE = re.compile(r"^\s*[*🛠🔵🚜📄]|Меня зовут Вячеслав|Отправлял вам|Отправил вам расчет|РАСЧЕТ|Прайс-лист|Чтобы я подобрал|"
                   r"Все интересующие вопросы|#отгрузки|docs\.google|Hello|my friend|Наша компания занимается|Занимаемся ж/д|"
                   r"Клиент где|Ты на связи|Ты сам|Фермеру|подготовь|Что за Юрий|R15 Вячеслав|Вот перевод", re.I)
TOPICS = [
    ("Цена и итог «под ключ»", r"цен|стоим|сколько (будет )?стоит|прайс|почем|бюджет|подешевле|скидк"),
    ("Наличие", r"налич|в питере есть|есть ли .* сейчас|посмотреть, пощупать"),
    ("Доставка до города", r"доставк|до (москв|питер|спб|казан|ростов|воронеж|улан|киров|ижевск)|транспортн|сдэк|пэк|фуру|самовывоз|где (вы )?находитесь|в каком городе"),
    ("Сроки поставки", r"срок|когда (будет|приедет|придет|прид[её]т)|сколько ждать|как по времени|к (маю|октябрю|сезону)"),
    ("Оплата и договор", r"оплат|предоплат|счет|счёт|договор|реквизит|рассрочк|кредит|лизинг|поручител|частями"),
    ("Документы, ЭПСМ, утильсбор", r"эпсм|псм|документ|утиль|растамож|таможн|гтд|гаи|учет|учёт|запчаст[ьи] как|без растаможки|vin|вин"),
    ("Комплектация и опции", r"комплект|кабин|печк|кондиц|отопит|ковш в комплекте|в базе|цвет|гусениц|поворот|гидролини"),
    ("Подбор и сравнение моделей", r"отлич|что лучше|какую|посовет|варианты|модел|характеристик|глубин|мощн|насос|двигател|кубот"),
    ("Навесное оборудование", r"навесн|ковш|гидробур|бур|ямобур|быстросъ|клык|гидромолот|удлинит|захват|шнек|грабл"),
    ("Запчасти и расходники", r"фильтр|запчаст|гусениц[аы] 1|масл|чехл|стартер|деталь"),
    ("Статус заказа после оплаты", r"новост|на какой стадии|как движется|отправили|доехал|когда приедет|где сейчас|фото и видео|что с фото"),
    ("Гарантия и надёжность", r"гаранти|мошенн|надежн|надёжн|риск|сервис"),
]


def main():
    db = sqlite3.connect(DB, timeout=120)
    msgs = collections.defaultdict(list)
    for m, c, t, side, api, typ, txt in db.execute("SELECT messenger,chat_id,time,side,from_api,type,text FROM ca_messages ORDER BY time"):
        msgs[(m, c)].append((t, side, api, typ, (txt or "").replace("\n", " ").strip()))
    names = {(m, c): n for m, c, n in db.execute("SELECT messenger,chat_id,name FROM ca_chats")}

    topic_chats = collections.defaultdict(set); topic_unans = collections.Counter(); topic_q = collections.Counter()
    resp, wk, off = [], [], []; unanswered = 0; client_chats = set(); qcount = 0
    for k, ms in msgs.items():
        for i, (t, side, api, typ, txt) in enumerate(ms):
            if side != "in" or not txt or NOISE.search(txt):
                continue
            client_chats.add(k)
            nxt = next((x for x in ms[i + 1:] if x[1] == "out" and x[2] == 0), None)
            # время ответа: только на первое сообщение клиента после ответа менеджера
            if i == 0 or ms[i - 1][1] == "out":
                if nxt:
                    d = (nxt[0] - t) / 60; resp.append(d)
                    h = dt.datetime.fromtimestamp(t, MSK)
                    (wk if h.weekday() < 5 and 9 <= h.hour < 19 else off).append(d)
                else:
                    unanswered += 1
            hits = [name for name, rx in TOPICS if re.search(rx, txt, re.I)]
            if hits and ("?" in txt or re.search(r"подскаж|интерес|можно|сколько|какая|какой|когда|где|есть ли|нужн", txt, re.I)):
                qcount += 1
                for h in hits:
                    topic_chats[h].add(k); topic_q[h] += 1
                    if not nxt: topic_unans[h] += 1

    bucket = collections.Counter("до 5 мин" if d <= 5 else "5–30 мин" if d <= 30 else "30 мин–2 ч" if d <= 120 else "2–24 ч" if d <= 1440 else "больше суток" for d in resp)
    order = ["до 5 мин", "5–30 мин", "30 мин–2 ч", "2–24 ч", "больше суток"]
    ch = collections.Counter(k[0] for k in client_chats)
    first = min(t for ms in msgs.values() for t, *_ in ms); last = max(t for ms in msgs.values() for t, *_ in ms)
    metrics = dict(
        chats_total=len(names), chats_with_history=len(msgs), client_chats=len(client_chats),
        messages=sum(len(v) for v in msgs.values()), client_questions=qcount,
        period=[dt.datetime.fromtimestamp(first, MSK).strftime("%d.%m.%Y"), dt.datetime.fromtimestamp(last, MSK).strftime("%d.%m.%Y")],
        resp_median_min=round(st.median(resp), 1), resp_work_median_min=round(st.median(wk), 1), resp_off_median_h=round(st.median(off) / 60, 1),
        unanswered_threads=unanswered,
        by_messenger={"WhatsApp": ch["grWhatsApp"], "Telegram": ch["telegram"], "MAX": ch["max"]})
    json.dump(metrics, open(os.path.join(ROOT, "data", "chat_metrics.json"), "w"), ensure_ascii=False, indent=1)

    import report_data
    rows = sorted(({"тема": n, "чатов": len(topic_chats[n]), "вопросов": topic_q[n], "без ответа": topic_unans[n],
                    "без ответа, %": round(100 * topic_unans[n] / topic_q[n], 1) if topic_q[n] else 0} for n, _ in TOPICS),
                  key=lambda r: -r["чатов"])
    report_data.save("chat_topics", rows, f"Вопросы клиентов в переписке ChatApp (WhatsApp, Telegram, MAX) за {metrics['period'][0]}–{metrics['period'][1]}: тема по ключевым словам, у вопроса может быть несколько тем. «Без ответа» — после вопроса не было сообщения менеджера.")
    report_data.save("chat_resp", [{"время ответа": b, "обращений": bucket[b]} for b in order],
                     "Время от первого сообщения клиента до ответа менеджера в чате (без ботов и автоответов).")
    k = metrics
    report_data.save("chat_kpi", [{"чатов с историей": k["client_chats"], "сообщений": k["messages"], "вопросов клиентов": k["client_questions"],
                                   "медиана ответа, мин": k["resp_median_min"], "медиана ответа в рабочее время, мин": k["resp_work_median_min"],
                                   "медиана ответа ночью и в выходные, ч": k["resp_off_median_h"], "обращений без ответа": k["unanswered_threads"],
                                   "период с": k["period"][0], "период по": k["period"][1]}],
                     "ChatApp хранит историю только за последние месяцы: WhatsApp с июня 2026, Telegram с марта, MAX с октября; основная часть сообщений за октябрь–ноябрь 2026.")
    print(json.dumps(metrics, ensure_ascii=False)); [print(r) for r in rows]


if __name__ == "__main__":
    import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
