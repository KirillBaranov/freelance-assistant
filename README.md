# Freelance Assistant

Personal lead-generation system. Monitors Russian freelance platforms, scores jobs, generates proposal drafts, and pushes A-leads to Telegram.

---

## What it does

1. **Collects** jobs from FL.ru (multi-feed RSS), Kwork (embedded JSON), and Telegram channels
2. **Scores** each lead against your skill profile — rule-based + source-aware ranking + LLM advisory
3. **Classifies** into A / B / C tiers
4. **Pushes A-leads** to your Telegram with inline action buttons
5. **Generates proposal drafts** on tap — selects relevant case snippets, calls LLM
6. **Tracks workflow** — new → applied → won/lost, with weak/noisy C-leads auto-archived

---

## Quick Start

**Prerequisites:** Docker, Python 3.12+

```bash
# 1. Clone and install
git clone <repo>
cd freelance-assitant
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure
cp .env.example .env
# Fill in: FA_TELEGRAM_BOT_TOKEN, FA_TELEGRAM_OWNER_ID, FA_LLM_API_KEY

# 3. Start infrastructure
docker compose up -d

# 4. Create DB tables
fa migrate

# 5. Run everything
fa run
```

Admin UI: `http://localhost:8000/admin`

---

## Configuration

All configuration lives in `config/` — edit YAML, restart. No code changes needed.

| File | Purpose |
|------|---------|
| `config/profile.yaml` | Your skills, preferred categories, avoid-list, min budget |
| `config/scoring.yaml` | Scorer weights, A/B/C thresholds |
| `config/sources.yaml` | Enable/disable sources, per-source settings |
| `config/workflow.yaml` | Status machine transitions, follow-up timing |
| `config/cases/*.yaml` | Case snippets used in proposal drafts |
| `config/templates/*.j2` | Jinja2 proposal templates |

### Environment Variables

```env
FA_DATABASE_URL=postgresql+asyncpg://fa:fa@localhost:5432/freelance_assistant
FA_REDIS_URL=redis://localhost:6379/0
FA_TELEGRAM_BOT_TOKEN=         # BotFather token
FA_TELEGRAM_OWNER_ID=          # your Telegram user ID
FA_LLM_BASE_URL=https://api.kblabs.ru
FA_LLM_API_KEY=                # optional static Bearer token
FA_LLM_CLIENT_ID=              # optional KB Labs gateway machine credential
FA_LLM_CLIENT_SECRET=          # optional KB Labs gateway machine credential
FA_LLM_CREDENTIALS_PATH=       # optional path to JSON with clientId/clientSecret
FA_LLM_MODEL=gpt-4o-mini
FA_AGENT_WEBHOOK_URL=          # optional POST endpoint for one-click agent handoff
FA_AGENT_WEBHOOK_TOKEN=        # optional Bearer/shared token for agent webhook
FA_AGENT_WEBHOOK_TIMEOUT_SECONDS=20
FA_ENABLED_SOURCES=fl_ru       # comma-separated: fl_ru,kwork
```

---

## Sources

| Source | Status | Method | Interval |
|--------|--------|--------|----------|
| FL.ru | ✅ Active | RSS feed | 3 min |
| Kwork | ✅ Active | Embedded JSON | 5 min |
| Telegram channels | Phase 6 | Telethon userbot | Event-driven |
| Freelance.ru | Deferred | HTML scrape | 10 min |

Enable sources in `config/sources.yaml` or via `FA_ENABLED_SOURCES`.

### FL.ru feed strategy

`FL.ru` now reads `feeds[]` from `config/sources.yaml` instead of a single `rss_url`.

- Use narrow programming feeds as primary inputs and mark them `source_quality: high`
- Keep `all.xml` as fallback/debug with `source_quality: low`
- Broad-feed noise such as design, 3D and logo work is filtered before it reaches scoring

```yaml
sources:
  fl_ru:
    feeds:
      - url: "https://www.fl.ru/rss/all.xml"
        label: "all"
        source_quality: "low"
        source_bucket: "broad_feed"
      - url: "https://www.fl.ru/rss/<programming-feed>.xml"
        label: "programming"
        category_hint: "Программирование"
        source_quality: "high"
        source_bucket: "programming_feed"
```

### Kwork category strategy

`Kwork` categories are configured as structured entries with quality metadata:

```yaml
sources:
  kwork:
    categories:
      - id: 41
        label: "Программирование"
        source_quality: "high"
        source_bucket: "programming_marketplace"
      - id: 79
        label: "Боты и чат-боты"
        source_quality: "high"
        source_bucket: "programming_marketplace"
```

### Adding a Telegram Channel Monitor

```yaml
sources:
  telegram:
    channels:
      - handle: "@python_jobs"
        label: "Python Jobs"
        quality: "high"
        tags: ["python", "jobs"]
        enabled: true
```

```env
FA_TELEGRAM_API_ID=12345
FA_TELEGRAM_API_HASH=abc123
```

Requires `telethon` package: `pip install ".[telegram-channels]"`

---

## Scoring

```
final_score = skill_fit(0.35) + money_fit(0.30) + fast_close_fit(0.20) + source_fit(0.15) - risk_score(0.15)
```

Then optionally blended with LLM advisory (80% rules + 20% LLM) for leads scoring above 0.50.

`source_fit` rewards leads from higher-signal sources such as programming-specific FL.ru feeds and Kwork programming categories.

**Tiers** (configurable in `config/scoring.yaml`):
- **A** (≥ 0.70) — pushed to Telegram immediately
- **B** (≥ 0.40) — visible in admin backlog
- **C** (< 0.40) — auto-archived as weak/noisy leads

---

## Telegram Bot

### Lead notification

```
🅰️ A-Lead | FL.ru | Score: 0.82

📋 Разработка Telegram-бота для учёта заказов
💰 15 000 ₽
🏷 Программирование / Боты

Нужен бот на aiogram + PostgreSQL...

[✍ Написать]  [⏭ Пропустить]
[🕐 Позже]    [🔗 Открыть ↗]
```

### Proposal draft (after tapping ✍)

```
✍ Отклик для: Разработка Telegram-бота...

Задача знакома — разработал 15+ ботов на aiogram...
[✅ Отправить]  [🔄 Заново]
[🔗 Открыть ↗]
```

### Commands

| Command | Description |
|---------|-------------|
| `/stats` | Daily summary: leads, A/B counts, applied, won |
| `/pipeline` | Active leads by status |
| `/today` | Earnings tracker vs 5k target |

---

## Workflow States

```
new → shortlisted → draft_ready → approved → applied → client_replied → won
                                                    ↓
                                              followup_due → ...
                                                    ↓
                                              lost / archived
```

States and transitions are configurable in `config/workflow.yaml`.

---

## Admin UI

Available at `/admin` after `fa run`.

- **Dashboard** — today's stats, earnings vs target, recent A-leads
- **Pipeline** — active leads by status
- **All Jobs** — full backlog with tier/source/status filters
- **Job Detail** — score breakdown, proposal draft, raw data
- **Send To Agent** — one-click webhook handoff with lead context + scoring + decision brief + agent prompt

---

## Architecture

```
fa run
├── FastAPI + uvicorn :8000    (API + admin UI)
├── arq worker                 (async task queue)
│   ├── ingest_source          every 3-5 min
│   ├── score_candidates       every 1 min
│   ├── notify_leads           every 1 min
│   ├── generate_proposal_task on-demand (from bot tap)
│   └── followup_check         every 30 min
└── aiogram bot                polling

Infrastructure:
├── PostgreSQL 16              (job storage)
└── Redis 7                    (arq queue)
```

---

## Extending

### Add a new source

```python
# collectors/my_source.py
from freelance_assitant.collectors.registry import CollectorRegistry
from freelance_assitant.collectors.base import BaseCollector

@CollectorRegistry.register("my_source")
class MyCollector(BaseCollector):
    source = SourcePlatform.MY_SOURCE
    poll_interval_seconds = 300

    async def collect(self) -> list[JobCandidateCreate]:
        ...
```

Then enable in `config/sources.yaml`. No other changes.

### Add a new scorer

```python
# scoring/my_scorer.py
class RecencyScorer(BaseScorer):
    name = "recency"
    async def evaluate(self, candidate, profile) -> float:
        ...
```

Register it in `ScoringEngine._build_default_scorers()` and add weight in `config/scoring.yaml`.

### Add a case snippet

Create `config/cases/my_case.yaml`:

```yaml
title: "My Case"
problem: "..."
solution: "..."
outcome: "..."
stack: [python, fastapi]
domain: [saas]
project_type: "интеграция"
proof_points:
  - "Did X for Y"
```

---

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Lint
ruff check src/

# One-shot ingestion (no Redis needed)
fa ingest

# Generate first Alembic migration
alembic revision --autogenerate -m "initial"
```

---

## Deployment

```bash
# On VPS (Debian/Ubuntu)
docker compose up -d
pip install -e .
fa migrate
fa run
```

Or with systemd — create `/etc/systemd/system/fa.service`:

```ini
[Unit]
Description=Freelance Assistant
After=network.target

[Service]
WorkingDirectory=/opt/freelance-assitant
EnvironmentFile=/opt/freelance-assitant/.env
ExecStart=/opt/freelance-assitant/.venv/bin/fa run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
