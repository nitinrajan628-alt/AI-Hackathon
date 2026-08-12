# Reserve Review Intelligence — AI-Enabled Actuarial Reserve Review POC

A working proof of concept that lets Chief Actuaries and Board members
interrogate a pre-populated library of eight quarterly reserve reviews
(2024 Q3 – 2026 Q2) through a chat interface. The language model interprets
questions and explains evidence; **all numerical diagnostics are produced by a
deterministic, allow-listed query engine** over a read-only SQLite database.
The POC does not calculate reserves or make actuarial judgements.

## What was built

- **Packaged review library** — eight quarterly reviews, each with a
  10-12 slide structured report, claims triangles, premium, assumption
  selections and result snapshots in `data/reserve_review.db`. All figures
  are generated deterministically and reconcile exactly: total reserve moves
  GBP 614m → GBP 640m (+26m) between 2026 Q1 and 2026 Q2, with class
  movements Casualty +18 / Property +7 / Motor +4 / Marine −3 and Finance
  Class movements Commercial +14 / Specialty +7 / Personal +4 / Reinsurance +1.
- **Report viewer** — the packs render as presentation-style slides
  (headline metrics, tables, bar/waterfall charts regenerated from the
  stored data), searchable via SQLite FTS5 and cited in answers
  ("2026 Q2 Reserve Review · slide 8").
- **Deterministic query layer** — a catalogue-driven policy/grain validator,
  parameterised SQL compiler, read-only executor and approved calculation set
  (aggregate, compare, trend, rank, share of total, contribution to
  movement, categorical change listing, pivot). Aggregate claims questions
  are forced onto the latest-diagonal view; premium can never be filtered by
  Loss Type; assumptions can never be broadcast to Region/Finance Class.
- **Bounded AI integration** — two structured calls through a
  provider-agnostic adapter (`LLMProvider`): a planning call that returns a
  schema-validated `PlanningResponse` (never SQL), and an answer-drafting
  call that receives only the assembled evidence package. Every number in a
  drafted answer is verified as *reconstructible* from that evidence — a
  supplied value, a column or group subtotal, a difference, or a percentage
  of them — so legitimate summarising is allowed while anything
  unsupported is rejected. On failure the answer is regenerated once, then
  replaced by a deterministic templated summary.
  Adapters: **Gemini** (`google-genai`, Interactions API, JSON-schema
  output, `store=False`) and a deterministic **fake** provider used by the
  test-suite and available as an offline demo mode.
- **Conversation orchestration** — explicit application-owned context
  (review, comparison periods, filters, grouping) carried across follow-ups;
  deterministic guardrail pre-checks plus model-side policy blocking with
  Appendix-C style refusals and useful alternatives.
- **Diagnostics library** — every successful structured/mixed answer is
  persisted (question, validated plan, compiled SQL, parameters, result,
  chart spec, evidence, hashes, timings) to a separate writable
  `data/diagnostics.db`, and can be reopened, renamed, and rerun with a
  result/version comparison. Model calls are audit-logged (no payloads by
  default, never credentials).
- **Deep analysis** — an analytical question ("analyse how Casualty has
  developed across accident years", "what's driving the movement", "why did
  X increase") triggers a deterministic **battery** of ten approved
  diagnostics instead of one query: current position, quarter-on-quarter and
  year-on-year movement, each group's contribution to the total movement, the
  full-history trend, IBNR/case composition, paid and incurred claims,
  projection-method changes, and two whole-portfolio comparators. All ten go
  through the same catalogue validation and read-only SQL as any other
  query. The answer model then reasons *across* the set — concentration,
  persistence, maturity, corroboration, whether the pattern is
  focus-specific or portfolio-wide — and returns a multi-section analysis.
  Auto-detected from phrasing, with an "Analysis depth" control
  (Auto / Deep analysis / Single query) in the chat header.
- **Deterministic scope repair** — between planning and validation, the
  application checks that scope the user stated explicitly survived into the
  plan: an accident year named in the question becomes a filter, and an
  explicit "by ‹dimension›" becomes a grouping (including a dimension the
  model only put in `sort`). Repairs never widen a query, are refused when
  the dataset grain does not support them, and are recorded in the
  provenance panel. This closes the one failure mode the numerical verifier
  cannot catch: a plan that silently answers a *wider* question than the one
  asked, using figures that are individually genuine.
- **Streamlit UI** — chat with answer cards (headline, drivers, evidence
  badges, explicit scope line, chart + always-available table, citations,
  save state), right-hand evidence panel (Slides / Provenance / Query tabs),
  report viewer, diagnostics library, context chips with reset, and three
  appearance modes: **light**, **dark** (its own palette with lighter type
  weights, since light-on-dark text renders optically heavier) and
  **rainbow** — a full-page animated gradient meme mode in Comic Sans, which
  keeps tables and charts on opaque panels so the numbers survive the joke.

## Quick start

Requires **Python 3.11 or newer** (built and tested on 3.14) and nothing else —
no database server, no Docker, no cloud setup. The review database and a
working `.env` (with API keys) are already inside this folder, so it runs
straight out of the zip.

If you received this as a zip: unzip it first, and work inside the
`reserve-review-poc` folder that appears.

### Windows (PowerShell)

Open PowerShell, then run these five commands one at a time:

```powershell
cd path\to\reserve-review-poc

py -m venv .venv                   # create an isolated Python environment
.venv\Scripts\Activate.ps1         # activate it — prompt now starts with (.venv)
pip install -r requirements.txt    # ~1-2 minutes the first time
streamlit run app.py
```

If PowerShell blocks the activate script with an execution-policy error, run
this once in the same window and then retry the activate line:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Alternative that avoids activation entirely — just prefix every command with
the venv's Python:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

Using **Command Prompt (cmd)** instead of PowerShell? The activate line is
`.venv\Scripts\activate.bat`; everything else is identical.

### macOS / Linux

```bash
cd reserve-review-poc
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Finding the localhost address

`streamlit run app.py` prints the URL in the terminal within a couple of
seconds. It looks like this:

```text
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.1.24:8501
```

**Open the Local URL — `http://localhost:8501`** — in a browser. Ctrl+click it
in most terminals, or copy-paste it. `8501` is Streamlit's default port; if
something else is already using it, Streamlit picks the next free one (8502,
8503, …), so always read the port from the printed line rather than assuming
8501.

To force a specific port:

```powershell
streamlit run app.py --server.port 8600
```

Leave the terminal window open while you use the app — closing it stops the
server. Press **Ctrl+C** in the terminal to shut it down. To restart after
changing `.env`, stop with Ctrl+C and run `streamlit run app.py` again.

The very first launch may ask for an email address in the terminal — that is
Streamlit's optional newsletter prompt. Just press **Enter** to skip it.

### Optional extras

```powershell
# Rebuild + validate the packaged database (it already ships prebuilt)
python scripts/build_all.py

# Run the test suite (uses the offline fake provider, no API calls)
python -m pytest tests -q
```

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `'python' is not recognized` | Use `py` instead on Windows, or install Python from python.org and tick **Add python.exe to PATH**. |
| `'streamlit' is not recognized` | The venv isn't active. Re-run the activate line, or use `.venv\Scripts\python.exe -m streamlit run app.py`. |
| Execution-policy error on activate | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| Browser doesn't open automatically | Copy the **Local URL** from the terminal into a browser manually. |
| Port 8501 already in use | Streamlit auto-picks the next port — read it from the terminal — or pass `--server.port 8600`. |
| Sidebar warns the API key is missing | Check `.env` sits next to `app.py` and that `LLM_PROVIDER` matches the key you have. |
| Rate-limit message from Gemini | Free-tier quota; wait a few seconds and retry, or set `LLM_PROVIDER=fake` to demo offline. |

The app opens with **2026 Q2** selected. Suggested demo arc: ask for the key
messages, then "How much did reserves change from last quarter?", then
"Which Reserving Classes drove that?", then "Show the same movement by
Finance Class instead.", then an out-of-scope question such as "Should we
strengthen Casualty reserves?" to see the guardrails.

### Choosing the model provider (one variable)

`LLM_PROVIDER` in `.env` is the only switch. A ready-to-use `.env` is included
in this folder (`.env.example` is the blank template). Edit `.env` in any text
editor, save, then stop the app with Ctrl+C and start it again:

```text
LLM_PROVIDER=gemini     # Google Gemini   -> uses GEMINI_API_KEY
LLM_PROVIDER=openai     # OpenAI/ChatGPT  -> uses OPENAI_API_KEY
LLM_PROVIDER=fake       # offline rule-based provider, no key, no network
```

Both keys can live in `.env` at once; only the selected provider's key is
read. Each provider carries its own default model in `config/llm.yaml`
(`gemini-3.5-flash-lite` / `gpt-4.1-mini`), so switching needs no other
change. Optional overrides: `LLM_MODEL` (applies to whichever provider is
selected), or `GEMINI_MODEL` / `OPENAI_MODEL` (provider-specific).

The active provider and model are shown in the sidebar, with a warning if
its key is missing. Nothing outside `services/openai_provider.py`,
`services/gemini_provider.py` and the config knows which provider is in use:
planning, validation, SQL compilation, execution, retrieval and the UI all
depend only on the `LLMProvider` protocol.

- The key is read server-side by the Gemini SDK; it is never logged, stored
  in diagnostics, or sent anywhere except Google's API.
- If the key is missing, the app still starts: report browsing, the
  diagnostics library and all deterministic machinery work, and AI-backed
  questions show a clear configuration message instead of an exception.
- `LLM_PROVIDER=fake` runs the entire app offline with a deterministic
  rule-based planner (useful for demos without network access — clearly a
  keyword matcher, not an LLM).
- Free-tier Gemini keys have small per-model quotas. If you see the
  rate-limit message, wait a few seconds and retry, or set `LLM_MODEL` to a
  model with more head-room (any Gemini model ID works; nothing else
  changes).

## Running the tests

With the virtual environment activated (see Quick start):

```bash
python -m pytest tests -q          # full suite, offline fake provider, no API calls
```

The live-model acceptance tests are opt-in via an environment variable:

```powershell
# Windows PowerShell
$env:RUN_LIVE_LLM=1; python -m pytest tests/acceptance/test_live_gemini.py -v
```

```bash
# macOS / Linux
RUN_LIVE_LLM=1 python -m pytest tests/acceptance/test_live_gemini.py -v
```

Latest results on this machine:

- `pytest tests -q` → **148 passed, 3 skipped** (the skips are the live
  Gemini tests, which are opt-in via `RUN_LIVE_LLM=1`).
- Live Gemini acceptance tests (planning schema validity, adequacy-question
  blocking, end-to-end movement question) → **3 passed**, verified against
  both `gemini-3.5-flash` and `gemini-3.5-flash-lite`.
- `scripts/validate_data.py` → all reconciliation, identity, uniqueness and
  report-to-data checks pass (127 report figures re-verified against SQL).

Test coverage follows section 16 of the specification: period resolution,
alias handling, grain/policy validation (including Loss-Type-on-premium and
inflation-by-Region rejections), allow-listed SQL compilation, comparison
calculations with zero-denominator handling, hash stability, Pydantic
extra-field rejection, fabricated-evidence rejection, the IT-001…IT-012
integration scenarios and the full nine-step acceptance demonstration
script.

## Repository layout

As specified: `app.py` + `pages/` (Streamlit), `services/` (orchestration,
policy, compiler, executor, providers, audit), `models/` (typed contracts),
`config/` (catalogue, aliases, guardrails, llm defaults, prompt contracts),
`data/` (packaged review DB + runtime diagnostics DB), `scripts/`
(deterministic data/report builders + validation), `tests/`
(unit / integration / acceptance), plus `ui/` (theme tokens and
components) and `.streamlit/` (base config).

## Implementation assumptions

Minor decisions taken where the specification allowed latitude:

1. **Model default** — `LLM_MODEL` defaults to `gemini-3.5-flash-lite`,
   which was verified end-to-end on the supplied key with good planning
   quality and 3-5s latency. `gemini-3.5-flash` also passed the live
   acceptance tests and gives slightly richer drafting, but its free-tier
   quota on this key is small (it was exhausted during build testing), so
   the lite model is the dependable default. It is configuration, not code.
2. **Review switching** — changing the review in the sidebar starts a new
   conversation context immediately (with an inline notice) rather than
   showing a confirmation dialog. A planner-proposed review switch never
   silently changes the UI selection; explicit quarters in a question apply
   to that question's plan only.
3. **Earlier-quarter narrative totals** — the specification fixes 2026 Q1/Q2;
   the six earlier quarters follow the section 6.6 narrative with totals
   580, 585, 592, 598, 606, 610 (GBP m) and class paths to match (Casualty
   rising throughout, Property large-loss theme from 2025 Q3, Marine
   releasing from 2025 Q4).
4. **Sort-field handling** — an invalid sort field proposed by the model is
   dropped with a recorded warning (it is never compiled into SQL) instead
   of failing the whole question.
5. **Assumption loss ratios** — `selected_loss_ratio` is derived from the
   seeded ultimates and premium at the selection grain, so it is consistent
   with the data rather than independently invented.
6. **Report-only answers** are stored for audit and offered a "Save to
   diagnostics" action; structured/mixed answers are auto-saved to the
   library per section 12.1.
7. **Non-additive assumption measures** (loss ratio, inflation, tail factor)
   may only be listed/compared at the full selection grain; the validator
   rejects any grouping that would require averaging.
8. **Diagnostics DB** (`data/diagnostics.db`) is created at runtime and
   gitignored; review data is opened with SQLite `mode=ro` so the packaged
   snapshots are immutable through the application.
9. **Year formatting** — `accident_year` and other ordinal fields are
   rendered as bare integers everywhere (tables, chart axes, report slides):
   `2026`, never `2,026` or `2026.0`. Chart year axes are passed as category
   labels so Plotly cannot reintroduce separators.
10. **Rainbow mode is a joke mode**, not a third serious theme: the whole
    page is an animated rainbow gradient, the typeface is Comic Sans, and
    buttons, chips and table headers all cycle through the spectrum. It is
    deliberately unusable for real work. Two concessions keep it functional
    rather than merely broken: content panels and the chart surface stay
    near-opaque white so figures remain readable, and the animation is
    disabled under `prefers-reduced-motion`. Its chart palette is a full
    saturated spectrum and is *not* CVD-validated — an accepted trade for a
    non-serious theme, mitigated by the table printed beneath every chart
    and the signed labels on movement bars. Light and dark are untouched by
    it.

## Known limitations

- **The supplied OpenAI key has no credits.** The adapter is complete and
  the switch works, but every OpenAI completion currently returns
  `credit_balance_exhausted`. That condition is classified as a
  configuration error (not a transient rate limit), so it is never retried
  and the UI shows "The OpenAI account has no remaining credit or quota. Add
  credits, or set LLM_PROVIDER=gemini". Add billing credit and the same
  build works with no code change. Gemini remains the working default.
- The Gemini free tier rate-limits aggressively (per-model request quotas).
  The app classifies 429s, backs off, and shows a clear retry message, but a
  rapid multi-question demo on a free key can exhaust the window. A paid
  key, or `LLM_MODEL` pointed at a higher-quota model, removes this.
- Answer drafting depends on model quality for phrasing; the numerical
  verifier plus deterministic fallback guarantee no invented figures, at
  the cost of an occasionally terser templated summary when verification
  fails. The verifier checks that each figure is *traceable*, not that the
  sentence around it is perfectly framed — in one observed deep analysis the
  model described a year-on-year row as "accident year 2024 at the
  equivalent age" when both sides were the same accident year. The numbers
  were correct; the label was loose. Treat the narrative as interpretation
  and the tables as the record.
- A deep analysis runs ten queries and sends a much larger evidence package,
  so it takes roughly 8–10 seconds against Gemini versus 3–5 for a single
  query. Set "Analysis depth" to Single query for quick lookups.
- The claims triangle is packaged at quarterly development periods per the
  schema; explicit development-period questions work through the
  `claims_triangle` dataset, but the UI has no dedicated triangle
  visualisation (out of the POC's required scope).
- Streamlit's own chrome is styled via CSS overrides for the dark theme;
  a future React client would own theming natively (the service layer is
  already separated for that move).
- Single-user local POC: no authentication, one conversation session per
  browser session, diagnostics stored locally.
