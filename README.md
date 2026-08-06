# Company_Data_Collector

A pipeline utilizing Apache Airflow and PostgreSQL to orchestrate and store data from web scrapers.

## Project Structure

- `docker/airflow/Dockerfile`: Custom Airflow Dockerfile equipped with Selenium headless capabilities (Chromium & ChromeDriver installed).
- `docker-compose.yml`: Docker orchestration config configuring a PostgreSQL database and Airflow services (Init, Webserver, Scheduler).
- `schema.sql`: Database schema that initializes the target `Company_database` table.
- `requirements.txt`: Python dependencies required for execution (Requests, HTTPX, Selenium, etc.).
- `scrapping/`: Directory containing scrapers (`yc_scraper.py`, `startup_india.py`, etc.).
- `dags/`: Mount point for Airflow DAGs.
- `logs/` & `plugins/`: Mount points for Airflow logs and custom plugins.

## Prerequisites

- Docker and Docker Compose installed.

## Setup & Running

1. **Verify Environment Variables**:
   Check the `.env` file at the root to ensure your Postgres and Airflow credentials are correct.

2. **Start the Environment**:
   Run the following command to build the custom Airflow image and start the database and Airflow services in detached mode:
   ```bash
   docker compose up -d --build
   ```

3. **Accessing the Services**:
   - **Airflow Web UI**: Open [http://localhost:8080](http://localhost:8080) and log in using the credentials defined in `.env` (default is admin/admin).
   - **PostgreSQL Database**: Port `5432` is exposed on the host machine. You can connect using any PostgreSQL client with the credentials in `.env`.