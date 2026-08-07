"""
Scraper for https://500.co/portfolio -> Company_database schema
(S_No, Company_name, Website, Sector, Source, Active, No_of_employees)

This script pulls directly from the 500.co public API endpoint to avoid browser overhead and Playwright setup errors.

RUN:
    python scrapping/global500.py

OUTPUT:
    companies.csv         -> ready to import / INSERT into Company_database
"""

import csv
import os
import requests
import logging
from datetime import datetime, timezone

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

API_URL = "https://500.co/api/startups"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "companies.csv")
SOURCE_LABEL = "500 Global Portfolio (500.co/portfolio)"


def scrape():
    companies = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    logger.info(f"Fetching data from {API_URL}...")
    try:
        response = requests.get(API_URL, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.exception("Error fetching data from API")
        return []

    startups = data.get("res", [])
    logger.info(f"Found {len(startups)} startups in API response.")

    for item in startups:
        org = item.get("organization") or {}
        
        # Name: Prioritize name, fallback to businessName or alternativeName
        name = org.get("name") or org.get("businessName") or org.get("alternativeName")
        if not name:
            continue
        
        name = name.strip()
        
        # Website: Ensure valid absolute URL format
        website = org.get("companyUrl")
        if website:
            website = website.strip()
            # Remove any leading/trailing slashes or whitespace
            if website and not (website.startswith("http://") or website.startswith("https://")):
                website = "https://" + website
        else:
            website = None
            
        # Sector: Get all industry names and join them
        industries = item.get("industries") or []
        sector_names = [ind.get("name") for ind in industries if ind and ind.get("name")]
        sector = ", ".join(sector_names) if sector_names else None
        
        # Country: Get country of operation name
        country_info = org.get("countryOfOperation") or {}
        country = country_info.get("name") if isinstance(country_info, dict) else None
        if country:
            country = country.strip()
            
        companies.append({
            "Company_name": name,
            "Website": website,
            "Sector": sector,
            "Country": country,
            "Source": SOURCE_LABEL,
            "Active": True,
            "No_of_employees": None  # Public API response does not contain employee counts
        })
        
    return companies


def write_csv(companies):
    # Output to the same directory as the script
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "S_No", "Company_name", "Website", "Sector", "Country",
                "Source", "Updated_at", "Active", "No_of_employees",
            ],
        )
        writer.writeheader()
        now = datetime.now(timezone.utc).isoformat()
        for i, c in enumerate(companies, start=1):
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
    logger.info(f"Wrote {len(companies)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    data = scrape()
    if not data:
        logger.warning("No companies could be retrieved.")
    else:
        # Write to local CSV backup
        write_csv(data)
        # Directly insert/upsert into PostgreSQL database
        logger.info("Upserting records directly to PostgreSQL database...")
        try:
            db_helper.upsert_companies(data)
            logger.info("Successfully completed data loading.")
        except Exception:
            logger.exception("Failed to complete data loading.")