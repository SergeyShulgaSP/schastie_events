"""Расшифровка выборки записей звонков (Telphin) через faster-whisper.

Выборка: самые длинные разговоры по успешным сделкам и по каждой причине отказа.
Результат: таблица transcripts в data/amo.sqlite. Можно перезапускать — продолжит с места остановки.
"""
import json, os, sqlite3, subprocess, sys, tempfile, time
import numpy as np
from faster_whisper import WhisperModel

DB = os.path.join(os.path.dirname(__file__), "..", "data", "amo.sqlite")
MAX_SEC = 300  # расшифровываем первые 5 минут разговора
PER_GROUP = {"won": 40, "lost": 15}


def pick(db):
    groups = {"won": "l.status_id=142"}
    for (rid,) in db.execute("SELECT id FROM loss_reasons WHERE name!='Спам'"):
        groups[f"lost_{rid}"] = f"l.status_id=143 AND l.loss_reason_id={rid}"
    groups["lost_none"] = "l.status_id=143 AND l.loss_reason_id IS NULL"
    picked = []
    for g, cond in groups.items():
        n = PER_GROUP["won" if g == "won" else "lost"]
        rows = db.execute(f"""
            SELECT n.id, n.lead_id, json_extract(n.params,'$.link'), json_extract(n.params,'$.duration')
            FROM lead_notes n JOIN leads l ON l.id=n.lead_id
            WHERE n.note_type LIKE 'call%' AND {cond}
              AND json_extract(n.params,'$.link') IS NOT NULL
              AND json_extract(n.params,'$.duration') BETWEEN 60 AND 1800
            ORDER BY l.created_at DESC, json_extract(n.params,'$.duration') DESC""").fetchall()
        seen = set()
        for r in rows:  # один (самый длинный свежий) разговор на сделку
            if r[1] in seen:
                continue
            seen.add(r[1]); picked.append((g,) + r)
            if len(seen) >= n:
                break
    return picked


def load(url):
    with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
        for i in range(4):
            r = subprocess.run(["curl", "-sL", "--max-time", "90", "-o", f.name, url])
            if r.returncode == 0 and os.path.getsize(f.name) > 1000:
                break
            time.sleep(3 * (i + 1))
        else:
            return None
        raw = subprocess.run(["ffmpeg", "-nostdin", "-t", str(MAX_SEC), "-i", f.name, "-f", "s16le",
                              "-ac", "1", "-ar", "16000", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def main():
    db = sqlite3.connect(DB, timeout=120)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS transcripts(note_id INTEGER PRIMARY KEY, lead_id INTEGER,
        grp TEXT, duration INTEGER, text TEXT)""")
    todo = [p for p in pick(db) if not db.execute("SELECT 1 FROM transcripts WHERE note_id=?", (p[1],)).fetchone()]
    print(f"к расшифровке: {len(todo)}", flush=True)
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "large-v3-turbo"), device="cpu",
                         compute_type="int8", cpu_threads=os.cpu_count())
    for i, (g, nid, lid, url, dur) in enumerate(todo, 1):
        audio = load(url)
        if audio is None or len(audio) < 16000:
            text = None
        else:
            segs, _ = model.transcribe(audio, language="ru", vad_filter=True, beam_size=1)
            text = "\n".join(s.text.strip() for s in segs)
        db.execute("REPLACE INTO transcripts VALUES(?,?,?,?,?)", (nid, lid, g, dur, text))
        db.commit()
        print(f"{i}/{len(todo)} {g} lead={lid} {dur}s {'ok' if text else 'нет записи'}", flush=True)


if __name__ == "__main__":
    main()
