# Using the company directory

A searchable list of startups pulled together from Y Combinator, Techstars, 500 Global, and the Startup India portal. Each company appears once, even when several of those sources list it.

The page is a single file with the data already inside it. Searching, filtering, and sorting happen in your browser and work offline — nothing is sent anywhere while you browse.

## Finding companies

**Search** matches company name, sector, and country at once, so `fintech kenya` narrows on both. It updates as you type.

**The three dropdowns** filter by source, sector, and country. They stack with each other and with the search box. **Reset** clears everything.

**Click any column heading** to sort by it; click again to reverse. The arrow shows which column is active.

The counter on the right of the toolbar always shows how many companies match right now, out of the total.

## What the columns mean

| Column | |
|---|---|
| **Company** | The name, linked to the company's website where we have one |
| **Sector** | What the company works on, as its source described it |
| **Country** | Where the company is based |
| **Team** | Headcount, when known. A dash means we don't have it |
| **Source** | Which directory this company came from. More than one tag means several listed it |

Two things to know about the data:

- **Sector wording is inconsistent.** Each source uses its own vocabulary, so `FinTech` and `Fintech` both appear, as do `AI/Machine Learning` and `Artificial intelligence and machine learning`. Search matches partial words, so `fin` finds all the fintech variants at once.
- **Country spellings are cleaned up.** `USA`, `US`, and `United States` are collapsed into one, so filtering by a country won't miss rows.

## Opening a company

Click a row — or focus it and press Enter — to open its detail panel. Clicking the company's *name* opens their website instead.

The panel shows what's already on the page immediately. Anything we don't have yet is looked up on the spot, which is why **the first time anyone opens a company it takes up to half a minute**. After that it's saved, so it opens instantly for everyone from then on. Most companies you open will already have been looked up by someone.

What you get:

- **A description** — one or two sentences on what the company actually does
- **Team, Founded, Stage** — headcount, founding year, and latest funding stage
- **Confidence** — how sure the research is, explained below
- **Sources** — the pages the facts came from. Every fact is traceable to one of them

### Reading it critically

**Blank fields are deliberate.** If a figure couldn't be found in a real source, it's left empty rather than estimated. An empty Team field means "we don't know", not "small". This is the single most important thing about the panel: it will not fill a gap with a plausible-sounding guess.

**Headcount comes with a date** — "2024 LinkedIn", "Q3 2023 filing". Team sizes change fast and a three-year-old number can be badly wrong. When a source gave a range, the midpoint is shown and the range noted alongside.

**Confidence** covers both whether we found the *right* company and how solid the figures are:

| | |
|---|---|
| **High** | The company was confirmed and the facts come from primary sources |
| **Medium** | Reasonably confirmed, but the sources are thinner |
| **Low** | Rests on a single weak or dated mention — treat every figure as a lead, not a fact |

**"No web presence found"** means the company couldn't be confirmed online. Many of these are genuinely defunct or were acquired years ago; some are small businesses that never had much of a website. It's an honest "we couldn't tell", not a judgement about the company.

Company names from public registries are often truncated or abbreviated, and plenty of unrelated businesses share a name. When the right company can't be confirmed, the panel says so instead of reporting facts about a different one.

## If a lookup doesn't work

| Message | What it means |
|---|---|
| *You're opening companies faster than the lookup budget allows* | Wait a minute and try again. Companies already looked up still open instantly |
| *Today's research budget is spent* | The daily limit for new lookups is used up. It resets tomorrow; already-researched companies are unaffected |
| *That lookup didn't complete* | A transient failure. Try again shortly |

There's a cap on new lookups because each one costs money. Browsing, searching, and reopening companies are unlimited and always free.

## Fair use

The data comes from public startup directories and public web sources, and it's here for research — finding companies, sizing a sector, spotting who's active in a market. Treat headcounts and funding stages as starting points to verify, not as authoritative records, and check the linked sources before acting on anything that matters.