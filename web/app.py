"""Live directory served straight from Postgres.

Unlike scripts/build_site.py, which bakes a snapshot into a file, this queries
the database per request - so a scraper run shows up on refresh.

Run locally:
    uvicorn web.app:app --reload --port 8000
"""

import os
import time
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BRAND = os.getenv("SITE_BRAND", "Company Data Collector")
HEADLINE = os.getenv("SITE_HEADLINE", "Sourced company directory")

# Long source labels are unreadable as table tags.
SOURCE_SHORT = {
    "500 Global Portfolio (500.co/portfolio)": "500 Global",
    "Techstars Portfolio (techstars.com/portfolio)": "Techstars",
    "Startup India Portal": "Startup India",
    "Y Combinator": "Y Combinator",
}
SOURCE_LONG = {short: long for long, short in SOURCE_SHORT.items()}

# Only these may reach an ORDER BY clause.
SORT_COLUMNS = {
    "n": "Company_name",
    "s": "Sector",
    "c": "Country",
    "e": "No_of_employees",
    "src": "Sources[1]",
}

app = FastAPI(title="Company Directory")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

_pool: Optional[pool.SimpleConnectionPool] = None
_facet_cache: dict = {"at": 0.0, "data": None}
FACET_TTL_SECONDS = 60


def get_pool() -> pool.SimpleConnectionPool:
    """One pool for the process - a connection per request would be wasteful."""
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(
            1, 8,
            host=os.getenv("PG_HOST", "postgres"),
            port=os.getenv("PG_PORT", "5432"),
            user=os.getenv("PG_USER", "airflow"),
            password=os.getenv("PG_PASSWORD", "airflow"),
            dbname=os.getenv("PG_DB", "airflow"),
        )
    return _pool


class connection:
    """Borrow a pooled connection for the duration of a block."""

    def __enter__(self):
        self._pool = get_pool()
        self._conn = self._pool.getconn()
        return self._conn

    def __exit__(self, *exc):
        self._pool.putconn(self._conn)
        return False


@app.on_event("shutdown")
def close_pool():
    if _pool is not None:
        _pool.closeall()


def build_where(q, source, sector, country):
    """Assemble the WHERE clause and its parameters - always parameterized."""
    clauses = []
    params = []

    if q:
        clauses.append("(Company_name ILIKE %s OR Sector ILIKE %s OR Country ILIKE %s)")
        term = f"%{q}%"
        params.extend([term, term, term])
    if source:
        clauses.append("%s = ANY(Sources)")
        params.append(SOURCE_LONG.get(source, source))
    if sector:
        clauses.append("Sector ILIKE %s")
        params.append(f"%{sector}%")
    if country:
        clauses.append("Country = %s")
        params.append(country)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


@app.get("/api/companies")
def companies(
    q: str = "",
    source: str = "",
    sector: str = "",
    country: str = "",
    sort: str = "n",
    dir: str = "asc",
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=500),
):
    """One page of companies matching the filters, plus the unpaged total."""
    column = SORT_COLUMNS.get(sort, "Company_name")
    direction = "DESC" if dir.lower() == "desc" else "ASC"
    where, params = build_where(q, source, sector, country)

    # COUNT(*) OVER() gives the filtered total without a second round trip.
    sql = f"""
        SELECT Company_name AS n, Website AS w, Sector AS s, Country AS c,
               Sources AS src, No_of_employees AS e,
               count(*) OVER() AS total
        FROM Company_database
        {where}
        ORDER BY {column} {direction} NULLS LAST, Company_name ASC
        LIMIT %s OFFSET %s;
    """
    with connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params + [per_page, page * per_page])
            rows = cur.fetchall()

    total = rows[0]["total"] if rows else 0
    for row in rows:
        row.pop("total", None)
        row["src"] = [SOURCE_SHORT.get(s, s) for s in (row["src"] or [])]

    return {"rows": rows, "total": total, "page": page, "per_page": per_page}


@app.get("/api/facets")
def facets():
    """Filter options and headline counts, cached briefly."""
    now = time.time()
    if _facet_cache["data"] and now - _facet_cache["at"] < FACET_TTL_SECONDS:
        return _facet_cache["data"]

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT Country FROM Company_database WHERE Country IS NOT NULL ORDER BY 1;")
            countries = [r[0] for r in cur.fetchall()]

            cur.execute("""
                SELECT trim(tag), count(*)
                FROM Company_database, unnest(string_to_array(Sector, ',')) AS tag
                WHERE Sector IS NOT NULL AND trim(tag) <> ''
                GROUP BY 1 ORDER BY 2 DESC LIMIT 40;
            """)
            sectors = [r[0] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT unnest(Sources) FROM Company_database ORDER BY 1;")
            sources = [SOURCE_SHORT.get(r[0], r[0]) for r in cur.fetchall()]

            cur.execute("SELECT count(*), max(Updated_at) FROM Company_database;")
            total, updated_at = cur.fetchone()

    data = {
        "countries": countries,
        "sectors": sectors,
        "sources": sources,
        "total": total,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }
    _facet_cache.update(at=now, data=data)
    return data


@app.get("/healthz")
def healthz():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "brand": BRAND,
        "headline": HEADLINE,
        "lede": ("Every company currently in the pipeline, live from the database. "
                 "Search by name, sector or country; click a column to sort."),
        "footer": "Live view of company_database",
    })
