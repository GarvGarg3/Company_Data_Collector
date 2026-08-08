import os
import re
import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

try:
    from scripts import company_filter
except ImportError:
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


# Sources disagree on both spelling and casing, which splits one country across
# several rows. Aliases are keyed on the lowercased, punctuation-free form.
COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u s a": "United States",
    "u s": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u k": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "britain": "United Kingdom",
    "uae": "United Arab Emirates",
    "czech republic": "Czechia",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "russian federation": "Russia",
    "viet nam": "Vietnam",
    "holland": "Netherlands",
}

# Words that stay lowercase inside a country name unless they lead it.
_COUNTRY_MINOR_WORDS = {"and", "of", "the", "da", "de"}


def clean_country(country):
    """Normalize a country to one canonical spelling so filters don't split.

    'USA', 'UNITED STATES' and 'United States' all collapse to 'United States'.
    """
    if not country:
        return None

    text = re.sub(r'\s+', ' ', str(country).strip())
    if not text:
        return None

    key = re.sub(r'[^a-z ]', ' ', text.lower())
    key = re.sub(r'\s+', ' ', key).strip()
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]

    # Title-case each word, but keep connectors lowercase and preserve
    # hyphenated parts ('Guinea-Bissau', 'Trinidad and Tobago', "Côte d'Ivoire").
    def cap_part(part):
        segments = part.split("'")
        if len(segments) == 2 and len(segments[0]) == 1:
            # Elided article: d'Ivoire, not D'ivoire.
            return f"{segments[0].lower()}'{segments[1].capitalize()}"
        return "'".join(segment.capitalize() for segment in segments)

    words = []
    for index, word in enumerate(text.split(" ")):
        lowered = word.lower()
        if index > 0 and lowered in _COUNTRY_MINOR_WORDS:
            words.append(lowered)
        else:
            words.append("-".join(cap_part(part) for part in lowered.split("-")))
    return " ".join(words)


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
        c_copy["Country"] = clean_country(c.get("Country"))
        cleaned_companies.append(c_copy)

    if not cleaned_companies:
        return

    # Drop shell entities and businesses outside venture scope before merging
    cleaned_companies = company_filter.filter_companies(cleaned_companies)

    if not cleaned_companies:
        logger.info("All records were removed by the relevance filter. Nothing to upsert.")
        return

    # Deduplicate in-memory by Company_name (case-insensitive) to avoid Postgres cardinality violation
    deduped = {}
    for c in cleaned_companies:
        name = c["Company_name"]
        key = name.lower()
        
        # Determine sources list for the current item
        source_val = c.get("Source")
        sources_val = c.get("Sources")
        if sources_val and isinstance(sources_val, list):
            src_list = [str(s).strip() for s in sources_val if s]
        elif source_val:
            src_list = [str(source_val).strip()]
        else:
            src_list = []

        if key not in deduped:
            deduped[key] = {
                "Company_name": name,
                "Website": c.get("Website"),
                "Sector": c.get("Sector"),
                "Country": c.get("Country"),
                "Sources": src_list,
                "Active": c.get("Active", True),
                "No_of_employees": c.get("No_of_employees"),
                "Updated_at": c.get("Updated_at", datetime.now())
            }
        else:
            existing = deduped[key]
            # Merge fields
            if not existing["Website"] and c.get("Website"):
                existing["Website"] = c.get("Website")
            if c.get("Sector"):
                if existing["Sector"]:
                    # Merge and deduplicate comma-separated sectors
                    exist_secs = set(s.strip() for s in existing["Sector"].split(",") if s.strip())
                    new_secs = set(s.strip() for s in c["Sector"].split(",") if s.strip())
                    existing["Sector"] = ", ".join(sorted(exist_secs.union(new_secs)))
                else:
                    existing["Sector"] = c.get("Sector")
            if not existing["Country"] and c.get("Country"):
                existing["Country"] = c.get("Country")
            
            # Combine sources list
            existing["Sources"] = list(set(existing["Sources"] + src_list))
            
            # Merge active status (True if any is active)
            existing["Active"] = existing["Active"] or c.get("Active", True)
            
            # Merge employees (take max)
            if c.get("No_of_employees") is not None:
                if existing["No_of_employees"] is not None:
                    existing["No_of_employees"] = max(existing["No_of_employees"], c["No_of_employees"])
                else:
                    existing["No_of_employees"] = c["No_of_employees"]
            
            # Merge updated_at (take max)
            if c.get("Updated_at"):
                existing["Updated_at"] = max(existing["Updated_at"], c["Updated_at"])

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

    rows = [
        (
            c["Company_name"],
            c["Website"],
            c["Sector"],
            c["Country"],
            c["Sources"],
            bool(c["Active"]),
            c["No_of_employees"],
            c["Updated_at"]
        )
        for c in deduped.values()
    ]

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, query, rows)
        logger.info(f"Upserted {len(rows)} normalized companies.")
    except Exception as e:
        logger.exception("Failed to upsert companies to database")
        raise e