import os
import re
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


def clean_display_name(name):
    if not name:
        return ""
    name_str = str(name).strip()
    # Strip leading/trailing quotes, periods, and commas first
    name_str = name_str.strip('.,\'"®™“”‘’')
    # Remove commas, periods, quotes, registered, trademark, and smart quotes
    cleaned = re.sub(r'[.,\'"®™“”‘’]', '', name_str)
    # Remove common corporate suffixes (case-insensitive, whole word boundaries)
    suffixes = r'\b(inc|llc|ltd|corp|corporation|co|gmbh|sa|pvt|plc|incorporated|limited)\b'
    cleaned = re.sub(suffixes, '', cleaned, flags=re.IGNORECASE)
    # Remove extra spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else name_str


def upsert_companies(companies):
    if not companies:
        return

    # Clean and filter company names at ingestion time
    cleaned_companies = []
    for c in companies:
        orig_name = c.get("Company_name")
        if not orig_name:
            continue
        cleaned_name = clean_display_name(orig_name)
        if not cleaned_name:
            continue
        c_copy = c.copy()
        c_copy["Company_name"] = cleaned_name
        cleaned_companies.append(c_copy)

    if not cleaned_companies:
        return

    query = """
    INSERT INTO Company_database (
        Company_name,
        Website,
        Sector,
        Country,
        Sources,
        Active,
        No_of_employees,
        Updated_at
    )
    VALUES %s
    ON CONFLICT (Company_name)
    DO UPDATE SET
        Website = COALESCE(EXCLUDED.Website, Company_database.Website),
        Sector = COALESCE(EXCLUDED.Sector, Company_database.Sector),
        Country = COALESCE(EXCLUDED.Country, Company_database.Country),
        Sources = ARRAY(
            SELECT DISTINCT e 
            FROM unnest(Company_database.Sources || EXCLUDED.Sources) AS e
        ),
        Active = EXCLUDED.Active,
        No_of_employees = COALESCE(
            EXCLUDED.No_of_employees,
            Company_database.No_of_employees
        ),
        Updated_at = CURRENT_TIMESTAMP;
    """

    rows = []
    for c in cleaned_companies:
        source_val = c.get("Source")
        sources_val = c.get("Sources")
        
        # Determine initial sources list
        if sources_val and isinstance(sources_val, list):
            src_list = [str(s).strip() for s in sources_val if s]
        elif source_val:
            src_list = [str(source_val).strip()]
        else:
            src_list = []
            
        rows.append((
            c["Company_name"],
            c.get("Website"),
            c.get("Sector"),
            c.get("Country"),
            src_list,
            c.get("Active", True),
            c.get("No_of_employees"),
            c.get("Updated_at", datetime.now()),
        ))

    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, query, rows)

    print(f"Upserted {len(rows)} normalized companies.")