# Анализ сделок amoCRM (K-truck)

Скрипты выгружают сделки из amoCRM и считают отчёт: воронка, причины отказов, источники,
скорость реакции, работа менеджеров, база вопросов клиентов.

Порядок запуска (данные пишутся в `data/`, эта папка не попадает в git — в ней персональные данные):

```bash
AMO_SUBDOMAIN=gres16 AMO_TOKEN=<долгосрочный токен> python3 amo_analytics/export.py
python3 amo_analytics/link_notes.py      # звонки из карточек контактов → к сделкам
python3 amo_analytics/analyze.py         # метрики → data/metrics.json
python3 amo_analytics/transcribe.py      # расшифровка выборки звонков (faster-whisper, долго)
python3 amo_analytics/reasons.py         # реальные причины отказа по текстам
python3 amo_analytics/report_data.py     # наборы данных для дашборда → data/report/
```

История статусов (`status_events`) догружается отдельно запросом `/api/v4/events`
с типами `lead_status_changed` и `lead_added`.
