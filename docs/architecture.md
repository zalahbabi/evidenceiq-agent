# How EvidenceIQ works

EvidenceIQ answers questions about Online Retail II using a local DuckDB database
and `gemma3:4b` through Ollama. Its experiment compares the same questions across
three tiers.

| Tier | Data access | Answer checking |
|---|---|---|
| 1 — Baseline | None; model receives the question | No evidence verification |
| 2 — Tools | Shared query patterns or model-written SQL, calculations and charts | Tool and query safeguards; no final claim verification |
| 3 — Verified | Same tools and patterns as Tier 2 | Deterministic checks, fact recovery, up to two retries, evidence-derived wording |

Common questions can use parameterised database queries without a model call.
Both grounded tiers share these patterns. Evaluation reports these separately
from model-written queries so their success is not mistaken for improved model
reasoning.

## Answer flow

1. Refuse known requests outside the dataset, such as profit or promotions.
2. Use a recognised query pattern, or ask the model to plan tool calls.
3. Run read-only SQL. For calculations, the model selects a supported operation
   and supplies inputs; it never executes arbitrary Python.
4. Build an answer from the returned evidence.
5. In Tier 3, bind claims to cells, recover omitted measurements from successful
   scoped queries, recompute arithmetic and check observable completeness. Failed
   queries also trigger repair even when no claims were produced.
6. Retain the strongest verified attempt and generate a direct answer from
   checked cells and arithmetic. Add a short explanation and useful next steps;
   display accepted charts and expandable figures and query evidence.

Every retry receives the previous failure and starts a fresh evidence log. All
attempts are saved for execution metrics; only the selected attempt can support
the displayed answer. `tier2_with_retries()` provides an optional execution-only
control with the same retry budget. Direct templates remain shared by both tiers.

SQL is parsed before execution. Database connections disable external access;
queries have a time limit and a row limit that fails explicitly rather than
silently truncating results. Recognised patterns have specific scope checks;
free-form queries have narrower safeguards. Sales/month joins must match the
month key, and month totals or trading days cannot be summed across invoice
lines. These checks prevent a monthly comparison from multiplying sales or
its day-count denominator. Explicit country requests are checked against the
database's country names, including comparisons, exclusions and share queries.

## Verification and its limits

- Claims can identify a tool call, row and column. Legacy claims need an
  unambiguous matching cell. Copied values also check labels and known units.
- Calculations require evidence-backed inputs and deterministic recomputation.
- Numeric tolerance is 0.011 absolute or one part per million relative.
  Boolean facts require exact boolean cells; `False` is not numeric zero.
- Undeclared numbers in prose are checked. Exact database labels and explicit
  identifiers are treated as labels, not measurements.
- Explanations and suggested next steps receive the same numerical exposure
  checks as the main answer. Explanations use deterministic rules and checked
  facts; they do not invent causes, profits or business targets.
- Chart columns and numeric axes are validated. Tier 3 withholds charts with
  values that failed verification.

Evidence matching does not prove that every free-form query answers the intended
business question. The public Tier 3 wording comes from evidence rather than model prose.
Query intent, chart meaning and answer usefulness still need human review. See [validation](validation.md) for observed failures.

## Where the code lives

| Location | Responsibility |
|---|---|
| `notebooks/01_eda.ipynb` | Dataset exploration |
| `notebooks/02_build_database.ipynb` | Explained database build |
| `notebooks/03_baseline_llm.ipynb` | Tier 1 |
| `notebooks/04_tier2_agent.ipynb` | Tier 2 and tools |
| `notebooks/05_tier3_verification.ipynb` | Tier 3 and verifier |
| `notebooks/06_evaluation.ipynb` | All tiers and benchmark scoring |
| `src/build_db.py` | Scripted database build |
| `app/dashboard.py` | Overview, analyst and evaluation UI |
| `tests/` | Regression tests and live example runner |

The dashboard loads definitions and constants from notebook 06 without running
its demos or evaluation loop. Overview queries run directly against the database.

## Maintenance rules

- Keep core logic in self-contained notebooks, using plain dictionaries.
  Shared function copies are deliberate; update every notebook defining a changed
  function. The test suite checks that shared copies agree.
- Keep verification deterministic and independent of the model.
- Preserve the three tiers and their shared tool behaviour for comparison.
- If cleaning or KPI rules change, update the documentation and rerun every
  benchmark reference query. A second teammate must review the ground truth.
- Keep runtime data out of Git. Build a replacement database and validate it
  before replacing the existing file.

The tool design incorporates Abdelateef's original Tier 2 implementation:
SQL parsing, constrained calculations, SQL-derived metadata and schema-constrained
model responses. Its source and attribution are preserved in
[the reference archive](../archive/reference/README.md).
