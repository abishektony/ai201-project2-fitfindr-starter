# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock listings dataset for items that match the user’s style description, optional size, and optional max price. Returns the best matches first.

**Input parameters:**
- `description` (str): Keywords like "vintage graphic tee".
- `size` (str | None): Optional size filter.
- `max_price` (float | None): Optional price cap.

**What it returns:**
A list of listing dicts with fields like `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

**What happens if it fails or returns nothing:**
Return an empty list and let the planning loop stop with a friendly no-results message.

---

### Tool 2: suggest_outfit

**What it does:**
Suggests 1–2 outfits that use the new item plus the user’s wardrobe, or gives general styling advice if the wardrobe is empty.

**Input parameters:**
- `new_item` (dict): The selected listing from `search_listings`.
- `wardrobe` (dict): The user’s wardrobe data.

**What it returns:**
A non-empty styling string with outfit ideas.

**What happens if it fails or returns nothing:**
If the wardrobe is empty, return broad styling tips instead of failing.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion into a short, shareable caption for the thrift find.

**Input parameters:**
- `outfit` (str): The outfit text from `suggest_outfit`.
- `new_item` (dict): The selected listing.

**What it returns:**
A 2–4 sentence caption string.

**What happens if it fails or returns nothing:**
If the outfit is missing or empty, return a clear error string.

---

### Additional Tools (if any)

### Tool 4: compare_price  *(stretch: price comparison)*

**What it does:**
Given a selected item, estimates whether its price is fair by comparing it
against comparable listings in the dataset (same category, with overlapping
style tags when possible).

**Input parameters:**
- `item` (dict): The selected listing.
- `listings` (list[dict] | None): Optional pool of comparables; defaults to the full dataset.

**What it returns:**
A dict: `{verdict, item_price, comparable_count, median, min, max, summary}` where
`verdict` is one of `"great deal"`, `"fair"`, `"overpriced"`, or `"no comparables"`.

**What happens if it fails or returns nothing:**
If there are too few comparables to judge, return `verdict="no comparables"` with a
neutral summary instead of raising.

---

### Tool 5: get_trending_styles  *(stretch: trend awareness)*

**What it does:**
Surfaces which styles are currently "popular." There is no live external
platform in this project, so trends are **derived from style-tag frequency in the
local dataset**, optionally restricted to listings in the user's size range.

**Input parameters:**
- `size` (str | None): Optional size filter to scope trends to the user's range.
- `top_n` (int): How many trending tags to return (default 5).
- `listings` (list[dict] | None): Optional pool; defaults to the full dataset.

**What it returns:**
A list of `{tag, count}` dicts, most popular first (possibly empty).

**What happens if it fails or returns nothing:**
If no listings match the size filter, fall back to dataset-wide trends; if still
empty, return an empty list.

---

## Stretch Features

### A. Retry logic with fallback
When `search_listings` returns nothing, the planning loop does not stop
immediately. It retries with progressively loosened constraints, in order:
(1) drop the size filter, (2) drop the price ceiling, (3) drop both. The first
retry that yields results wins, and the agent records which constraints it
relaxed in `session["adjustments"]` and prepends a note to the user
("No exact matches, so I loosened the size filter…"). Only if every loosened
attempt is still empty does it set `session["error"]`.

### B. Style profile memory
A small JSON profile (`data/user_profile.json`, via `utils/profile.py`) persists
a user's saved wardrobe and preferred style tags across sessions. The UI gains a
"My saved profile" wardrobe option and a "Save as my profile" button. Saved
style preferences are appended to the search description so returning users get
results biased toward their taste without re-describing themselves.

### C. Trend awareness
`get_trending_styles` (Tool 5) computes the most common style tags in the user's
size range and the agent attaches them to `session["trending"]`; the UI shows
them, and the no-results path suggests trending styles as alternatives.

### D. Price comparison
`compare_price` (Tool 4) runs after a listing is selected, attaches a fairness
verdict to `session["price_assessment"]`, and the UI shows it in the listing
panel ("💸 Price check: great deal — median for similar items is $X").

---

## Planning Loop

**How does your agent decide which tool to call next?**
1. Parse the query into `description`, `size`, and `max_price`. Parsing uses the
   LLM to extract a clean item noun-phrase from conversational queries (e.g.
   pulling `"vintage graphic tee"` out of "I'm looking for a vintage graphic tee
   under $30, I mostly wear baggy jeans..."), with a deterministic regex parser
   as an offline fallback if the LLM call fails.
2. Call `search_listings` first.
3. If no listings are returned, stop and show a helpful no-results message.
4. Otherwise choose the top listing, call `suggest_outfit`, then call `create_fit_card`.
5. Return once the fit card is created.

---

## State Management

**How does information from one tool get passed to the next?**
Use one session dict for the whole run. It stores the original query, parsed filters, search results, the selected item, the outfit suggestion, the fit card, and any error message. Each tool reads the needed fields from the session and writes its result back before the next step.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Stop early and return a friendly no-results message. |
| suggest_outfit | Wardrobe is empty | Return general styling advice instead of failing. |
| create_fit_card | Outfit input is missing or incomplete | Return a clear error string and skip caption generation. |

---

## Architecture

```mermaid
flowchart TD
     U[User query] --> P[Parse query (LLM, regex fallback)]
     P --> S[search_listings]
     S -->|results| Sel[Select top listing]
     S -->|empty| RT{Any filters to loosen?}
     RT -->|yes| LF[Loosen size, then price, then both] --> S2[search_listings retry]
     RT -->|no| E[Set session.error and STOP]
     S2 -->|results| Sel
     S2 -->|still empty| E
     Sel --> PC[compare_price]
     PC --> O[suggest_outfit]
     O --> C[create_fit_card]
     C --> R[Return session]

     W[(Wardrobe)] --> O
     Q[(Session state)] --> P
     Q --> S
     Q --> Sel
     Q --> O
     Q --> C
```

Control flow branches at the `search_listings` result; data flows through the
single session dict (dashed `Q` edges). `compare_price` and the retry/loosen path
are stretch features — the required loop is U → P → S → (Sel → O → C → R) or the
early STOP on no results.

---

## AI Tool Plan

I used an AI coding assistant (Claude) for a first pass on each component, then
reviewed and verified every change before keeping it. Below is exactly which
sections of this document I fed the AI to prompt each piece, and how I checked
the generated code against the spec.

**Milestone 3 — Individual tool implementations (`tools.py`):**
- *Prompt input:* the **Tools** section above (the Tool 1–3 blocks — inputs,
  return values, and the "what happens if it fails" line for each).
- *What it produced:* standalone `search_listings`, `suggest_outfit`, and
  `create_fit_card` functions.
- *How I verified against the spec:* I ran each tool in isolation on a happy-path
  input and on its documented failure mode, and locked those in as unit tests in
  `tests/test_tools.py` (one test per failure mode). Writing those tests caught a
  divergence from the spec — `suggest_outfit`/`create_fit_card` only fell back on
  a falsy response, so a whitespace-only LLM reply slipped past the "never return
  an empty string" requirement; I changed the guards to `.strip()`.

**Milestone 4 — Planning loop and state management (`agent.py`):**
- *Prompt input:* the **Planning Loop**, **State Management**, and **Error
  Handling** sections plus the **Architecture** diagram above.
- *What it produced:* a `run_agent()` that parses the query, calls the tools in
  order, threads results through the session dict, and stops on no-results.
- *How I verified against the spec:* I confirmed the conditional branch by
  asserting (by object identity) that the *same* `selected_item` dict stored in
  the session is the one passed into both downstream tools, and that the
  no-results branch never calls them (`fit_card` stays `None`). The first parser
  the AI generated was pure regex and left whole conversational sentences in
  `description` — diverging from the Step 1 walkthrough that expects a clean
  `"vintage graphic tee"` — so I overrode it with an LLM extractor backed by the
  regex parser as an offline fallback, and updated this doc to match.

**Stretch features (`tools.py`, `agent.py`, `utils/profile.py`):**
- *Prompt input:* the **Additional Tools** (Tools 4–5) and **Stretch Features**
  sections above.
- *How I verified:* `tests/test_stretch.py` covers each feature, including
  `compare_price`'s "no comparables" path, the trending size-scope fallback, and
  the retry/loosen branch recording its adjustments.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The LLM-backed parser extracts `description = "vintage graphic tee"`, `size = None`, and `max_price = 30` from the conversational query (ignoring the "baggy jeans / chunky sneakers" aside, which is wardrobe context, not a buy filter), then the agent calls `search_listings`.

**Step 2:**
`search_listings` returns the best matching listing, so the agent stores it as `selected_item` and calls `suggest_outfit` with that item and the wardrobe.

**Step 3:**
`suggest_outfit` returns 1–2 outfit ideas using the user’s clothes, then the agent calls `create_fit_card` with the outfit and selected item.

**Final output to user:**
A shortlist of listings, a styling suggestion, and a short fit-card caption ready to share.
