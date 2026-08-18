/**
 * Groq backend: two calls, because Groq splits the two halves of the job.
 *
 *   1. `groq/compound-mini` has built-in web search (Tavily-backed) but does not
 *      support user tools, and structured outputs are not documented for it.
 *   2. `openai/gpt-oss-120b` supports strict structured outputs - guaranteed
 *      schema adherence via constrained decoding - but cannot search.
 *
 * So step 1 researches into prose and step 2 extracts that prose into the shared
 * schema. Strict mode is the important part: without it a best-effort model can
 * return JSON that doesn't match, and that would land in a 90-day cache.
 *
 * Compound's citation payload shape is undocumented, so the research prompt asks
 * for URLs inline in the prose and the extractor lifts them out. That depends on
 * nothing beyond the message text.
 */

import Groq from "groq-sdk";
import {
  describe,
  FIELD_RULES,
  SCHEMA,
  type Enrichment,
  type IndexEntry,
  type Provider,
} from "./enrichment.mts";

const SEARCH_MODEL = process.env.GROQ_SEARCH_MODEL ?? "groq/compound-mini";
const EXTRACT_MODEL = process.env.GROQ_EXTRACT_MODEL ?? "openai/gpt-oss-120b";

const RESEARCH_SYSTEM = `You research companies using web search and report what you find in plain prose.

Search for the company you are given, read the results, and write a short brief
covering: current employee headcount (and when that figure is from), founding
year, latest funding stage, and one or two sentences on what the company does.

Critical rules:
- After every fact, put the full URL you got it from in parentheses. A fact with
  no URL will be discarded.
- State plainly when you could not find something. Do not estimate, and do not
  fill gaps with what is typical for similar companies.
- Company names here are often truncated or shared with unrelated businesses. If
  a website is given, that domain is the company - ignore same-named companies
  elsewhere. If you cannot confirm you found the right one, say so explicitly and
  report nothing else.
- If the company looks defunct, acquired, or absent from the web, say that.`;

const EXTRACT_SYSTEM = `You convert a research brief into structured JSON.

Use only what the brief states. The brief is your only source - do not add facts
from your own knowledge, and do not resolve gaps the brief left open.

Field rules:
${FIELD_RULES}

If the brief says the company could not be confirmed, could not be found, or is
defunct, set not_found to true and leave the fact fields null.`;

export const groqProvider: Provider = {
  label: `groq:${SEARCH_MODEL}+${EXTRACT_MODEL}`,

  async lookup(entry: IndexEntry): Promise<Enrichment> {
    const client = new Groq(); // reads GROQ_API_KEY

    // Step 1 - research into prose, with search on.
    const research = await client.chat.completions.create({
      model: SEARCH_MODEL,
      messages: [
        { role: "system", content: RESEARCH_SYSTEM },
        { role: "user", content: describe(entry) },
      ],
      compound_custom: { tools: { enabled_tools: ["web_search"] } },
    });

    const brief = research.choices[0]?.message?.content?.trim();
    if (!brief) throw new Error("search step returned no content");

    // Step 2 - extract under strict constrained decoding.
    const extracted = await client.chat.completions.create({
      model: EXTRACT_MODEL,
      messages: [
        { role: "system", content: EXTRACT_SYSTEM },
        { role: "user", content: `${describe(entry)}\n\nResearch brief:\n${brief}` },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: "company_enrichment", strict: true, schema: SCHEMA },
      },
    });

    const payload = extracted.choices[0]?.message?.content;
    if (!payload) throw new Error("extraction step returned no content");
    return JSON.parse(payload) as Enrichment;
  },
};