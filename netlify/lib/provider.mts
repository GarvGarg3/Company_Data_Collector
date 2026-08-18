/**
 * Picks the enrichment backend.
 *
 * Set ENRICH_PROVIDER to "groq" or "anthropic". With it unset, whichever API key
 * is present wins, Anthropic first - so dropping ANTHROPIC_API_KEY into the
 * environment is the entire switch back.
 */

import type { Provider } from "./enrichment.mts";
import { anthropicProvider } from "./provider-anthropic.mts";
import { groqProvider } from "./provider-groq.mts";

export function selectProvider(): Provider {
  const choice = (process.env.ENRICH_PROVIDER ?? "").toLowerCase();

  if (choice === "anthropic") return anthropicProvider;
  if (choice === "groq") return groqProvider;
  if (choice) throw new Error(`unknown ENRICH_PROVIDER: ${choice}`);

  if (process.env.ANTHROPIC_API_KEY) return anthropicProvider;
  if (process.env.GROQ_API_KEY) return groqProvider;

  throw new Error("no provider configured - set ANTHROPIC_API_KEY or GROQ_API_KEY");
}

export type { Enrichment, IndexEntry, Provider } from "./enrichment.mts";