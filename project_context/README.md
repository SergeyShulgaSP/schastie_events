# Проект: аналитика продаж K-truck

Обзор проекта и его структуры. С этого файла начинает работу любой человек или ИИ-агент.

## Что это за проект

**Клиент:** K-truck (ООО «Ки-Трак», Санкт-Петербург, k-truck.ru, Telegram-канал t.me/k_truck). Компания поставляет из Китая под заказ мини-экскаваторы, мини-погрузчики, мини-думперы и навесное (Rippa, HighTop / RUMM и другие), а также возит грузы по инвойсу клиента.

**Цель проекта:** понять, почему компания теряет сделки, что спрашивают клиенты и как отвечают менеджеры, и на этой основе:
- собрать отчёты по сделкам, звонкам и переписке;
- вести базу вопросов клиентов и эталонных ответов;
- подготовить материалы для обучения менеджеров и ИИ-консультанта;
- дать рекомендации по продажам, продукту, сервису и маркетингу.

**Период данных:** апрель 2024 — ноябрь 2026. **Начало проекта:** 20.11.2026.

## Источники данных

| Источник | Что взяли | Как получаем | Где лежит |
|---|---|---|---|
| amoCRM (gres16.amocrm.ru) | 7 009 сделок, история статусов, заметки, задачи, звонки Telphin, события чатов | API v4, долгосрочный токен | `data/amo.sqlite` |
| Записи звонков Telphin | 108 звонков (выборка), расшифровки Whisper | ссылки из заметок amoCRM | таблица `transcripts` |
| ChatApp (WhatsApp, Telegram, MAX) | 413 чатов, 8 тыс. сообщений (март–ноябрь 2026) | API ChatApp, токен на 24 ч | таблицы `ca_chats`, `ca_messages` |
| Экспорт Telegram (рабочий аккаунт) | 962 диалога с клиентами, 1 280 комментариев канала (2024–2026) | HTML-экспорт с Google Диска | таблица `tg_messages` |
| Ручная таблица учёта сделок (Google Таблица) | 437 строк → 185 сделок (окт. 2024 — нояб. 2026) | выгрузка xlsx по ссылке | таблица `hist_deals` |

Папка `data/` в git **не попадает**: там персональные данные клиентов.

## Структура репозитория

```
CLAUDE.md                 — точка входа для ИИ-агентов (ссылается сюда)
project_context/          — база знаний проекта
  README.md               — этот файл: обзор и структура
  knowledge_base.md       — исследования, факты, цифры, выводы
  agent_instructions.md   — правила работы для ИИ-агентов
  memory.md               — журнал решений и изменений
amo_analytics/            — скрипты выгрузки и анализа (Python)
  export.py               — выгрузка amoCRM → SQLite
  link_notes.py           — привязка звонков из карточек контактов к сделкам
  analyze.py              — метрики сделок → data/metrics.json
  reasons.py              — реальные причины отказов по текстам
  transcribe.py           — расшифровка звонков (faster-whisper)
  chatapp_export.py       — выгрузка переписки ChatApp
  chat_analysis.py        — анализ переписки ChatApp
  tg_download.py, tg_parse.py, tg_analysis.py — экспорт Telegram: скачивание, разбор, анализ
  deep_analysis.py        — углублённый анализ: сезонность, скорость, источники, география, портрет и др.
  goals_tracker.py        — трекер целей на квартал → reports/k-truck-goals-q1-2027.xlsx
  deals_history.py        — ручная таблица учёта сделок: склейка дублей, метрики
  knowledge_base.py       — база вопросов и разбор ответов → SQLite и xlsx
  report_data.py          — наборы данных для интерактивного отчёта
  html_report.py          — автономная HTML-страница отчёта
  ai_guide.py             — путеводитель и диалоги для ИИ-консультанта
reports/                  — готовые результаты без персональных данных
  k-truck-report.html     — отчёт одной страницей
  k-truck-knowledge-base.xlsx — база вопросов и разбор ответов
  k-truck-ai-guide.md     — путеводитель для ИИ-консультанта
  k-truck-goals-q1-2027.xlsx — трекер целей (шаблон, загружен в Google Таблицу)
  k-truck-ai-qa.jsonl     — 50 диалогов для дообучения
data/                     — сырые данные и SQLite (только локально, в .gitignore)
```

## Результаты и где они

| Результат | Где |
|---|---|
| Интерактивный отчёт по сделкам, звонкам и переписке | https://claude.ai/artifact/M9zGLLew3xwm5L2z9UjRMJ |
| Google Док «Анализ сделок K-truck» | https://docs.google.com/document/d/1L-JAC-rM7mmr2Rz3jpGwNyuNJr258pxZf7bPUMoFGPU/edit |
| Google Док «Анализ переписки K-truck» (ChatApp) | https://docs.google.com/document/d/1A5wzMy2b668q_Ci4Lzvr3eztMK1s_Pp-SYHU4JshD6I/edit |
| Google Док «Анализ переписки Telegram K-truck» | https://docs.google.com/document/d/1hWvSRaErcrxejUEPTWotZf5_Prp5_8dU5j5VKc-62UQ/edit |
| Google Таблица «База вопросов клиентов K-truck» | https://docs.google.com/spreadsheets/d/1u1R4L6TK8b8VnlOmQmUEn3pEnxkICbj-ZTGOenzQlPc/edit |
| Google Док «Углублённый анализ K-truck: 10 направлений» | https://docs.google.com/document/d/1A3glnH9Da_DaQUjIlXL1_NmcpCIqadAdnBzFJ7ODCVg/edit |
| Google Док «Цели K-truck на I квартал 2027» | https://docs.google.com/document/d/1-gWyJ_O7FyZaAEM35f2gGXkcY6mSopXxkzAhJSWZJyQ/edit |
| Google Таблица «Трекер целей K-truck — I квартал 2027» | https://docs.google.com/spreadsheets/d/1yaQg0kUqM_Bu-BrZx5jbPRyS5vY8YR0IQ2PgjSpYC9Y/edit |
| Путеводитель для ИИ-консультанта | `reports/k-truck-ai-guide.md`, `reports/k-truck-ai-qa.jsonl` |

## Как пересобрать всё с нуля

См. `amo_analytics/README.md` и раздел «Пайплайн» в `agent_instructions.md`.
