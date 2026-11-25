"""Выборка звонков из архива Telphin по сделкам с покупкой (вторая выборка, sampled=2).

Запись архива сопоставляется с заметкой звонка amoCRM: длительность совпадает (±3 с), заметка создана
в конце звонка (±15 с). Сделка с покупкой — этап «Предоплата», «Заказ в производстве», «В пути»,
«Оплата получена» или «Груз выдан». Фаза: «до покупки» — звонок не позже суток после первого перехода
на этап «Договор отправлен» или дальше, иначе «после покупки».
Берём все звонки до покупки и до 3 самых длинных звонков после покупки на сделку (от 60 с).
Результат: таблица tel_won(file, lead_id, phase), tel_calls.sampled=2. Затем: telphin_transcribe.py N."""
import bisect, collections, json, os, sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "amo.sqlite")
WON = (142, 65899094, 65738822, 90231690, 90231694)
BUY = (66041750,) + WON
POST_PER_LEAD = 3


def main():
    db = sqlite3.connect(DB, timeout=120)
    calls = sorted(db.execute("SELECT ts,file,dur FROM tel_calls").fetchall())
    tss = [c[0] for c in calls]
    info = {f: (ts, du) for ts, f, du in calls}
    first = dict(db.execute(f"SELECT lead_id,MIN(created_at) FROM status_events WHERE to_status IN {BUY} GROUP BY lead_id"))
    notes = db.execute(f"""SELECT n.lead_id,n.created_at,n.params FROM lead_notes n JOIN leads l ON l.id=n.lead_id
        WHERE n.note_type IN ('call_in','call_out') AND l.status_id IN {WON} AND n.created_at>=?""", (tss[0],)).fetchall()
    match = {}
    for lid, ca, p in notes:
        d = json.loads(p).get("duration") or 0
        i = bisect.bisect_left(tss, ca - d - 30)
        while i < len(calls) and calls[i][0] <= ca - d + 30:
            ts, f, du = calls[i]
            if abs(du - d) <= 3 and abs(ca - ts - du) <= 15:
                match[f] = lid
            i += 1
    rows, post = [], collections.defaultdict(list)
    for f, lid in match.items():
        ts, du = info[f]
        if du < 60 or lid not in first:
            continue
        if ts <= first[lid] + 86400:
            rows.append((f, lid, "до покупки"))
        else:
            post[lid].append((du, f))
    for lid, lst in post.items():
        for du, f in sorted(lst, reverse=True)[:POST_PER_LEAD]:
            rows.append((f, lid, "после покупки"))
    db.execute("CREATE TABLE IF NOT EXISTS tel_won(file TEXT PRIMARY KEY, lead_id INT, phase TEXT)")
    db.execute("DELETE FROM tel_won")
    db.executemany("INSERT INTO tel_won VALUES(?,?,?)", rows)
    db.executemany("UPDATE tel_calls SET sampled=2 WHERE file=? AND sampled=0", [(r[0],) for r in rows])
    db.commit()
    done = {r[0] for r in db.execute("SELECT file FROM tel_transcripts")}
    c = collections.Counter(r[2] for r in rows)
    new = [r for r in rows if r[0] not in done]
    print(f"сопоставлено {len(match)} записей с {len(set(match.values()))} сделками с покупкой")
    print(f"выборка {len(rows)}: {dict(c)}, сделок {len({r[1] for r in rows})}; уже расшифровано {len(rows)-len(new)}, новых {len(new)}")


if __name__ == "__main__":
    main()
