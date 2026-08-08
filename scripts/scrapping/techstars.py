"""
Scraper for the FULL Techstars portfolio (5,000+ companies) via their
Typesense search API -- no Playwright/Selenium needed.

Usage:
    python techstars.py
    python techstars.py --year-min 2021 --region Europe --limit 500
"""

import argparse
import csv
import os
import time
import requests
import logging
from datetime import datetime, timezone

try:
    from scripts import db_helper, company_filter
except ImportError:
    try:
        from scrapping import db_helper, company_filter
    except ImportError:
        import db_helper
        import company_filter

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TYPESENSE_HOST = "https://8gbms7c94riane0lp-1.a1.typesense.net"
API_KEY = "yPf0UzHocD8TcYlb7KqJFJuRO1OoCRn2"
COLLECTION = "companies"
PER_PAGE = 250          # Typesense max page size
REQUEST_DELAY = 0.3     # be polite, avoid hammering their cluster

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "techstarts_companies.csv")
ROOT_CSV = os.path.join(os.path.dirname(SCRIPT_DIR), "techstarts_companies.csv")

SOURCE_LABEL = "Techstars Portfolio (techstars.com/portfolio)"

QUERY_BY_FIELDS = (
    "company_name,brief_description,city,state_province,country,"
    "worldregion,program_names,industry_vertical"
)
FACET_BY_FIELDS = "first_session_year,industry_vertical,program_names,worldregion"

HEADERS = {"Content-Type": "application/json"}


def build_filter_by(args) -> str:
    """Translate CLI options into a Typesense `filter_by` expression."""
    clauses = []
    if args.year_min is not None:
        clauses.append(f"first_session_year:>={args.year_min}")
    if args.year_max is not None:
        clauses.append(f"first_session_year:<={args.year_max}")
    for field, values in (
        ("worldregion", args.region),
        ("industry_vertical", args.vertical),
        ("program_names", args.program),
        ("country", args.country),
    ):
        if values:
            joined = ",".join(f"`{v}`" for v in values)
            clauses.append(f"{field}:=[{joined}]")
    return " && ".join(clauses)


def search(page: int, per_page: int = PER_PAGE, filter_by: str = "") -> dict:
    """Fire a single multi_search request and return the parsed JSON."""
    url = f"{TYPESENSE_HOST}/multi_search?x-typesense-api-key={API_KEY}"
    search_params = {
        "collection": COLLECTION,
        "q": "*",
        "query_by": QUERY_BY_FIELDS,
        "facet_by": FACET_BY_FIELDS,
        "max_facet_values": 200,
        "sort_by": "website_order:asc",
        "page": page,
        "per_page": per_page,
    }
    if filter_by:
        search_params["filter_by"] = filter_by
    payload = {"searches": [search_params]}
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def save_to_csv(filepath, deduped_companies):
    # Check if the output CSV already exists
    file_exists = os.path.exists(filepath)
    
    # Write to CSV in append mode ("a"), writing the header only if the file doesn't exist
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "S_No", "Company_name", "Website", "Sector", "Country",
                "Source", "Updated_at", "Active", "No_of_employees",
            ],
        )
        if not file_exists or os.path.getsize(filepath) == 0:
            writer.writeheader()
            start_no = 1
        else:
            # If the file already exists and has data, let's find the last S_No
            # so we can increment from there.
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
        for i, c in enumerate(deduped_companies, start=start_no):
            writer.writerow({
                "S_No": i,
                "Company_name": c["Company_name"],
                "Website": c["Website"],
                "Sector": c["Sector"],
                "Country": c["Country"],
                "Source": c["Source"],
                "Updated_at": now,
                "Active": c["Active"],
                "No_of_employees": c["No_of_employees"],
            })
    logger.info(f"Done. Wrote/Appended {len(deduped_companies)} companies to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Scrape the Techstars portfolio directory.")
    parser.add_argument("--limit", type=int, help="stop after N companies")
    parser.add_argument("--year-min", type=int, help="only companies whose first Techstars session was in or after this year")
    parser.add_argument("--year-max", type=int, help="only companies whose first Techstars session was in or before this year")
    parser.add_argument("--region", action="append", default=[], help="filter by world region, e.g. 'Europe' (repeatable)")
    parser.add_argument("--vertical", action="append", default=[], help="filter by industry vertical (repeatable)")
    parser.add_argument("--program", action="append", default=[], help="filter by program name (repeatable)")
    parser.add_argument("--country", action="append", default=[], help="filter by country (repeatable)")
    args = parser.parse_args()

    filter_by = build_filter_by(args)
    if filter_by:
        logger.info(f"Applying Typesense filter: {filter_by}")

    logger.info("Fetching page 1 to find total company count...")
    try:
        first = search(page=1, per_page=PER_PAGE, filter_by=filter_by)
        result = first["results"][0]
        total_found = result["found"]
    except Exception:
        logger.exception("Error fetching data from Typesense API")
        return

    logger.info(f"Total companies matching query: {total_found}")

    all_hits = list(result["hits"])
    target = min(total_found, args.limit) if args.limit else total_found
    total_pages = (target + PER_PAGE - 1) // PER_PAGE
    logger.info(f"Fetching remaining pages (per_page={PER_PAGE}, {total_pages} pages total)...")

    for page in range(2, total_pages + 1):
        if args.limit and len(all_hits) >= args.limit:
            break
        time.sleep(REQUEST_DELAY)
        try:
            data = search(page=page, per_page=PER_PAGE, filter_by=filter_by)
            hits = data["results"][0]["hits"]
            all_hits.extend(hits)
            logger.info(f"  page {page}/{total_pages} -> {len(hits)} hits (running total: {len(all_hits)})")
        except Exception:
            logger.exception(f"Error fetching page {page}")
            break

    if args.limit:
        all_hits = all_hits[:args.limit]

    # Format the data to match the database schema
    companies = []
    for hit in all_hits:
        doc = hit.get("document") or {}
        
        name = doc.get("company_name")
        if not name:
            continue
        name = name.strip()
        
        website = doc.get("website")
        if website:
            website = website.strip()
            if not (website.startswith("http://") or website.startswith("https://")):
                website = "https://" + website
        else:
            website = None
            
        # Sector: industry_vertical can be a list or a string
        industry_val = doc.get("industry_vertical")
        if isinstance(industry_val, list):
            sector = ", ".join(industry_val)
        elif isinstance(industry_val, str):
            sector = industry_val.strip()
        else:
            sector = None
            
        country = doc.get("country")
        if country:
            country = country.strip()
            
        companies.append({
            "Company_name": name,
            "Website": website,
            "Sector": sector,
            "Country": country,
            "Source": SOURCE_LABEL,
            "Active": True,
            "No_of_employees": None
        })

    # Deduplicate companies by name (case-insensitive) just to be clean
    seen = set()
    deduped_companies = []
    for c in companies:
        name_lower = c["Company_name"].lower()
        if name_lower not in seen:
            seen.add(name_lower)
            deduped_companies.append(c)

    # Drop shell/non-venture records before they reach the CSV or the database
    deduped_companies = company_filter.filter_companies(deduped_companies, SOURCE_LABEL)

    # Save to both target locations
    save_to_csv(OUTPUT_CSV, deduped_companies)
    save_to_csv(ROOT_CSV, deduped_companies)
    
    # Directly insert/upsert into PostgreSQL database
    logger.info("Upserting records directly to PostgreSQL database...")
    try:
        db_helper.upsert_companies(deduped_companies)
        logger.info("Successfully completed data loading.")
    except Exception:
        logger.exception("Failed to load data into database")

if __name__ == "__main__":
    main()