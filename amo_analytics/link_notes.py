"""Привязка заметок контактов (звонки!) к сделкам.

В amoCRM звонки Telphin сохраняются в карточке контакта. Каждый такой звонок
относим к сделке этого контакта, созданной последней на момент звонка.
Результат: таблица lead_notes (все заметки сделок + заметки контактов).
"""
import bisect, collections, json, os, sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "data", "amo.sqlite")


def build(db):
    by_contact = collections.defaultdict(list)
    for lid, created, cids in db.execute("SELECT id,created_at,contact_ids FROM leads"):
        for c in json.loads(cids or "[]"):
            by_contact[c].append((created, lid))
    for v in by_contact.values():
        v.sort()
    db.execute("DROP TABLE IF EXISTS lead_notes")
    db.execute("""CREATE TABLE lead_notes AS SELECT id, entity_id AS lead_id, 'lead' AS via, note_type, created_by,
                  created_at, text, params FROM notes WHERE entity_type='leads'""")
    rows = []
    for nid, cid, nt, by, at, text, prm in db.execute(
            "SELECT id,entity_id,note_type,created_by,created_at,text,params FROM notes WHERE entity_type='contacts'"):
        cand = by_contact.get(cid)
        if not cand:
            continue
        i = bisect.bisect_right([c[0] for c in cand], at + 3600) - 1
        rows.append((nid, cand[max(i, 0)][1], "contact", nt, by, at, text, prm))
    db.executemany("INSERT INTO lead_notes VALUES(?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE INDEX IF NOT EXISTS ix_lead_notes ON lead_notes(lead_id)")
    db.commit()
    return len(rows)


if __name__ == "__main__":
    print("привязано заметок контактов:", build(sqlite3.connect(DB, timeout=120)))
