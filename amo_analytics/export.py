"""Выгрузка сделок и всей переписки/заметок из amoCRM (API v4) в SQLite.

Запуск:
    AMO_SUBDOMAIN=mycompany python3 amo_analytics/export.py [--since 2025-01-01]

Токен: переменная AMO_TOKEN (долгосрочный токен интеграции). В облачной сессии
токен подставляет прокси, поэтому AMO_TOKEN может быть любой заглушкой.
"""
import argparse, json, os, sqlite3, sys, time
from datetime import datetime, timezone
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "amo.sqlite")


class Amo:
    def __init__(self, subdomain, token, domain="amocrm.ru"):
        self.base = f"https://{subdomain}.{domain}/api/v4"
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, params=None):
        for attempt in range(6):
            r = self.s.get(self.base + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 204:
                return None
            if r.status_code == 401:
                sys.exit("401: токен не принят amoCRM — проверьте долгосрочный токен")
            r.raise_for_status()
            time.sleep(0.16)  # лимит amoCRM ~7 запросов/сек
            return r.json()
        r.raise_for_status()

    def paginate(self, path, key, params=None):
        params = dict(params or {}, limit=250, page=1)
        while True:
            data = self.get(path, params)
            if not data:
                return
            items = data.get("_embedded", {}).get(key, [])
            yield from items
            if not data.get("_links", {}).get("next") or not items:
                return
            params["page"] += 1
            print(f"  {path}: страница {params['page']}", file=sys.stderr)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS pipelines(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS statuses(id INTEGER, pipeline_id INTEGER, name TEXT, sort INTEGER, type INTEGER,
    PRIMARY KEY(id, pipeline_id));
CREATE TABLE IF NOT EXISTS loss_reasons(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY, name TEXT, price INTEGER, pipeline_id INTEGER,
    status_id INTEGER, responsible_user_id INTEGER, loss_reason_id INTEGER, created_at INTEGER,
    updated_at INTEGER, closed_at INTEGER, custom_fields TEXT, tags TEXT, contact_ids TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, name TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, entity_type TEXT, entity_id INTEGER, note_type TEXT,
    created_by INTEGER, created_at INTEGER, text TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, entity_type TEXT, entity_id INTEGER,
    responsible_user_id INTEGER, text TEXT, result TEXT, is_completed INTEGER, created_at INTEGER, complete_till INTEGER);
CREATE TABLE IF NOT EXISTS chat_events(id TEXT PRIMARY KEY, type TEXT, entity_type TEXT, entity_id INTEGER,
    created_by INTEGER, created_at INTEGER, raw TEXT);
-- База знаний: заполняется на этапе анализа
CREATE TABLE IF NOT EXISTS kb_questions(id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, question TEXT,
    best_answer TEXT, frequency INTEGER, example_lead_ids TEXT);
CREATE TABLE IF NOT EXISTS manager_answers(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER,
    manager_id INTEGER, question TEXT, answer TEXT, score INTEGER, comment TEXT);
CREATE TABLE IF NOT EXISTS lead_analysis(lead_id INTEGER PRIMARY KEY, outcome TEXT, real_loss_reason TEXT,
    objections TEXT, summary TEXT);
"""


def j(x):
    return json.dumps(x, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="выгружать сделки, созданные с даты YYYY-MM-DD")
    ap.add_argument("--domain", default=os.environ.get("AMO_DOMAIN", "amocrm.ru"))
    a = ap.parse_args()
    sub = os.environ.get("AMO_SUBDOMAIN") or sys.exit("Задайте AMO_SUBDOMAIN")
    amo = Amo(sub, os.environ.get("AMO_TOKEN", "proxy-injected"), a.domain)

    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)

    acc = amo.get("/account")
    print(f"Аккаунт: {acc.get('name')} (id {acc.get('id')})")

    print("Пользователи…")
    for u in amo.paginate("/users", "users"):
        db.execute("REPLACE INTO users VALUES(?,?,?,?)", (u["id"], u["name"], u.get("email"), j(u)))

    print("Воронки и этапы…")
    for p in amo.paginate("/leads/pipelines", "pipelines"):
        db.execute("REPLACE INTO pipelines VALUES(?,?)", (p["id"], p["name"]))
        for s in p["_embedded"]["statuses"]:
            db.execute("REPLACE INTO statuses VALUES(?,?,?,?,?)",
                       (s["id"], p["id"], s["name"], s.get("sort"), s.get("type")))

    print("Причины отказа…")
    try:
        for r in amo.paginate("/leads/loss_reasons", "loss_reasons"):
            db.execute("REPLACE INTO loss_reasons VALUES(?,?)", (r["id"], r["name"]))
    except requests.HTTPError as e:
        print(f"  причины отказа недоступны: {e}")

    params = {"with": "contacts,loss_reason"}
    if a.since:
        ts = int(datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        params["filter[created_at][from]"] = ts
    print("Сделки…")
    lead_ids = []
    for l in amo.paginate("/leads", "leads", params):
        emb = l.get("_embedded", {})
        lr = (emb.get("loss_reason") or [{}])
        lead_ids.append(l["id"])
        db.execute("REPLACE INTO leads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            l["id"], l.get("name"), l.get("price"), l.get("pipeline_id"), l.get("status_id"),
            l.get("responsible_user_id"), l.get("loss_reason_id") or (lr[0].get("id") if lr else None),
            l.get("created_at"), l.get("updated_at"), l.get("closed_at"),
            j(l.get("custom_fields_values")), j([t["name"] for t in emb.get("tags", [])]),
            j([c["id"] for c in emb.get("contacts", [])]), j(l)))
    print(f"  сделок: {len(lead_ids)}")
    db.commit()

    def notes_for(entity, ids):
        for i in range(0, len(ids), 50):
            p = {f"filter[entity_id][{k}]": v for k, v in enumerate(ids[i:i + 50])}
            for n in amo.paginate(f"/{entity}/notes", "notes", p):
                prm = n.get("params") or {}
                text = prm.get("text") or prm.get("service") or ""
                db.execute("REPLACE INTO notes VALUES(?,?,?,?,?,?,?,?)", (
                    n["id"], entity, n["entity_id"], n["note_type"], n.get("created_by"),
                    n.get("created_at"), text, j(prm)))
            db.commit()

    print("Заметки и звонки по сделкам…")
    notes_for("leads", lead_ids)

    contact_ids = sorted({c for (cs,) in db.execute("SELECT contact_ids FROM leads") for c in json.loads(cs)})
    print(f"Контакты ({len(contact_ids)}) и их заметки…")
    for i in range(0, len(contact_ids), 50):
        p = {f"filter[id][{k}]": v for k, v in enumerate(contact_ids[i:i + 50])}
        for c in amo.paginate("/contacts", "contacts", p):
            db.execute("REPLACE INTO contacts VALUES(?,?,?)", (c["id"], c.get("name"), j(c)))
    notes_for("contacts", contact_ids)

    print("Задачи (с результатами)…")
    tp = {"filter[entity_type]": "leads"}
    if a.since:
        tp["filter[updated_at][from]"] = params["filter[created_at][from]"]
    for t in amo.paginate("/tasks", "tasks", tp):
        db.execute("REPLACE INTO tasks VALUES(?,?,?,?,?,?,?,?,?)", (
            t["id"], t.get("entity_type"), t.get("entity_id"), t.get("responsible_user_id"),
            t.get("text"), j(t.get("result")), int(t.get("is_completed", False)),
            t.get("created_at"), t.get("complete_till")))
    db.commit()

    print("История статусов сделок…")
    db.execute("""CREATE TABLE IF NOT EXISTS status_events(id TEXT PRIMARY KEY, lead_id INTEGER, created_by INTEGER,
        created_at INTEGER, from_status INTEGER, to_status INTEGER, from_pipeline INTEGER, to_pipeline INTEGER)""")
    sp = {"filter[type][0]": "lead_status_changed", "filter[type][1]": "lead_added"}
    for e in amo.paginate("/events", "events", sp):
        vb = e.get("value_before") or [{}]; va = e.get("value_after") or [{}]
        b = (vb[0] or {}).get("lead_status", {}); af = (va[0] or {}).get("lead_status", {})
        db.execute("REPLACE INTO status_events VALUES(?,?,?,?,?,?,?,?)", (e["id"], e["entity_id"], e.get("created_by"),
                   e["created_at"], b.get("id"), af.get("id"), b.get("pipeline_id"), af.get("pipeline_id")))
    db.commit()

    print("События чатов (метаданные сообщений)…")
    ep = {"filter[type][0]": "incoming_chat_message", "filter[type][1]": "outgoing_chat_message"}
    if a.since:
        ep["filter[created_at][from]"] = params["filter[created_at][from]"]
    try:
        for e in amo.paginate("/events", "events", ep):
            db.execute("REPLACE INTO chat_events VALUES(?,?,?,?,?,?,?)", (
                e["id"], e["type"], e.get("entity_type"), e.get("entity_id"),
                e.get("created_by"), e.get("created_at"), j(e)))
    except requests.HTTPError as e:
        print(f"  события недоступны: {e}")
    db.commit()

    for t in ("leads", "notes", "tasks", "chat_events", "contacts"):
        print(f"{t}: {db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    print(f"Готово: {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    main()
