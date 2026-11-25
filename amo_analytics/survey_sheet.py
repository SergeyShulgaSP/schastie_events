"""Таблица обзвона покупателей: сценарий, список выигранных сделок amoCRM (по одной на контакт, без имён и телефонов —
менеджер открывает карточку по ссылке), ответы с выпадающими списками, сводка формулами.
Результат: data/survey/k-truck-obzvon.xlsx (в git не попадает — ссылки на сделки)."""
import datetime as dt, json, os, re, sqlite3
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "data", "survey", "k-truck-obzvon.xlsx")

LISTS = {
    "Статус звонка": ["Не звонили", "Не дозвонились", "Перезвонить", "Опрошен", "Отказался говорить"],
    "Техника работает": ["Да, всё хорошо", "Есть мелкие вопросы", "Есть проблема"],
    "Почему выбрали нас": ["Цена ниже дилера или наличия", "Полная комплектация", "Консультация и подбор", "Доверие: офис в СПб, договор, фото и видео этапов",
                           "Отзывы, канал, YouTube", "Рекомендация знакомых", "Нужная модель (HighTop RUMM и др.)", "Двигатель Kubota",
                           "Навесное и подарки в комплекте", "Быстро ответили", "Оплата частями", "Документы (ЭПСМ, ПСМ)", "Другое"],
    "Как узнали": ["Сайт / поиск", "Авито", "Telegram-канал", "YouTube", "Рекомендация", "Реклама (Яндекс, ВК)", "Покупал раньше", "Другое"],
    "Что ещё рассматривали": ["Официальный дилер Rippa", "Наличие (Авито, другие продавцы)", "Другие поставщики из Китая", "Сам напрямую из Китая",
                              "Б/у японская или европейская", "Никого"],
    "Что чуть не остановило": ["Цена", "Сроки поставки", "Страх предоплаты, мошенников", "Документы", "Китайский двигатель, качество",
                               "Доставка до города", "Ничего"],
    "Самое неудобное": ["Сроки и задержки", "Оплата (банк, агенты)", "Связь с менеджером", "Документы", "Сборка, инструкции", "Доставка", "Ничего"],
    "Для каких работ": ["Участок, свой дом", "Стройка: фундамент, траншеи, септик", "Работа на заказ, аренда", "Снег, благоустройство",
                        "Ферма", "Лес, пни", "Другое"],
    "Что нужно сейчас": ["Навесное", "Запчасти", "ТО и расходники", "Вторая машина", "Ничего"],
    "Да/Нет/Позже": ["Да", "Нет", "Позже"],
}
COLS = [("№", 5, None), ("Сделка в amoCRM", 16, None), ("Дата покупки", 11, None), ("Что купил (если известно)", 28, None), ("Источник в amoCRM", 16, None),
        ("Статус звонка", 15, "Статус звонка"), ("Дата звонка", 11, None), ("Кто звонил", 12, None),
        ("1. Техника работает?", 15, "Техника работает"), ("Проблема (текст)", 22, None),
        ("2. Главная причина выбора", 24, "Почему выбрали нас"), ("Другие причины (своими словами)", 30, None),
        ("3. Как узнали", 15, "Как узнали"), ("4. Что ещё рассматривали", 20, "Что ещё рассматривали"),
        ("5. Что чуть не остановило", 20, "Что чуть не остановило"), ("6. Самое неудобное", 18, "Самое неудобное"),
        ("7. Для каких работ", 20, "Для каких работ"), ("8. Оценка 0–10", 9, None),
        ("Почему такая оценка", 26, None), ("9. Что нужно сейчас", 15, "Что нужно сейчас"),
        ("10. Отзыв или видео", 10, "Да/Нет/Позже"), ("11. Есть кому порекомендовать", 12, "Да/Нет/Позже"), ("Комментарий, следующий шаг", 30, None)]

SCRIPT = [
    ("Цель", "Узнать, почему клиенты купили у K-truck, что мешало и что нужно сейчас. Не продавать в лоб — сначала слушать. 5–7 минут."),
    ("Перед звонком", "Открыть карточку сделки по ссылке: что купил, когда, были ли задержки. Записывать ответы сразу в таблицу."),
    ("Начало", "«Здравствуйте, [имя]! Это [имя], компания K-truck. Вы у нас брали [модель] в [месяц]. Звоню не продавать — хотим стать лучше, и ваше мнение очень важно. Есть 5 минут?»"),
    ("1. Техника", "«Как техника, всё работает? Были вопросы по сборке, запчастям, ТО?» → если проблема: записать и пообещать ответ в течение дня (задача в amoCRM)."),
    ("2. Почему мы", "«Почему в итоге выбрали нас? Что стало решающим?» — дать ответить своими словами, потом уточнить: цена, комплектация, консультация, доверие, отзывы, знакомые."),
    ("3. Как узнали", "«Как вы о нас узнали впервые?»"),
    ("4. Альтернативы", "«Кого ещё рассматривали? Почему не у них?»"),
    ("5. Сомнения", "«Что чуть не остановило от покупки?»"),
    ("6. Неудобства", "«Что было самым неудобным: сроки, оплата, связь, документы, доставка, сборка?»"),
    ("7. Работы", "«Для каких работ используете? Зарабатываете на ней или для себя?»"),
    ("8. Оценка", "«По шкале от 0 до 10 — насколько вероятно, что порекомендуете нас знакомым? Почему такая оценка?»"),
    ("9. Что нужно", "«Что сейчас может пригодиться: навесное, запчасти, масла и фильтры к ТО, может быть, вторая машина?» → если да: КП в мессенджер, сделка в воронке «Покупатели»."),
    ("10. Отзыв", "«Можно попросить короткий отзыв на Авито / Яндекс или видео, как техника работает? Это очень помогает» (бонус: скидка на навесное)."),
    ("11. Рекомендация", "«Есть знакомые, кому нужна техника? За рекомендацию — [бонус]»."),
    ("Завершение", "«Спасибо большое! Если что-то понадобится — пишите мне напрямую»."),
    ("Важно", "Не спорить и не оправдываться на критику — записать дословно. Плохие оценки (0–6) — сразу руководителю."),
]

HEAD = PatternFill("solid", fgColor="1F3864"); HF = Font(bold=True, color="FFFFFF")
thin = Side(style="thin", color="C9CED6"); BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
INPUT = PatternFill("solid", fgColor="FFF8E1")


def buyers():
    db = sqlite3.connect(os.path.join(ROOT, "data", "amo.sqlite"))
    rows = db.execute("SELECT l.id,l.contact_ids,l.closed_at,l.raw,f.model,f.category,f.source FROM leads l JOIN lead_features f ON f.lead_id=l.id "
                      "WHERE f.outcome='won' ORDER BY l.closed_at DESC").fetchall()
    seen, out = set(), []
    for lid, cids, closed, raw, model, cat, src in rows:
        c = (json.loads(cids or "[]") or [None])[0]
        if c is not None and c in seen: continue
        seen.add(c)
        f = {x["field_name"]: x["values"][0]["value"] for x in (json.loads(raw).get("custom_fields_values") or [])}
        what = f.get("Состав груза") or model or cat or ""
        what = re.sub(r"&amp;nbsp;|&nbsp;", " ", str(what))[:80]
        out.append((lid, dt.datetime.fromtimestamp(closed).date() if closed else None, what, src or ""))
    return out


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb = Workbook()
    s = wb.active; s.title = "Сценарий"
    s["A1"] = "Обзвон покупателей K-truck: сценарий"; s["A1"].font = Font(bold=True, size=14)
    for i, (k, v) in enumerate(SCRIPT, 3):
        s.cell(i, 1, k).font = Font(bold=True); s.cell(i, 2, v).alignment = Alignment(wrap_text=True, vertical="top")
    s.column_dimensions["A"].width = 16; s.column_dimensions["B"].width = 110
    # справочник
    r = wb.create_sheet("Справочник")
    for j, (name, vals) in enumerate(LISTS.items(), 1):
        r.cell(1, j, name).font = Font(bold=True); r.column_dimensions[L(j)].width = 30
        for i, v in enumerate(vals, 2): r.cell(i, j, v)
    ref = {name: f"Справочник!${L(j)}$2:${L(j)}${len(vals) + 1}" for j, (name, vals) in enumerate(LISTS.items(), 1)}
    # обзвон
    o = wb.create_sheet("Обзвон", 1)
    for j, (h, w, _) in enumerate(COLS, 1):
        c = o.cell(1, j, h); c.fill = HEAD; c.font = HF; c.alignment = Alignment(wrap_text=True, vertical="center"); c.border = BOX
        o.column_dimensions[L(j)].width = w
    o.row_dimensions[1].height = 45
    data = buyers(); n = len(data)
    for i, (lid, d, what, src) in enumerate(data, 2):
        url = f"https://gres16.amocrm.ru/leads/detail/{lid}"
        o.cell(i, 1, i - 1); c = o.cell(i, 2, f"Сделка {lid}"); c.hyperlink = url; c.font = Font(color="1155CC", underline="single")
        o.cell(i, 3, d).number_format = "DD.MM.YYYY"; o.cell(i, 4, what); o.cell(i, 5, src); o.cell(i, 6, "Не звонили")
        for j in range(1, len(COLS) + 1):
            o.cell(i, j).border = BOX
            if j >= 6: o.cell(i, j).fill = INPUT
    last = n + 1
    for j, (_, _, lst) in enumerate(COLS, 1):
        if lst:
            dv = DataValidation(type="list", formula1=f"={ref[lst]}", allow_blank=True); o.add_data_validation(dv); dv.add(f"{L(j)}2:{L(j)}{last}")
    dv = DataValidation(type="whole", operator="between", formula1="0", formula2="10", allow_blank=True); o.add_data_validation(dv); dv.add(f"R2:R{last}")
    o.freeze_panes = "C2"; o.auto_filter.ref = f"A1:{L(len(COLS))}{last}"
    # сводка
    v = wb.create_sheet("Сводка", 2)
    v["A1"] = "Сводка обзвона (считается сама)"; v["A1"].font = Font(bold=True, size=14)
    v["A3"] = "Всего покупателей в списке" ; v["B3"] = f"=COUNTA(Обзвон!B2:B{last})"
    v["A4"] = "Опрошено" ; v["B4"] = f'=COUNTIF(Обзвон!F2:F{last},"Опрошен")'
    v["A5"] = "Средняя оценка 0–10" ; v["B5"] = f'=IFERROR(AVERAGE(Обзвон!R2:R{last}),"")'
    v["A6"] = "Индекс рекомендации (NPS)"
    v["B6"] = f'=IFERROR((COUNTIF(Обзвон!R2:R{last},">=9")-COUNTIF(Обзвон!R2:R{last},"<=6"))/COUNT(Обзвон!R2:R{last})*100,"")'
    v["A7"] = "Есть проблема с техникой" ; v["B7"] = f'=COUNTIF(Обзвон!I2:I{last},"Есть проблема")'
    row = 9
    for title, col, lst in [("Главная причина выбора", "K", "Почему выбрали нас"), ("Как узнали", "M", "Как узнали"),
                            ("Что ещё рассматривали", "N", "Что ещё рассматривали"), ("Что чуть не остановило", "O", "Что чуть не остановило"),
                            ("Самое неудобное", "P", "Самое неудобное"), ("Для каких работ", "Q", "Для каких работ"), ("Что нужно сейчас", "T", "Что нужно сейчас")]:
        v.cell(row, 1, title).font = Font(bold=True); v.cell(row, 2, "Ответов").font = Font(bold=True); row += 1
        for val in LISTS[lst]:
            v.cell(row, 1, val); v.cell(row, 2, f'=COUNTIF(Обзвон!{col}2:{col}{last},A{row})'); row += 1
        row += 1
    v.column_dimensions["A"].width = 50; v.column_dimensions["B"].width = 12
    wb.save(OUT); print(OUT, n, "покупателей")


if __name__ == "__main__":
    main()
