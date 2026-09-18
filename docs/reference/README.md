# Reference material

Not part of the running project. Kept because it is the original work these
notebooks were built from, and because the report should credit it.

## tier2_original_abdelateef/

Abdelateef's Tier 2 agent, as he delivered it — a proper Python package with
Pydantic models, its own 30-question benchmark and a test suite.

**The running code is `notebooks/04_tier2_agent.ipynb`**, which is his design
rewritten in the plain-dict, self-contained style the rest of the notebooks
use. Nothing imports anything from this folder.

Four of his ideas were kept because they are better than what we had:

| Idea | Why it is better |
|---|---|
| Parse the SQL with `sqlglot` instead of searching for banned words | a column called `updated_at` contains the word "update"; a parser is not fooled |
| The model never writes Python — it picks an operation and hands us the numbers | nothing arbitrary ever runs, and the operation plus its inputs land in the log where Tier 3 can re-check them |
| Read `fields_used` and `filters_used` off the executed SQL | the model makes them up otherwise, and they are two of the seven things we must show |
| Ask the model for JSON matching a schema, not just "reply in JSON" | Ollama enforces the shape, so a 4B model stops inventing fields |

Also taken: one SQL repair attempt with the error message fed back, a guard
that refuses month-over-month arithmetic when December 2011 is involved, and
a fallback that builds claims from the tool log when the model forgets to
list them.

### What his benchmark measured

His 30 questions checked the **process** — which tools were used, which tables
appeared in the SQL, how many claims came back. Ours checks whether the
**answer is right**. They are complementary, and his results are worth quoting
in the report:

```
execution success       93.3%
tool selection          90.0%
SQL business rules      90.0%
claim source validity   93.3%
mean latency            9.2s   (gemma3:12b)
```

Fifteen of his questions were adapted into `eval/benchmark.yaml` as q16–q30,
with ground-truth values computed and verified against the database.
