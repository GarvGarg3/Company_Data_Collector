"""Build a standalone, self-hostable directory page from the database.

Produces one HTML file with the data embedded, no external requests and no
build step - open it locally, email it, or drop it on any static host.

Usage:
    python build_site.py
    python build_site.py --brand "Acme Ventures" --output site/index.html
"""

import argparse
import html
import json
import logging
import os
import sys
from datetime import date

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "site", "templates")

# Long source labels are unreadable as table tags.
SOURCE_SHORT = {
    "500 Global Portfolio (500.co/portfolio)": "500 Global",
    "Techstars Portfolio (techstars.com/portfolio)": "Techstars",
    "Startup India Portal": "Startup India",
    "Y Combinator": "Y Combinator",
}

SKELETON = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="icon" href="data:image/svg+xml,{favicon}">
<style>*,*::before,*::after{{box-sizing:border-box}}body,h1,h2,h3,p,ul,figure{{margin:0}}ul{{padding:0}}img{{max-width:100%}}</style>
</head>
<body>
{content}
</body>
</html>
"""

# Inline favicon: a single glyph on a transparent ground, so no file is needed.
FAVICON = (
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%94%8E%3C/text%3E%3C/svg%3E"
)


def load_rows():
    query = """
        SELECT S_No, Company_name, Website, Sector, Country, Sources, No_of_employees
        FROM Company_database
        ORDER BY Company_name;
    """
    with db_helper.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def build_dataset(rows):
    packed = []
    sector_counts = {}
    countries = set()
    sources = set()

    for s_no, name, website, sector, country, srcs, employees in rows:
        short = [SOURCE_SHORT.get(s, s) for s in (srcs or [])]
        sources.update(short)
        if country:
            countries.add(country)
        for tag in (sector or "").split(","):
            tag = tag.strip()
            if tag:
                sector_counts[tag] = sector_counts.get(tag, 0) + 1
        packed.append({
            "i": s_no, "n": name, "w": website, "s": sector,
            "c": country, "src": short, "e": employees,
        })

    top_sectors = sorted(sector_counts, key=lambda t: -sector_counts[t])[:40]
    return {
        "rows": packed,
        "countries": sorted(countries),
        "sectors": top_sectors,
        "sources": sorted(sources),
    }


def build_index(rows):
    """The id -> name/website map the enrichment function validates against.

    Bundled with the Netlify function, never served to browsers. It is what makes
    the endpoint's input bounded: only ids in here can ever trigger a paid
    lookup, and the function needs the name and site to search with anyway.
    """
    return {str(s_no): {"n": name, "w": website} for s_no, name, website, *_ in rows}


def read_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main():
    parser = argparse.ArgumentParser(description="Build the standalone directory page.")
    parser.add_argument("--brand", default="Company Data Collector", help="name shown above the title")
    parser.add_argument("--headline", default="Sourced company directory", help="page headline")
    parser.add_argument("--output", default=os.path.join(ROOT, "site", "index.html"), help="file to write")
    parser.add_argument("--index", default=os.path.join(ROOT, "data", "companies.json"),
                        help="id lookup map for the enrichment function")
    args = parser.parse_args()

    try:
        rows = load_rows()
    except Exception:
        logger.exception("Failed to read Company_database")
        return 1

    if not rows:
        logger.warning("Company_database is empty - nothing to build.")
        return 1

    dataset = build_dataset(rows)
    total = len(dataset["rows"])
    source_list = ", ".join(dataset["sources"])
    today = date.today().strftime("%-d %b %Y")

    lede = (
        "Every company currently in the pipeline, merged from "
        f"{len(dataset['sources'])} sources and filtered for venture relevance. "
        "Search by name, sector or country; click a column to sort."
    )
    footer = f"Snapshot of {total:,} companies, {today} &middot; {source_list}"

    content = read_template("head.html")
    for token, value in (
        ("{{BRAND}}", html.escape(args.brand)),
        ("{{HEADLINE}}", html.escape(args.headline)),
        ("{{LEDE}}", html.escape(lede)),
        ("{{FOOTER}}", footer),
    ):
        content = content.replace(token, value)

    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":"))
    # A literal </script> inside the JSON would close the tag early.
    payload = payload.replace("</", "<\\/")

    content += '<script id="data" type="application/json">' + payload + read_template("tail.html")

    page = SKELETON.format(
        title=html.escape(f"{args.headline} - {args.brand}"),
        description=html.escape(f"{total:,} companies sourced from {source_list}."),
        favicon=FAVICON,
        content=content,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(page)

    size_kb = os.path.getsize(args.output) / 1024
    logger.info(f"Wrote {args.output} - {total:,} companies, {size_kb:.0f} KB, no external requests.")

    os.makedirs(os.path.dirname(os.path.abspath(args.index)), exist_ok=True)
    with open(args.index, "w", encoding="utf-8") as handle:
        json.dump(build_index(rows), handle, ensure_ascii=False, separators=(",", ":"))
    logger.info(f"Wrote {args.index} - {total:,} ids for the enrichment function.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
