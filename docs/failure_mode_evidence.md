# Milestone 5 — Failure Mode Evidence

Each of the three documented failure modes (see `planning.md` → Error Handling)
was triggered deliberately from the terminal. In every case the tool returns a
**specific, informative value and exits cleanly (exit code 0) — no Python
exception is raised.**

Reproduce all three at once with: `python demo_failure_modes.py`

---

## Failure 1 — `search_listings` returns zero results

**Trigger**
```bash
python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
```
**Output**
```
[]
```
Returns an empty list, no exception.

**Through the full agent** (`run_agent("designer ballgown size XXS under $5", ...)`):
```
error    : No listings matched "designer ballgown", size XXS, under $5. Try loosening
           the filters — a different style description, a larger size range, or a higher price.
fit_card : None
```
The message names *what* failed and *what the user can try* — and the agent
branches: `suggest_outfit` / `create_fit_card` are never called, so `fit_card`
stays `None`.

---

## Failure 2 — `suggest_outfit` with an empty wardrobe

**Trigger**
```bash
python -c "
from tools import search_listings, suggest_outfit
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
results = search_listings('vintage graphic tee', size=None, max_price=50)
print(suggest_outfit(results[0], get_empty_wardrobe()))
"
```
**Output (general styling advice, non-empty string):**
```
I just adore this Y2K baby tee - it's so playful and sweet. To style it, I'd recommend
pairing it with high-waisted jeans or a flowy skirt for a cute, casual look... [etc.]
```
Falls back to general styling advice instead of trying to name closet pieces it
doesn't have. Never empty, never raises.

---

## Failure 3 — `create_fit_card` with an empty outfit string

**Trigger**
```bash
python -c "
from tools import search_listings, create_fit_card
results = search_listings('vintage graphic tee', size=None, max_price=50)
print(create_fit_card('', results[0]))
"
```
**Output (descriptive error string, not an exception):**
```
Error: no outfit suggestion was provided, so a fit card could not be created. Run suggest_outfit first.
```

---

## Automated regression coverage

These same failure modes are locked in as tests in `tests/test_tools.py`
(`test_search_no_results_returns_empty_list`,
`test_suggest_outfit_empty_wardrobe_gives_general_advice`,
`test_create_fit_card_empty_outfit_returns_error`). Run with `pytest -q`.
