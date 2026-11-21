"""Скачивание экспорта Telegram (HTML) из публичной папки Google Диска в data/tg_export/chats/<chat>/."""
import os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "tg_export")
S = requests.Session()


def get(url):
    for i in range(6):
        try:
            r = S.get(url, timeout=90)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return None


def entries(folder_id):
    r = get(f"https://drive.google.com/embeddedfolderview?id={folder_id}")
    if not r:
        return []
    return re.findall(r'href="https://drive\.google\.com/(?:file/d|drive/folders)/([\w-]{20,})[^"]*"[^>]*>.*?flip-entry-title">([^<]+)', r.text, re.S)


def one(item):
    fid, name = item
    out = os.path.join(ROOT, "chats", name)
    if os.path.exists(os.path.join(out, ".done")):
        return 0
    os.makedirs(out, exist_ok=True)
    n = 0
    for xid, title in entries(fid):
        if not title.endswith(".html"):
            continue
        r = get(f"https://drive.usercontent.google.com/download?id={xid}&export=download&confirm=t")
        if r:
            open(os.path.join(out, title), "wb").write(r.content); n += 1
    open(os.path.join(out, ".done"), "w").write(str(n))
    return n


def main():
    chats = entries(sys.argv[1])
    print("чатов:", len(chats), flush=True)
    done = 0
    with ThreadPoolExecutor(8) as ex:
        for i, n in enumerate(ex.map(one, chats), 1):
            done += n
            if i % 100 == 0:
                print(i, "чатов,", done, "файлов", flush=True)
    print("готово", done, flush=True)


if __name__ == "__main__":
    main()
