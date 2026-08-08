"""Shared relevance filter applied at ingestion time.

Every source funnels through `db_helper.upsert_companies`, so the rules here are
the single place that decides whether a record is worth a row: shell/holding
vehicles and non-venture-backable businesses are dropped before insertion.

Set COMPANY_FILTER_DISABLED=1 to ingest everything unfiltered (useful when
back-filling a source and inspecting what the rules would have removed).
"""

import os
import re
import logging

logger = logging.getLogger(__name__)

# Sectors that read as tech even though the surrounding word is on an exclusion
# list ("agritech" must survive the "agriculture" rule, and so on).
TECH_OVERRIDE = re.compile(
    r'\b('
    r'\w*tech|\w*saas|software|platform|marketplace|app|api|cloud|'
    r'artificial intelligence|machine learning|\bai\b|\bml\b|analytics|data|'
    r'fintech|biotech|healthtech|edtech|agritech|foodtech|proptech|insurtech|'
    r'cleantech|deeptech|robotics|semiconductor|cyber\s?security|blockchain|'
    r'developer tools|internet|e-?commerce|mobile|devices|hardware'
    r')\b',
    re.IGNORECASE,
)

# Sources that are already curated by an investor. A company in one of these
# portfolios has cleared a real diligence bar, so only the junk and paper-entity
# rules apply - sector and name heuristics would throw away good leads.
CURATED_SOURCE_PATTERNS = re.compile(
    r'y combinator|techstars|500 global', re.IGNORECASE
)

# Name patterns for financial vehicles and paper entities. These are never
# operating companies, so they drop regardless of what sector is claimed.
HARD_NAME_PATTERNS = re.compile(
    r'\b('
    r'spv|special purpose vehicle|'
    r'nidhi|chit fund|chit funds|mutual fund|mutual benefit|'
    r'asset management|investment trust|unit trust|'
    r'shell|dormant|struck off|'
    r'& sons|and sons|& co|& brothers|and brothers|'
    r'huf|sole proprietorship'
    r')\b',
    re.IGNORECASE,
)

# Weaker signals: often a holding or family entity, but sometimes a real
# operating startup. Dropped only when nothing else marks the record as tech.
SOFT_NAME_PATTERNS = re.compile(
    r'\b('
    r'holdings?|holding company|'
    r'capital|capitals|investments?|investors?|equity|securities|'
    r'partners|associates|trust|trustees|'
    r'realty|real estate|properties|estates|builders|infra|infrastructure|'
    r'traders?|trading|enterprises|udyog|industries|mills|'
    r'contractors?|constructions?|developers'
    r')\b',
    re.IGNORECASE,
)

# Placeholder / junk names produced by dirty directory records.
JUNK_NAME_PATTERNS = re.compile(
    r'^('
    r'n/?a|na|none|null|nil|test|testing|demo|sample|unknown|tbd|xxx+|'
    r'no name|not applicable|company|startup|business'
    r')$',
    re.IGNORECASE,
)

# Sectors a venture fund does not write cheques into. Checked only after
# TECH_OVERRIDE has had its say.
EXCLUDED_SECTOR_PATTERNS = re.compile(
    r'\b('
    r'restaurants?|food service|catering|cafe|bakery|brewery|breweries|'
    r'hotels?|hospitality|tourism|travel agency|'
    r'salons?|spa|barber|beauty parlou?r|'
    r'agriculture|farming|fishery|forestry|plantation|dairy|poultry|'
    r'construction|real estate|realty|property management|'
    r'mining|quarry|oil and gas|petroleum|coal|'
    r'textiles?|apparel manufacturing|garments?|handicrafts?|jewell?ery|'
    r'printing|stationery|furniture|'
    r'retail store|grocery|kirana|supermarket|wholesale|'
    r'law firm|legal services|accounting|audit|bookkeeping|'
    r'staffing|recruitment agency|manpower|placement|'
    r'consultancy|consulting services|advisory services|'
    r'government|public sector|ngo|non-?profit|charity|trust and society|'
    r'education institute|school|college|coaching|tuition|'
    r'transport(ation)? services|trucking|packers and movers|'
    r'security services|housekeeping|cleaning services|facility management|'
    r'event management|wedding planning|photography|'
    r'gym|fitness centre|fitness center|yoga'
    r')\b',
    re.IGNORECASE,
)


def _filter_disabled():
    return os.getenv("COMPANY_FILTER_DISABLED", "").strip().lower() in ("1", "true", "yes")


def _text(value):
    return str(value).strip() if value else ""


def is_curated(company):
    """True when the record comes from an investor-curated portfolio."""
    sources = company.get("Sources") or []
    if not isinstance(sources, list):
        sources = [sources]
    labels = [str(s) for s in sources if s]
    if company.get("Source"):
        labels.append(str(company["Source"]))
    return any(CURATED_SOURCE_PATTERNS.search(label) for label in labels)


def evaluate(company, curated=None):
    """Return (keep, reason). `reason` names the rule that rejected the record.

    Records from curated portfolios skip the sector and soft-name heuristics:
    a fund already vetted them, so "Darb Technology Holding (PropTech)" is a
    real target rather than a holding vehicle.
    """
    name = _text(company.get("Company_name"))
    sector = _text(company.get("Sector"))
    website = _text(company.get("Website"))

    if curated is None:
        curated = is_curated(company)

    if not name:
        return False, "empty name"

    if JUNK_NAME_PATTERNS.match(name):
        return False, "placeholder name"

    # A name that is all digits/punctuation, or a single character, is a
    # registration artefact rather than a company.
    if len(re.sub(r'[^A-Za-z]', '', name)) < 2:
        return False, "name has no alphabetic content"

    hard = HARD_NAME_PATTERNS.search(name)
    if hard:
        return False, f"shell-entity name pattern '{hard.group(0)}'"

    if curated:
        # Vetted by a fund already - nothing further to prove.
        return True, None

    looks_tech = bool(TECH_OVERRIDE.search(sector)) if sector else False

    soft = SOFT_NAME_PATTERNS.search(name)
    if soft and not looks_tech:
        return False, f"financial/trading name pattern '{soft.group(0)}'"

    if sector and not looks_tech:
        excluded = EXCLUDED_SECTOR_PATTERNS.search(sector)
        if excluded:
            return False, f"non-venture sector '{excluded.group(0)}'"

    # Nothing to research and nothing to categorise by: not a usable lead.
    if not website and not sector:
        return False, "no website and no sector"

    return True, None


def filter_companies(companies, source_label=None):
    """Drop records that fail `evaluate`, logging a per-reason breakdown."""
    if _filter_disabled():
        logger.info("COMPANY_FILTER_DISABLED set - skipping relevance filter.")
        return list(companies)

    kept = []
    reasons = {}
    for company in companies:
        keep, reason = evaluate(company)
        if keep:
            kept.append(company)
        else:
            reasons[reason] = reasons.get(reason, 0) + 1

    dropped = sum(reasons.values())
    if dropped:
        label = f" from {source_label}" if source_label else ""
        breakdown = ", ".join(f"{r} x{c}" for r, c in sorted(reasons.items(), key=lambda kv: -kv[1]))
        logger.info(f"Relevance filter dropped {dropped}/{len(companies)} records{label}: {breakdown}")
    return kept
