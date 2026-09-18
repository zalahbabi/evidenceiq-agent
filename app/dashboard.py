"""EvidenceIQ's presentation layer. Run: streamlit run app/dashboard.py.

The notebooks still own the agent and verifier. This app loads their definitions
without running demo questions, evaluation loops or database-building cells.
"""

import ast
import json
import re
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/evidenceiq.duckdb"
NOTEBOOK = ROOT / "notebooks/06_evaluation.ipynb"
GREEN = "#537660"

st.set_page_config(page_title="EvidenceIQ · Retail intelligence", page_icon="◈", layout="wide")
st.markdown("""<style>
html, body, [class*="css"], .stApp {font-family:'DM Sans',sans-serif;}
h1,h2,h3 {font-family:'Manrope',sans-serif!important;letter-spacing:-.045em;}
h1 {font-size:2.55rem!important;font-weight:800!important; padding-bottom:.35rem!important;}
h3 {font-size:1.13rem!important;letter-spacing:-.025em;}
.block-container {max-width:1500px;padding:2.4rem 3.2rem 3rem;}
[data-testid="stSidebar"] {background:#edf0e9;border-right:1px solid #dde3d9;}
[data-testid="stSidebar"] .block-container {padding:2rem 1.5rem;}
[data-testid="stMetric"] {background:white;border:1px solid #e0e5dc;border-radius:14px;padding:20px 22px;min-height:136px;}
[data-testid="stMetricLabel"] {font-size:.83rem;color:#6b786e;}
[data-testid="stMetricValue"] {font-family:'Manrope',sans-serif;font-size:1.9rem;font-weight:700;letter-spacing:-.04em;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius:14px!important;}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlockBorderWrapper"] {background:transparent;}
[data-testid="stAlert"] {border-radius:12px;}
.stButton > button,.stDownloadButton > button {border-radius:9px;font-weight:600;}
.eyebrow {color:#718071;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;}
.brand {font-family:'Manrope',sans-serif;font-size:25px;font-weight:800;letter-spacing:-1px; margin-bottom:3px;}
.brand-icon {display:inline-block;background:#315440;color:#e5edcc;border-radius:10px;padding:1px 10px;margin-right:9px;}
.brand-sub {color:#7d887d;font-size:11px;letter-spacing:1.5px;margin-left:49px;margin-bottom:38px;}
.status {display:inline-block;border:1px solid #d8e2cf;background:#eaf0e2;color:#47603a;padding:7px 12px;border-radius:24px;font-size:11px;font-weight:600;}
.subtle {color:#718071;font-size:13px;line-height:1.7;}
.side-note {border-top:1px solid #d6ded0;padding-top:18px;margin-top:34px;color:#768273;font-size:12px;line-height:1.8;}
.insight {background:#eaf0e2;border:1px solid #d9e3cf;border-radius:12px;padding:16px 20px;color:#41573e;font-size:13px;line-height:1.7;}
.footer {margin-top:28px;border-top:1px solid #e0e5dc;padding-top:16px;color:#8b948b;font-size:11px;}
@media(max-width:800px){.block-container{padding:1.5rem 1rem;}h1{font-size:2rem!important;}}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def query(sql, params, database_version):
    """Cache small aggregate results, invalidating whenever the database changes."""
    with duckdb.connect(str(DB), read_only=True, config={"enable_external_access": "false"}) as con:
        return con.execute(sql, params).df()


def read(sql, params=()):
    return query(sql, tuple(params), DB.stat().st_mtime_ns)


@st.cache_resource(show_spinner=False)
def notebook_runtime(notebook_version):
    """Load trusted local definitions only; the self-contained notebooks stay authoritative."""
    notebook = json.loads(NOTEBOOK.read_text())
    constants = {"DB", "MODEL", "TOLERANCE", "FORBIDDEN", "OPERATIONS", "CHART_TYPES",
                 "SCHEMA", "RULES", "EXAMPLES", "SYSTEM", "PLAN_PROMPT", "ANSWER_PROMPT"}
    nodes = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
                nodes.append(node)
            elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and
                    (t.id in constants or t.id.endswith("_SHAPE")) for t in node.targets):
                nodes.append(node)
    namespace = {"__name__": "evidenceiq_notebook"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
    namespace["DB"] = str(DB)
    return namespace


def chart_style(chart):
    return (chart.configure_view(strokeWidth=0)
            .configure_axis(gridColor="#edf0e9", domain=False, labelColor="#7c877e",
                            titleColor="#637166", labelFontSize=11, titleFontSize=11)
            .configure_legend(labelColor="#637166", title=None))


def heading(kicker, title, subtitle):
    st.markdown('<div class="eyebrow">'+kicker+'</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(subtitle)
    st.write("")


def overview():
    heading("WORKSPACE / OVERVIEW", "A clearer view of your business.",
            "Explore retail performance. Follow every figure back to the data.")
    choices = read("SELECT DISTINCT year(invoice_date) AS year FROM sales ORDER BY year DESC").year.astype(int).tolist()
    countries = read("SELECT DISTINCT country FROM sales ORDER BY country").country.tolist()
    filters = st.columns([1, 1.5, 1.5, 1.4])
    year = filters[0].selectbox("Reporting year", choices, key="year")
    country = filters[1].selectbox("Market", ["All markets"]+countries, key="market")
    complete = filters[2].toggle("Complete months only", value=True,
                                 help="Excludes December 2011, which ends on the 9th.")
    filters[3].markdown('<div class="status" style="margin-top:27px">● &nbsp; LOCAL DATA CONNECTED</div>', unsafe_allow_html=True)
    where = "year(s.invoice_date) = ?"
    params = [year]
    if country != "All markets":
        where += " AND s.country = ?"
        params.append(country)
    if complete:
        where += " AND m.is_complete_month"
    base = " FROM sales s JOIN dim_month m USING (invoice_month) WHERE " + where
    metrics_sql = """SELECT COALESCE(SUM(revenue) FILTER (WHERE NOT is_cancellation),0) AS revenue,
        COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_cancellation) AS orders,
        COUNT(DISTINCT customer_id) FILTER (WHERE NOT is_cancellation) AS customers,
        COUNT(*) AS lines, COUNT(*) FILTER (WHERE customer_id IS NULL) AS unidentified,
        MIN(invoice_date) AS first_day, MAX(invoice_date) AS last_day,
        COUNT(DISTINCT invoice_date) AS days""" + base
    metrics = read(metrics_sql, params).iloc[0]
    if metrics.lines == 0:
        st.info("No transactions match this selection. Choose another market or year.")
        return
    st.caption(f"{pd.Timestamp(metrics.first_day):%d %b %Y} – {pd.Timestamp(metrics.last_day):%d %b %Y} · "
               f"{int(metrics.days)} observed trading days · Revenue excludes cancellations · GBP")
    if year == 2011 and not complete:
        st.warning("December 2011 is partial: the dataset stops on 9 December. Its monthly total is not comparable with a complete month.")
    cols = st.columns(4)
    cols[0].metric("Revenue", f"£{metrics.revenue:,.0f}", help=f"Exact value: £{metrics.revenue:,.2f}. Excludes cancellations.")
    cols[1].metric("Completed orders", f"{metrics.orders:,.0f}", help="Distinct invoice numbers, excluding cancellations.")
    cols[2].metric("Average order value", f"£{metrics.revenue/metrics.orders:,.2f}" if metrics.orders else "—")
    cols[3].metric("Identified customers", f"{metrics.customers:,.0f}", help="Customers with a known ID and at least one completed order.")
    st.write("")
    monthly_sql = """SELECT s.invoice_month AS month,
        SUM(revenue) FILTER (WHERE NOT is_cancellation) AS revenue,
        COUNT(DISTINCT s.invoice_date) AS trading_days,
        BOOL_AND(m.is_complete_month) AS complete""" + base + " GROUP BY s.invoice_month ORDER BY month"
    monthly = read(monthly_sql, params)
    monthly["date"] = pd.to_datetime(monthly.month)
    monthly["Revenue per trading day"] = monthly.revenue / monthly.trading_days
    left, right = st.columns([1.8, 1])
    with left, st.container(border=True):
        st.subheader("Revenue over time")
        mode = st.radio("Measure", ["Monthly revenue", "Per trading day"], horizontal=True, label_visibility="collapsed")
        y = "revenue" if mode == "Monthly revenue" else "Revenue per trading day"
        st.caption("A day-adjusted view helps account for different month lengths.")
        chart = alt.Chart(monthly).encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%b", tickCount=len(monthly))),
            y=alt.Y(y+":Q", title="GBP", axis=alt.Axis(format="~s")),
            tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip(y+":Q", format=",.2f", title="GBP"),
                     alt.Tooltip("trading_days:Q", title="Trading days"), alt.Tooltip("complete:N", title="Complete month")])
        st.altair_chart(chart_style(chart.mark_area(color=GREEN, opacity=.12) +
                                   chart.mark_line(color=GREEN, strokeWidth=3, point=alt.OverlayMarkDef(color=GREEN, size=38))),
                         width='stretch')
    with right, st.container(border=True):
        st.subheader("Revenue by market")
        international = st.checkbox("Focus on international markets", value=True)
        market_sql = "SELECT country AS market, SUM(revenue) AS revenue" + base + " AND NOT is_cancellation"
        if international:
            market_sql += " AND country <> 'United Kingdom'"
        market_sql += " GROUP BY country ORDER BY revenue DESC LIMIT 6"
        markets = read(market_sql, params)
        if markets.empty:
            st.info("No international sales in this selection. Turn off the international filter to see this market.")
        else:
            chart = alt.Chart(markets).mark_bar(color=GREEN, cornerRadiusEnd=4, size=19).encode(
                y=alt.Y("market:N", sort="-x", title=None, axis=alt.Axis(labelLimit=140)),
                x=alt.X("revenue:Q", title="GBP", axis=alt.Axis(format="~s")),
                tooltip=["market", alt.Tooltip("revenue:Q", format=",.2f", title="Revenue (GBP)")]).properties(height=245)
            st.altair_chart(chart_style(chart), width='stretch')
        st.caption("Cancellations excluded. The UK accounts for most sales across the dataset.")
    st.write("")
    left, right = st.columns([1.8, 1])
    product_sql = """SELECT stock_code AS "Code", mode(description) AS "Product",
        ROUND(SUM(revenue),2) AS "Revenue (GBP)",
        SUM(quantity) FILTER (WHERE quantity > 0) AS "Units sold"
        """ + base + """
        AND NOT is_cancellation AND is_product AND NOT is_outlier
        GROUP BY stock_code ORDER BY "Revenue (GBP)" DESC LIMIT 5"""
    products = read(product_sql, params)
    with left, st.container(border=True):
        st.subheader("Products leading the way")
        st.caption("Top five by revenue · Fees, adjustments and flagged outlier orders excluded")
        st.dataframe(products, hide_index=True, width='stretch',
                     column_config={"Revenue (GBP)": st.column_config.NumberColumn(format="£ %.2f")})
    with right, st.container(border=True):
        st.subheader("The context behind the numbers")
        st.markdown("**One retailer. A real, imperfect dataset.**")
        st.write(f"{100*metrics.unidentified/metrics.lines:.1f}% of transaction lines in this selection have no customer ID. Customer counts cover identified customers only.")
        st.caption("Product revenue applies extra exclusions, so the top products do not reconcile directly to the headline revenue total.")
        st.caption("Costs, profit and marketing spend are not available in this dataset.")
    with st.expander("Inspect the source & download data"):
        st.caption("These are direct database aggregates. Filters above apply to every query below.")
        st.code(metrics_sql, language="sql")
        st.code(monthly_sql, language="sql")
        st.code(product_sql, language="sql")
        st.write("Query parameters:", params)
        st.download_button("Download monthly figures", monthly.drop(columns="date").to_csv(index=False),
                           "evidenceiq-monthly.csv", "text/csv")


def display_text(value):
    """Keep model/tool annotations in the evidence panel, out of business prose."""
    text = re.sub(r"\[call\s+(?:\d+|\[unverified\])\]", "", str(value or ""), flags=re.I)
    text = re.sub(r"\b(?:from_call\s*:|from[_ ]run_sql\b).*", "", text, flags=re.I | re.S)
    return text.strip()


def analyst():
    heading("WORKSPACE / ASK THE ANALYST", "Ask a question. See the evidence.",
            "Explore your data through common analyses and a local model. See the evidence behind each answer.")
    runtime = notebook_runtime(NOTEBOOK.stat().st_mtime_ns)
    tier = st.radio("Analysis mode", ["Tier 3 · Verified", "Tier 2 · Grounded", "Tier 1 · Baseline"], horizontal=True)
    st.caption({"Tier 3 · Verified": "Numbers and yes/no facts are checked against evidence. Common analyses also use checked KPI queries.",
                "Tier 2 · Grounded": "Uses real queries. The written interpretation is not verified.",
                "Tier 1 · Baseline": "Has no database access. Its answers are ungrounded experimental outputs."}[tier])
    prompts = ["What was our total revenue in 2011?", "Which five products generated the most revenue in 2011?",
               "Did November 2011 beat October 2011 on revenue, and by what percentage?", "Is December 2011 a complete month in the dataset?", "What was our profit margin in 2011?"]
    example = st.selectbox("Start with an example", prompts)
    # A suggested follow-up fills the form; the user still chooses when to run it.
    if st.session_state.get("last_example") != example or "analyst_question" not in st.session_state:
        st.session_state.analyst_question = example
        st.session_state.last_example = example
    next_question = st.session_state.pop("next_question", None)
    if next_question:
        st.session_state.analyst_question = next_question
    with st.form("question_form"):
        question = st.text_area("Your business question", key="analyst_question", height=100, max_chars=1500)
        submitted = st.form_submit_button("Analyze question →", type="primary")
    if submitted:
        if not question.strip():
            st.warning("Enter a business question first.")
        else:
            st.session_state.pop("answer", None)
            try:
                with st.spinner("Working through the question and collecting evidence. The local model may take a few minutes…"):
                    number = int(tier[5])
                    st.session_state.answer = runtime[f"tier{number}"](question.strip())
            except Exception as error:
                st.error("The local analysis could not finish. Check Ollama is running and gemma3:4b is installed, then try again.")
                with st.expander("Connection or model details"):
                    st.text(str(error))
    answer = st.session_state.get("answer")
    if not answer:
        with st.container(border=True):
            st.subheader("Your next answer starts with a question.")
            st.write("Explore revenue, products, customers and trading patterns. The evidence trail will appear here.")
            st.caption("Common analyses run directly against the database. Other questions require Ollama with gemma3:4b.")
        return
    st.divider()
    st.subheader("Analysis")
    st.caption(f"Tier {answer['tier']} · {answer['seconds']} seconds · {answer['retries']} retries")
    st.write(answer["question"])
    if answer.get('route') == 'query_pattern':
        st.caption("Direct database analysis · uses a checked KPI query")
    elif answer['tier'] == 3 and not answer.get('insufficient_data'):
        st.caption("Custom analysis · review the supporting data before acting")
    if answer['tier'] < 3:
        st.warning("Experimental output: the answer below has not passed verification.")
    if answer.get("insufficient_data"):
        st.info("This question cannot be answered from the available data.")
    with st.container(border=True):
        st.write(display_text(answer.get("findings", "")) or "See the reported facts and limitations below.")
    if answer.get("interpretation"):
        st.subheader("What this means")
        st.write(display_text(answer["interpretation"]))
    next_steps = answer.get("suggested_next_steps") or []
    if next_steps:
        st.subheader("Useful next steps")
        for index, step in enumerate(next_steps):
            step = display_text(step)
            if step.endswith("?"):
                if st.button(step, key=f"follow_up_{index}", width="stretch"):
                    st.session_state.next_question = step
                    st.rerun()
            else:
                st.write("• " + step)
    if answer.get("limitations"):
        if answer.get("completeness_issues") or answer.get("scope_errors"):
            st.warning(answer["limitations"])
        else:
            st.caption(answer["limitations"])
    claims = runtime["claims_to_show"](answer) if answer["tier"] == 3 else answer.get("claims", [])
    if claims:
        label = "See all checked figures" if answer["tier"] == 3 else "See reported figures · unchecked"
        with st.expander(f"{label} ({len(claims)})"):
            for claim in claims:
                st.write(display_text(claim.get("text", "")))
            st.caption("Open the query evidence below to inspect the sources and calculations.")
    spec = answer.get("chart")
    if isinstance(spec, dict):
        source = next((c for c in answer.get("log", []) if c.get("n") == spec.get("source_tool_call") and c.get("ok")), None)
        if source and source.get("rows"):
            data = pd.DataFrame(source["rows"])
            x, y = spec.get("x"), spec.get("y")
            if x in data and y in data and spec.get("type") in ("bar", "line", "scatter", "pie", "table"):
                st.subheader("Query result")
                if spec["type"] == "table":
                    st.dataframe(data, hide_index=True)
                elif pd.api.types.is_numeric_dtype(data[y]):
                    value_title = 'Revenue (GBP)' if y in ('revenue', 'net_revenue') else y.replace('_', ' ').title()
                    if spec['type'] == 'bar':
                        # Long product names are easier to read beside horizontal bars.
                        chart = alt.Chart(data).mark_bar(color=GREEN, cornerRadiusEnd=4).encode(
                            x=alt.X(y+':Q', title=value_title),
                            y=alt.Y(x+':N', title=None, sort='-x', axis=alt.Axis(labelLimit=260)),
                            tooltip=list(data.columns)).properties(height=max(220, min(700, len(data)*42)))
                    elif spec['type'] == 'pie':
                        chart = alt.Chart(data).mark_arc(innerRadius=55).encode(
                            theta=alt.Theta(y+':Q', title=value_title),
                            color=alt.Color(x+':N', title=None), tooltip=list(data.columns))
                    else:
                        chart = alt.Chart(data).encode(x=alt.X(x, title=x.replace('_', ' ').title()),
                                                      y=alt.Y(y+':Q', title=value_title), tooltip=list(data.columns))
                        chart = {'line': chart.mark_line, 'scatter': chart.mark_point}[spec['type']](color=GREEN)
                    st.altair_chart(chart_style(chart), width='stretch')
    with st.expander("Inspect executed queries & evidence"):
        st.caption("Raw tool results for inspection. Query correctness still needs review; numeric matching does not prove the SQL answered the intended question.")
        for call in answer.get("log", []):
            st.write(f"Call {call['n']} · {call['tool']} · {'Succeeded' if call['ok'] else 'Failed'}")
            st.code(str(call['code']))
            if call['ok']:
                st.dataframe(pd.DataFrame(call['rows']), hide_index=True)
            else:
                st.text(call.get('error'))
        st.write("Fields used:", answer.get("fields_used", []))
        st.write("Filters applied:", answer.get("filters_used", []))
    # Export the same safe surface users see, not the unverified diagnostic claims.
    export = {key: answer.get(key) for key in ("question", "tier", "findings", "interpretation", "suggested_next_steps", "limitations", "seconds", "retries", "route", "scope_check")}
    export["findings"] = display_text(export.get("findings"))
    export["interpretation"] = display_text(export.get("interpretation"))
    export["suggested_next_steps"] = [display_text(step) for step in export.get("suggested_next_steps") or []]
    export["claims"] = [dict(claim, text=display_text(claim.get("text"))) for claim in claims]
    st.download_button("Download analysis", json.dumps(export, indent=2, default=str), "evidenceiq-analysis.json", "application/json")


def evaluation():
    heading("WORKSPACE / EVALUATION", "Measure the difference evidence makes.",
            "One benchmark. Three distinct tiers. Results from completed runs only.")
    questions = yaml.safe_load((ROOT / "eval/benchmark.yaml").read_text())["questions"]
    cols = st.columns(3)
    cols[0].metric("Benchmark questions", len(questions))
    cols[1].metric("Answerable with data", sum(q['answerable'] for q in questions))
    cols[2].metric("Human-reviewed", sum(bool(q.get('reviewed_by')) for q in questions))
    st.write("")
    if not all(q.get('reviewed_by') for q in questions):
        st.warning("Benchmark review is incomplete. A second team member must confirm each ground truth before results are considered final.")
    results = ROOT / "eval/results/all_runs.csv"
    if not results.exists():
        with st.container(border=True):
            st.subheader("The experiment is ready. The scoreboard is waiting.")
            st.write("Run the full benchmark with dashboard publishing enabled. Accuracy, evidence coverage and response time will appear here.")
            st.code("python tests/run_examples.py --full --publish", language="bash")
            st.caption("No benchmark run has been saved yet. There are no performance scores to report.")
    else:
        try:
            frame = pd.read_csv(results)
            required = {'tier', 'id', 'correct', 'answerable', 'seconds', 'error', 'evidence_coverage'}
            if not required.issubset(frame):
                st.info("This results file uses an older format. Run the full benchmark with --publish to update the scoreboard.")
            elif frame.empty:
                st.info("The results file is empty. Run the full benchmark with --publish to collect results.")
            else:
                st.caption(f"{len(frame)} / {len(questions)*3} runs recorded · {frame.error.notna().sum()} execution errors")
                if {'displayed_claims', 'sql_successes', 'api_cost_usd', 'retries'}.issubset(frame):
                    runtime = notebook_runtime(NOTEBOOK.stat().st_mtime_ns)
                    summary = runtime['evaluation_summary'](frame)
                    routes = summary[summary.route.ne('all')].copy()
                    routes['route'] = routes.route.map({'model_tools': 'Model-written queries',
                        'query_pattern': 'Direct database patterns', 'rules_refusal': 'Known data-gap rules',
                        'model': 'Model without data'}).fillna(routes.route)
                    st.subheader('Results by analysis route')
                    st.caption('Compare the same question subsets. Direct patterns and refusal rules run without the model. Accuracy checks requested facts and extra numerical claims; useful context is scored separately.')
                    st.dataframe(routes[['tier', 'route', 'answerable_cases', 'correct_answers', 'accuracy', 'refusal_cases', 'refused_tricks', 'avg_seconds']],
                        hide_index=True, width='stretch', column_config={
                            'route': 'Analysis route', 'answerable_cases': 'Answerable',
                            'correct_answers': 'Correct', 'accuracy': st.column_config.NumberColumn('Answer accuracy', format='percent'),
                            'refusal_cases': 'Refusal cases', 'refused_tricks': 'Correct refusals',
                            'avg_seconds': st.column_config.NumberColumn('Average seconds', format='%.1f')})
                    model_rows = routes[routes.route.eq('Model-written queries') & routes.answerable_cases.gt(0)]
                    if not model_rows.empty:
                        chart = alt.Chart(model_rows).mark_bar(color=GREEN, cornerRadiusEnd=5).encode(
                            x=alt.X('tier:O', title='Tier'), y=alt.Y('accuracy:Q', scale=alt.Scale(domain=[0,1]), axis=alt.Axis(format='%')),
                            tooltip=['tier', 'answerable_cases', alt.Tooltip('accuracy:Q', format='.1%')]).properties(height=260)
                        st.altair_chart(chart_style(chart), width='stretch')
                        st.caption('This chart compares the two tiers that write queries, excluding direct database patterns. The data-free baseline appears in the table above; use matching case IDs when comparing its results with this subset.')
                    st.subheader('Evidence and execution')
                    overall = summary[summary.route.eq('all')]
                    st.dataframe(overall[['tier', 'displayed_claims', 'displayed_supported', 'evidence_coverage',
                        'unsupported_rate', 'sql_attempts', 'queries_ok', 'required_charts', 'chart_correct', 'api_cost_usd']],
                        hide_index=True, width='stretch', column_config={
                            'evidence_coverage': st.column_config.NumberColumn('Displayed claims supported', format='percent'),
                            'unsupported_rate': st.column_config.NumberColumn('Displayed claims unsupported', format='percent'),
                            'queries_ok': st.column_config.NumberColumn('SQL success', format='percent'),
                            'chart_correct': st.column_config.NumberColumn('Required chart checks', format='percent'),
                            'api_cost_usd': st.column_config.NumberColumn('Local API fees (USD)', format='%.2f')})
                    st.caption('SQL success includes saved retry attempts. Chart checks cover source, axes and required type; human review is needed for meaning and readability. Hardware and electricity costs are not estimated.')
                    rated = frame.get('usefulness_rating', pd.Series(dtype=float)).notna().sum()
                    st.caption(f'Human usefulness ratings: {rated} / {len(frame)}. Unrated answers are not treated as zero.')
                else:
                    st.warning('These are historical results from the previous scorer. Run the current full benchmark to publish comparable route and evidence metrics.')
                    answerable = frame[frame.answerable.eq(True)]
                    summary = answerable.groupby('tier').agg(accuracy=('correct', 'mean'), seconds=('seconds', 'mean')).reset_index()
                    st.dataframe(summary, hide_index=True, column_config={
                        'accuracy': st.column_config.NumberColumn('Historical accuracy', format='percent')})
                st.download_button("Download all runs", results.read_bytes(), "all_runs.csv", "text/csv")
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as error:
            st.error("The saved results could not be read. Run the full benchmark with --publish to regenerate them.")
    with st.expander("Explore the benchmark", expanded=True):
        frame = pd.DataFrame([{'ID':q['id'],'Question':q['question'],'Difficulty':q['difficulty'],
                               'Answerable':q['answerable'],'Reviewed by':q.get('reviewed_by') or 'Pending'} for q in questions])
        st.dataframe(frame, hide_index=True, width='stretch')


with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-icon">◈</span>EvidenceIQ</div><div class="brand-sub">RETAIL INTELLIGENCE</div>', unsafe_allow_html=True)
    st.caption("WORKSPACE")
    page = st.radio("Navigate", ["Overview", "Ask the analyst", "Evaluation"], label_visibility="collapsed")
    st.markdown('<div class="side-note"><b>Built on evidence.</b><br>Online Retail II<br>Dec 2009 — Dec 2011<br><br>Local data · Local model<br>ZAKA × SnowHeap</div>', unsafe_allow_html=True)

try:
    if page == "Evaluation":
        evaluation()
    elif not DB.exists():
        heading("GETTING STARTED", "Connect your retail data.", "Build the local database once to unlock the dashboard.")
        st.info("The database is missing. Add the Online Retail II Excel file to data/raw, then run the database builder.")
        st.code("python src/build_db.py", language="bash")
    elif page == "Overview":
        overview()
    else:
        analyst()
except duckdb.Error as error:
    st.error("The database could not be read. Close any notebook writing to it, then reload this page.")
    with st.expander("Database details"):
        st.text(str(error))
st.markdown('<div class="footer">EVIDENCEIQ &nbsp; / &nbsp; University capstone · Historical retail data · GBP</div>', unsafe_allow_html=True)
