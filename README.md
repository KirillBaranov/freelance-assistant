# freelance-assistant

> Autonomous lead pipeline for Russian freelance platforms — scrapes, scores with LLM, and delivers A-tier leads to Telegram.

![Python](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169e1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-dc382d?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-compose-2496ed?logo=docker&logoColor=white)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088ff?logo=githubactions&logoColor=white)
[![KB Labs](https://img.shields.io/badge/infra-KB_Labs-6366f1)](https://kblabs.ru)

Built for personal use. Running 24/7 on a VPS — collects leads every 3 minutes, scores them, pushes only the worthwhile ones.

---

## What it does

Monitors FL.ru (RSS) and Kwork (embedded-JSON scraping) on a cron schedule, runs each job through a composite scoring pipeline, and pushes **A-tier leads only** to a Telegram bot with one-tap proposal generation.

```
FL.ru RSS  ──┐
              ├──▶  normalize  ──▶  score  ──▶  tier A / B / C
Kwork JSON ──┘                                       │
                                               ┌─────┴─────┐
                                               ▼           ▼
                                        Telegram bot   Admin UI
                                        (A-leads +     (backlog,
                                        inline draft)   pipeline)
```

---

## Scoring pipeline

```
score = skill_fit×0.35 + money_fit×0.30 + fast_close×0.20 + source_fit×0.15 − risk×0.15

if score ≥ 0.50:  blend with LLM advisory  (80% rules + 20% LLM)
if shortlisted:   enrich with decision brief, milestones, risk summary
```

| Tier | Threshold | Outcome |
|------|-----------|---------|
| **A** | ≥ 0.62 | Pushed to Telegram immediately |
| **B** | 0.40 – 0.62 | Visible in admin backlog |
| **C** | < 0.40 | Auto-archived |

All weights and thresholds live in `config/scoring.yaml` — no code changes to tune behavior.

---

## Architecture

```
fa run
│
├── FastAPI + uvicorn :8000
│   ├── GET  /admin                 dashboard (stats, A-leads, source health)
│   ├── GET  /admin/jobs            backlog with tier/source/status filters
│   ├── POST /jobs/{id}/action      status transitions (skip, approve, won, lost…)
│   └── GET  /jobs/{id}/agent-payload + POST /jobs/{id}/send-to-agent
│
├── arq worker  (async job queue, Redis-backed)
│   ├── cron: ingest_source         every 3 min  — poll collectors, upsert candidates
│   ├── cron: score_candidates      every 1 min  — run scoring engine on new rows
│   ├── cron: notify_leads          every 1 min  — push A-leads to Telegram
│   ├── cron: followup_check        every 30 min — remind about applied bids
│   ├── cron: check_job_statuses    every 30 min — detect closed/won jobs on platform
│   └── task: generate_proposal     on-demand    — triggered by Telegram inline tap
│
└── aiogram 3 bot  (long polling)
    ├── Inline buttons: draft / skip / later / approve
    ├── /stats  — daily summary (leads, tiers, applied, won)
    ├── /pipeline — active leads by status
    └── /today  — earnings tracker vs daily target

Storage
├── PostgreSQL 16  — job_candidates table (JSONB score_details, JSONB raw_data)
└── Redis 7        — arq queue + per-source dedup state (recent_ids ring buffer)
```

### Key design decisions

**Registry pattern for collectors.** `@CollectorRegistry.register("source_name")` — add a new platform in one file; the worker picks it up automatically. No wiring needed.

**Rules before LLM.** Five rule-based scorers handle ~80% of decisions at zero API cost. LLM advisory fires only for borderline leads (score ≥ 0.50), keeping inference costs low.

**Async throughout.** `asyncio` + `asyncpg` + `arq` — no threads or sync I/O in hot paths. FastAPI, arq worker, and bot share one event loop via `asyncio.gather`.

**YAML-driven configuration.** Scoring weights, skill profile, source feeds, proposal templates, follow-up timing — all in `config/`. Behavior tuning requires no code changes.

**Single container.** API, worker, and bot run in one process. VPS footprint: ~150 MB RAM, one Docker container.

---

## Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI 0.115 + Uvicorn |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| Job queue | arq (Redis-backed) |
| Bot | aiogram 3 |
| LLM | OpenAI-compatible API via [KB Labs](https://kblabs.ru) |
| Scraping | httpx + feedparser + BeautifulSoup4 |
| Config | pydantic-settings + PyYAML + Jinja2 |
| Migrations | Alembic |
| Tests | pytest + pytest-asyncio + pytest-httpx |
| Lint | ruff |
| CI/CD | GitHub Actions → GHCR → VPS |

---

## Quick start

**Requires:** Docker, Python 3.12+

```bash
git clone https://github.com/KirillBaranov/freelance-assistant
cd freelance-assistant

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env          # set FA_TELEGRAM_BOT_TOKEN, FA_TELEGRAM_OWNER_ID, FA_LLM_API_KEY
docker compose up -d          # PostgreSQL 16 + Redis 7
fa migrate                    # run Alembic migrations
fa run                        # start API + worker + bot
```

Admin UI → `http://localhost:8000/admin`

---

## Configuration

All runtime behavior lives in `config/` — edit and restart.

| File | Controls |
|------|----------|
| `config/profile.yaml` | Skills, preferred categories, minimum budget, avoid-list |
| `config/scoring.yaml` | Scorer weights, tier thresholds, LLM blend ratio |
| `config/sources.yaml` | Platforms, RSS feeds, Kwork category IDs |
| `config/workflow.yaml` | Status machine transitions, follow-up timing |
| `config/cases/*.yaml` | Past-work snippets injected into proposal drafts |
| `config/templates/` | Jinja2 templates (quick / qualified proposal modes) |

Key environment variables:

```env
FA_DATABASE_URL=postgresql+asyncpg://fa:fa@localhost:5432/freelance_assistant
FA_REDIS_URL=redis://localhost:6379/0
FA_TELEGRAM_BOT_TOKEN=
FA_TELEGRAM_OWNER_ID=
FA_LLM_BASE_URL=https://api.kblabs.ru/llm/v1  # KB Labs Gateway (https://kblabs.ru) or any OpenAI-compatible endpoint
FA_LLM_API_KEY=
FA_LLM_MODEL=gpt-4o-mini
FA_ENABLED_SOURCES=fl_ru,kwork
```

---

## Telegram bot

Lead notification:
```
🅰️ A-Lead · FL.ru · 0.81

📋 Разработка Telegram-бота для учёта заказов
💰 15 000 ₽ · Программирование / Боты

Нужен бот на aiogram + PostgreSQL, интеграция с CRM…

[ ✍ Draft ]  [ ⏭ Skip ]
[ 🕐 Later ]  [ 🔗 Open ↗ ]
```

Tapping **Draft** enqueues `generate_proposal_task` in arq; the result lands in the same chat within seconds.

---

## CI/CD

```
push to main
  → GitHub Actions
  → docker build + push → ghcr.io/kirillbaranov/freelance-assistant:latest
  → SSH to VPS: docker compose pull && up -d && fa migrate
```

---

## Extending

**New source** — one file, one decorator:

```python
# collectors/my_platform.py
@CollectorRegistry.register("my_platform")
class MyCollector(BaseCollector):
    source = SourcePlatform.MY_PLATFORM
    poll_interval_seconds = 300

    async def collect(self) -> list[JobCandidateCreate]: ...
```

Enable in `config/sources.yaml`. Nothing else to change.

**New scorer** — inherit `BaseScorer`, register in `ScoringEngine`, add weight in YAML:

```python
class RecencyScorer(BaseScorer):
    name = "recency"
    async def evaluate(self, candidate, profile) -> float: ...
```

---

## Infrastructure

LLM scoring and proposal generation run on **[KB Labs](https://kblabs.ru)** — an infrastructure platform that puts every vendor behind one contract and one stable interface: LLM, embeddings, vector stores, cache, databases, event bus and more. Swap any vendor with a config line; service code never changes.

This project uses KB Labs for LLM inference and embeddings. The same platform backs all other products in this portfolio.

---

## Development

```bash
pytest tests/ -v                          # run test suite
ruff check src/                           # lint
fa ingest --source fl_ru                  # one-shot ingest (no Redis needed)
fa rescore --limit 100                    # recompute scores for existing rows
alembic revision --autogenerate -m "msg"  # generate migration
```
