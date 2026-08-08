"""Collapse country spellings already stored in Company_database.

`db_helper.clean_country` normalizes new records at ingestion; this applies the
same function to rows written before it existed, so both paths always agree.

Usage:
    python normalize_countries.py            # show the statements, change nothing
    python normalize_countries.py --apply    # run them
"""

import argparse
import logging
import sys

try:
    from scripts import db_helper
except ImportError:
    import db_helper

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def load_country_counts():
    query = """
        SELECT Country, count(*)
        FROM Company_database
        WHERE Country IS NOT NULL
        GROUP BY Country
        ORDER BY count(*) DESC;
    """
    with db_helper.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Normalize stored country spellings.")
    parser.add_argument("--apply", action="store_true", help="execute the updates (default: preview only)")
    args = parser.parse_args()

    try:
        rows = load_country_counts()
    except Exception:
        logger.exception("Failed to read Company_database")
        return 1

    changes = []
    for stored, count in rows:
        canonical = db_helper.clean_country(stored)
        if canonical and canonical != stored:
            changes.append((stored, canonical, count))

    if not changes:
        logger.info(f"All {len(rows)} stored country spellings are already canonical.")
        return 0

    affected = sum(count for _, _, count in changes)
    logger.info(f"{len(changes)} of {len(rows)} spellings need rewriting, affecting {affected} rows:")
    for stored, canonical, count in changes:
        logger.info(f"  UPDATE Company_database SET Country = '{canonical}' "
                    f"WHERE Country = '{stored}';   -- {count} rows")

    if not args.apply:
        logger.info("Preview only - rerun with --apply to execute.")
        return 0

    query = "UPDATE Company_database SET Country = %s WHERE Country = %s;"
    try:
        with db_helper.get_connection() as conn:
            with conn.cursor() as cur:
                total = 0
                for stored, canonical, _ in changes:
                    cur.execute(query, (canonical, stored))
                    total += cur.rowcount
        logger.info(f"Rewrote {total} rows across {len(changes)} spellings.")
    except Exception:
        logger.exception("Failed to normalize countries")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
