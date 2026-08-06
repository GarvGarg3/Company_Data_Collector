"""
Scraper for the Startup India directory (startupindia.gov.in) using their public search API.

This script fetches data directly from the Startup India search API, avoiding the overhead,
instability, and dependency requirements of browser automation (Selenium).

Usage:
    python scrapping/startup_india.py --pages 5
"""

import argparse
import csv
import os
from datetime import datetime, timezone
import requests

try:
    from scripts import db_helper
except ImportError:
    import db_helper

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
            
    print(f"Appended {len(startups)} startups to {filepath}")

def main():
    parser = argparse.ArgumentParser(description="Scrape the Startup India directory using API.")
    parser.add_argument("--pages", type=int, default=5, help="Number of pages to scrape (default: 5)")
    args = parser.parse_args()

    print(f"Initializing Startup India API Scraper (Fetching {args.pages} pages)...")
    startups_buffer = []
    
    for page in range(args.pages):
        print(f"Fetching page {page} of Startup India listings...")
        try:
            data = fetch_page(page)
            content = data.get("content", [])
            print(f"Retrieved {len(content)} startups from page {page}.")
            
            for item in content:
                name = item.get("name")
                if not name:
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
                
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
            
    if startups_buffer:
        # Write extracted startups to both locations
        save_to_csv(OUTPUT_CSV, startups_buffer)
        save_to_csv(ROOT_CSV, startups_buffer)
        
        # Directly insert/upsert into PostgreSQL database
        print("Upserting records directly to PostgreSQL database...")
        try:
            db_helper.upsert_companies(startups_buffer)
        except Exception as e:
            print(f"Error inserting into database: {e}")
            print("CSV files have been saved as backup.")
    else:
        print("No startups could be retrieved.")

if __name__ == "__main__":
    main()
