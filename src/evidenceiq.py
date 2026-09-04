"""
EvidenceIQ - all the shared code in one file.

The notebooks import from here so we don't copy-paste the same functions
into every notebook.

    import sys; sys.path.append("../src")
    import evidenceiq as eiq

What's in here:
    run_sql, run_python, make_chart   the tools the agent can use
    ask_gemma                         talks to the local model
    tier1, tier2, tier3               the three systems we compare
    verify                            our checking layer (no AI, just Python)
"""

import json
import re
import time

import duckdb

DB = "../data/processed/evidenceiq.duckdb"
MODEL = "gemma3:4b"
TOLERANCE = 0.01          # a number counts as matching if it's within 1%


# =====================================================================
# 1. THE TOOLS
# =====================================================================

# We never let the agent write to the database. Two safety nets:
# this list, and opening DuckDB with read_only=True.
BAD_WORDS = ["insert", "update", "delete", "drop", "create", "alter",
             "attach", "copy", "truncate", "replace", "pragma"]


def is_safe(sql):
    """True if this looks like a read-only query."""
    text = " " + re.sub(r"\s+", " ", sql.lower()).strip() + " "
    if not text.strip().startswith(("select", "with")):
        return False
    for word in BAD_WORDS:
        if " " + word + " " in text:
            return False
    return True


def run_sql(sql, log):
    """Run one SELECT and add the result to the log."""
    if not is_safe(sql):
        return add_to_log(log, "run_sql", sql, False, error="not a read-only query")
    try:
        con = duckdb.connect(DB, read_only=True)
        df = con.execute(sql).df()
        con.close()
        # .to_dict() gives numpy types which json can't handle, so clean them
        rows = json.loads(df.head(50).to_json(orient="records"))
        return add_to_log(log, "run_sql", sql, True, rows)
    except Exception as e:
        return add_to_log(log, "run_sql", sql, False, error=str(e))


def run_python(code, log):
    """Run a small calculation. The code must put its answer in `result`."""
    space = {}
    try:
        exec(code, {"__builtins__": {"round": round, "abs": abs, "sum": sum,
                                     "min": min, "max": max, "len": len}}, space)
        if "result" not in space:
            return add_to_log(log, "run_python", code, False,
                              error="you must put the answer in a variable called result")
        answer = space["result"]
        rows = [answer] if isinstance(answer, dict) else [{"result": answer}]
        return add_to_log(log, "run_python", code, True, rows)
    except Exception as e:
        return add_to_log(log, "run_python", code, False, error=str(e))


CHART_TYPES = ["bar", "line", "pie", "scatter", "table"]


def make_chart(spec, log):
    """We don't draw the chart here, we just check the spec makes sense."""
    if spec.get("type") not in CHART_TYPES:
        return add_to_log(log, "make_chart", str(spec), False,
                          error="chart type must be one of " + str(CHART_TYPES))
    return add_to_log(log, "make_chart", str(spec), True, [spec])


def add_to_log(log, tool, code, ok, rows=None, error=None):
    """Every tool call goes in the log. The verifier only trusts what's here."""
    call = {"n": len(log), "tool": tool, "code": code,
            "ok": ok, "rows": rows or [], "error": error}
    log.append(call)
    return call


def numbers_in_log(log):
    """Every number the tools actually returned, with which call it came from."""
    found = []
    for call in log:
        if not call["ok"]:
            continue                      # a failed query proves nothing
        for row in call["rows"]:
            for value in row.values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    found.append((call["n"], float(value)))
    return found


def show_results(log, start=0):
    """Turn the log into text we can paste into the next prompt."""
    if len(log) <= start:
        return "(no queries were run)"
    text = ""
    for call in log[start:]:
        text += "[call %d] %s\n%s\n" % (call["n"], call["tool"], call["code"].strip())
        text += "-> %s\n\n" % (json.dumps(call["rows"][:20]) if call["ok"]
                               else "FAILED: " + str(call["error"]))
    return text


# =====================================================================
# 2. TALKING TO THE MODEL
# =====================================================================

def ask_gemma(system, question):
    """Send one message to the local model and get JSON back."""
    import ollama
    reply = ollama.chat(model=MODEL, format="json",
                        options={"temperature": 0},
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": question}])
    return reply["message"]["content"]


def get_json(text):
    """Gemma sometimes wraps the JSON in other text, so dig it out."""
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"broken_json": True, "raw": text}


# =====================================================================
# 3. THE PROMPTS
# =====================================================================

SCHEMA = """
Database: a UK online gift wholesaler, Dec 2009 to 9 Dec 2011, 1,033,030 rows.

TABLE sales (one row per invoice line)
  invoice_no, stock_code, description, quantity, unit_price, customer_id,
  country, revenue (= quantity * unit_price), invoice_date, invoice_month,
  is_cancellation, is_product, is_outlier

TABLE dim_month   invoice_month, trading_days, net_revenue, is_complete_month
TABLE dim_product stock_code, description, units_sold, gross_revenue
TABLE dim_customer customer_id, country, first_order, last_order, orders, net_revenue

There is NO cost, profit, margin, discount, competitor or customer age data.
"""

RULES = """
RULES (the answer is wrong without these):
1. Revenue always excludes cancellations:  WHERE NOT is_cancellation
2. Product questions also need:            AND is_product AND NOT is_outlier
3. Group products by stock_code, and use mode(description) for the name.
4. For anything about months use dim_month (it has trading_days already).
5. December 2011 only has 8 trading days, so never compare it as a full month.
6. Units sold also needs quantity > 0.
7. Never say what CAUSED something, only what contributed to it.
8. If the data can't answer the question, say so instead of guessing.
"""

EXAMPLES = """
EXAMPLES

Total revenue in 2011:
  SELECT ROUND(SUM(revenue),2) AS revenue FROM sales
  WHERE NOT is_cancellation AND year(invoice_date) = 2011

Top 5 products in 2011:
  SELECT stock_code, mode(description) AS description, ROUND(SUM(revenue),2) AS revenue
  FROM sales
  WHERE NOT is_cancellation AND is_product AND NOT is_outlier
    AND year(invoice_date) = 2011
  GROUP BY stock_code ORDER BY revenue DESC LIMIT 5

Two months compared:
  SELECT invoice_month, ROUND(net_revenue,2) AS revenue, trading_days
  FROM dim_month WHERE invoice_month IN ('2011-10','2011-11')
"""

TIER1_PROMPT = """You are a business data analyst for a UK online gift wholesaler.
""" + SCHEMA + """
You have NO access to the database and cannot run a query. Answer from memory.
If the data could not answer the question, set insufficient_data to true.

Reply with JSON only:
{"answer": "...", "value": 0.0, "unit": "GBP", "insufficient_data": false}
"""

PLAN_PROMPT = """You are a business data analyst. Plan the queries needed to answer
the question. Do NOT answer yet - you have not seen any data.
""" + SCHEMA + RULES + EXAMPLES + """
Reply with JSON only:
{"plan": ["step 1", "step 2"],
 "calls": [{"tool": "run_sql", "code": "SELECT ..."}],
 "chart": {"type": "bar", "x": "...", "y": "...", "title": "..."},
 "insufficient_data": false,
 "limitations": null}

Tools you can use: run_sql, run_python (put the answer in `result`).
If the data cannot answer the question, return no calls and set insufficient_data.
"""

ANSWER_PROMPT = """You asked for some queries and here are the results.
Write the answer using ONLY these numbers.
""" + RULES + """
Reply with JSON only:
{"findings": "two or three sentences",
 "claims": [
   {"text": "November revenue was GBP 1,456,145.80", "value": 1456145.80,
    "unit": "GBP", "from_call": 0, "calc": "none", "inputs": []},
   {"text": "an increase of 36.17%", "value": 36.17, "unit": "%",
    "from_call": 1, "calc": "pct_change", "inputs": [1456145.80, 1069368.23]}],
 "kpis": {},
 "fields_used": [],
 "filters_used": [],
 "insufficient_data": false,
 "limitations": null}

calc can be: none, pct_change, share, sum, diff, ratio.
For any calculated number you MUST fill in calc and inputs so we can check it.
Every number in findings must also be a claim.
"""


# =====================================================================
# 4. THE THREE TIERS
# =====================================================================

def tier1(question):
    """No data access at all. This is our baseline - it makes numbers up."""
    start = time.time()
    reply = get_json(ask_gemma(TIER1_PROMPT, question))
    claims = []
    if reply.get("value") is not None:
        claims = [{"text": reply.get("answer", ""), "value": reply.get("value"),
                   "unit": reply.get("unit"), "from_call": None,
                   "calc": "none", "inputs": []}]
    return {"question": question, "tier": 1,
            "findings": reply.get("answer", ""),
            "claims": claims,
            "kpis": {}, "fields_used": [], "filters_used": [], "chart": None,
            "insufficient_data": bool(reply.get("insufficient_data")),
            "limitations": reply.get("limitations"),
            "log": [], "retries": 0,
            "seconds": round(time.time() - start, 1)}


def tier2(question, log=None, feedback=""):
    """Plans, runs real SQL, then writes the answer from the real rows.

    Two model calls on purpose. If we asked for the answer in one call the
    model would have to guess what its own query returns, which is how made-up
    numbers get in.
    """
    log = log if log is not None else []
    start = time.time()
    first_call = len(log)

    # --- step 1: plan
    ask = question if not feedback else question + "\n\nLast attempt failed:\n" + feedback
    plan = get_json(ask_gemma(PLAN_PROMPT, ask))

    if plan.get("insufficient_data"):
        return {"question": question, "tier": 2,
                "findings": plan.get("limitations") or "The data cannot answer this.",
                "claims": [], "kpis": {}, "fields_used": [], "filters_used": [],
                "chart": None, "insufficient_data": True,
                "limitations": plan.get("limitations"),
                "log": log, "retries": 0, "plan": plan.get("plan", []),
                "seconds": round(time.time() - start, 1)}

    # --- step 2: run the tools
    for call in (plan.get("calls") or [])[:6]:
        if call.get("tool") == "run_sql":
            run_sql(call.get("code", ""), log)
        elif call.get("tool") == "run_python":
            run_python(call.get("code", ""), log)
        else:
            add_to_log(log, str(call.get("tool")), str(call.get("code")), False,
                       error="unknown tool")

    chart = plan.get("chart")
    if chart and chart.get("type") in CHART_TYPES:
        make_chart(chart, log)

    # --- step 3: write the answer, now that we can see the real numbers
    prompt = "QUESTION\n" + question + "\n\nTOOL RESULTS\n" + show_results(log, first_call)
    if feedback:
        prompt += "\n\nYOUR LAST ANSWER FAILED CHECKING\n" + feedback
    reply = get_json(ask_gemma(ANSWER_PROMPT, prompt))

    if reply.get("broken_json"):
        return {"question": question, "tier": 2,
                "findings": str(reply.get("raw"))[:1000],
                "claims": [], "kpis": {}, "fields_used": [], "filters_used": [],
                "chart": chart, "insufficient_data": False,
                "limitations": "the model did not return valid JSON",
                "log": log, "retries": 0, "plan": plan.get("plan", []),
                "seconds": round(time.time() - start, 1)}

    return {"question": question, "tier": 2,
            "findings": reply.get("findings", ""),
            "claims": reply.get("claims") or [],
            "kpis": reply.get("kpis") or {},
            "fields_used": reply.get("fields_used") or [],
            "filters_used": reply.get("filters_used") or [],
            "chart": chart,
            "insufficient_data": bool(reply.get("insufficient_data")),
            "limitations": reply.get("limitations"),
            "log": log, "retries": 0, "plan": plan.get("plan", []),
            "seconds": round(time.time() - start, 1)}


def tier3(question, max_retries=2):
    """Tier 2, but every number gets checked before the user sees it."""
    log = []
    start = time.time()
    feedback = ""
    answer = None

    for attempt in range(max_retries + 1):
        answer = tier2(question, log, feedback)
        answer = verify(answer)
        answer["retries"] = attempt
        feedback = write_feedback(answer)
        if feedback == "":
            break

    answer["tier"] = 3
    answer["seconds"] = round(time.time() - start, 1)

    hidden = len([c for c in answer["claims"] if c.get("status") == "unsupported"])
    if hidden:
        note = "%d claim(s) could not be verified and were hidden." % hidden
        answer["limitations"] = ((answer.get("limitations") or "") + " " + note).strip()
    return answer


# =====================================================================
# 5. THE VERIFIER  (this is our contribution - no AI in here)
# =====================================================================

def about_equal(a, b, tol=TOLERANCE):
    """Compare two numbers allowing a small relative difference."""
    if a == b:
        return True
    biggest = max(abs(a), abs(b))
    if biggest == 0:
        return True
    return abs(a - b) / biggest <= tol


def recalculate(calc, inputs):
    """Work the number out ourselves, so we can compare."""
    try:
        if calc == "pct_change" and len(inputs) == 2:
            new, old = inputs
            return (new - old) / old * 100
        if calc == "share" and len(inputs) == 2:
            part, total = inputs
            return part / total * 100
        if calc == "diff" and len(inputs) == 2:
            return inputs[0] - inputs[1]
        if calc == "ratio" and len(inputs) == 2:
            return inputs[0] / inputs[1]
        if calc == "sum" and inputs:
            return sum(inputs)
    except ZeroDivisionError:
        return None
    return None


def verify(answer):
    """Check every claim. Adds status / evidence / problem to each one.

    CHECK 1  is the number actually in the log?
    CHECK 2  if it was calculated, does it recalculate the same?
    CHECK 3  do the parts add up to the total?
    """
    log = answer.get("log", [])
    log_numbers = numbers_in_log(log)

    for claim in answer.get("claims", []):
        # the model doesn't get to mark its own homework
        claim["status"] = None
        claim["evidence"] = None
        claim["problem"] = None

        value = claim.get("value")

        # ---- CHECK 1: is this number in the log?
        if value is None:
            claim["status"] = "supported"          # a sentence with no number
        else:
            claim["status"] = "unsupported"
            claim["problem"] = "this number is not in any query result"
            for call_number, number in log_numbers:
                if about_equal(float(value), number):
                    claim["status"] = "supported"
                    claim["problem"] = None
                    claim["from_call"] = call_number
                    claim["evidence"] = log[call_number]["code"]
                    break

        # ---- CHECK 2: if it was calculated, redo the maths
        calc = claim.get("calc", "none")
        inputs = claim.get("inputs") or []
        if calc not in (None, "none") and inputs and value is not None:
            expected = recalculate(calc, inputs)
            if expected is not None and not about_equal(float(value), expected):
                note = "we get %.2f, not %.2f" % (expected, float(value))
                if claim["status"] == "unsupported":
                    claim["problem"] = claim["problem"] + "; " + note
                else:
                    claim["status"] = "flagged"
                    claim["problem"] = note

    # ---- CHECK 3: do the pieces add up?
    for problem in check_totals(answer):
        answer["limitations"] = ((answer.get("limitations") or "")
                                 + " " + problem).strip()
    return answer


def check_totals(answer):
    """Shares should add to 100%. Parts should add to the stated total."""
    problems = []
    claims = answer.get("claims", [])

    shares = [c for c in claims if c.get("calc") == "share" and c.get("value") is not None]
    if len(shares) > 1:
        total = sum(float(c["value"]) for c in shares)
        if not about_equal(total, 100.0, 0.02):
            problems.append("The shares add up to %.1f%%, not 100%%." % total)

    totals = [c for c in claims if c.get("calc") == "sum" and c.get("value") is not None]
    parts = [c for c in claims
             if c.get("calc") in (None, "none") and c.get("value") is not None
             and c.get("unit") not in (None, "%")]
    for total_claim in totals:
        if not parts:
            continue
        added = sum(float(c["value"]) for c in parts)
        if not about_equal(added, float(total_claim["value"]), 0.02):
            problems.append("The parts add up to %.2f but the total says %.2f."
                            % (added, float(total_claim["value"])))
    return problems


def write_feedback(answer):
    """What we send back to the model when something failed. Empty = all good."""
    bad = [c for c in answer.get("claims", [])
           if c.get("status") in ("unsupported", "flagged")]
    if not bad:
        return ""

    lines = ["Some numbers did not pass checking. Fix them and answer again.", ""]
    for c in bad:
        lines.append('- "%s" -> %s: %s' % (c.get("text"), c.get("status"), c.get("problem")))
    lines += ["",
              "Only use numbers that a query actually returned.",
              "For calculated numbers, fill in calc and inputs so we can check the maths."]
    return "\n".join(lines)


# =====================================================================
# 6. LOOKING AT THE RESULT
# =====================================================================

def claims_to_show(answer):
    """Unsupported claims are hidden from the user."""
    return [c for c in answer.get("claims", []) if c.get("status") != "unsupported"]


def score(answer):
    """The numbers the evaluation notebook needs."""
    claims = answer.get("claims", [])
    n = len(claims)
    supported = len([c for c in claims if c.get("status") == "supported"])
    flagged = len([c for c in claims if c.get("status") == "flagged"])
    hidden = len([c for c in claims if c.get("status") == "unsupported"])
    calls = answer.get("log", [])
    return {"claims": n,
            "supported": supported,
            "flagged": flagged,
            "unsupported": hidden,
            "evidence_coverage": supported / n if n else 0,
            "unsupported_rate": hidden / n if n else 0,
            "queries": len(calls),
            "queries_ok": len([c for c in calls if c["ok"]]) / len(calls) if calls else None}


def show(answer):
    """Print an answer the way the user would see it."""
    icons = {"supported": "[OK]  ", "flagged": "[WARN]", "unsupported": "[HIDE]"}
    print(answer.get("findings", ""))
    print()
    for c in claims_to_show(answer):
        print(icons.get(c.get("status"), "      "), c.get("text"))
        if c.get("problem"):
            print("         !", c["problem"])
        elif c.get("evidence"):
            print("         evidence:", c["evidence"].strip().replace("\n", " ")[:70])

    hidden = len(answer.get("claims", [])) - len(claims_to_show(answer))
    if hidden:
        print("\n%d claim(s) hidden - could not be verified." % hidden)
    if answer.get("limitations"):
        print("\nLimitations:", answer["limitations"])
    if answer.get("insufficient_data"):
        print("\nThe data cannot answer this question.")
    print("\ntier %s | %s retries | %s seconds"
          % (answer.get("tier"), answer.get("retries"), answer.get("seconds")))
