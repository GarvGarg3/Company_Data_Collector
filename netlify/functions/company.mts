/**
 * On-demand company enrichment, cached forever after the first look.
 *
 * GET /api/company/:id  ->  { status: "cached" | "fresh" | "unavailable", data }
 *
 * The static page ships name/sector/country/source for all 12,712 companies.
 * Everything else (headcount, founding year, funding stage, blurb) is looked up
 * the first time somebody opens a row, then served from the blob store.
 *
 * This endpoint spends money per cache miss, so read GUARDS below before
 * loosening anything.
 */

import { getStore, type Store } from "@netlify/blobs";
import type { Config, Context } from "@netlify/functions";
import { readFile } from "node:fs/promises";
import { selectProvider, type Enrichment, type IndexEntry } from "../lib/provider.mts";

// --- GUARDS -----------------------------------------------------------------
// A public endpoint that calls a paid API is an open tap. Four things keep the
// worst case bounded:
//   1. Only integer ids present in data/companies.json are accepted, so the set
//      of possible cache misses is finite and known (no free-text queries).
//   2. DAILY_MISS_CAP is the real backstop - a ceiling on paid lookups per
//      day, enforced with a compare-and-swap where the store supports it (see
//      claimSlot). Past the cap, cached rows still serve; misses return
//      "unavailable".
//   3. IP_MISSES_PER_MIN throttles a single visitor. Cache hits are unmetered.
//   4. netlify.toml keeps the function on the default concurrency, so a burst
//      can't fan out into hundreds of parallel model calls.
const DAILY_MISS_CAP = Number(process.env.ENRICH_DAILY_MISS_CAP ?? 200);
const IP_MISSES_PER_MIN = Number(process.env.ENRICH_IP_PER_MIN ?? 5);

// Headcount goes stale; a hit older than this is re-looked-up.
const CACHE_TTL_DAYS = Number(process.env.ENRICH_TTL_DAYS ?? 90);

const COMPANY_INDEX_PATH = "data/companies.json";

type CompanyIndex = Record<string, IndexEntry>;

// `name` is stored so a cache hit can be checked against the current index.
// S_No is a SERIAL: rebuild the database from scratch and the same id maps to a
// different company, which would otherwise serve one company's research under
// another's name for the whole TTL. `provider` records which backend produced
// the record, so a switch is visible in the data rather than silent.
type CachedRecord = Enrichment & { name: string; enriched_at: string; provider: string };

let indexPromise: Promise<CompanyIndex> | undefined;
// Cold-start once, then reused across invocations on the same instance.
const loadIndex = (): Promise<CompanyIndex> =>
  (indexPromise ??= readFile(COMPANY_INDEX_PATH, "utf8").then(JSON.parse));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

/**
 * Increment a counter only if it is below `limit`, returning false once it is.
 *
 * Prefers a compare-and-swap, which makes the ceiling exact: concurrent requests
 * cannot both read `limit - 1` and both proceed. Under genuine contention we
 * fail closed after a few attempts, because this is what stands between a
 * scraper and the bill.
 *
 * But not every backend honours conditional writes - Netlify's local blobs
 * server ignores `onlyIfMatch` entirely, so every CAS reports `modified: false`
 * and a strict implementation refuses *all* traffic rather than merely being
 * approximate. So we tell the two cases apart: under real contention the stored
 * value moves between reads, and when it never moves while our conditional
 * writes are being refused, conditional writes aren't supported and we fall back
 * to a plain write. That gives an exact ceiling where the platform allows one
 * and an approximate ceiling where it doesn't, instead of a dead endpoint.
 */
async function claimSlot(store: Store, key: string, limit: number): Promise<boolean> {
  let observed: number | null = null;
  let valueMoved = false;

  for (let attempt = 0; attempt < 5; attempt++) {
    const existing = await store.getWithMetadata(key, { type: "json" });
    const current: number = existing?.data?.n ?? 0;
    if (current >= limit) return false;

    if (observed !== null && current !== observed) valueMoved = true;
    observed = current;

    const write = existing?.etag
      ? await store.setJSON(key, { n: current + 1 }, { onlyIfMatch: existing.etag })
      : await store.setJSON(key, { n: current + 1 }, { onlyIfNew: true });

    if (write.modified) return true;
  }

  if (!valueMoved && observed !== null) {
    console.warn(`conditional writes unavailable on ${key}; counting approximately`);
    await store.setJSON(key, { n: observed + 1 });
    return true;
  }
  return false; // real contention - fail closed
}

function isStale(record: CachedRecord): boolean {
  const age = Date.now() - Date.parse(record.enriched_at);
  return !Number.isFinite(age) || age > CACHE_TTL_DAYS * 86_400_000;
}

export default async (_req: Request, context: Context) => {
  const id = context.params.id;

  // Guard 1: bounded input. Anything not an id we shipped is rejected before a
  // single paid call is possible.
  if (!/^\d+$/.test(id)) return json({ error: "bad id" }, 400);
  const entry = (await loadIndex())[id];
  // Deliberately 400, not 404: Netlify treats a 404 from a function as "this
  // handler declined" and re-dispatches the request to the static handler, which
  // re-enters this same route as "<id>.html" and answers with a misleading
  // "bad id". 400 is answered as-is.
  if (!entry) return json({ error: "unknown company" }, 400);

  const cache = getStore("company-enrichment");
  const stored = (await cache.get(`c/${id}`, { type: "json" })) as CachedRecord | null;
  // A record whose name no longer matches this id belongs to a different
  // company (see CachedRecord) - discard it rather than serve it.
  const cached = stored && stored.name === entry.n ? stored : null;
  if (cached && !isStale(cached)) {
    return json({ status: "cached", data: cached });
  }

  const meters = getStore("enrichment-meters");
  const now = new Date();
  const day = now.toISOString().slice(0, 10);
  const minute = now.toISOString().slice(0, 16);
  const ip = context.ip ?? "unknown";

  // Guard 3 before guard 2: a single abusive client shouldn't be able to eat the
  // shared daily budget just by being fast.
  if (!(await claimSlot(meters, `ip/${ip}/${minute}`, IP_MISSES_PER_MIN))) {
    return json({ status: "unavailable", reason: "rate_limited", data: cached ?? null }, 429);
  }
  // Guard 2: the hard ceiling.
  if (!(await claimSlot(meters, `day/${day}`, DAILY_MISS_CAP))) {
    return json({ status: "unavailable", reason: "daily_cap", data: cached ?? null }, 503);
  }

  try {
    const provider = selectProvider();
    const result = await provider.lookup(entry);
    const record: CachedRecord = {
      ...result,
      name: entry.n,
      enriched_at: new Date().toISOString(),
      provider: provider.label,
    };
    // Negative results are cached too. Dead companies are exactly what people
    // click out of curiosity, and re-paying for "still gone" every time is the
    // easiest way to burn the daily cap on nothing.
    await cache.setJSON(`c/${id}`, record);
    return json({ status: "fresh", data: record });
  } catch (error) {
    console.error(`enrichment failed for ${id} (${entry.n}):`, error);
    // The daily slot stays consumed: a failure that cost tokens should still
    // count against the budget, and it stops a failing company from being
    // retried in a loop.
    return json({ status: "unavailable", reason: "lookup_failed", data: cached ?? null }, 502);
  }
};

export const config: Config = {
  path: "/api/company/:id",
};
