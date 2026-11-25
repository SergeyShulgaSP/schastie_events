"""Расшифровка выборки звонков из годового архива Telphin (data/telphin_archive/mp3, в git не попадает).
Выборка: разговоры 60–1200 с, поровну по месяцам и по входящим/исходящим (seed=42), ~400 звонков,
расшифровываются первые 8 минут моделью large-v3-turbo. Повторный запуск продолжает с места остановки.
Таблицы: tel_calls (все записи архива), tel_transcripts (расшифровки)."""
import collections, datetime as dt, os, random, re, sqlite3, subprocess, sys, time
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MP3 = os.path.join(ROOT, "data", "telphin_archive", "mp3")
DB = os.path.join(ROOT, "data", "amo.sqlite")
PER_MONTH, MAX_SEC = 31, 480
RX = re.compile(r"(\d{4})-(\d\d)-(\d\d)-(\d\d)-(\d\d)-(\d\d)-UTC_(in|out)_(\d+)_(\w+)\.mp3$")


def index(db):
    db.execute("CREATE TABLE IF NOT EXISTS tel_calls(file TEXT PRIMARY KEY, ts INT, month TEXT, dir TEXT, ext TEXT, dur REAL, sampled INT DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS tel_transcripts(file TEXT PRIMARY KEY, text TEXT, sec REAL)")
    if db.execute("SELECT COUNT(*) FROM tel_calls").fetchone()[0]: return
    rows = []
    for f in os.listdir(MP3):
        m = RX.match(f)
        if not m: continue
        y, mo, d, h, mi, s, dr, ext, _ = m.groups()
        t = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=dt.timezone.utc)
        rows.append((f, int(t.timestamp()), f"{y}-{mo}", dr, ext, os.path.getsize(os.path.join(MP3, f)) / 2000))  # 16 кбит/с
    db.executemany("INSERT INTO tel_calls(file,ts,month,dir,ext,dur) VALUES(?,?,?,?,?,?)", rows)
    rnd = random.Random(42); pick = []
    by = collections.defaultdict(list)
    for f, ts, mon, dr, ext, dur in rows:
        if 60 <= dur <= 1200: by[(mon, dr)].append(f)
    for mon in sorted({r[2] for r in rows}):
        a, b = sorted(by[(mon, "in")]), sorted(by[(mon, "out")])
        rnd.shuffle(a); rnd.shuffle(b)
        k = PER_MONTH // 2
        take = a[:k] + b[:PER_MONTH - k]
        if len(take) < PER_MONTH: take += (a[k:] + b[PER_MONTH - k:])[:PER_MONTH - len(take)]
        pick += take
    db.executemany("UPDATE tel_calls SET sampled=1 WHERE file=?", [(f,) for f in pick])
    db.commit()


def main():
    db = sqlite3.connect(DB, timeout=120); db.execute("PRAGMA journal_mode=WAL")
    index(db)
    todo = [r[0] for r in db.execute("SELECT file FROM tel_calls WHERE sampled>=1 AND file NOT IN (SELECT file FROM tel_transcripts) ORDER BY sampled, ts")]
    upto = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # расшифровать, пока всего готово не станет upto (партии по 50)
    if upto:
        done = db.execute("SELECT COUNT(*) FROM tel_transcripts").fetchone()[0]
        todo = todo[:max(0, upto - done)]
    total = db.execute("SELECT COUNT(*) FROM tel_calls WHERE sampled>=1").fetchone()[0]
    print(f"выборка {total}, осталось {len(todo)}", flush=True)
    if not todo: return
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=os.cpu_count())
    t0 = time.time()
    for i, f in enumerate(todo, 1):
        raw = subprocess.run(["ffmpeg", "-nostdin", "-t", str(MAX_SEC), "-i", os.path.join(MP3, f), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True).stdout
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        segs, _ = model.transcribe(audio, language="ru", vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segs)
        db.execute("INSERT OR REPLACE INTO tel_transcripts VALUES(?,?,?)", (f, text, len(audio) / 16000)); db.commit()
        if i % 10 == 0:
            el = time.time() - t0
            print(f"{i}/{len(todo)} за {el/60:.0f} мин, осталось ~{el/i*(len(todo)-i)/3600:.1f} ч", flush=True)
    print("готово", flush=True)


if __name__ == "__main__":
    main()
