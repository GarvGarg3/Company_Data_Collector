/**
 * What a company lookup returns, and the prompt/schema shared by every provider.
 *
 * The schema is deliberately written to satisfy both Anthropic structured
 * outputs and Groq strict mode: every field required, `additionalProperties`
 * false, and nullability expressed with `anyOf` rather than a type array. Both
 * accept that form, so one schema serves both backends.
 */

export type Enrichment = {
  employees: number | null;
  employees_asof: string | null;
  founded_year: number | null;
  funding_stage: string | null;
  description: string | null;
  sources: { url: string; label: string }[];
  not_found: boolean;
  confidence: "high" | "medium" | "low";
};

export type IndexEntry = { n: string; w: string | null };

/** A provider takes one company and returns facts about it. */
export type Provider = {
  readonly label: string;
  lookup(entry: IndexEntry): Promise<Enrichment>;
};

const nullable = (type: string) => ({ anyOf: [{ type }, { type: "null" }] });

export const SCHEMA = {
  type: "object",
  properties: {
    employees: nullable("integer"),
    employees_asof: nullable("string"),
    founded_year: nullable("integer"),
    funding_stage: nullable("string"),
    description: nullable("string"),
    sources: {
      type: "array",
      items: {
        type: "object",
        properties: { url: { type: "string" }, label: { type: "string" } },
        required: ["url", "label"],
        additionalProperties: false,
      },
    },
    not_found: { type: "boolean" },
    confidence: { type: "string", enum: ["high", "medium", "low"] },
  },
  required: [
    "employees",
    "employees_asof",
    "founded_year",
    "funding_stage",
    "description",
    "sources",
    "not_found",
    "confidence",
  ],
  additionalProperties: false,
} as const;

/**
 * The field-by-field contract. Shared by both providers so a backend switch
 * doesn't silently change what lands in the cache.
 *
 * Many companies in this dataset are dead startups with no web presence. Saying
 * so is a valid, cacheable answer - guessing is not, because a confident wrong
 * headcount is worse than an empty column and we cache it for months either way.
 */
export const FIELD_RULES = `- Never guess or estimate. If a figure is not stated in a source you read, it is
  null. An empty field is a correct answer; an invented one is not.
- Company names in this dataset are often truncated, abbreviated, or shared with
  unrelated businesses. If a website is given, treat it as the authoritative
  identity and ignore same-named companies at other domains. If you cannot
  confirm you found the right company, set not_found to true and leave the fact
  fields null rather than reporting facts about a different company.
- If the company appears defunct, acquired, or has no findable web presence, set
  not_found to true, and say which of those it is in description when you know.
- employees is the current headcount as a single integer. If a source gives a
  range or a band, use the midpoint and note the band in employees_asof.
- employees_asof records when the headcount was reported ("2024 LinkedIn",
  "Q3 2023 filing"). Headcounts age badly and the reader needs to know how much.
- founded_year is the year the company was founded, as an integer.
- funding_stage is the latest known stage in plain terms (Seed, Series A,
  Acquired, Public, Bootstrapped). Null if unclear.
- description is one or two sentences on what the company actually does. No
  marketing language, no filler, no restating the sector tag.
- sources lists the pages actually used, each with a short human label. Every
  non-null fact must be traceable to one of them.
- confidence covers the identity match and the figures together: high if the
  company was confirmed from primary sources, low if it rests on a single weak
  or dated mention.`;

export const describe = (entry: IndexEntry) =>
  `Company: ${entry.n}\n${entry.w ? `Website: ${entry.w}` : "Website: unknown"}`;