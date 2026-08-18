# Company Data Collector

A dynamic, scalable ETL pipeline utilizing Apache Airflow and PostgreSQL to orchestrate and store sanitized data from multiple API endpoints and web scrapers, published as a searchable directory with on-demand company research.

> Using the published directory rather than working on the pipeline? See **[docs/USING.md](docs/USING.md)**.

## Project Structure

- `dags/company_collector_dag.py`: Dynamic Airflow DAG that scans directories to register API sources and scrapers in parallel task groups.
- `docker/airflow/Dockerfile`: Custom Airflow image optimized with python constraints.
- `docker-compose.yml`: Local multi-container orchestration for PostgreSQL and Apache Airflow.
- `schema.sql`: Database schema initializing the `Company_database` table with `TEXT`/`TEXT[]` types and functional b-tree indexes.
- `requirements.txt`: Python package requirements (requests, psycopg2-binary, httpx, etc.).
- `scripts/`: Contains data collection scripts.
  - `api_source/`: Scripts for API-driven ingestion (CompaniesAPI, Product Hunt).
  - `scrapping/`: Scripts for directory scrapers (Y Combinator, Techstars, 500 Global, Startup India).
  - `db_helper.py`: Centralized DB management script managing normalization, in-memory merging, and Postgres upsert operations.
  - `company_filter.py`: Shared relevance rules that drop shell entities and non-venture businesses at ingestion time.
  - `prune_companies.py`: Applies the same rules to rows already stored, reporting by default.
  - `normalize_countries.py`: Backfills stored country spellings through the same normalizer used at ingestion.
  - `build_site.py`: Bakes the whole table into one self-contained HTML page, plus the id index the enrichment endpoint validates against.
- `site/`: The published directory page. `templates/head.html` and `templates/tail.html` are the source; `index.html` is generated and gitignored.
- `web/`: FastAPI app serving the same directory live from Postgres, for when a snapshot isn't fresh enough.
- `netlify/`: The on-demand enrichment endpoint (see [On-demand enrichment](#on-demand-enrichment)).
  - `functions/company.mts`: `GET /api/company/:id` — cache, spend guards, HTTP surface.
  - `lib/`: The provider seam — shared schema and prompt, plus one module per backend.
- `netlify.toml`: Publish directory, functions config, and the files bundled with them.

## Key Features

1. **Dynamic DAG Architecture**: Automatically discovers and schedules tasks for any script placed in the `api_source/` or `scrapping/` folders without requiring code edits in the DAG.
2. **Ingestion-Time Normalization**: Strips corporate suffixes (`Inc`, `LLC`, `Ltd`, etc.), smart quotes, and punctuation from company names, and collapses country spellings to one canonical form (`USA`, `UNITED STATES`, `United States` → `United States`) so filters never split a country across rows.
3. **Array-Based Source Merging**: Resolves duplicate company records by updating values and dynamically appending new contributing sources into a PostgreSQL array (`Sources TEXT[]`), avoiding row duplication.
4. **Functional B-Tree Indexing**: Implements a functional database index on `LOWER(Company_name)` to guarantee millisecond execution times for case-insensitive checks even at millions of rows.
5. **Incremental Batch Ingestion**: Crawler for Startup India fetches pages in batches of 11 (~100 startups), checks existence against database using `= ANY(%s)`, and terminates early if historical duplicates are met or limit is satisfied.
6. **Polite Fetch Delay & 429 Resilience**: Product Hunt and CompaniesAPI loops respect rate limits (up to 2.0s delay) and catch `429 Too Many Requests` status codes to terminate loops gracefully with exit code `0` rather than causing task failures.
7. **Scaffolded Standard Logging**: All scripts use python `logging` format (`[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s`) and capture detailed traceback execution logs via `logger.exception()`.

## Normalization

`db_helper.clean_country()` runs on every record at ingestion, so one country never splits across spellings. It handles casing, aliases (`USA`/`US`/`U.S.A.` → `United States`, `UK`/`England` → `United Kingdom`, `UAE`, `Holland`, `Czech Republic` → `Czechia`), and keeps connectors lowercase (`Trinidad and Tobago`, `Guinea-Bissau`, `Côte d'Ivoire`).

Rows written before this existed are fixed with the same function:
```bash
python scripts/normalize_countries.py           # print the UPDATE statements, change nothing
python scripts/normalize_countries.py --apply   # execute them
```

**Sector is not yet normalized.** `FinTech` and `Fintech` remain distinct values, as do `AI/Machine Learning` and `Artificial intelligence and machine learning` — each source ships its own taxonomy, so collapsing them needs a mapping table rather than a case fix. Use `ILIKE` when querying by sector until that exists.

## Filtering

### Relevance filter (all sources)
`scripts/company_filter.py` runs inside `db_helper.upsert_companies()`, so every source is filtered in one place. It drops:

- **Shell / paper entities** by name: `Holdings`, `SPV`, `Nidhi`, `Chit Fund`, `Asset Management`, `& Sons`, `HUF`, …
- **Financial and trading vehicles** by name: `Capital`, `Investments`, `Partners`, `Realty`, `Builders`, `Enterprises`, `Traders`, … — kept when the sector reads as tech, so *Blue Ridge Partners (SaaS)* survives while *Agarwal Capital (Investments)* does not.
- **Non-venture sectors**: restaurants, hotels, salons, agriculture, construction, real estate, mining, textiles, retail, law/accounting, staffing, consultancy, coaching, event management, and similar. A `TECH_OVERRIDE` list runs first, so `agritech`, `foodtech`, `proptech`, and `constructiontech` are never caught by their parent word.
- **Junk records**: placeholder names (`N/A`, `test`, `demo`), names with no alphabetic content, and rows with neither a website nor a sector.

Records from investor-curated portfolios (Y Combinator, Techstars, 500 Global) skip the sector and soft-name rules — a fund has already vetted them, so *Darb Technology Holding (PropTech)* is a target rather than a holding vehicle. Only junk names and paper entities (`SPV`, `Nidhi`, …) are removed from those sources. Open directories are filtered in full.

Every run logs the count and reason for what was removed. Set `COMPANY_FILTER_DISABLED=1` to ingest unfiltered.

To clean rows collected before the filter existed:
```bash
python scripts/prune_companies.py                      # report only (default)
python scripts/prune_companies.py --action deactivate  # set Active = FALSE
python scripts/prune_companies.py --action delete      # remove the rows
```

### Per-source filters

| Script | Options |
|---|---|
| `companies_api_source.py` | `--limit`; industry include/exclude keyword lists in the source |
| `product_hunt_source.py` | `--limit` |
| `startup_india.py` | `--limit`, `--query`, `--stage` (API-side); `--state`, `--city`, `--industry`, `--sector` (applied to returned records — the portal's facets require internal ids) |
| `techstars.py` | `--limit`, `--year-min`, `--year-max`, `--region`, `--vertical`, `--program`, `--country` (all pushed into a Typesense `filter_by`) |
| `yc_scraper.py` | `--batch`, `--limit`, `--delay`, `-o` |
| `global500.py` | none — full portfolio dump |

Repeatable options accept multiple values:
```bash
python scripts/scrapping/techstars.py --year-min 2022 --region Europe --limit 300
python scripts/scrapping/startup_india.py --state Karnataka --industry "IT Services" --stage Scaling --limit 500
```

### Querying the collected data
Since sources merge into a single table, most slicing is a SQL query:
```sql
-- companies confirmed by more than one source
SELECT * FROM Company_database WHERE array_length(Sources, 1) > 1;

-- venture-shaped leads in a sector and size band
SELECT Company_name, Website, Sector, Country
FROM Company_database
WHERE Sector ILIKE '%fintech%'
  AND No_of_employees BETWEEN 10 AND 200
  AND Active
  AND Updated_at > NOW() - INTERVAL '30 days';
```

## Publishing the directory

There are two front-ends over the same table. They answer different questions, and neither replaces the other.

| | `scripts/build_site.py` | `web/app.py` |
|---|---|---|
| What it is | One self-contained HTML file, data embedded | FastAPI app querying Postgres per request |
| Freshness | A snapshot, frozen at build time | Live — a scraper run shows up on refresh |
| Needs | Nothing. Open the file, email it, drop it on any static host | An always-on process and a reachable database |
| Hosted at | Netlify | Not deployed |

Build the snapshot:

```bash
python3 scripts/build_site.py                       # site/index.html + data/companies.json
python3 scripts/build_site.py --brand "Acme Ventures" --output /tmp/acme.html
```

Both outputs are gitignored, so **the machine that builds is the machine that deploys**. `data/companies.json` is the id → name/website map bundled with the enrichment function; it is never served to browsers.

Run the live view instead:

```bash
docker compose up -d postgres web    # http://localhost:8000
```

## On-demand enrichment

The published page ships name, sector, country, and source for every company. Headcount, founding year, funding stage, and a description are looked up **the first time somebody opens a row**, then cached. Enriching all ~23k companies up front would cost hundreds of dollars for data nobody reads; enriching the few hundred anyone actually clicks costs a fraction of that, and every later view is free and instant.

```
click row → GET /api/company/:id
              ├─ cache hit  → JSON immediately (~200ms, no spend)
              └─ cache miss → search + extract → cache → JSON (~10-15s)
```

Records are stored in Netlify Blobs and re-looked-up after `ENRICH_TTL_DAYS` (headcounts age badly). Negative results are cached too — dead startups are exactly what people click out of curiosity, and re-paying for "still gone" is the easiest way to burn the daily budget on nothing.

### Guards

The endpoint is public and spends money per cache miss. Four things bound the worst case; read `netlify/functions/company.mts` before loosening any of them.

1. **Bounded input.** Only integer ids present in `data/companies.json` are accepted — no free-text queries, so the set of possible paid lookups is finite and known.
2. **Daily ceiling** (`ENRICH_DAILY_MISS_CAP`). The real backstop. Past it, cached rows still serve and misses return `unavailable`.
3. **Per-IP throttle** (`ENRICH_IP_PER_MIN`). Cache hits are unmetered.
4. **Default function concurrency**, so a burst can't fan out into hundreds of parallel model calls.

Counting is approximate rather than exact: `claimSlot()` prefers a compare-and-swap, but falls back to a plain write when the store refuses the conditional (see the note in that function). Drift is bounded by concurrency.

### Providers

`netlify/lib/` holds a provider seam so the backend is a config change, not a rewrite. Both share one JSON schema and one set of field rules, so switching backends can't silently change what lands in the cache.

| | Anthropic | Groq |
|---|---|---|
| Calls | One — `web_search` and schema-validated output in the same request | Two — `compound-mini` searches, `gpt-oss-120b` extracts under strict decoding |
| Why | Server-side search means no separate retrieval step | Compound can't do structured output; the strict models can't search |
| Cost | Paid | Free tier (expect occasional 429s and retries) |

Selection is `ENRICH_PROVIDER`. Leave it unset and whichever key is present wins, Anthropic first — but pin it explicitly, because SDKs resolve credentials from more places than the environment variable.

### Configuration

Only one variable is required. Everything else has a working default.

| Variable | Default | |
|---|---|---|
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | — | **One is required** |
| `ENRICH_PROVIDER` | key presence | `groq` or `anthropic` — pin it |
| `ENRICH_DAILY_MISS_CAP` | `200` | Paid lookups per day |
| `ENRICH_IP_PER_MIN` | `5` | Misses per IP per minute |
| `ENRICH_TTL_DAYS` | `90` | Before a cached record is refreshed |
| `ENRICH_MODEL` | `claude-opus-5` | Anthropic only |
| `ENRICH_MAX_SEARCHES` | `4` | Anthropic only |
| `GROQ_SEARCH_MODEL` | `groq/compound-mini` | |
| `GROQ_EXTRACT_MODEL` | `openai/gpt-oss-120b` | Must support strict structured outputs |

None of the `PG_*`, `AIRFLOW_*`, or scraper keys go to Netlify — it runs the endpoint and nothing else.

### Running and deploying it

```bash
npm install
netlify env:set GROQ_API_KEY gsk_...     # production; `.env` covers local only
netlify dev                              # site + function on :8888
netlify deploy --prod
```

Two behaviours worth knowing before you change the code:

- **Never return 404 from the function.** Netlify reads it as "this handler declined" and re-dispatches to the static handler, which re-enters the same route as `<id>.html` and answers with a misleading `bad id`. Unknown ids return 400 on purpose.
- **A `pause_turn` must be resumed.** A search loop that hits its iteration cap otherwise returns a truncated answer with no error, and that gets cached as fact.

## Local development notes

The pipeline normally runs inside Docker, where compose injects the environment. Running the Python scripts **from the host** needs three fixes that aren't obvious:

```bash
python3 -m venv .venv                    # `python` does not exist on macOS; use python3
.venv/bin/pip install -r requirements.txt
```

- `PG_HOST` in `.env` is `postgres`, the compose service name. From the host it must be `localhost`.
- **Nothing loads `.env` into Python.** `db_helper` falls back to its default password and connects to the wrong place, or fails with a confusing auth error. Export the variables, or run the script inside the container.
- `set -a; source .env` currently fails in zsh: some lines are written `KEY = value` with spaces around `=`.

## Setup & Running

### 1. Verify Environment Variables
Create a `.env` file at the root by copying `.env.example` and filling in your credentials:
```bash
cp .env.example .env
```

### 2. Start the Environment
Run the following command to build the custom Airflow image and start the database and Airflow services in detached mode:
```bash
docker compose up -d --build
```

### 3. Accessing the Services
- **Airflow Web UI**: Open [http://localhost:8080](http://localhost:8080) and log in using the credentials defined in `.env` (default is admin/admin).
- **PostgreSQL Database**: Port `5432` is exposed on the host machine. You can connect using any PostgreSQL client with the credentials in `.env`.

### 4. Running the DAG for Past Dates
To trigger a DAG run manually for a specific date (e.g. for testing historical weeks), run the following CLI command:
```bash
docker compose exec airflow-scheduler airflow dags trigger company_collector_dag -e YYYY-MM-DD
```
*(Note: Use `-e` or `--exec-date` rather than `--logical-date` to match the Airflow 2.8.1 version requirements).*