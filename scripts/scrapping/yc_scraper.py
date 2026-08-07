"""Scrape the Y Combinator company directory to CSV.

Columns follow the Company_database table in schema.sql, so the output loads
straight into that table -- but nothing here touches a database.

Why not plain HTML parsing: ycombinator.com/companies is a React/Inertia SPA.
Its server-rendered props are just {env, currentBatch} -- there is no company
markup to select. The listing is fetched client-side from YC's Algolia index,
whose credentials are embedded in the page as `window.AlgoliaOpts`. Those are
read at runtime rather than hardcoded, because YC rotates the key. The key is
index-restricted and tag-filtered to `ycdc_public` by YC itself, so it only
returns publicly listed companies.

Algolia refuses to page past 1000 hits (~6.1k companies exist), so a naive
paging loop silently truncates most of the directory. Instead the index is
sliced by its own `batch` facet: ~50 queries, each well under the cap.

Column mapping:
    S_No            <- YC's own company id (stable across runs)
    Company_name    <- name
    Website         <- website
    Sector          <- industry
    Country         <- last segment of all_locations, else regions[0]
    Source          <- "Y Combinator"
    Updated_at      <- scrape time (UTC)
    Active          <- status == "Active"
    No_of_employees <- team_size

Usage:
    python yc_scraper.py                             # -> companies.csv
    python yc_scraper.py -o w24.csv --batch "Winter 2024"
    python yc_scraper.py --limit 50
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode

import httpx

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

try:
    from scripts import db_helper
except ImportError:
    try:
        from scrapping import db_helper
    except ImportError:
        import db_helper

BASE_URL = "https://www.ycombinator.com"
DIRECTORY_URL = f"{BASE_URL}/companies"
ALGOLIA_INDEX = "YCCompany_production"
SOURCE = "Y Combinator"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# window.AlgoliaOpts = {"app":"...","key":"..."};
_ALGOLIA_OPTS_RE = re.compile(r"window\.AlgoliaOpts\s*=\s*(\{.*?\})\s*;", re.DOTALL)

# Matches the Company_database column order in schema.sql.
COLUMNS = [
    "S_No",
    "Company_name",
    "Website",
    "Sector",
    "Country",
    "Source",
    "Updated_at",
    "Active",
    "No_of_employees",
]


class YCScraperError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def extract_country(hit: dict[str, Any]) -> str | None:
    """Pull a country out of an Algolia hit.

    `all_locations` looks like "San Francisco, CA, USA; Remote" -- take the
    first location and its last comma-separated segment. Roughly 3% of hits
    have no location at all, so fall back to the first `regions` entry.
    """
    locations = (hit.get("all_locations") or "").strip()
    if locations:
        first = locations.split(";")[0]
        country = first.split(",")[-1].strip()
        if country and country.lower() != "remote":
            return country

    for region in hit.get("regions") or []:
        if region not in ("Remote", "Fully Remote", "Partly Remote"):
            return region
    return None


class YCScraper:
    """Scrapes the YC company directory and writes CSV rows."""

    def __init__(
        self,
        *,
        delay: float = 0.3,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.delay = delay
        self.max_retries = max_retries
        self.client = httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True)
        self._algolia: dict[str, str] | None = None

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "YCScraper":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- http --

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a request, retrying with backoff on timeouts, 429s and 5xx."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.request(method, url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning("Rate limit hit, retrying after sleep...")
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code} from {url}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)
        raise YCScraperError(f"{method} {url} failed after {self.max_retries} tries: {last_error}")

    # ------------------------------------------------------------- algolia --

    def algolia_credentials(self) -> dict[str, str]:
        """Read the app id + secured API key off the directory page."""
        if self._algolia is not None:
            return self._algolia

        html = self._request("GET", DIRECTORY_URL).text
        match = _ALGOLIA_OPTS_RE.search(html)
        if not match:
            raise YCScraperError(
                "window.AlgoliaOpts not found on /companies -- YC changed the page layout"
            )
        opts = json.loads(match.group(1))
        app_id, api_key = opts.get("app"), opts.get("key")
        if not app_id or not api_key:
            raise YCScraperError(f"unexpected AlgoliaOpts payload: {opts}")

        self._algolia = {"app_id": app_id, "api_key": api_key}
        return self._algolia

    def _query(self, **params: Any) -> dict[str, Any]:
        """Run one Algolia query. `params` is form-encoded into its `params` string."""
        creds = self.algolia_credentials()
        encoded = urlencode({"query": "", **params})
        resp = self._request(
            "POST",
            f"https://{creds['app_id'].lower()}-dsn.algolia.net/1/indexes/*/queries",
            json={"requests": [{"indexName": ALGOLIA_INDEX, "params": encoded}]},
            headers={
                "X-Algolia-Application-Id": creds["app_id"],
                "X-Algolia-API-Key": creds["api_key"],
            },
        )
        return resp.json()["results"][0]

    def list_batches(self) -> list[str]:
        """Every batch name, taken from the index's own facet counts."""
        result = self._query(hitsPerPage=0, facets=json.dumps(["batch"]))
        facets = result.get("facets", {}).get("batch", {})
        if not facets:
            raise YCScraperError("no batch facet returned -- cannot slice the index")
        return sorted(facets, key=lambda name: facets[name], reverse=True)

    def iter_companies(self, batches: Iterable[str] | None = None) -> Iterator[dict[str, Any]]:
        """Yield one Algolia hit per company, batch by batch."""
        names = list(batches) if batches is not None else self.list_batches()
        seen: set[int] = set()

        for batch in names:
            page = 0
            while True:
                result = self._query(
                    hitsPerPage=1000,
                    page=page,
                    facetFilters=json.dumps([[f"batch:{batch}"]]),
                )
                hits = result.get("hits", [])
                for hit in hits:
                    company_id = hit.get("id")
                    if company_id is None or company_id in seen:
                        continue
                    seen.add(company_id)
                    yield hit

                page += 1
                if not hits or page >= result.get("nbPages", 1):
                    break
                time.sleep(self.delay)
            time.sleep(self.delay)

    # --------------------------------------------------------------- write --

    def to_row(self, hit: dict[str, Any], now: str) -> dict[str, Any]:
        """Map one Algolia hit onto the CSV columns."""
        return {
            "S_No": hit["id"],
            "Company_name": hit.get("name"),
            "Website": hit.get("website"),
            "Sector": hit.get("industry"),
            "Country": extract_country(hit),
            "Source": SOURCE,
            "Updated_at": now,
            "Active": 1 if hit.get("status") == "Active" else 0,
            "No_of_employees": hit.get("team_size"),
        }

    def scrape(
        self,
        path: str | Path = "companies.csv",
        *,
        batches: Iterable[str] | None = None,
        limit: int | None = None,
        verbose: bool = True,
    ) -> int:
        """Scrape the directory to a CSV file and directly to PostgreSQL.

        Rows stream out as they arrive rather than accumulating in memory. The
        file is UTF-8 with a BOM so Excel renders non-ASCII company names, and
        newline="" lets the csv module own line endings.
        """
        now = _utcnow()
        count = 0
        db_buffer = []
        BATCH_SIZE = 500

        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for hit in self.iter_companies(batches):
                row = self.to_row(hit, now)
                writer.writerow(row)
                
                # Add to DB upsert buffer
                db_buffer.append(row)
                
                count += 1
                if len(db_buffer) >= BATCH_SIZE:
                    if verbose:
                        logger.info(f"  Scraped {count} companies. Upserting batch of {len(db_buffer)} to database...")
                    try:
                        db_helper.upsert_companies(db_buffer)
                    except Exception:
                        logger.exception("Failed to upsert scraper batch")
                    db_buffer.clear()

                if limit is not None and count >= limit:
                    break
            
            # Upsert any remaining rows
            if db_buffer:
                if verbose:
                    logger.info(f"  Scrape finished. Upserting final batch of {len(db_buffer)} to database...")
                try:
                    db_helper.upsert_companies(db_buffer)
                except Exception:
                    logger.exception("Failed to upsert final scraper batch")
                db_buffer.clear()

        return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape the Y Combinator company directory.")
    parser.add_argument(
        "-o", "--output", default="companies.csv", help="CSV file to write (default: companies.csv)"
    )
    parser.add_argument(
        "--batch", action="append", help="limit to a batch, e.g. 'Winter 2024' (repeatable)"
    )
    parser.add_argument("--limit", type=int, help="stop after N companies")
    parser.add_argument(
        "--delay", type=float, default=0.3, help="seconds between requests (default: 0.3)"
    )
    args = parser.parse_args()

    try:
        with YCScraper(delay=args.delay) as scraper:
            count = scraper.scrape(args.output, batches=args.batch, limit=args.limit)
    except YCScraperError as exc:
        logger.exception("Scraper runtime error")
        return 1

    logger.info(f"done: {count} companies written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
