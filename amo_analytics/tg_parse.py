"""Разбор HTML-экспорта Telegram в таблицу tg_messages (data/amo.sqlite)."""
import collections, glob, os, re, sqlite3
from datetime import datetime
from bs4 import BeautifulSoup

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def main():
    db = sqlite3.connect(os.path.join(ROOT, "amo.sqlite"), timeout=120)
    db.execute("DROP TABLE IF EXISTS tg_messages")
    db.execute("""CREATE TABLE tg_messages(chat TEXT, chat_name TEXT, msg_id INTEGER, time INTEGER, sender TEXT,
                  text TEXT, media TEXT, reply_to INTEGER, PRIMARY KEY(chat, msg_id))""")
    rows = []
    for d in sorted(glob.glob(os.path.join(ROOT, "tg_export", "chats", "chat_*"))):
        chat = os.path.basename(d)
        files = sorted(glob.glob(os.path.join(d, "messages*.html")), key=lambda p: int(re.findall(r"(\d*)\.html", p)[0] or 1))
        last_sender = None; name = None
        for f in files:
            soup = BeautifulSoup(open(f, encoding="utf-8").read(), "lxml")
            if name is None:
                h = soup.select_one(".page_header .text")
                name = h.get_text(" ", strip=True) if h else chat
            for m in soup.select("div.message.default"):
                mid = int(m["id"].replace("message", ""))
                dt = m.select_one(".date.details")
                t = None
                if dt and dt.get("title"):
                    t = int(datetime.strptime(dt["title"][:19], "%d.%m.%Y %H:%M:%S").timestamp())
                fn = m.select_one(".from_name")
                if fn:
                    for s in fn.select("span"):
                        s.extract()
                    last_sender = fn.get_text(" ", strip=True)
                txt = m.select_one(".text")
                text = txt.get_text("\n", strip=True) if txt else ""
                media = ""
                mw = m.select_one(".media_wrap")
                if mw:
                    tt = mw.select_one(".title")
                    media = (tt.get_text(" ", strip=True) if tt else "media")[:100]
                rep = m.select_one(".reply_to a")
                rto = None
                if rep and rep.get("href"):
                    r = re.findall(r"message(-?\d+)", rep["href"])
                    rto = int(r[0]) if r else None
                rows.append((chat, name, mid, t, last_sender, text, media, rto))
    db.executemany("INSERT OR REPLACE INTO tg_messages VALUES(?,?,?,?,?,?,?,?)", rows)
    db.commit()
    print("сообщений:", len(rows))


if __name__ == "__main__":
    main()
