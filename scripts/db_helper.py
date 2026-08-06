import os
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values


def get_connection():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "postgres"),
        port=os.getenv("PG_PORT", "5432"),
        user=os.getenv("PG_USER", "airflow"),
        password=os.getenv("PG_PASSWORD", "airflow"),
        dbname=os.getenv("PG_DB", "airflow"),
    )


def upsert_companies(companies):
    if not companies:
        return

    companies = [
        c for c in companies
        if c.get("Company_name")
    ]

    if not companies:
        return

    query = """
    INSERT INTO Company_database (
        Company_name,
        Website,
        Sector,
        Country,
        Source,
        Active,
        No_of_employees,
        Updated_at
    )
    VALUES %s
    ON CONFLICT (Company_name, Source)
    DO UPDATE SET
        Website = COALESCE(EXCLUDED.Website, Company_database.Website),
        Sector = COALESCE(EXCLUDED.Sector, Company_database.Sector),
        Country = COALESCE(EXCLUDED.Country, Company_database.Country),
        Active = EXCLUDED.Active,
        No_of_employees = COALESCE(
            EXCLUDED.No_of_employees,
            Company_database.No_of_employees
        ),
        Updated_at = CURRENT_TIMESTAMP;
    """

    rows = [
        (
            c["Company_name"].strip(),
            c.get("Website"),
            c.get("Sector"),
            c.get("Country"),
            c["Source"],
            c.get("Active", True),
            c.get("No_of_employees"),
            c.get("Updated_at", datetime.now()),
        )
        for c in companies
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, query, rows)

    print(f"Upserted {len(rows)} companies.")