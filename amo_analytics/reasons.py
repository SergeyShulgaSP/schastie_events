"""Классификация реальных причин отказа и возражений по тексту заметок и результатов задач.
Ключевые слова подобраны по выборочному чтению заметок менеджеров K-truck."""
import collections, json, os, re, sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "data", "amo.sqlite")

RULES = [
    ("Не выходит на связь (не берёт трубку, игнорирует)",
     r"не бер[её]т|не взял|не отвеча|не ответил|игнор|выключен|недоступ|автоответчик|не выход\w* на связь|скинул|сбросил|молчит|не дозвон|нет ответа|не в сети|трубк\w* не"),
    ("Хочет технику из наличия, не готов ждать/платить вперёд",
     r"налич|под заказ|предоплат|плат\w* вперед|долго|срок\w* не|ждать не|не хочет ждать|опасается заказ"),
    ("Бюджет ниже цены / дорого / ищет дешевле",
     r"дорог|бюджет|дешев|б/у|б\.у|бу |подешевле|до \d{3} ?к|денег нет|нет денег|кредит|рассрочк|лизинг"),
    ("Отложил покупку (сезон, позже, весной)",
     r"отлож|весн|зим|осен|сезон|позже|позднее|не планир|через (месяц|неделю|год)|на следующ|в следующем|вернется|после праздник"),
    ("Просто изучает рынок / нет чёткой потребности",
     r"изуча|присматрив|смотрел[и]? вариант|издалека|просто (смотр|интерес|узна)|пока не знает|интересовал\w* ценой"),
    ("Купил у других / выбрал другой вариант",
     r"купил|уже взял|выбрал|решил вопрос|у других|у конкурент|рф производ|российск\w* производ|у дилер|в рипп"),
    ("Нужны документы: ПСМ, учёт, НДС, ГТД, лизинг",
     r"псм|эпсм|на учет|учёт|документ|ндс|гтд|официальн|в белую|сертификат"),
    ("Нецелевое обращение (ошибка, не оставлял заявку, спам, другая услуга)",
     r"не оставлял|ошибк|спам|реклам|не интересовал|не та|дубл|повторн\w* заявк|предлагал\w* услуг|логистик\w* компан|номер набран"),
    ("Нужна другая техника / запчасти / мелочь",
     r"запчаст|мотоблок|квадр|насос|фильтр|гидромотор|распределител"),
    ("Сомнения в надёжности / доверии / качестве",
     r"мошенн|боит|опасает|довер|гаранти|качеств|отзыв|надежн|надёжн|ломает"),
]


def classify(text):
    t = text.lower()
    return [name for name, rx in RULES if re.search(rx, t)]


def main():
    db = sqlite3.connect(DB, timeout=120)
    txt = collections.defaultdict(list)
    skip = re.compile(r"^(Выбер|Additional information|Заявка |Какую технику|whatsapp:|Мини.*SKU|.*Shipping:)", re.S)
    for lid, t in db.execute("SELECT lead_id,text FROM lead_notes WHERE note_type='common' AND created_by!=0"):
        if t and not skip.match(t.strip()):
            txt[lid].append(t)
    for lid, t in db.execute("SELECT entity_id,json_extract(result,'$.text') FROM tasks WHERE entity_type='leads'"):
        if t:
            txt[lid].append(t)
    for lid, t in db.execute("SELECT lead_id,text FROM transcripts WHERE text IS NOT NULL"):
        txt[lid].append(t)
    feats = {r[0]: r[1:] for r in db.execute("SELECT lead_id,outcome,reason FROM lead_features")}
    out = collections.defaultdict(collections.Counter); with_text = collections.Counter()
    cross = collections.defaultdict(collections.Counter)
    for lid, ts in txt.items():
        if lid not in feats or feats[lid][0] != "lost" or feats[lid][1] == "Спам":
            continue
        labels = classify("\n".join(ts)) or ["Нет понятной причины в заметках"]
        crm = feats[lid][1] or "Не указана"
        with_text[crm] += 1
        for lb in labels:
            out["all"][lb] += 1; cross[crm][lb] += 1
    res = dict(lost_with_text=sum(with_text.values()), by_crm_reason_count=with_text,
               real_reasons=out["all"].most_common(), cross={k: v.most_common() for k, v in cross.items()})
    json.dump(res, open(os.path.join(os.path.dirname(DB), "reasons.json"), "w"), ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, ensure_ascii=False, indent=1)[:5000])
