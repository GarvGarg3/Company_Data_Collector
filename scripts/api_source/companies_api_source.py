import os
import sys
import time
import requests
import logging

# Add the scripts directory to sys.path to allow importing db_helper later
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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


def load_env(env_path=".env"):
    """Simple helper to load key-value pairs from .env file."""
    env_vars = {}
    paths_to_check = [
        env_path,
        os.path.join("..", env_path),
        os.path.join("..", "..", env_path),
        os.path.join(os.path.dirname(__file__), "..", "..", env_path)
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        if "#" in val:
                            val = val.split("#", 1)[0]
                        env_vars[key.strip()] = val.strip()
            break
    return env_vars

def fetch_companies_api_data(api_key, target_count=200):
    url = "https://api.thecompaniesapi.com/v2/companies"
    companies = []
    page = 1
    
    # Filter keywords
    include_keywords = [
        "tech", "software", "internet", "biotech", "financial", "banking", 
        "health", "pharma", "robotics", "semiconductor", "it-services", 
        "computer", "telecommunications", "data"
    ]
    exclude_keywords = [
        "food", "beverage", "restaurant", "brewery", "breweries", "cafe", 
        "catering", "kitchen", "pub", "bar", "hotel", "bistro", "diner", 
        "grill", "eatery", "pizzeria", "bakery", "agriculture", "construction"
    ]
    
    logger.info(f"Starting fetch from CompaniesAPI for {target_count} companies...")
    
    while len(companies) < target_count:
        params = {
            "token": api_key,
            "simplified": "true",
            "page": page,
            "size": 100
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 429:
                logger.warning("Rate limit (429) hit. Stopping fetch gracefully.")
                break
            response.raise_for_status()
            data = response.json()
            items = data.get("companies", [])
            
            if not items:
                logger.info("No more companies returned by API.")
                break
                
            for item in items:
                about = item.get("about", {})
                name = about.get("name")
                if not name:
                    continue
                    
                industry = about.get("industry", "")
                ind_lower = industry.lower()
                
                # Check inclusion criteria
                is_tech = any(kw in ind_lower for kw in include_keywords)
                # Check exclusion criteria
                is_excluded = any(kw in ind_lower for kw in exclude_keywords)
                
                if is_tech and not is_excluded:
                    domain = item.get("domain", {}).get("domain")
                    website = f"https://{domain}" if domain else None
                    
                    companies.append({
                        "Company_name": name,
                        "Website": website,
                        "Sector": industry.replace("-", " ").title(),
                        "Country": None,
                        "Source": "CompaniesAPI",
                        "Active": True,
                        "No_of_employees": None
                    })
                    
                    if len(companies) >= target_count:
                        break
            
            logger.info(f"Page {page}: Accumulated {len(companies)} matching companies...")
            page += 1
            # Rate limit politeness
            time.sleep(1.0)
            
        except Exception:
            logger.exception(f"Error fetching page {page}")
            break
            
    logger.info(f"Fetched {len(companies)} companies total.")
    return companies[:target_count]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch companies from CompaniesAPI.")
    parser.add_argument("--limit", type=int, default=2000, help="Limit number of companies to fetch (default: 2000)")
    args = parser.parse_args()

    env_vars = load_env()
    api_key = env_vars.get("COMPANIESAPI_KEY") or os.getenv("COMPANIESAPI_KEY")
    if not api_key:
        logger.error("COMPANIESAPI_KEY not found in env variables or .env file.")
        sys.exit(1)
        
    companies = fetch_companies_api_data(api_key, args.limit)
    
    if not companies:
        logger.warning("No companies fetched (possibly due to API rate limit or error). Gracefully exiting.")
        sys.exit(0)
        
    logger.info("Upserting companies to Postgres database...")
    try:
        db_helper.upsert_companies(companies)
        logger.info("Successfully completed data loading.")
    except Exception:
        logger.exception("Failed to complete data loading.")
        sys.exit(1)

if __name__ == "__main__":
    main()

