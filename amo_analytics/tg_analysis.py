"""Анализ переписки с клиентами из экспорта Telegram (рабочий аккаунт K-truck).
Классы чатов: client (диалоги с клиентами), channel_chat (комментарии канала), skip (публичные и внутренние группы).
Результат: таблицы tg_dialogs, tg_client_msgs; data/tg_metrics.json; data/report/tg_*.json."""
import collections, datetime as dt, json, os, re, sqlite3, statistics as st

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "data", "amo.sqlite")
OWN = {"K-truck", "K-TRUCK - доставка из Китая 🇨🇳"}
SKIP = {"Куплю Запчасти", "Запчасти на спецтехнику из Европы и США Chat", "K-TRUCK Задачи", "Сергей Шульга"}
CHANNEL_CHAT = "Техника и запчасти из Китая - k-truck Chat"

TOPICS = [
    ("Цена и стоимость", r"цен|стоим|сколько (будет )?стоит|почем|прайс|дорог|дешев|скидк"),
    ("Доставка и логистика", r"доставк|довез|привез|транспортн|контейнер|сдэк|пэк|деловые|фур|забрать|самовывоз|уссурийск|владивосток"),
    ("Сроки", r"срок|когда (будет|приед|прид|отправ)|сколько ждать|долго|задерж"),
    ("Оплата и договор", r"оплат|предоплат|аванс|счет|счёт|договор|реквизит|рассрочк|кредит|лизинг|ндс|нал"),
    ("Документы и таможня", r"эпсм|псм|документ|утиль|таможн|растамож|гтд|деклараци|учет|учёт|vin|вин"),
    ("Подбор модели и характеристики", r"какую|что лучше|посовет|отлич|характеристик|глубин|мощн|вес|тонн|двигател|кубот|kubota|насос|гидравлик"),
    ("Комплектация и опции", r"кабин|печк|отопит|кондиц|комплект|поворот|раздвижн|гусениц|джойстик|гидролини|цвет"),
    ("Навесное", r"навесн|ковш|бур|быстросъ|клык|гидромолот|удлинит|грабл|щипц|захват"),
    ("Запчасти и расходники", r"запчаст|фильтр|масл|ремкомплект|сальник|гидромотор|цилиндр|насос|стартер|ремень"),
    ("Сервис, поломки, гарантия", r"слома|не работа|не заводит|теч[её]т|течь|подтек|брак|гаранти|ремонт|неисправ|поломк|треск|стук|перегрев|заклин"),
    ("Наличие", r"налич|в наличии|есть ли .*сейчас|на складе"),
    ("Статус заказа", r"новост|где (сейчас|груз)|на каком этап|отгрузили|отправили|доехал|трек|накладн"),
]
COMPETITORS = [
    ("Авито", r"авито|avito"), ("Alibaba / 1688 / прямо из Китая", r"alibaba|алибаба|1688|али ?экспресс|aliexpress|напрямую с китай"),
    ("Другие дилеры и поставщики", r"у других|другие компании|конкурент|дилер|предлагают дешевле|нашел дешевле|нашёл дешевле|в другой компании"),
    ("Б/у техника", r"\bб/у\b|\bбу\b|подержан"),
    ("Японская и европейская техника", r"yanmar|янмар|takeuchi|такеучи|kobelco|кобелко|bobcat|бобкэт|jcb|komatsu|комацу|hitachi|хитачи|volvo|caterpillar|кат\b"),
    ("Другие китайские бренды", r"zoomlion|xcmg|sany|сани|liugong|лиугонг|shandong|lonking|hengwang|хенгван|nuoman|науман|zhongmei|kaifeng|ковер|kovea|everun|эверан|cnfoot"),
]
REPUTATION_POS = r"спасибо|благодар|доволен|довольн|рекоменд|всё отлично|все отлично|молодцы|отлично работает|хорошая техника"
REPUTATION_NEG = r"мошенн|обман|кинул|развод|не верю|недовол|претензи|верните деньги|возврат денег|суд\b|жалоб|ужас|безобраз"
SOURCES = [("Telegram-канал", r"канал|телеграм|telegram|тг\b"), ("Авито", r"авито|avito"), ("Сайт", r"сайт|k-truck\.ru"),
           ("YouTube / видео", r"ютуб|youtube|видео на"), ("Рекомендация знакомых", r"посоветовал|знакомый|друг купил|по рекомендации|сосед")]
MODELS = [("Rippa R10/R319 (до 1 т)", r"r ?10\b|r-?10|319|р ?10\b|р-?319|ndi ?315"), ("Rippa R13/R15", r"r ?1[35]\b|р ?1[35]\b|r327|327"),
          ("Rippa R18/R22", r"r ?18\b|r ?22|р ?18\b|р ?22|322|r330|330"), ("Rippa R32 и больше", r"r ?32\b|р ?32|r ?35|r ?50"),
          ("HighTop HT08/HT10", r"ht ?0?8|ht ?10|хт ?10|hightop 10|rumm ?10"), ("HighTop/RUMM 12–18", r"rumm ?1[2-8]|рам ?1[2-8]|ht ?1[2-8]|ht12"),
          ("HighTop/RUMM 20–30", r"rumm ?(2\d|30)|рам ?(2\d|30)|ht ?(2\d|30)"), ("Мини-погрузчики", r"погрузчик|rs0\d|906|r906|ht ?380|382|wz"),
          ("Мини-думперы", r"думпер|dumper|ht-?500"), ("Мини-тракторы", r"трактор")]
REQS = [("Двигатель Kubota / японский", r"кубот|kubota|япон"), ("Кабина / обогрев", r"кабин|печк|отопит|обогрев"), ("Кондиционер", r"кондиц"),
        ("Глубина копания 2 м+", r"глубин\w* (копани\w* )?(2|два|2[,.]5|3)"), ("Поворот стрелы", r"поворот\w* стрел"), ("Раздвижные гусеницы", r"раздвижн|выдвижн"),
        ("Гидролиния под навесное", r"гидролини|доп\.? ?лини"), ("Дизель", r"дизел"), ("Бензин", r"бензин"), ("Электро", r"электр\w* (думпер|экскаватор|привод)|электродвиг|аккумулятор"),
        ("Перевозка на прицепе / вес до 1 т", r"прицеп|газел"), ("Документы / ЭПСМ", r"эпсм|псм|на учет|на учёт")]


def classify(rows, rules):
    c = collections.Counter()
    for name, rx in rules:
        c[name] = sum(1 for t in rows if re.search(rx, t, re.I))
    return c


def main():
    db = sqlite3.connect(DB, timeout=120)
    q = lambda s, *a: db.execute(s, a).fetchall()
    msgs = collections.defaultdict(list)
    names = {}
    for chat, name, mid, t, s, text, media in q("SELECT chat,chat_name,msg_id,time,sender,text,media FROM tg_messages ORDER BY chat,time,msg_id"):
        msgs[chat].append((t, s, text or "", media or "")); names[chat] = name
    dialogs = {}
    for chat, ms in msgs.items():
        senders = {s for _, s, _, _ in ms if s}
        own = sum(1 for _, s, _, _ in ms if s in OWN); other = len(ms) - own
        if names[chat] in SKIP or names[chat] == CHANNEL_CHAT:
            continue
        if own and other and len(senders) <= 6:
            dialogs[chat] = ms
    # метрики диалогов
    resp, unanswered, years, firsts = [], 0, collections.Counter(), []
    buy = re.compile(r"оплатил|оплачено|перевел|перевёл|чек|реквизит|договор подпис|подписал|получил техник|забрал", re.I)
    feat = []
    for chat, ms in dialogs.items():
        start = next((t for t, *_ in ms if t), None)
        if start: years[dt.datetime.fromtimestamp(start).year] += 1
        r_chat = []
        for i, (t, s, txt, media) in enumerate(ms):
            if s not in OWN and (i == 0 or ms[i - 1][1] in OWN):
                nxt = next((x for x in ms[i + 1:] if x[1] in OWN), None)
                if nxt and t and nxt[0]: r_chat.append((nxt[0] - t) / 60)
                elif not nxt: unanswered += 1
        resp += r_chat
        client_txt = "\n".join(x[2] for x in ms if x[1] not in OWN)
        bought = bool(buy.search(client_txt)) or bool(re.search(r"оплату получили|оплата поступила|спасибо за оплату", "\n".join(x[2] for x in ms if x[1] in OWN), re.I))
        feat.append(dict(chat=chat, msgs=len(ms), client=sum(1 for x in ms if x[1] not in OWN), bought=bought,
                         first_resp=r_chat[0] if r_chat else None, days=((ms[-1][0] or 0) - (start or 0)) / 86400 if start else 0))
    client_msgs = [x[2] for ms in dialogs.values() for x in ms if x[1] not in OWN and x[2]]
    client_by_chat = {c: "\n".join(x[2] for x in ms if x[1] not in OWN).lower() for c, ms in dialogs.items()}
    per_chat = lambda rules: sorted(((n, sum(1 for t in client_by_chat.values() if re.search(rx, t, re.I))) for n, rx in rules), key=lambda x: -x[1])
    topics = per_chat(TOPICS); comps = per_chat(COMPETITORS); reqs = per_chat(REQS); models = per_chat(MODELS); srcs = per_chat(SOURCES)
    pos = sum(1 for t in client_by_chat.values() if re.search(REPUTATION_POS, t)); neg = sum(1 for t in client_by_chat.values() if re.search(REPUTATION_NEG, t))
    # спрос по годам
    model_year = collections.defaultdict(collections.Counter)
    for c, ms in dialogs.items():
        y = next((dt.datetime.fromtimestamp(t).year for t, *_ in ms if t), None)
        txt = client_by_chat[c]
        for n, rx in MODELS:
            if re.search(rx, txt, re.I): model_year[n][y] += 1
    b = [f for f in feat if f["bought"]]; nb = [f for f in feat if not f["bought"]]
    med = lambda xs: round(st.median(xs), 1) if xs else None
    bucket = lambda m: "до 15 мин" if m <= 15 else "15–60 мин" if m <= 60 else "1–24 ч" if m <= 1440 else "больше суток"
    fr = collections.defaultdict(lambda: [0, 0])
    for f in feat:
        if f["first_resp"] is not None:
            k = bucket(f["first_resp"]); fr[k][0] += 1; fr[k][1] += f["bought"]
    m = dict(dialogs=len(dialogs), messages=sum(len(v) for v in dialogs.values()), client_messages=len(client_msgs),
             years=dict(sorted(years.items())), resp_median_min=med(resp), unanswered=unanswered,
             bought=len(b), bought_pct=round(100 * len(b) / len(feat), 1),
             msgs_bought=med([f["msgs"] for f in b]), msgs_not=med([f["msgs"] for f in nb]),
             first_resp_bought=med([f["first_resp"] for f in b if f["first_resp"] is not None]),
             first_resp_not=med([f["first_resp"] for f in nb if f["first_resp"] is not None]),
             first_resp_conv={k: dict(n=v[0], bought=v[1], pct=round(100 * v[1] / v[0], 1)) for k, v in fr.items()},
             topics=topics, competitors=comps, requirements=reqs, models=models, sources=srcs, rep_pos=pos, rep_neg=neg,
             model_year={k: dict(sorted(v.items())) for k, v in model_year.items()})
    json.dump(m, open(os.path.join(ROOT, "data", "tg_metrics.json"), "w"), ensure_ascii=False, indent=1, default=str)
    db.execute("DROP TABLE IF EXISTS tg_dialogs")
    db.execute("CREATE TABLE tg_dialogs(chat TEXT PRIMARY KEY, msgs INT, client INT, bought INT, first_resp REAL, days REAL)")
    db.executemany("INSERT INTO tg_dialogs VALUES(?,?,?,?,?,?)", [(f["chat"], f["msgs"], f["client"], int(f["bought"]), f["first_resp"], f["days"]) for f in feat])
    db.commit()
    print(json.dumps(m, ensure_ascii=False, default=str)[:4000])


if __name__ == "__main__":
    main()
