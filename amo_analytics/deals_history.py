"""Разбор ручной таблицы истории сделок (Google Таблица, несколько форматов учёта).
Одна фамилия = одна сделка. Строки-платежи и дубли между листами склеиваются по фамилии и номеру договора.
Результат: таблицы hist_rows, hist_deals в data/amo.sqlite и data/hist_metrics.json."""
import collections, datetime as dt, json, os, re, sqlite3, warnings
import openpyxl

warnings.filterwarnings("ignore")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
XLSX = os.path.join(ROOT, "data", "deals_history", "history.xlsx")

NAMES = set("""александр алексей анатолий андрей антон аркадий арсений артем артём артур богдан борис вадим валентин валерий василий виктор виталий владимир владислав вячеслав геннадий георгий герман глеб григорий давид даниил данил денис дмитрий евгений егор иван игорь илья кирилл константин лев леонид максим марат марк матвей михаил никита николай олег павел паша петр пётр роман руслан сергей семен семён станислав степан тимур федор фёдор филипп эдуард юрий яков ярослав рустам ринат ильдар азат альберт сурен филюс януш захар
анна елена ирина мария наталья ольга светлана татьяна екатерина юлия марина виктория дарья ксения людмила галина надежда вера инна""".split())
STOP = set("ооо ип ао зао пао тоо компания клиент авито счет счёт договор без от на для по и с телега".split())
PATR = re.compile(r"(ович|евич|овна|евна|ична|инична)$")
MODELS = [("Rippa R10 / R10-5", r"\br-?10\b|r10-?5|р-?10\b|ndi ?315|rumm ?10\b|рам ?10\b"), ("Rippa R319", r"319"), ("Rippa R13", r"\br-?13\b|р-?13\b"),
          ("Rippa R15", r"\br-?15\b|р-?15\b"), ("Rippa R18 / NDI335", r"\br-?18\b|ndi ?335|р-?18\b"), ("Rippa R22 / R322 / NDI322", r"\br-?22\b|322|р-?22\b"),
          ("Rippa R32 / R330 / R327", r"\br-?32\b|330|327|328|р-?32\b"), ("HighTop RUMM 13–20", r"rumm ?1[3-9]|rumm ?20|рам ?1[3-9]|ht-?1[5-9]|ht-?20|hightop 1[5-9]"),
          ("HighTop HT08 / HT10", r"ht-?0?8\b|ht-?10|хт-?10"), ("Мини-погрузчики", r"погрузчик|ht ?3[68]\d|r906|906|деретт|rs0\d|ndi ?6\d\d|lp0?5|думпер"),
          ("Квадроциклы", r"квадр"), ("Тракторы / кракен", r"трактор|кракен")]
TECH = re.compile(r"экскаватор|погрузчик|думпер|квадр|трактор|\br-?\d{2,3}|р-?\d{2}\b|rumm|рам ?\d|ht-?\d|ndi|lp0|кракен|\b3\d\d\b", re.I)
CITIES = set()


def num(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    s = re.sub(r"[^\d.,]", "", str(x).split("+")[0]).replace(",", ".")
    try: return float(s) if s else None
    except ValueError: return None


def date(x, contract=""):
    if isinstance(x, dt.datetime) and x.year > 2020: return x.date()
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", f"{x or ''} {contract}")
    if m:
        try: return dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError: return None
    m = re.search(r"от (\d{2})\.(\d{2})", f"{contract}")
    if m:
        mon = int(m[2]); yr = 2024 if mon >= 7 else 2025
        try: return dt.date(yr, mon, int(m[1]))
        except ValueError: return None
    return None


def tokens(s):
    return [t for t in re.findall(r"[А-Яа-яЁёA-Za-z]+", s or "")]


def surname(client):
    s = client or ""
    outside = re.sub(r"\(.*?\)", " ", s); inside = " ".join(re.findall(r"\((.*?)\)", s))
    fallback = None
    for part in (outside, inside):
        for t in tokens(part):
            l = t.lower().replace("ё", "е")
            if len(l) < 3 or l in STOP or l in NAMES or l in CITIES: continue
            if PATR.search(l):
                fallback = fallback or l
                continue
            return l
    return fallback


def status_group(s):
    s = (s or "").lower()
    if re.search(r"отработан|выдан|куплен из наличия", s): return "Завершена"
    if re.search(r"гарант", s): return "Завершена (гарантия)"
    if re.search(r"ждем оплаты|проект|бронь", s): return "Ожидает оплаты"
    if s: return "В работе"
    return "Нет статуса"


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    rows = lambda n: [r for r in wb[n].iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
    for n, ci in [("НОВАЯ ТАБЛИЦА УЧЕТА", 4), ("НОВАЯ ТАБЛИЦА УЧЕТА (копия)", 3), ("Лист1", 10), (".....", 5)]:
        for r in rows(n)[1:]:
            for t in tokens(str(r[ci] or "")): CITIES.add(t.lower())
    out = []
    def add(sheet, contract, d, client, mgr, city, cargo, status, pays, total, dest=None, weight=None, commission=None):
        if not client or not str(client).strip(): return
        out.append(dict(sheet=sheet, contract=str(contract or "").strip(), date=d, client=str(client).strip(), manager=(mgr or "").strip() if isinstance(mgr, str) else None,
                        city=str(city or "").strip(), cargo=str(cargo or "").strip(), status=str(status or "").strip(), pays=[p for p in pays if p], total=total,
                        dest=dest or [], weight=weight, commission=commission))
    for r in rows("НОВАЯ ТАБЛИЦА УЧЕТА")[1:]:
        r = list(r) + [None] * 20
        add("НОВАЯ", r[0], date(r[1]), r[2], r[3], r[4], r[5], r[13], [num(r[6])], num(r[7]), [r[8]] if isinstance(r[8], str) else [])
    for r in rows("НОВАЯ ТАБЛИЦА УЧЕТА (копия)")[1:]:
        r = list(r) + [None] * 20
        add("КОПИЯ", r[0], date(r[6]), r[1], r[2], r[3], r[4], r[5], [num(r[7]), num(r[10]), num(r[13]), num(r[16])], num(r[17]),
            [x for x in (r[8], r[11], r[14]) if isinstance(x, str)])
    for r in rows("Лист1")[1:]:
        r = list(r) + [None] * 20
        add("ЛИСТ1-2024", r[2], date(r[1], r[2]), r[3], r[4], r[10], r[11], r[12], [num(r[5]), num(r[6]), num(r[7])], None, None, num(r[13]), num(r[15]) or num(r[14]))
    for r in rows(".....")[2:]:
        r = list(r) + [None] * 20
        if isinstance(r[1], dt.datetime):  # строка в формате «НОВАЯ», сдвинутая на колонку
            add("ТОЧКИ", r[0], date(r[1]), r[2], r[3], r[4], r[5], None, [num(r[6])], num(r[7]), [r[8]] if isinstance(r[8], str) else [])
        else:
            add("ТОЧКИ", r[0], date(r[2]), r[3], None, r[5], r[7], r[4], [num(r[8]), num(r[9])], None, None, num(r[14]))
    # склейка: одна фамилия = одна сделка; строки без фамилии присоединяем по номеру договора, если он однозначен
    groups = collections.defaultdict(list); by_contract = collections.defaultdict(set)
    for o in out:
        o["surname"] = surname(o["client"])
        cb = re.match(r"\d{4}", o["contract"])
        o["cbase"] = cb.group(0) if cb and not re.match(r"\d{10,}", o["contract"]) and cb.group(0) != "2249" else None
        if o["surname"]:
            groups["s:" + o["surname"]].append(o)
            if o["cbase"]: by_contract[o["cbase"]].add("s:" + o["surname"])
    for o in out:
        if o["surname"]: continue
        cands = by_contract.get(o["cbase"]) if o["cbase"] else None
        if cands and len(cands) == 1: groups[next(iter(cands))].append(o)
        else: groups["raw:" + (o["cbase"] or o["client"].lower())].append(o)
    deals = []
    for g in groups.values():
        by_sheet = collections.defaultdict(list)
        for o in g: by_sheet[o["sheet"]].append(o)
        total = max([o["total"] for o in g if o["total"]] or [0])
        pays_sheet = max(sum(sorted(set(p for o in v for p in o["pays"]))) for v in by_sheet.values())
        amount = total or pays_sheet or None
        cargo = max((o["cargo"] for o in g), key=len)
        statuses = [o["status"] for o in g if o["status"]]
        grp = "Завершена" if any(status_group(s) == "Завершена" for s in statuses) else (status_group(statuses[-1]) if statuses else "Нет статуса")
        dates = [o["date"] for o in g if o["date"]]
        models = [n for n, rx in MODELS if re.search(rx, cargo, re.I)]
        dest = collections.Counter(d.strip().strip('"').replace('ООО "КИ-ТРАК"', "ООО «Ки-Трак»") for o in g for d in o["dest"])
        deals.append(dict(key=g[0]["surname"] or g[0]["contract"] or g[0]["client"], client=max((o["client"] for o in g), key=len),
                          sheets=sorted(by_sheet), rows=len(g), date=min(dates).isoformat() if dates else None,
                          manager=next((o["manager"] for o in g if o["manager"]), None), city=max((o["city"] for o in g), key=len),
                          cargo=cargo, kind="Техника" if TECH.search(cargo) else ("Не указан" if not cargo else "Навесное / запчасти / прочее"),
                          models=models, status=grp, amount=amount, commission=max([o["commission"] or 0 for o in g]) or None,
                          weight=max([o["weight"] or 0 for o in g]) or None, dest=dict(dest)))
    db = sqlite3.connect(os.path.join(ROOT, "data", "amo.sqlite"), timeout=120)
    db.execute("DROP TABLE IF EXISTS hist_deals")
    db.execute("CREATE TABLE hist_deals(key TEXT, client TEXT, sheets TEXT, rows INT, date TEXT, manager TEXT, city TEXT, cargo TEXT, kind TEXT, models TEXT, status TEXT, amount REAL, commission REAL, weight REAL, dest TEXT)")
    db.executemany("INSERT INTO hist_deals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [(d["key"], d["client"], json.dumps(d["sheets"], ensure_ascii=False), d["rows"], d["date"], d["manager"], d["city"], d["cargo"], d["kind"],
                     json.dumps(d["models"], ensure_ascii=False), d["status"], d["amount"], d["commission"], d["weight"], json.dumps(d["dest"], ensure_ascii=False)) for d in deals])
    db.commit()
    print("строк:", len(out), "сделок после склейки:", len(deals))
    return out, deals


if __name__ == "__main__":
    main()
