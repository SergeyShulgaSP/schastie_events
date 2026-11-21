"""Настройка amoCRM по итогам анализа (согласовано с пользователем 21.11.2026).
1) Воронка «Китай»: переименование этапов + этапы «Заказ в производстве» и «В пути».
2) Новые воронки «Покупатели» и «Отложено до сезона»; удаление пустой старой «Воронки».
3) Причины отказа. 4) Поля сделки. 5) Разовые задачи на открытые сделки.
Запуск: python3 amo_analytics/amo_setup.py            — только показать план
        python3 amo_analytics/amo_setup.py --apply    — применить
Повторный запуск безопасен: уже сделанное пропускается."""
import datetime as dt, sys, time
sys.path.insert(0, __import__("os").path.dirname(__file__))
from export import Amo

APPLY = "--apply" in sys.argv
CHINA, OLD = 8016678, 3804781
VYACHESLAV = 14013310
MSK = dt.timezone(dt.timedelta(hours=3))

RENAME = {65739762: "Новая заявка", 65738814: "Выявлена потребность", 65738818: "КП отправлено",
          66041750: "Договор отправлен", 65738822: "Предоплата получена", 65899094: "Оплата получена"}
NEW_STAGES = [("Заказ в производстве", 63, "#ffeab2"), ("В пути", 66, "#deff81")]
PIPELINES = {
    "Покупатели": [("Сервисный звонок (7 дней после выдачи)", 10, "#98cbff"), ("Предложить навесное и ТО", 20, "#fffeb2"),
                   ("Отзыв или видео", 30, "#ffce5a"), ("Повторная продажа в работе", 40, "#87f2c0"),
                   ("Повторная продажа", 142, None), ("Без повторной продажи", 143, None)],
    "Отложено до сезона": [("Вернуться к сезону", 10, "#98cbff"), ("Предложение к сезону отправлено", 20, "#fffeb2"),
                           ("Готов вернуться к покупке", 30, "#87f2c0"),
                           ("Вернулся — перенесён в «Китай»", 142, None), ("Не актуально", 143, None)],
}
LOSS = ["Не выходит на связь", "Хочет из наличия / не готов ждать", "Бюджет ниже цены", "Нужен лизинг / документы",
        "Купил у других", "Нецелевое"]
FIELDS = [
    ("Источник заявки", "select", ["Звонок", "WhatsApp", "Telegram (чат)", "Квиз-бот Telegram", "Сайт: форма", "Сайт: корзина",
                                    "Сайт: онлайн-чат", "MAX", "Авито", "YouTube", "Telegram-канал", "Рекомендация", "Повторный клиент", "E-mail", "Другое"]),
    ("Тип клиента", "select", ["Частник", "ИП", "ООО / организация"]),
    ("Задача клиента", "multiselect", ["Участок, дача, дом", "Стройка: фундамент, траншеи, септик", "Работа на заказ, аренда",
                                       "Уборка снега, благоустройство", "Ферма, сельское хозяйство", "Лес, пни, расчистка", "Пруд, дренаж", "Другое"]),
    ("Пакет навесного", "select", ["Без навесного", "Старт: ковш + быстросъём + планировочный", "Участок: Старт + гидробур",
                                   "Профи: + щипцы, удлинитель, Kubota", "Своя комплектация"]),
    ("Нужен ЭПСМ", "checkbox", None),
    ("Город доставки", "text", None),
]


class AmoW(Amo):
    def send(self, method, path, body):
        if not APPLY:
            print("   [проверка]", method, path); return None
        for attempt in range(6):
            r = self.s.request(method, self.base + path, json=body, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt); continue
            if r.status_code >= 400:
                print("   ОШИБКА", r.status_code, r.text[:600]); return None
            time.sleep(0.2)
            return r.json() if r.text else {}


def main():
    a = AmoW("gres16", "proxy-injected")
    pipes = {p["id"]: p for p in a.get("/leads/pipelines")["_embedded"]["pipelines"]}
    by_name = {p["name"]: p for p in pipes.values()}
    china = pipes[CHINA]; sts = {s["id"]: s for s in china["_embedded"]["statuses"]}

    print("1. Этапы воронки «Китай»")
    # ВНИМАНИЕ: PATCH этапа в amoCRM сбрасывает непереданные поля (без sort этапы переставляются,
    # без name — название стирается). Всегда передавать name + sort + color. Порядок после правок
    # проверять: amoCRM сдвигает соседей, иногда нужен sort «между» соседями (45, 75).
    for sid, name in RENAME.items():
        if sts[sid]["name"] != name:
            print(f"   «{sts[sid]['name']}» → «{name}»")
            a.send("PATCH", f"/leads/pipelines/{CHINA}/statuses/{sid}", {"name": name, "sort": sts[sid]["sort"], "color": sts[sid]["color"]})
    have = {s["name"] for s in sts.values()}
    for name, sort, color in NEW_STAGES:
        if name not in have:
            print(f"   + «{name}»"); a.send("POST", f"/leads/pipelines/{CHINA}/statuses", [{"name": name, "sort": sort, "color": color}])

    print("2. Воронки")
    for pname, stages in PIPELINES.items():
        if pname in by_name: print(f"   «{pname}» уже есть"); continue
        st = []
        for n, s, c in stages:
            d = {"name": n, "sort": s} if s < 100 else {"id": s, "name": n}
            if c: d["color"] = c
            st.append(d)
        print(f"   + «{pname}»: " + " → ".join(n for n, _, _ in stages))
        a.send("POST", "/leads/pipelines", [{"name": pname, "is_main": False, "is_unsorted_on": False, "sort": 100 + len(by_name),
                                             "_embedded": {"statuses": st}}])
    if OLD in pipes:
        cnt = sum(1 for _ in a.paginate("/leads", "leads", {"filter[pipeline_id]": OLD}))
        if cnt == 0:
            print(f"   − удалить пустую «{pipes[OLD]['name']}»"); a.send("DELETE", f"/leads/pipelines/{OLD}", None)
        else:
            print(f"   старая воронка не пуста ({cnt}) — не удаляю")

    print("3. Причины отказа")
    have = {r["name"] for r in a.get("/leads/loss_reasons")["_embedded"]["loss_reasons"]}
    new = [{"name": n} for n in LOSS if n not in have]
    if new: print("   + " + ", ".join(x["name"] for x in new)); a.send("POST", "/leads/loss_reasons", new)

    print("4. Поля сделки")
    have = {f["name"] for f in a.paginate("/leads/custom_fields", "custom_fields")}
    new = []
    for name, typ, enums in FIELDS:
        if name in have: continue
        f = {"name": name, "type": typ}
        if enums: f["enums"] = [{"value": v, "sort": (i + 1) * 10} for i, v in enumerate(enums)]
        new.append(f); print(f"   + «{name}» ({typ})")
    if new: a.send("POST", "/leads/custom_fields", new)

    print("5. Разовые задачи")
    users = {u["id"]: u["rights"].get("is_active") for u in a.get("/users")["_embedded"]["users"]}
    open_sts = [65739762, 65738814, 65738818, 66041750, 65738822, 65899094]
    params = {}
    for i, s in enumerate(open_sts):
        params[f"filter[statuses][{i}][pipeline_id]"] = CHINA; params[f"filter[statuses][{i}][status_id]"] = s
    leads = list(a.paginate("/leads", "leads", params))
    with_task = {t["entity_id"] for t in a.paginate("/tasks", "tasks", {"filter[is_completed]": 0, "filter[entity_type]": "leads"})}
    now = time.time()
    tomorrow = dt.datetime.now(MSK).replace(hour=12, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    if tomorrow.weekday() >= 5: tomorrow += dt.timedelta(days=7 - tomorrow.weekday())
    tasks, stale, plain, moved = [], 0, 0, 0
    for l in leads:
        is_stale = l["status_id"] == 65738818 and now - l["updated_at"] > 30 * 86400
        if l["id"] in with_task and not is_stale: continue
        resp = l["responsible_user_id"] if users.get(l["responsible_user_id"]) else VYACHESLAV
        moved += resp != l["responsible_user_id"]
        if is_stale:
            text, stale = "КП висит больше 30 дней: дожать (видео, отзыв, акция к сезону) или закрыть с причиной / перенести в «Отложено до сезона»", stale + 1
        else:
            text, plain = "Нет следующего шага: связаться с клиентом, узнать статус и назначить следующую задачу", plain + 1
        tasks.append({"entity_id": l["id"], "entity_type": "leads", "task_type_id": 1, "responsible_user_id": resp,
                      "text": text, "complete_till": int(tomorrow.timestamp())})
    print(f"   открытых сделок: {len(leads)}; задач «Связаться»: {plain}; «Дожать или закрыть»: {stale}; "
          f"из них на Вячеслава (ответственный неактивен): {moved}; срок — {tomorrow:%d.%m %H:%M} МСК")
    for i in range(0, len(tasks), 50):
        a.send("POST", "/tasks", tasks[i:i + 50])
    print("Готово." if APPLY else "Это проверка. Для применения: --apply")


if __name__ == "__main__":
    main()
