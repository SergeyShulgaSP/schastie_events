"""Автономная HTML-страница отчёта (без внешних библиотек) → reports/k-truck-report.html.
Берёт наборы данных из data/report/*.json (их готовит report_data.py)."""
import html, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
R = lambda n: json.load(open(os.path.join(ROOT, "data", "report", f"{n}.json")))["rows"]
has = lambda n: os.path.exists(os.path.join(ROOT, "data", "report", f"{n}.json"))
e = html.escape
MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def nf(v):
    if v is None: return '—'
    if isinstance(v, (int, float)):
        return f"{int(v):,}".replace(",", " ") if float(v).is_integer() else f"{v:.1f}".replace(".", ",")
    if re.fullmatch(r"\d{4}-\d{2}", str(v)):
        y, m = v.split('-'); return MON[int(m) - 1] + ' ' + y
    return e(str(v))


pc = lambda v: nf(round(float(v), 1)) + '%'


def hbar(rows, L, V, C=None, pct=False, narrow=False):
    W, lw, cut = (460, 215, 30) if narrow else (760, 300, 44)
    bh, g = 22, 8
    mx = max(float(r[V]) for r in rows) or 1; H = len(rows) * (bh + g)
    s = f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">'
    for i, r in enumerate(rows):
        y = i * (bh + g); w = max(1, (W - lw - (110 if C else 60)) * float(r[V]) / mx)
        lab = str(r[L]).split(' (')[0].split(' / ')[0] if narrow else str(r[L]); lab = lab if len(lab) <= cut else lab[:cut - 1] + '…'
        val = (pc(r[V]) if pct else nf(r[V])) + (f' · {pc(r[C])}' if C else '')
        tip = f"{r[L]}: {pc(r[V]) if pct else nf(r[V])}" + (f", конверсия {pc(r[C])}" if C else "")
        s += (f'<g><title>{e(tip)}</title><text x="{lw-8}" y="{y+bh/2}" dy="0.35em" text-anchor="end" class="l">{e(lab)}</text>'
              f'<rect x="{lw}" y="{y}" width="{w:.1f}" height="{bh}" rx="3" class="b"/>'
              f'<text x="{lw+w+6:.1f}" y="{y+bh/2}" dy="0.35em" class="v">{val}</text></g>')
    return s + '</svg>'


def monthly(rows):
    W, H, ml, mb = 760, 220, 40, 26; n = len(rows); bw = (W - ml) / n; mx = max(r['сделок'] for r in rows)
    sy = lambda v: (H - mb) - (H - mb - 10) * v / mx
    s = f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">'
    for t in range(0, int(mx) + 1, 100):
        s += f'<line x1="{ml}" x2="{W}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="g"/><text x="{ml-6}" y="{sy(t):.1f}" dy="0.35em" text-anchor="end" class="v">{t}</text>'
    for i, r in enumerate(rows):
        x = ml + i * bw + bw * 0.1; w = bw * 0.8
        s += (f'<g><title>{nf(r["месяц"])}: {r["сделок"]} сделок, выиграно {r["выиграно"]} ({pc(r["конверсия, %"])})</title>'
              f'<rect x="{x:.1f}" y="{sy(r["сделок"]):.1f}" width="{w:.1f}" height="{(H-mb)-sy(r["сделок"]):.1f}" class="b" opacity="0.35"/>'
              f'<rect x="{x:.1f}" y="{sy(r["выиграно"]):.1f}" width="{w:.1f}" height="{(H-mb)-sy(r["выиграно"]):.1f}" class="b"/></g>')
        if i % 4 == 0:
            s += f'<text x="{x+w/2:.1f}" y="{H-8}" text-anchor="middle" class="v">{nf(r["месяц"])}</text>'
    return s + '</svg>'


def table(rows, cols, heads):
    h = '<div class="tw"><table><thead><tr>' + ''.join(f'<th>{e(x)}</th>' for x in heads) + '</tr></thead><tbody>'
    for r in rows:
        h += '<tr>' + ''.join(f'<td class="{"n" if isinstance(r[c], (int, float)) else ""}">{nf(r[c])}</td>' for c in cols) + '</tr>'
    return h + '</tbody></table></div>'


def main():
    k = R('kpi')[0]; y = {r['год']: r for r in R('years')}; s = {r['источник']: r for r in R('sources')}
    f = {r['этап']: r['дошло сделок'] for r in R('funnel')}; cb = {r['перезвон']: r['звонков'] for r in R('callbacks')}
    rc = {r['скорость реакции']: r for r in R('reaction')}; fu = {r['касаний после КП']: r for r in R('followup')}
    tile = lambda v, l, c='': f'<div class="tile"><span class="tv {c}">{v}</span><span class="tl">{l}</span></div>'
    kb = ''
    if has('kb'):
        kb += f'<section id="kb"><h2>База вопросов клиентов и ответов</h2><p>Типовые вопросы из звонков и комментариев и лучшие ответы менеджеров K-truck. Основа для скрипта продаж и обучения новых сотрудников.</p>{table(R("kb"), ["тема","вопрос клиента","как отвечать","как часто"], ["Тема","Вопрос клиента","Как отвечать","Встречается"])}</section>'
    if has('answers'):
        kb += f'<section id="answers"><h2>Разбор ответов менеджеров</h2><p>Ситуации из расшифрованных звонков: что сказал менеджер, оценка от 1 до 5 и как ответить лучше.</p>{table(R("answers"), ["ситуация","что сказал менеджер","оценка","как лучше"], ["Ситуация","Что сказал менеджер","Оценка","Как лучше"])}</section>'
    kbnav = '<a href="#kb">База вопросов</a><a href="#answers">Ответы менеджеров</a>' if kb else ''
    H = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Анализ сделок K-truck</title>
<style>
:root{{--bg:#f7f8f6;--fg:#1c2421;--mut:#5d6964;--panel:#fff;--line:#dde3df;--acc:#2f7d5b;--bad:#b4442f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151a18;--fg:#e8ede9;--mut:#9aa7a1;--panel:#1d2421;--line:#2f3a35;--acc:#5fbf91;--bad:#e2775f}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:32px max(16px,env(safe-area-inset-left)) 64px;display:flex;flex-direction:column;gap:40px}}
h1{{font:400 2.2rem/1.15 Georgia,serif;margin:0}} h2{{font-size:1.35rem;margin:0}} h3{{font-size:1rem;margin:0}}
p{{margin:0;max-width:75ch}} .lede{{font-size:1.15rem}} .mut{{color:var(--mut);font-size:.85rem}}
section{{display:flex;flex-direction:column;gap:14px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.tile{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:4px}}
.tv{{font:400 1.9rem/1.1 Georgia,serif;font-variant-numeric:tabular-nums}} .tl{{color:var(--mut);font-size:.82rem}} .bad{{color:var(--bad)}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px}} .grid2>div{{min-width:0;display:flex;flex-direction:column;gap:8px}}
svg text{{font-size:12px;fill:var(--mut)}} svg text.l{{fill:var(--fg)}} .b{{fill:var(--acc)}} .g{{stroke:var(--line)}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}} th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mut);font-weight:600}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
ol{{padding-left:1.3em;display:flex;flex-direction:column;gap:10px;max-width:80ch;margin:0}}
nav{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.85rem}} nav a{{color:var(--mut)}}
</style></head><body><main>
<header style="display:flex;flex-direction:column;gap:10px">
<h1>Анализ сделок K-truck</h1>
<p class="mut">amoCRM gres16 · воронка «Китай» · сделки с апреля 2024 по ноябрь 2026 · выгрузка 20.11.2026</p>
<p class="lede">Из {nf(k['сделок'])} сделок до выдачи груза дошли {nf(k['выиграно'])} ({pc(k['конверсия, %'])}). Больше всего сделок теряется после отправки КП и на этапе «Менеджер назначен», а у {pc(k['отказов без причины, %'])} отказов причина не указана.</p>
<nav><a href="#funnel">Воронка</a><a href="#losses">Отказы</a><a href="#sources">Источники</a><a href="#work">Работа с клиентом</a><a href="#managers">Менеджеры</a><a href="#demand">Спрос</a>{kbnav}<a href="#recs">Что делать</a></nav>
</header>
<section class="tiles">{tile(nf(k['сделок']),'сделок всего')}{tile(nf(k['выиграно']),'грузов выдано')}{tile(pc(k['конверсия без спама, %']),'конверсия без учёта спама')}{tile(pc(k['отказов без причины, %']),'отказов без указанной причины','bad')}{tile(nf(k['медиана реакции, ч'])+' ч','медиана до первого звонка или сообщения')}{tile(nf(k['дней до выдачи груза (медиана)'])+' дн.','от заявки до выдачи груза, медиана')}</section>
<section><h2>Заявок стало меньше, конверсия падает</h2>
<p>Конверсия по году создания сделки: 2024 — {pc(y['2024']['конверсия, %'])}, 2025 — {pc(y['2025']['конверсия, %'])}, 2026 — {pc(y['2026']['конверсия, %'])} (год неполный, {nf(k['в работе'])} сделок ещё в работе).</p>
{monthly(R('monthly'))}<p class="mut">Столбики — новые сделки за месяц, тёмная часть — сколько из них дошли до выдачи груза. Наведите на столбик, чтобы увидеть цифры.</p></section>
<section id="funnel"><h2>Воронка: обрыв после КП</h2>
<p>Расчёт или КП получили {nf(f['расчет отправлен/КП'])} сделок, а до договора дошли только {nf(f['На покупку согласен/отправлен договор'])}.</p>
{hbar(R('funnel'),'этап','дошло сделок')}
<h3>С какого этапа закрывают проигранные сделки</h3>{hbar(R('closed_from'),'этап','закрыто сделок')}</section>
<section id="losses"><h2>Причины отказов: что пишут в CRM и что на самом деле</h2>
<div class="grid2"><div><h3>Причина в карточке сделки</h3>{hbar(R('loss_crm'),'причина в CRM','сделок',narrow=True)}<p class="mut">«Нет денег» часто ставят по умолчанию: в заметках по таким сделкам обычно нет ни слова о бюджете.</p></div>
<div><h3>Причина по комментариям и звонкам</h3>{hbar(R('loss_real'),'реальная причина','сделок',narrow=True)}<p class="mut">По ключевым словам в комментариях, результатах задач и расшифровках звонков. У сделки может быть несколько причин.</p></div></div></section>
<section id="sources"><h2>Источники: квиз-бот даёт много заявок и почти не продаёт</h2>
<p>Квиз-бот в Telegram привёл {nf(s['Telegram-бот (квиз)']['сделок'])} сделок с конверсией {pc(s['Telegram-бот (квиз)']['конверсия, %'])}. Входящий звонок — {pc(s['Звонок на номер']['конверсия, %'])}, чат WhatsApp — {pc(s['Входящий чат: WhatsApp']['конверсия, %'])}, заказ из корзины сайта — {pc(s['Заказ через корзину сайта']['конверсия, %'])}.</p>
{hbar(R('sources'),'источник','сделок','конверсия, %')}<p class="mut">Длина полосы — число сделок, справа — конверсия в выданный груз.</p></section>
<section id="work"><h2>Работа с клиентом: скорость и дожим</h2>
<div class="grid2"><div><h3>Конверсия по скорости первого касания</h3>{hbar(R('reaction'),'скорость реакции','конверсия, %',pct=True,narrow=True)}<p class="mut">Ответ за 5–30 минут — {pc(rc['5–30 мин']['конверсия, %'])}, через 2–24 часа — {pc(rc['2–24 ч']['конверсия, %'])}.</p></div>
<div><h3>Конверсия по числу касаний после КП</h3>{hbar(R('followup'),'касаний после КП','конверсия, %',pct=True,narrow=True)}<p class="mut">У {nf(fu['нет касаний']['проиграно'])} проигранных сделок после КП не было ни одного звонка или сообщения.</p></div></div>
<h3>Пропущенные входящие звонки: когда перезвонили</h3>{hbar(R('callbacks'),'перезвон','звонков')}</section>
<section id="managers"><h2>Менеджеры</h2>
<p>Почти все сделки числятся за «Сергей Директор», хотя комментарии пишут разные сотрудники, поэтому таблица показывает скорее дисциплину ведения CRM, чем личную результативность. Вячеслав работает с 2026 года, и много его сделок ещё открыто.</p>
{table(R('managers'),['менеджер','сделок','выиграно','конверсия, %','медиана реакции, ч','без исходящего касания, %','отказов без причины, %','задач закрыто без комментария, %'],['Менеджер','Сделок','Выиграно','Конверсия, %','Реакция, ч','Без касания, %','Отказ без причины, %','Задачи без комментария, %'])}</section>
<section id="demand"><h2>Что спрашивают</h2><div class="grid2">
<div><h3>Категория техники</h3>{hbar(R('categories'),'категория','сделок','конверсия, %',narrow=True)}</div>
<div><h3>Способ доставки в квиз-боте</h3>{hbar(R('delivery'),'способ доставки','сделок','конверсия, %',narrow=True)}</div></div></section>
{kb}
<section id="recs"><h2>Что делать</h2><ol>
<li><b>Сделать причину отказа обязательной.</b> Сейчас у {nf(k['отказов без причины'])} закрытых сделок причины нет. Добавить причины «Не вышел на связь», «Хочет из наличия, не готов ждать», «Бюджет ниже рынка», «Отложил покупку», «Купил у других», «Нецелевая заявка».</li>
<li><b>Отвечать на заявку в первые 30 минут.</b> Медиана сейчас {nf(k['медиана реакции, ч'])} ч. Мгновенная задача «Позвонить» на новую сделку и уведомление в мессенджер; ночные заявки разбирать первыми утром.</li>
<li><b>Дожимать после КП по графику.</b> День 1 — звонок «получили ли расчёт», день 3 — видео или кейс по модели, день 7 — место в ближайшем контейнере, день 14 — финальный вопрос. Закрывать сделку только после 3 касаний.</li>
<li><b>Перезванивать на пропущенные в течение 15 минут.</b> {nf(cb['не перезвонили'])} пропущенных так и остались без ответа, на {nf(cb['позже суток'])} перезвонили позже чем через сутки.</li>
<li><b>Пересобрать квиз-бот и рекламу Яндекса.</b> Добавить в квиз вопросы о бюджете и сроке покупки, заявки без бюджета отправлять в автопрогрев, бюджет перенести в кампании, которые дают звонки и заказы с сайта.</li>
<li><b>Отработать возражение «хочу из наличия».</b> Держать на складе 2–3 ходовые модели (R319, RUMM 13, HT 10), продавать места в ближайшем контейнере с фиксированной датой, показывать отзывы клиентов.</li>
<li><b>Писать результат задачи словами.</b> 70–77% задач закрываются с «+», точкой или датой. Нужна одна строка: что обсудили и следующий шаг.</li>
<li><b>Сохранять переписку из мессенджеров.</b> Текст сообщений WhatsApp, Telegram и MAX недоступен через API amoCRM; нужен экспорт чатов из ChatApp или итог переписки в примечании.</li></ol></section>
<details><summary>Как считали</summary><p class="mut">Данные выгружены из amoCRM через API v4: сделки, история статусов, заметки сделок и контактов (звонки Telphin привязаны к сделке контакта), задачи и их результаты, события чатов. Конверсия — доля сделок в статусе «Груз выдан». Спам исключён из конверсий по источникам, реакции и воронке.{"" if kb else " База вопросов клиентов и разбор ответов менеджеров готовятся по расшифровкам звонков."}</p></details>
</main></body></html>'''
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    out = os.path.join(ROOT, "reports", "k-truck-report.html")
    open(out, "w").write(H)
    print(out)


if __name__ == "__main__":
    main()
