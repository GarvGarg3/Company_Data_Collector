"""Audit (and optionally clean) rows already stored in Company_database.

The ingestion filter only guards new records, so rows collected before it
existed still need a pass. Reports by default - nothing is modified unless an
action is chosen explicitly.

Usage:
    python prune_companies.py                      # report only
    python prune_companies.py --sample 20          # report + show examples
    python prune_companies.py --action deactivate  # set Active = FALSE
    python prune_companies.py --action delete      # remove the rows
"""

import argparse
import logging
import sys

try:
    from scripts import db_helper, company_filter
except ImportError:
    import db_helper
    import company_filter

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def load_rows():
    query = "SELECT S_No, Company_name, Website, Sector, Sources FROM Company_database;"
    with db_helper.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def apply_action(ids, action):
    if action == "deactivate":
        query = "UPDATE Company_database SET Active = FALSE WHERE S_No = ANY(%s);"
    else:
        query = "DELETE FROM Company_database WHERE S_No = ANY(%s);"
    with db_helper.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (ids,))
            return cur.rowcount


def main():
    parser = argparse.ArgumentParser(description="Find shell / non-venture companies already in the database.")
    parser.add_argument("--action", choices=["report", "deactivate", "delete"], default="report",
                        help="report (default), flag rows inactive, or delete them")
    parser.add_argument("--sample", type=int, default=10, help="how many example rejections to print per reason")
    args = parser.parse_args()

    try:
        rows = load_rows()
    except Exception:
        logger.exception("Failed to read Company_database")
        return 1

    logger.info(f"Evaluating {len(rows)} stored companies...")

    rejected = []
    by_reason = {}
    for s_no, name, website, sector, sources in rows:
        keep, reason = company_filter.evaluate(
            {"Company_name": name, "Website": website, "Sector": sector, "Sources": sources}
        )
        if not keep:
            rejected.append(s_no)
            by_reason.setdefault(reason, []).append(name)

    if not rejected:
        logger.info("No stored companies match the rejection rules.")
        return 0

    logger.info(f"{len(rejected)} of {len(rows)} stored companies fail the relevance rules:")
    for reason, names in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        examples = ", ".join(names[:args.sample])
        logger.info(f"  {len(names):>6}  {reason}  (e.g. {examples})")

    if args.action == "report":
        logger.info("Report only - rerun with --action deactivate or --action delete to change the table.")
        return 0

    try:
        affected = apply_action(rejected, args.action)
        logger.info(f"{args.action}d {affected} rows.")
    except Exception:
        logger.exception(f"Failed to {args.action} rows")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
