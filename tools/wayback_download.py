#!/usr/bin/env python3
"""Скачивает из Wayback Machine последние снимки всех страниц и картинок сайта.

Запуск (нужен только Python 3.9+, без дополнительных библиотек):

    python wayback_download.py

Результат: папка wayback/ и архив wayback-schastie.zip рядом со скриптом.
Скрипт можно прервать и запустить снова: уже скачанные файлы пропускаются.
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

DOMAINS = ["schastie-events.com", "msk.schastie-events.com"]
OUT = "wayback"
ZIP_NAME = "wayback-schastie.zip"
PAUSE = 1.5          # пауза между запросами, чтобы архив не начал отказывать
RETRIES = 5
UA = "Mozilla/5.0 (site-restore script)"

SKIP_PARTS = ("/wp-json/", "/feed", "/wp-admin", "/xmlrpc", "?s=", "/wp-includes/",
              "replytocom=", "elementor-preview", "/comments/", "/embed")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")


def get(url, timeout=90):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001 - сеть, таймауты
            last = e
        wait = PAUSE * (2 ** attempt) * 2
        print(f"   повтор через {wait:.0f} с ({last})")
        time.sleep(wait)
    raise last


def list_snapshots(domain):
    """Последний удачный снимок для каждого уникального URL домена."""
    q = urllib.parse.urlencode({
        "url": f"{domain}/*",
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode",
        "filter": "statuscode:200",
    })
    # берём все снимки и сами выбираем самый свежий для каждого URL
    print(f"Получаю список снимков {domain} …")
    rows = json.loads(get(f"https://web.archive.org/cdx/search/cdx?{q}", timeout=300) or b"[]")
    latest = {}
    for ts, original, mime, _status in rows[1:]:
        key = original.split("://", 1)[-1].lower().rstrip("/")
        if key.startswith("www."):
            key = key[4:]
        if key not in latest or ts > latest[key][0]:
            latest[key] = (ts, original, mime)
    print(f"   уникальных URL: {len(latest)}")
    return latest.values()


def wanted(original, mime):
    low = original.lower()
    if any(p in low for p in SKIP_PARTS):
        return None
    parts = urllib.parse.urlsplit(low)
    path = parts.path
    if parts.query:
        return None
    if path.endswith(IMAGE_EXT) or mime.startswith("image/"):
        return "image"
    if mime == "text/html":
        return "page"
    return None


def local_path(original, kind):
    parts = urllib.parse.urlsplit(original)
    host = parts.netloc.lower().removeprefix("www.")
    path = urllib.parse.unquote(parts.path) or "/"
    if kind == "page":
        path = path.rstrip("/") + "/index.html"
    safe = "".join(c if c not in '<>:"|?*' else "_" for c in path.lstrip("/"))
    return os.path.join(OUT, host, safe)


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = []
    for domain in DOMAINS:
        for ts, original, mime in list_snapshots(domain):
            kind = wanted(original, mime)
            if kind:
                manifest.append((kind, ts, original, local_path(original, kind)))

    pages = sum(1 for m in manifest if m[0] == "page")
    print(f"\nК скачиванию: страниц {pages}, картинок {len(manifest) - pages}\n")

    ok = failed = 0
    for i, (kind, ts, original, dest) in enumerate(manifest, 1):
        if os.path.exists(dest):
            ok += 1
            continue
        # id_ — исходный файл без панели и переписанных ссылок архива
        url = f"https://web.archive.org/web/{ts}id_/{original}"
        print(f"[{i}/{len(manifest)}] {kind} {original}")
        try:
            data = get(url)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"   не скачалось: {e}")
            failed += 1
        time.sleep(PAUSE)

    with open(os.path.join(OUT, "manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "timestamp", "url", "file", "downloaded"])
        for kind, ts, original, dest in manifest:
            w.writerow([kind, ts, original, os.path.relpath(dest, OUT), os.path.exists(dest)])

    with zipfile.ZipFile(ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(OUT):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, OUT))

    size = os.path.getsize(ZIP_NAME) / 1024 / 1024
    print(f"\nГотово: скачано {ok}, ошибок {failed}. Архив {ZIP_NAME} ({size:.1f} МБ)")
    print("Загрузите его на Google Drive или dropmefiles и пришлите ссылку.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено. Запустите снова — скачанное пропустится.")
        sys.exit(1)
