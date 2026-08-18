/**
 * Anthropic backend: one call does search, read, and schema-validated extraction.
 *
 * The server-side web_search tool means there is no separate retrieval step and
 * no search API key to hold - which is why this is the preferred backend when a
 * key is available.
 */

import Anthropic from "@anthropic-ai/sdk";
import {
  describe,
  FIELD_RULES,
  SCHEMA,
  type Enrichment,
  type IndexEntry,
  type Provider,
} from "./enrichment.mts";

const MODEL = process.env.ENRICH_MODEL ?? "claude-opus-5";
// Bounds one lookup. Raising this raises the per-miss cost roughly linearly.
const MAX_SEARCHES = Number(process.env.ENRICH_MAX_SEARCHES ?? 4);

const SYSTEM = `You research companies and return structured facts about them.

You are given a company name and, usually, its website. Search the web, read what
you find, and report only what the sources actually support.

Rules:
${FIELD_RULES}`;

export const anthropicProvider: Provider = {
  label: `anthropic:${MODEL}`,

  async lookup(entry: IndexEntry): Promise<Enrichment> {
    const client = new Anthropic(); // reads ANTHROPIC_API_KEY
    const messages: Anthropic.MessageParam[] = [{ role: "user", content: describe(entry) }];

    // Server-tool turns can stop with pause_turn when the search loop hits its
    // iteration limit. Resending resumes it; unhandled, the turn returns a
    // truncated answer with no error.
    for (let turn = 0; turn < 3; turn++) {
      const response = await client.messages.create({
        model: MODEL,
        max_tokens: 4096,
        // Extraction from retrieved text, not hard reasoning - medium keeps the
        // interactive path responsive. Raise if identity matching proves weak.
        output_config: { effort: "medium", format: { type: "json_schema", schema: SCHEMA } },
        tools: [{ type: "web_search_20260209", name: "web_search", max_uses: MAX_SEARCHES }],
        system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
        messages,
      });

      if (response.stop_reason === "pause_turn") {
        messages.push({ role: "assistant", content: response.content });
        continue;
      }
      if (response.stop_reason === "refusal") throw new Error("model declined the request");
      if (response.stop_reason === "max_tokens") {
        throw new Error("response truncated before the JSON was complete");
      }

      // With web search in play the response also carries server_tool_use and
      // web_search_tool_result blocks; the schema-constrained JSON is the final
      // text block.
      const text = response.content.filter((b) => b.type === "text").at(-1);
      if (!text) throw new Error("no text block in response");
      return JSON.parse(text.text) as Enrichment;
    }

    throw new Error("search loop did not settle");
  },
};