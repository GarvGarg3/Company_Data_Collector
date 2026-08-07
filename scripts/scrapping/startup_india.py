"""
Scraper for the Startup India directory (startupindia.gov.in) using their public search API.

This script fetches data directly from the Startup India search API, avoiding the overhead,
instability, and dependency requirements of browser automation (Selenium).

Usage:
    python scrapping/startup_india.py --pages 5
"""

import sys
import argparse
import csv
import os
import time
import logging
from datetime import datetime, timezone
import requests

# Add scripts directory to sys.path to allow execution from any Cwd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    from scripts import db_helper
except ImportError:
    import db_helper

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Resolve file paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "startup_india_companies.csv")
ROOT_CSV = os.path.join(os.path.dirname(SCRIPT_DIR), "startup_india_companies.csv")

SOURCE_LABEL = "Startup India Portal"
API_URL = "https://api.startupindia.gov.in/sih/api/noauth/search/profiles"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def fetch_page(page_num):
    """Fetch a single page of startup profiles from the API."""
    payload = {
        "query": "",
        "focusSector": False,
        "industries": [],
        "sectors": [],
        "states": [],
        "cities": [],
        "stages": [],
        "badges": [],
        "internationalUser": False,
        "page": page_num,
        "roles": ["Startup"],
        "sort": {
            "orders": [
                {
                    "field": "registeredOn",
                    "direction": "DESC"
                }
            ]
        }
    }
    
    response = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()

def save_to_csv(filepath, startups):
    """Save the list of startups to the target CSV in append mode."""
    if not startups:
        return
        
    file_exists = os.path.exists(filepath)
    
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "S_No", "Company_name", "Website", "Sector", "Country",
                "Source", "Updated_at", "Active", "No_of_employees"
            ]
        )
        
        if not file_exists or os.path.getsize(filepath) == 0:
            writer.writeheader()
            start_no = 1
        else:
            start_no = 1
            try:
                with open(filepath, "r", encoding="utf-8") as rf:
                    reader = list(csv.reader(rf))
                    if len(reader) > 1:
                        last_row = reader[-1]
                        if last_row and last_row[0].isdigit():
                            start_no = int(last_row[0]) + 1
            except Exception:
                pass
                
        now = datetime.now(timezone.utc).isoformat()
        for i, s in enumerate(startups, start=start_no):
            writer.writerow({
                "S_No": i,
                "Company_name": s["Company_name"],
                "Website": s["Website"],
                "Sector": s["Sector"],
                "Country": s["Country"],
                "Source": s["Source"],
                "Updated_at": now,
                "Active": s["Active"],
                "No_of_employees": s["No_of_employees"]
            })
            
    logger.info(f"Appended {len(startups)} startups to {filepath}")

def check_existing_companies(names):
    """Query database selectively to check which names in the batch already exist."""
    if not names:
        return set()
    cleaned_names = [db_helper.clean_display_name(n).strip() for n in names if n]
    cleaned_names = [n for n in cleaned_names if n]
    if not cleaned_names:
        return set()
        
    query = "SELECT Company_name FROM Company_database WHERE LOWER(Company_name) = ANY(%s);"
    try:
        with db_helper.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (list(n.lower() for n in cleaned_names),))
                return {row[0].lower().strip() for row in cur.fetchall()}
    except Exception:
        logger.exception("Failed to check existing companies in database")
        return set()


def main():
    parser = argparse.ArgumentParser(description="Scrape the Startup India directory using API.")
    parser.add_argument("--limit", type=int, default=1000, help="Target number of new startups to scrape (default: 1000)")
    args = parser.parse_args()

    logger.info(f"Initializing Startup India API Scraper (Searching for at least {args.limit} new companies)...")
    
    startups_buffer = []
    new_companies_found = 0
    page = 0
    max_pages = 10000
    batch_size_pages = 11  # Process 11 pages (99 startups) at a time to check close to 100 at a time
    
    while new_companies_found < args.limit and page < max_pages:
        logger.info(f"Fetching batch of pages {page} to {page + batch_size_pages - 1}...")
        batch_startups = []
        
        # 1. Fetch page batch
        for p in range(page, page + batch_size_pages):
            try:
                data = fetch_page(p)
                content = data.get("content", [])
                if not content:
                    logger.info(f"No more startups returned by API at page {p}.")
                    break
                
                logger.info(f"Page {p}: Retrieved {len(content)} startups.")
                for item in content:
                    name = item.get("name")
                    if not name:
                        continue
                    batch_startups.append((name, item))
                
                time.sleep(0.1)  # Rate limit politeness
            except Exception:
                logger.exception(f"Error fetching page {p}")
                break
                
        if not batch_startups:
            logger.info("No startups retrieved in this batch. Exiting loop.")
            break
            
        # 2. Query Postgres selectively for this batch of names
        batch_names = [item[0] for item in batch_startups]
        existing_in_db = check_existing_companies(batch_names)
        
        # 3. Filter out duplicates
        page_new_count = 0
        for name, item in batch_startups:
            name_clean = db_helper.clean_display_name(name).strip()
            if not name_clean:
                continue
                
            if name_clean.lower() in existing_in_db:
                continue
                
            # Construct profile URL
            profile_id = item.get("id")
            profile_url = f"https://www.startupindia.gov.in/content/sih/en/profile.Startup.{profile_id}.html"
            
            # Join sectors and industries
            sectors = item.get("sectors") or []
            industries = item.get("industries") or []
            all_sectors = list(set(sectors + industries))
            sector_desc = ", ".join(all_sectors) if all_sectors else "Tech / Services"
            
            startups_buffer.append({
                "Company_name": name.strip(),
                "Website": profile_url,
                "Sector": sector_desc,
                "Country": "INDIA",
                "Source": SOURCE_LABEL,
                "Active": True,
                "No_of_employees": None
            })
            
            page_new_count += 1
            new_companies_found += 1
            
            # Add to local set to prevent duplicate names inside the same batch
            existing_in_db.add(name_clean.lower())
            
            if new_companies_found >= args.limit:
                break
                
        logger.info(f"Batch processed: found {page_new_count} new startups (total new found: {new_companies_found}/{args.limit}).")
        
        # If an entire batch of 99 startups returns 0 new entries, we have hit history
        if page_new_count == 0:
            logger.info("Found 0 new startups in this batch of 99. Assuming previously ingested history reached. Stopping.")
            break
            
        page += batch_size_pages

    if startups_buffer:
        # Write extracted startups to both locations
        save_to_csv(OUTPUT_CSV, startups_buffer)
        save_to_csv(ROOT_CSV, startups_buffer)
        
        # Directly insert/upsert into PostgreSQL database
        logger.info("Upserting records directly to PostgreSQL database...")
        try:
            db_helper.upsert_companies(startups_buffer)
            logger.info("Successfully completed data loading.")
        except Exception:
            logger.exception("Failed to insert into database")
    else:
        logger.warning("No new startups could be retrieved.")


if __name__ == "__main__":
    main()
