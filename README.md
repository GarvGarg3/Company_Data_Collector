# Company Data Collector

A dynamic, scalable ETL pipeline utilizing Apache Airflow and PostgreSQL to orchestrate and store sanitized data from multiple API endpoints and web scrapers.

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

## Key Features

1. **Dynamic DAG Architecture**: Automatically discovers and schedules tasks for any script placed in the `api_source/` or `scrapping/` folders without requiring code edits in the DAG.
2. **Ingestion-Time Normalization**: Strips corporate suffixes (`Inc`, `LLC`, `Ltd`, etc.), smart quotes, and punctuation before insertion to maintain consistent records.
3. **Array-Based Source Merging**: Resolves duplicate company records by updating values and dynamically appending new contributing sources into a PostgreSQL array (`Sources TEXT[]`), avoiding row duplication.
4. **Functional B-Tree Indexing**: Implements a functional database index on `LOWER(Company_name)` to guarantee millisecond execution times for case-insensitive checks even at millions of rows.
5. **Incremental Batch Ingestion**: Crawler for Startup India fetches pages in batches of 11 (~100 startups), checks existence against database using `= ANY(%s)`, and terminates early if historical duplicates are met or limit is satisfied.
6. **Polite Fetch Delay & 429 Resilience**: Product Hunt and CompaniesAPI loops respect rate limits (up to 2.0s delay) and catch `429 Too Many Requests` status codes to terminate loops gracefully with exit code `0` rather than causing task failures.
7. **Scaffolded Standard Logging**: All scripts use python `logging` format (`[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s`) and capture detailed traceback execution logs via `logger.exception()`.

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