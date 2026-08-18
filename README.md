# Company Data Collector

A dockerized Airflow + PostgreSQL ETL pipeline that ingests company records from multiple APIs and directory scrapers, normalizes them at write time, and merges duplicates into a single row per company with an array of contributing sources.

Adding a new data source requires dropping a script into a folder — no DAG code changes.

**Current state:** «N» companies across «M» sources. Runs «daily / weekly» on Airflow 2.8.1.

---

## Sources

| Type | Source | Script |
| --- | --- | --- |
| API | CompaniesAPI | `scripts/api_source/` |
| API | Product Hunt | `scripts/api_source/` |
| Scraper | Y Combinator | `scripts/scrapping/` |
| Scraper | Techstars | `scripts/scrapping/` |
| Scraper | 500 Global | `scripts/scrapping/` |
| Scraper | Startup India | `scripts/scrapping/` |

---

## How it works

```
       scripts/api_source/*.py        scripts/scrapping/*.py
                │                              │
                └──────────┬───────────────────┘
                           ▼
        company_collector_dag.py  — scans both dirs at parse time,
                           │        registers one task per script
                           │        in parallel task groups
                           ▼
                     db_helper.py  — normalize → in-memory merge → upsert
                           ▼
                    PostgreSQL  (Company_database)
                    Sources TEXT[]  ·  idx on LOWER(Company_name)
```

### Dynamic DAG architecture

`dags/company_collector_dag.py` scans `scripts/api_source/` and `scripts/scrapping/` when the DAG is parsed and registers a task for every script it finds, grouped into two parallel task groups. New source = new file. No DAG edits, no re-registration.

### Ingestion-time normalization

Corporate suffixes (`Inc`, `LLC`, `Ltd`, …), smart quotes, and stray punctuation are stripped before insertion, so `Acme Inc.` from Product Hunt and `Acme` from Y Combinator resolve to the same key rather than two rows.

### Array-based source merging

A company found in three directories is one row, not three. On a duplicate hit the pipeline updates the existing values and appends the new source name to a PostgreSQL `TEXT[]` column (`Sources`), so provenance is preserved without row duplication.

### Functional b-tree indexing

Dedupe checks are case-insensitive, which would otherwise force a sequential scan. A functional index on `LOWER(Company_name)` keeps those lookups in the millisecond range as the table grows.

### Incremental batch ingestion

The Startup India crawler fetches pages in batches of 11 (~100 startups), checks the whole batch against the database in one query using `= ANY(%s)`, and terminates early once it hits historical duplicates or satisfies the run limit — so a re-run costs a couple of requests, not a full crawl.

### Rate-limit resilience

Product Hunt and CompaniesAPI loops apply a polite fetch delay (up to 2.0s) and catch HTTP 429 explicitly, exiting with code `0` and whatever was collected so far. A rate limit ends the task cleanly instead of marking the DAG run failed.

### Logging

All scripts use a shared `logging` format (`[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s`) and capture full tracebacks via `logger.exception()`, so a failed scrape is diagnosable from the Airflow task log alone.

---

## Project structure

```
dags/company_collector_dag.py   dynamic DAG — discovers and schedules scripts
docker/airflow/Dockerfile       custom Airflow image, pinned via constraints
docker-compose.yml              Postgres + Airflow, local multi-container setup
schema.sql                      Company_database table, TEXT/TEXT[] cols, functional index
requirements.txt                requests, psycopg2-binary, httpx, …
scripts/
  api_source/                   API-driven ingestion
  scrapping/                    directory scrapers
  db_helper.py                  normalization, in-memory merge, Postgres upsert
```

---

## Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Fill in database credentials, Airflow admin credentials, and any source API keys.

### 2. Start

```bash
docker compose up -d --build
```

Builds the custom Airflow image and brings up Postgres and Airflow in detached mode.

### 3. Access

- **Airflow UI** — <http://localhost:8080> (defaults to `admin`/`admin` unless changed in `.env`)
- **PostgreSQL** — port `5432` on the host, credentials from `.env`

### 4. Trigger a run for a past date

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger company_collector_dag -e YYYY-MM-DD
```

Use `-e` / `--exec-date`, not `--logical-date` — this is Airflow 2.8.1.

---

## Known limitations

- Deduplication is exact-match on the normalized name. `Acme Technologies` and `Acme Tech` stay separate rows; probabilistic matching is not implemented.
- Scrapers target current page structures and will break when those change. Failures are logged per-source and do not block the rest of the DAG.
- `scripts/scrapping/` is a misspelling of "scraping" retained for path stability.
