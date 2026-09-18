"""Regression cases for query repair and business populations, without Gemma."""
import pytest

from test_notebooks import load_notebook


@pytest.fixture
def sql_runtime():
    return load_notebook('06_evaluation.ipynb')


def test_month_comparison_can_scope_dates_inside_conditional_aggregates(sql_runtime):
    sql = """SELECT
      MAX(CASE WHEN invoice_month = '2010-06' THEN net_revenue END)
        - MAX(CASE WHEN invoice_month = '2010-05' THEN net_revenue END) AS difference
      FROM dim_month"""
    question = 'Compare June 2010 with May 2010 revenue in pounds.'
    assert sql_runtime['query_scope_problem'](sql, question) is None
    # The accepted conditional form must compute the same result as two rows.
    log = []
    result = sql_runtime['run_sql'](sql, log, question)
    raw = sql_runtime['run_sql']("SELECT invoice_month, net_revenue FROM dim_month WHERE invoice_month IN ('2010-05','2010-06') ORDER BY invoice_month", log)
    assert result['ok'] and raw['ok']
    assert result['rows'][0]['difference'] == pytest.approx(raw['rows'][1]['net_revenue'] - raw['rows'][0]['net_revenue'])


@pytest.mark.parametrize('sql', [
    "SELECT SUM(revenue) AS revenue, 2010 AS year FROM sales WHERE NOT is_cancellation",
    "SELECT SUM(CASE WHEN year(invoice_date)=2010 THEN revenue ELSE 0 END) AS chosen, SUM(revenue) AS all_time FROM sales WHERE NOT is_cancellation",
])
def test_year_label_or_one_scoped_aggregate_cannot_hide_unscoped_total(sql_runtime, sql):
    assert sql_runtime['query_scope_problem'](sql, 'Report overall revenue for the year 2010.')


def test_country_name_repair_preserves_the_real_population(sql_runtime):
    question = 'Report revenue from the UK in the year 2010.'
    query = "SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 AND country='UK'"
    feedback = sql_runtime['query_scope_problem'](query, question)
    assert feedback and 'United Kingdom' in feedback
    assert sql_runtime['query_scope_problem'](query.replace("'UK'", "'United Kingdom'"), question) is None


@pytest.mark.parametrize('filter_clause', ['AND is_product', 'AND NOT is_outlier', 'AND quantity > 0'])
def test_country_revenue_does_not_inherit_product_or_unit_filters(sql_runtime, filter_clause):
    question = 'Rank countries by revenue during 2010.'
    query = "SELECT country,SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 {extra} GROUP BY country"
    assert sql_runtime['query_scope_problem'](query.format(extra=filter_clause), question)
    assert sql_runtime['query_scope_problem'](query.format(extra=''), question) is None


def test_customer_ranking_is_grouped_by_identified_customers(sql_runtime):
    question = 'Which three customers generated the most revenue in 2010?'
    query = "SELECT {key}, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 {extra} GROUP BY {key} ORDER BY revenue DESC LIMIT 3"
    assert sql_runtime['query_scope_problem'](query.format(key='country', extra='AND customer_id IS NOT NULL'), question)
    assert sql_runtime['query_scope_problem'](query.format(key='customer_id', extra=''), question)
    assert sql_runtime['query_scope_problem'](query.format(key='customer_id', extra='AND customer_id IS NOT NULL'), question) is None


def test_yearly_customer_revenue_cannot_use_all_time_dimension_totals(sql_runtime):
    query = "SELECT customer_id,net_revenue FROM dim_customer WHERE year(first_order)=2010 ORDER BY net_revenue DESC LIMIT 3"
    assert sql_runtime['query_scope_problem'](query, 'Which three customers generated the most revenue in 2010?')


def test_country_revenue_avoids_customer_join_that_drops_guests(sql_runtime):
    query = """SELECT s.country,SUM(s.revenue) AS revenue FROM sales s
        JOIN dim_customer c ON s.customer_id=c.customer_id
        WHERE NOT s.is_cancellation AND year(s.invoice_date)=2010 GROUP BY s.country"""
    assert sql_runtime['query_scope_problem'](query, 'Rank countries by revenue in 2010.')


def test_completed_orders_require_distinct_invoices(sql_runtime):
    question = 'Which three customers placed the most orders in 2010?'
    query = "SELECT customer_id,COUNT({argument}) AS orders FROM sales WHERE NOT is_cancellation AND customer_id IS NOT NULL AND year(invoice_date)=2010 GROUP BY customer_id ORDER BY orders DESC LIMIT 3"
    for argument in ['*', 'invoice_no', 'DISTINCT customer_id']:
        assert sql_runtime['query_scope_problem'](query.format(argument=argument), question)
    assert sql_runtime['query_scope_problem'](query.format(argument='DISTINCT invoice_no'), question) is None


def test_month_revenue_ranking_keeps_completeness_and_net_metric(sql_runtime):
    question = 'Which complete month had the lowest revenue?'
    query = 'SELECT invoice_month,net_revenue,trading_days FROM dim_month WHERE is_complete_month ORDER BY net_revenue LIMIT 1'
    assert sql_runtime['query_scope_problem'](query, question) is None
    assert sql_runtime['query_scope_problem'](query.replace('WHERE is_complete_month', ''), question)
    assert sql_runtime['query_scope_problem'](query.replace('net_revenue', 'gross_revenue'), question)


def test_verifier_feedback_reaches_sql_generation_and_immediate_repair(sql_runtime):
    feedback = 'The previous attempt omitted the requested country label; preserve that label and the date scope.'
    prompts = []
    sql_calls = []

    def model(system, prompt, shape):
        if shape is sql_runtime['PLAN_SHAPE']:
            return {'sufficient_data': True, 'steps': [{'step': 1, 'tool': 'run_sql', 'objective': 'Fetch revenue by country'}]}
        if shape is sql_runtime['SQL_SHAPE']:
            prompts.append(prompt)
            return {'sql': 'SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation GROUP BY country'}
        if shape is sql_runtime['ANSWER_SHAPE']:
            return {'findings': 'Sweden revenue was 120.', 'claims': [], 'insufficient_data': False}
        raise AssertionError('Unexpected model call')

    def run_sql(sql, log, question=None):
        sql_calls.append(sql)
        call = {'n': len(log), 'tool': 'run_sql', 'code': sql, 'ok': len(sql_calls) > 1,
                'rows': [{'country': 'Sweden', 'revenue': 120}] if len(sql_calls) > 1 else [],
                'error': 'Missing requested year restriction' if len(sql_calls) == 1 else None}
        log.append(call)
        return call

    sql_runtime['ask_gemma'] = model
    sql_runtime['run_sql'] = run_sql
    sql_runtime['tier2']('Show revenue for each country during 2010.', feedback=feedback)
    assert len(prompts) == 2
    assert all(feedback in prompt for prompt in prompts)
    assert 'Missing requested year restriction' in prompts[1]


def test_flag_mention_does_not_prove_population_exclusion(sql_runtime):
    question = 'Report revenue by country.'
    query = 'SELECT country,SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation OR country=\'Sweden\' GROUP BY country'
    assert sql_runtime['query_scope_problem'](query, question)
    assert sql_runtime['query_scope_problem'](query.replace(' OR ', ' AND '), question) is None
    monthly = 'SELECT invoice_month,net_revenue FROM dim_month WHERE is_complete_month=FALSE ORDER BY net_revenue LIMIT 1'
    assert sql_runtime['query_scope_problem'](monthly, 'Which month had the lowest revenue?')


def test_negated_compound_filter_obeys_de_morgan(sql_runtime):
    query = "SELECT SUM(revenue) AS revenue FROM sales WHERE NOT (is_cancellation {operator} country='Sweden')"
    assert sql_runtime['query_scope_problem'](query.format(operator='AND'), 'Report overall revenue.')
    assert sql_runtime['query_scope_problem'](query.format(operator='OR'), 'Report overall revenue.') is None


def test_aggregate_filter_cannot_scope_a_neighbouring_aggregate(sql_runtime):
    query = "SELECT SUM(revenue) FILTER (WHERE year(invoice_date)=2010) AS chosen{extra} FROM sales WHERE NOT is_cancellation"
    question = 'Report overall revenue during 2010.'
    assert sql_runtime['query_scope_problem'](query.format(extra=',SUM(revenue) AS all_time'), question)
    assert sql_runtime['query_scope_problem'](query.format(extra=''), question) is None


def test_year_in_only_one_or_branch_does_not_restrict_the_other(sql_runtime):
    query = "SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND (year(invoice_date)=2010 {operator} country='Sweden')"
    question = 'Report overall revenue during 2010.'
    assert sql_runtime['query_scope_problem'](query.format(operator='OR'), question)
    assert sql_runtime['query_scope_problem'](query.format(operator='AND'), question) is None


def test_case_else_cannot_reintroduce_revenue_from_other_dates(sql_runtime):
    query = "SELECT SUM(CASE WHEN year(invoice_date)=2010 THEN revenue ELSE {other} END) AS revenue FROM sales WHERE NOT is_cancellation"
    question = 'Report overall revenue during 2010.'
    assert sql_runtime['query_scope_problem'](query.format(other='revenue'), question)
    assert sql_runtime['query_scope_problem'](query.format(other='0'), question) is None


def test_missing_customer_id_filter_receives_one_concrete_repair(sql_runtime):
    sql = 'SELECT customer_id,SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 GROUP BY customer_id ORDER BY revenue DESC LIMIT 3'
    question = 'Which three customers generated the most revenue in 2010?'
    error = sql_runtime['query_scope_problem'](sql, question)
    prompt = sql_runtime['repair_prompt'](question, 'Rank customers by revenue', sql, error)
    assert 'AND customer_id IS NOT NULL' in prompt
    assert 'before GROUP BY' in prompt
    # The failed query is already grouped correctly; the repair preserves it.
    edits = prompt.split('REQUIRED EDIT')[1]
    assert 'do not group a customer ranking by country' not in edits
    assert sql_runtime['SCHEMA'].strip() not in prompt
    assert sql_runtime['EXAMPLES'].strip() not in prompt
    first_prompt = sql_runtime['sql_prompt'](question, 'Rank customers by revenue')
    assert sql_runtime['SCHEMA'].strip() not in first_prompt


@pytest.mark.parametrize('join', [
    'JOIN dim_month m ON 1=1',
    'CROSS JOIN dim_month m',
    "JOIN dim_month m ON s.invoice_month=m.invoice_month OR m.invoice_month='2010-05'",
])
def test_unlinked_month_join_cannot_repeat_all_time_sales(sql_runtime, join):
    query = f"SELECT m.invoice_month,SUM(s.revenue) AS revenue FROM sales s {join} WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06') GROUP BY m.invoice_month"
    assert sql_runtime['query_scope_problem'](query, 'Compare revenue in May 2010 with June 2010.')


@pytest.mark.parametrize('expression', ['SUM(m.trading_days)', 'SUM(m.net_revenue)', 'AVG(m.net_revenue)', 'SUM(CASE WHEN m.invoice_month=\'2010-05\' THEN m.trading_days ELSE 0 END)'])
def test_month_measures_are_not_aggregated_at_invoice_line_grain(sql_runtime, expression):
    query = f"SELECT m.invoice_month,SUM(s.revenue) AS revenue,{expression} AS repeated_measure FROM sales s JOIN dim_month m ON s.invoice_month=m.invoice_month WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06') GROUP BY m.invoice_month"
    assert sql_runtime['query_scope_problem'](query, 'Compare revenue per trading day in May 2010 with June 2010.')


def test_date_link_and_grouped_day_context_keep_the_correct_population(sql_runtime):
    query = """SELECT s.invoice_month,SUM(s.revenue) AS revenue,MAX(m.trading_days) AS trading_days
        FROM sales s JOIN dim_month m ON s.invoice_month=m.invoice_month
        WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06')
        GROUP BY s.invoice_month ORDER BY s.invoice_month"""
    question = 'Compare revenue per trading day in May 2010 with June 2010.'
    assert sql_runtime['query_scope_problem'](query, question) is None
    log = []
    actual = sql_runtime['run_sql'](query, log, question)
    expected = sql_runtime['run_sql']("SELECT invoice_month,net_revenue AS revenue,trading_days FROM dim_month WHERE invoice_month IN ('2010-05','2010-06') ORDER BY invoice_month", log)
    assert actual['ok'] and expected['ok']
    for left, right in zip(actual['rows'], expected['rows']):
        assert left['invoice_month'] == right['invoice_month']
        assert left['trading_days'] == right['trading_days']
        assert left['revenue'] == pytest.approx(right['revenue'])


def test_monthly_preaggregation_can_use_month_measures_once(sql_runtime):
    query = """WITH monthly AS (
        SELECT invoice_month,SUM(revenue) AS revenue FROM sales
        WHERE NOT is_cancellation AND year(invoice_date)=2010 GROUP BY invoice_month)
        SELECT SUM(m.trading_days) AS trading_days FROM monthly s JOIN dim_month m ON s.invoice_month=m.invoice_month"""
    assert sql_runtime['query_scope_problem'](query, 'What were the trading days in 2010?') is None


def test_cte_and_subquery_wrappers_do_not_hide_an_unlinked_fact_join(sql_runtime):
    for relation in ['sales', '(SELECT * FROM sales)']:
        query = f"SELECT m.invoice_month,SUM(s.revenue) AS revenue FROM {relation} s CROSS JOIN dim_month m WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06') GROUP BY m.invoice_month"
        assert sql_runtime['query_scope_problem'](query, 'Compare revenue in May 2010 with June 2010.')
    cte = "WITH raw_sales AS (SELECT * FROM sales) SELECT m.invoice_month,SUM(s.revenue) AS revenue FROM raw_sales s CROSS JOIN dim_month m WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06') GROUP BY m.invoice_month"
    assert sql_runtime['query_scope_problem'](cte, 'Compare revenue in May 2010 with June 2010.')


def test_month_join_using_is_allowed_in_both_orientations(sql_runtime):
    for join in ['sales s JOIN dim_month m USING(invoice_month)', 'dim_month m JOIN sales s USING(invoice_month)']:
        query = f"SELECT s.invoice_month,SUM(s.revenue) AS revenue FROM {join} WHERE NOT s.is_cancellation AND m.invoice_month IN ('2010-05','2010-06') GROUP BY s.invoice_month"
        assert sql_runtime['query_scope_problem'](query, 'Compare revenue in May 2010 with June 2010.') is None


@pytest.mark.parametrize('country', ['Sweden', 'Canada', 'United Arab Emirates'])
def test_named_country_guard_uses_database_markets(sql_runtime, country):
    question = f'How much revenue came from {country} during 2010?'
    query = "SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010{scope}"
    assert sql_runtime['query_scope_problem'](query.format(scope=f" AND country='{country}'"), question) is None
    assert sql_runtime['query_scope_problem'](query.format(scope=" AND country='United Kingdom'"), question)
    assert sql_runtime['query_scope_problem'](query.format(scope=''), question)


def test_named_country_comparison_accepts_both_countries_and_individual_steps(sql_runtime):
    question = 'Compare Sweden and Denmark revenue in 2010.'
    query = "SELECT country,SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 AND country {scope} GROUP BY country"
    for scope in ["IN ('Sweden','Denmark')", "='Sweden'", "='Denmark'"]:
        assert sql_runtime['query_scope_problem'](query.format(scope=scope), question) is None
    assert sql_runtime['query_scope_problem'](query.format(scope="IN ('Sweden','Canada')"), question)


def test_country_share_keeps_an_unrestricted_denominator(sql_runtime):
    question = 'What share of revenue came from France in 2010?'
    query = "SELECT SUM(CASE WHEN country='France' THEN revenue ELSE 0 END)/SUM(revenue)*100 AS share_pct FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010"
    assert sql_runtime['query_scope_problem'](query, question) is None
    assert sql_runtime['query_scope_problem'](query.replace("country='France'", "country='United Kingdom'"), question)


def test_country_case_comparison_keeps_each_measure_scoped(sql_runtime):
    query = "SELECT SUM(CASE WHEN country='Sweden' THEN revenue ELSE 0 END) AS sweden,SUM(CASE WHEN country='Denmark' THEN revenue ELSE 0 END) AS denmark FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010"
    question = 'Compare Sweden and Denmark revenue in 2010.'
    assert sql_runtime['query_scope_problem'](query, question) is None
    assert sql_runtime['query_scope_problem'](query.replace("CASE WHEN country='Denmark' THEN revenue ELSE 0 END", 'revenue'), question)


def test_country_exclusion_selects_the_other_markets(sql_runtime):
    question = 'Rank countries by revenue during 2010 outside the UK.'
    query = "SELECT country,SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010{scope} GROUP BY country"
    assert sql_runtime['query_scope_problem'](query.format(scope=" AND country<>'United Kingdom'"), question) is None
    assert sql_runtime['query_scope_problem'](query.format(scope=" AND country='United Kingdom'"), question)
    assert sql_runtime['query_scope_problem'](query.format(scope=''), question)
    multiple = 'Rank countries by revenue during 2010 excluding Sweden and Denmark.'
    assert sql_runtime['query_scope_problem'](query.format(scope=" AND country NOT IN ('Sweden','Denmark')"), multiple) is None


def test_named_country_filter_cannot_be_bypassed_with_or(sql_runtime):
    question = 'How much revenue came from Canada during 2010?'
    query = "SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010 AND (country='Canada' OR quantity>0)"
    assert sql_runtime['query_scope_problem'](query, question)


def test_country_share_can_fetch_its_denominator_in_a_separate_step(sql_runtime):
    question = 'What percentage of revenue came from France in 2010?'
    total = 'SELECT SUM(revenue) AS total_revenue FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2010'
    assert sql_runtime['query_scope_problem'](total, question) is None
    numerator = total + " AND country='France'"
    assert sql_runtime['query_scope_problem'](numerator, question) is None
    assert sql_runtime['query_scope_problem'](total + " AND country='United Kingdom'", question)
