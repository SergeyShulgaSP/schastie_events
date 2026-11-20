"""Выгрузка переписки из ChatApp (WhatsApp, Telegram, MAX) в data/amo.sqlite.

Запуск: CHATAPP_TOKEN=<accessToken> python3 amo_analytics/chatapp_export.py [--license 47091]
Токен получают запросом POST https://api.chatapp.online/v1/tokens (email, password, appId), живёт 24 часа.
Можно перезапускать: уже выгруженные чаты пропускаются."""
import argparse, json, os, sqlite3, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

DB = os.path.join(os.path.dirname(__file__), "..", "data", "amo.sqlite")
BASE = "https://api.chatapp.online"
local = threading.local()


def sess():
    if not hasattr(local, "s"):
        local.s = requests.Session()
        local.s.headers.update({"Authorization": os.environ["CHATAPP_TOKEN"], "Lang": "ru"})
    return local.s


def get(path, params=None):
    for i in range(8):
        try:
            r = sess().get(BASE + path, params=params, timeout=90)
            if r.status_code == 403:
                sys.exit(f"403: {r.text[:200]} — токен истёк или недействителен")
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(r.status_code)
            d = r.json()
            if d.get("success"):
                return d["data"]
            raise RuntimeError(d.get("error"))
        except SystemExit:
            raise
        except Exception as e:
            time.sleep(min(30, 2 ** i))
    print(f"  не удалось: {path} {params}", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--license", default="47091")
    ap.add_argument("--types", default="grWhatsApp,telegram,max")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=120, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS ca_chats(messenger TEXT, chat_id TEXT, phone TEXT, username TEXT, name TEXT,
        last_time INTEGER, raw TEXT, done INTEGER DEFAULT 0, PRIMARY KEY(messenger, chat_id));
    CREATE TABLE IF NOT EXISTS ca_messages(messenger TEXT, chat_id TEXT, id TEXT, time INTEGER, side TEXT,
        from_api INTEGER, type TEXT, text TEXT, file_type TEXT, PRIMARY KEY(messenger, chat_id, id));
    """)
    lock = threading.Lock()
    for t in a.types.split(","):
        print(f"{t}: список чатов…", flush=True)
        last, n = None, 0
        while True:
            p = {"limit": 100}
            if last: p["lastTime"] = last
            d = get(f"/v1/licenses/{a.license}/messengers/{t}/chats", p)
            items = (d or {}).get("items") or []
            if not items: break
            for c in items:
                db.execute("INSERT OR IGNORE INTO ca_chats(messenger,chat_id,phone,username,name,last_time,raw) VALUES(?,?,?,?,?,?,?)",
                           (t, c["id"], c.get("phone"), c.get("username"), c.get("name"), c.get("lastTime"), json.dumps(c, ensure_ascii=False)))
            n += len(items); db.commit()
            nl = items[-1].get("lastTime")
            if nl == last or len(items) < 100: break
            last = nl
        print(f"  чатов: {n}", flush=True)

    todo = db.execute("SELECT messenger,chat_id FROM ca_chats WHERE done=0").fetchall()
    print(f"чатов к выгрузке сообщений: {len(todo)}", flush=True)
    cnt = [0]

    def one(mc):
        t, cid = mc
        rows, page = [], None
        while True:
            p = {"limit": 100}
            if page: p["nextPage"] = page
            d = get(f"/v1/licenses/{a.license}/messengers/{t}/chats/{cid}/messages", p)
            if d is None: return
            for m in d.get("items") or []:
                msg = m.get("message") or {}
                text = (msg.get("text") or "") + ("\n" + msg["caption"] if msg.get("caption") else "")
                f = msg.get("file") or {}
                rows.append((t, cid, m["id"], m.get("time"), m.get("side"), int(bool(m.get("fromApi"))), m.get("type"),
                             text.strip(), f.get("contentType")))
            np_ = d.get("nextPage")
            if not np_ or not d.get("items") or np_ == page: break
            page = np_
        with lock:
            db.executemany("INSERT OR IGNORE INTO ca_messages VALUES(?,?,?,?,?,?,?,?,?)", rows)
            db.execute("UPDATE ca_chats SET done=1 WHERE messenger=? AND chat_id=?", (t, cid))
            db.commit(); cnt[0] += 1
            if cnt[0] % 200 == 0:
                print(f"  {cnt[0]}/{len(todo)} чатов", flush=True)

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, todo))
    for r in db.execute("SELECT messenger,count(DISTINCT chat_id),count(*),sum(side='in'),sum(side='out') FROM ca_messages GROUP BY 1"):
        print(r)


if __name__ == "__main__":
    main()
