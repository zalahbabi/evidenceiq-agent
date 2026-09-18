"""Public wording and completeness checks use tool facts, without a model call."""
from copy import deepcopy

import pytest

from test_notebooks import load_notebook


@pytest.fixture(params=['05_tier3_verification.ipynb', '06_evaluation.ipynb'])
def runtime(request):
    return load_notebook(request.param)


def result(rows, sql, question='Show the recorded measurements.'):
    return {'question': question, 'findings': '', 'limitations': '', 'claims': [],
            'log': [{'n': 4, 'tool': 'run_sql', 'ok': True, 'code': sql, 'rows': rows}],
            'insufficient_data': False}


def checked(runtime, answer):
    return runtime['verify'](runtime['recover_evidence_claims'](answer))


def test_wrong_country_prose_cannot_survive_verified_rendering(runtime):
    answer = result([{'country': 'France', 'revenue': 120}],
                    "SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation GROUP BY country")
    answer.update(findings='Germany made £120 because its marketing worked.',
                  limitations='Germany had strong demand.')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'France generated £120.00 in revenue' in public['findings']
    assert 'Germany' not in public['findings'] + public['limitations']
    assert 'marketing' not in public['findings']
    assert 'Cancellations are excluded.' in public['findings']
    assert all('France' in claim['text'] for claim in public['claims'])


def test_scalar_query_retains_country_filter_label(runtime):
    answer = result([{'revenue': 120}],
                    "SELECT SUM(revenue) AS revenue FROM sales WHERE country = 'France' AND NOT is_cancellation")
    answer['findings'] = 'Germany revenue was £120.'
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'France' in public['findings'] and 'Germany' not in public['findings']


def test_customer_identifiers_and_months_are_labels(runtime):
    answer = result([{'customer_id': 14911, 'orders': 17}],
                    'SELECT customer_id, COUNT(DISTINCT invoice_no) AS orders FROM sales WHERE NOT is_cancellation GROUP BY customer_id')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'Customer 14911' in public['findings'] and '17 completed orders' in public['findings']
    assert [claim['value'] for claim in public['claims']] == [17]
    month = result([{'invoice_month': '2010-04', 'is_complete_month': True, 'trading_days': 22}],
                   "SELECT invoice_month, is_complete_month, trading_days FROM dim_month WHERE invoice_month = '2010-04'")
    public = runtime['render_verified_answer'](checked(runtime, month))
    assert 'April 2010: Yes, this is a complete reporting month.' in public['findings']
    assert 'April 2010: 22 trading days.' in public['findings']


def test_scalar_stock_code_stays_an_identifier_after_rendering(runtime):
    answer = result([{'revenue': 120}],
                    "SELECT SUM(revenue) AS revenue FROM sales WHERE stock_code = '22423' AND NOT is_cancellation",
                    'How much revenue did stock code 22423 generate?')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'Stock code 22423' in public['findings']
    assert runtime['undeclared_numbers'](public) == []


def test_float_customer_id_is_a_label_only_with_its_prefix(runtime):
    answer = result([{'customer_id': 14911.0, 'orders': 188}],
                    'SELECT customer_id, COUNT(DISTINCT invoice_no) AS orders FROM sales WHERE NOT is_cancellation AND customer_id IS NOT NULL GROUP BY customer_id')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'Customer 14911' in public['findings'] and '188 completed orders' in public['findings']
    assert runtime['undeclared_numbers'](public) == []
    public['findings'] += ' We sold 14911 items.'
    assert 14911 in runtime['undeclared_numbers'](public)


def test_missing_ranked_measurements_are_recovered_from_cells(runtime):
    answer = result([{'country': 'Spain', 'revenue': 140}, {'country': 'France', 'revenue': 120},
                     {'country': 'Germany', 'revenue': 100}],
                    'SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation GROUP BY country ORDER BY revenue DESC LIMIT 3',
                    'Show the top 3 countries by revenue.')
    answer['claims'] = [runtime['evidence_claim'](answer['log'][0], 0, 'revenue', 'Spain earned £140.', 'GBP')]
    partial = runtime['verify'](deepcopy(answer))
    assert runtime['completeness_problems'](partial)
    recovered = checked(runtime, answer)
    assert not runtime['completeness_problems'](recovered)
    assert len(recovered['claims']) == 3
    assert all(claim['status'] == 'supported' for claim in recovered['claims'])


def test_top_n_only_demands_more_rows_when_query_truncates_too_early(runtime):
    answer = result([{'country': 'Spain', 'revenue': 140}],
                    'SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation GROUP BY country ORDER BY revenue DESC LIMIT 1',
                    'Show the top 3 countries by revenue.')
    assert any('limits the result to 1' in issue for issue in runtime['completeness_problems'](checked(runtime, answer)))
    answer['log'][0]['code'] = answer['log'][0]['code'].replace('LIMIT 1', 'LIMIT 3')
    # A database may genuinely have only one country; never invent two others.
    assert not runtime['completeness_problems'](checked(runtime, answer))


def test_month_comparison_requires_both_periods_and_percentage(runtime):
    answer = result([{'invoice_month': '2010-04', 'net_revenue': 120}],
                    "SELECT invoice_month, net_revenue FROM dim_month WHERE invoice_month IN ('2010-04', '2010-03')",
                    'Compare April 2010 with March 2010 revenue and report the percentage change.')
    issues = runtime['completeness_problems'](checked(runtime, answer))
    assert any('each requested month' in issue for issue in issues)
    assert any('percentage change is missing' in issue for issue in issues)
    answer['log'][0]['rows'].append({'invoice_month': '2010-03', 'net_revenue': 100})
    answer['claims'].append({'value': 20, 'calc': 'pct_change', 'inputs': [120, 100], 'unit': '%',
                             'text': 'Wrong narrative from the model',
                             'input_cells': [{'from_call': 4, 'row': 0, 'column': 'net_revenue'},
                                             {'from_call': 4, 'row': 1, 'column': 'net_revenue'}]})
    complete = checked(runtime, answer)
    assert not runtime['completeness_problems'](complete)
    public = runtime['render_verified_answer'](complete)
    assert 'higher in April 2010 than in March 2010' in public['findings']
    assert '20.00%' in public['findings']
    assert 'Wrong narrative' not in public['findings']


def test_tie_sensitive_extremum_requests_preserve_all_winners(runtime):
    answer = result([{'invoice_month': '2010-03', 'trading_days': 24}],
                    'SELECT invoice_month, trading_days FROM dim_month ORDER BY trading_days DESC LIMIT 1',
                    'Which month had the most trading days?')
    assert any('hide tied winners' in issue for issue in runtime['completeness_problems'](checked(runtime, answer)))
    answer['log'][0]['code'] = 'SELECT invoice_month, trading_days FROM dim_month WHERE trading_days = (SELECT MAX(trading_days) FROM dim_month)'
    answer['log'][0]['rows'].append({'invoice_month': '2010-04', 'trading_days': 24})
    recovered = checked(runtime, answer)
    assert not runtime['completeness_problems'](recovered)
    public = runtime['render_verified_answer'](recovered)
    assert 'March 2010' in public['findings'] and 'April 2010' in public['findings']


def test_singular_peak_revenue_is_not_automatically_rejected_for_limit_one(runtime):
    answer = result([{'invoice_month': '2010-03', 'net_revenue': 120}],
                    'SELECT invoice_month, net_revenue FROM dim_month WHERE is_complete_month ORDER BY net_revenue DESC LIMIT 1',
                    'Which month had the highest revenue?')
    assert not runtime['completeness_problems'](checked(runtime, answer))


def test_failed_or_empty_sql_does_not_create_claims(runtime):
    answer = result([{'revenue': 999}], 'SELECT SUM(revenue) AS revenue FROM sales')
    answer['log'][0]['ok'] = False
    answer['findings'] = 'We earned £999.'
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert not public['claims'] and '999' not in public['findings']
    answer['log'][0].update(ok=True, rows=[])
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert public['findings'] == 'No usable data was returned for this request.'


def test_unsupported_query_scope_cannot_be_recovered_as_facts(runtime):
    answer = result([{'revenue': 120}], 'SELECT SUM(revenue) AS revenue FROM sales',
                    'What was our total revenue in 2011?')
    assert not runtime['recover_evidence_claims'](answer)['claims']


def test_known_data_gap_and_cancellation_caveats_are_preserved(runtime):
    gap = result([], '', 'What was our profit margin in 2011?')
    gap['log'] = []
    gap['insufficient_data'] = True
    public = runtime['render_verified_answer'](checked(runtime, gap))
    assert 'cost' in public['findings'] and 'not' in public['findings']
    answer = result([{'cancellation_rate': 15}], 'SELECT 15 AS cancellation_rate')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'not the share of orders later cancelled' in public['limitations']
    assert 'Cancellations are excluded' not in public['findings']


def test_rendering_ignores_reference_answer_fields(runtime):
    answer = result([{'revenue': 120}], 'SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation')
    answer.update(gt_value=999, gt_answer='Germany earned £999', expected_rows=[{'country': 'Germany', 'revenue': 999}])
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert '120' in public['findings'] and '999' not in public['findings'] and 'Germany' not in public['findings']


def test_shared_year_per_day_comparison_needs_both_comparisons(runtime):
    question = 'Revenue dropped from March to April 2010. How big was the drop, and does it look different per trading day?'
    assert runtime['requested_periods'](question) == ['2010-03', '2010-04']
    answer = result([{'invoice_month': '2010-03', 'net_revenue': 120, 'revenue_per_day': 12},
                     {'invoice_month': '2010-04', 'net_revenue': 90, 'revenue_per_day': 9}],
                    "SELECT invoice_month, net_revenue, net_revenue / trading_days AS revenue_per_day FROM dim_month WHERE invoice_month IN ('2010-04', '2010-03')",
                    question)
    answer['claims'] = [{'value': -25, 'calc': 'pct_change', 'inputs': [90, 120],
                         'input_cells': [{'from_call': 4, 'row': 1, 'column': 'net_revenue'},
                                         {'from_call': 4, 'row': 0, 'column': 'net_revenue'}]}]
    partial = checked(runtime, answer)
    assert any('change in revenue per trading day' in issue for issue in runtime['completeness_problems'](partial))
    answer['claims'].append({'value': -25, 'calc': 'pct_change', 'inputs': [9, 12],
                            'input_cells': [{'from_call': 4, 'row': 1, 'column': 'revenue_per_day'},
                                            {'from_call': 4, 'row': 0, 'column': 'revenue_per_day'}]})
    complete = checked(runtime, answer)
    assert not runtime['completeness_problems'](complete)
    public = runtime['render_verified_answer'](complete)
    assert 'Revenue per trading day was lower in April 2010 than in March 2010' in public['findings']
    assert '-25.00%' in public['findings']


def test_all_null_query_result_has_no_usable_data(runtime):
    answer = result([{'revenue': None}], 'SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert public['findings'] == 'No usable data was returned for this request. Cancellations are excluded.'


def test_country_comparison_requires_requested_pound_difference(runtime):
    answer = result([{'country': 'Germany', 'revenue': 120}, {'country': 'France', 'revenue': 100}],
                    "SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND country IN ('Germany', 'France') GROUP BY country",
                    'Did Germany generate more revenue than France, and by how much in pounds?')
    partial = checked(runtime, answer)
    assert any('difference in pounds is missing' in issue for issue in runtime['completeness_problems'](partial))
    answer['claims'].append({'value': 20, 'calc': 'difference', 'inputs': [120, 100],
                            'input_cells': [{'from_call': 4, 'row': 0, 'column': 'revenue'},
                                            {'from_call': 4, 'row': 1, 'column': 'revenue'}]})
    complete = checked(runtime, answer)
    assert not runtime['completeness_problems'](complete)
    findings = runtime['render_verified_answer'](complete)['findings']
    assert 'higher in Germany than in France' in findings and 'difference of £20.00' in findings


def test_share_question_requires_computed_share(runtime):
    answer = result([{'uk_revenue': 120, 'total_revenue': 400}],
                    "SELECT SUM(CASE WHEN country='United Kingdom' THEN revenue ELSE 0 END) AS uk_revenue, SUM(revenue) AS total_revenue FROM sales WHERE NOT is_cancellation",
                    'What share of revenue came from the UK?')
    partial = checked(runtime, answer)
    assert any('requests a share' in issue for issue in runtime['completeness_problems'](partial))
    answer['claims'].append({'value': 30, 'calc': 'share', 'inputs': [120, 400],
                            'input_cells': [{'from_call': 4, 'row': 0, 'column': 'uk_revenue'},
                                            {'from_call': 4, 'row': 0, 'column': 'total_revenue'}]})
    complete = checked(runtime, answer)
    assert not runtime['completeness_problems'](complete)
    assert 'accounted for 30.00% of the reported total' in runtime['render_verified_answer'](complete)['findings']


@pytest.mark.parametrize(('word', 'counts', 'winners'), [('most', [21, 24, 24], [1, 2]),
                                                       ('fewest', [21, 21, 24], [0, 1])])
def test_complete_month_result_displays_only_all_tied_extrema(runtime, word, counts, winners):
    rows = [{'invoice_month': f'2013-0{index + 1}', 'trading_days': days} for index, days in enumerate(counts)]
    answer = result(rows, 'SELECT invoice_month, trading_days FROM dim_month ORDER BY invoice_month',
                    f'Which month had the {word} trading days?')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    visible = runtime['claims_to_show'](public)
    assert [claim['row'] for claim in visible] == winners
    assert public['answer_selection']['rows'] == winners
    assert len(public['claims']) == 3 and len(public['log'][0]['rows']) == 3
    assert all(claim['status'] == 'supported' for claim in public['claims'])
    assert len([claim for claim in public['claims'] if claim['display_role'] == 'context']) == 1
    assert 'could not' not in public['limitations']
    assert public['findings'].count('trading days.') == 2


@pytest.mark.parametrize('suffix', ['LIMIT 1', "WHERE invoice_month = '2013-02'"])
def test_partial_month_query_cannot_assert_global_tie_coverage(runtime, suffix):
    answer = result([{'invoice_month': '2013-02', 'trading_days': 24}],
                    'SELECT invoice_month, trading_days FROM dim_month ' + suffix,
                    'Which month had the most trading days?')
    public = runtime['render_verified_answer'](checked(runtime, answer))
    assert 'answer_selection' not in public
    assert all('display_role' not in claim for claim in public['claims'])
    if suffix == 'LIMIT 1':
        assert any('hide tied winners' in issue for issue in runtime['completeness_problems'](public))


def test_percentage_change_question_is_not_a_share_request(runtime):
    answer = result([{'invoice_month': '2010-04', 'net_revenue': 120},
                     {'invoice_month': '2010-03', 'net_revenue': 100}],
                    "SELECT invoice_month, net_revenue FROM dim_month WHERE invoice_month IN ('2010-04', '2010-03')",
                    'Compare April 2010 with March 2010 revenue: by what percentage did it change?')
    answer['claims'] = [{'value': 20, 'calc': 'pct_change', 'inputs': [120, 100],
                         'input_cells': [{'from_call': 4, 'row': 0, 'column': 'net_revenue'},
                                         {'from_call': 4, 'row': 1, 'column': 'net_revenue'}]}]
    assert not runtime['completeness_problems'](checked(runtime, answer))
