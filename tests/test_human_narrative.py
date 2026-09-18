"""Useful explanations must stay tied to verified facts and explicit limits."""
from copy import deepcopy

import pytest

from test_notebooks import load_notebook


@pytest.fixture(params=['05_tier3_verification.ipynb', '06_evaluation.ipynb'])
def runtime(request):
    namespace = load_notebook(request.param)
    namespace['ask_gemma'] = lambda *args: pytest.fail('Narrative tests must not call a model')
    return namespace


def public_text(answer):
    return ' '.join([answer.get('findings', ''), answer.get('interpretation', ''),
                     *answer.get('suggested_next_steps', [])])


def test_actual_revenue_total_explains_use_and_offers_scoped_followup(runtime):
    answer = runtime['tier3']('What was our total revenue in 2011?')
    assert '£9,809,614.01' in answer['findings']
    assert 'sales baseline' in answer['interpretation']
    assert 'How did revenue change by month in 2011?' in answer['suggested_next_steps']
    assert not runtime['undeclared_numbers'](answer)


def test_actual_product_ranking_leads_with_leader_keeps_all_claims(runtime):
    answer = runtime['tier3']('Top 3 products in 2010?')
    assert 'REGENCY CAKESTAND 3 TIER leads' in answer['findings']
    assert 'among the products shown' in answer['findings']
    assert '£184,128.54' in answer['findings']
    assert 'stock review' in answer['interpretation']
    assert 'Which products sold the most units in 2010?' in answer['suggested_next_steps']
    assert len(runtime['claims_to_show'](answer)) == 3
    assert not runtime['undeclared_numbers'](answer)


def test_actual_month_comparison_explains_reporting_length(runtime):
    answer = runtime['tier3']('Did November 2011 beat October 2011 on revenue, and by what percentage?')
    assert answer['findings'].startswith('Yes. Revenue was higher in November 2011')
    assert '30.63%' in answer['findings']
    assert 'same number of trading days' in answer['interpretation']
    assert 'do not establish its cause' in answer['interpretation']
    assert 'What was revenue per trading day in October 2011 and November 2011?' in answer['suggested_next_steps']
    assert not runtime['undeclared_numbers'](answer)


def test_decline_retains_signed_verified_percentage(runtime):
    answer = runtime['tier3']('Did October 2011 beat November 2011 on revenue, and by what percentage?')
    percentage = next(claim for claim in answer['claims'] if claim.get('calc') == 'pct_change')
    assert 'lower in October 2011' in answer['findings']
    assert f"{percentage['value']:.2f}%" in answer['findings']
    assert not runtime['undeclared_numbers'](answer)


def test_partial_and_missing_months_explain_what_to_do_next(runtime):
    partial = runtime['tier3']('Is December 2011 a complete month in the dataset?')
    assert '8 trading days' in partial['findings']
    assert 'Use revenue per trading day' in partial['interpretation']
    assert partial['suggested_next_steps'][0] == 'What was revenue per trading day in December 2011?'
    empty = runtime['tier3']('Is December 2099 a complete month in the dataset?')
    assert 'No usable data' in empty['findings']
    assert 'does not establish that sales were zero' in empty['interpretation']
    assert not empty['claims']
    assert not runtime['undeclared_numbers'](empty)


def test_profit_refusal_offers_answerable_alternative(runtime):
    answer = runtime['tier3']('What was our profit margin in 2011?')
    assert answer['insufficient_data']
    assert 'requires cost data' in answer['interpretation']
    assert 'What was total revenue across the available dataset?' in answer['suggested_next_steps']
    assert not runtime['undeclared_numbers'](answer)


def test_model_causality_and_unbound_numbers_do_not_survive(runtime):
    answer = runtime['tier3']('What was our total revenue in 2011?')
    answer.update(findings='A promotion caused 80% of revenue.',
                  interpretation='Germany grew because prices dropped by 80%.',
                  suggested_next_steps=['Forecast 80% growth.'])
    rendered = runtime['render_verified_answer'](answer)
    assert 'promotion' not in public_text(rendered).lower()
    assert '80%' not in public_text(rendered)
    assert 'Germany' not in public_text(rendered)
    assert not runtime['undeclared_numbers'](rendered)


def test_share_context_uses_only_verified_magnitude(runtime):
    answer = {'question': 'What share came from the selected group?', 'findings': '', 'limitations': '',
              'claims': [{'status': 'supported', 'calc': 'share', 'value': 75, 'inputs': [300, 400], 'unit': '%'}],
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql', 'code': 'SELECT 300 AS part, 400 AS total',
                       'rows': [{'part': 300, 'total': 400}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](answer))
    assert '75.00%' in answer['findings']
    assert 'Most of the reported total is concentrated' in answer['interpretation']
    assert not runtime['undeclared_numbers'](answer)


def test_unequal_trading_days_are_context_not_invented_cause(runtime):
    answer = runtime['tier3']('Did November 2011 beat October 2011 on revenue, and by what percentage?')
    altered = deepcopy(answer)
    # Change the mocked evidence and its bound claim together; this probes the
    # wording rule without pretending the local historical dataset changed.
    for call in altered['log']:
        if call.get('tool') == 'run_sql':
            for index, row in enumerate(call['rows']):
                if row.get('invoice_month') == '2011-10':
                    row['trading_days'] = 25
                    for claim in altered['claims']:
                        if claim.get('from_call') == call['n'] and claim.get('row') == index and claim.get('column') == 'trading_days':
                            claim['value'] = 25
    rendered = runtime['render_verified_answer'](runtime['verify'](altered))
    assert 'different numbers of trading days' in rendered['interpretation']
    assert 'caused' not in rendered['interpretation']
    assert not runtime['undeclared_numbers'](rendered)


def test_country_scope_survives_scalar_result_in_followups(runtime):
    answer = {'question': 'Show revenue for France.', 'claims': [], 'findings': '',
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql',
                       'code': "SELECT SUM(revenue) AS revenue FROM sales WHERE country = 'France' AND NOT is_cancellation",
                       'rows': [{'revenue': 120}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](runtime['recover_evidence_claims'](answer)))
    assert 'France generated £120.00' in answer['findings']
    assert all('in France' in question for question in answer['suggested_next_steps'] if question.endswith('?'))


def test_public_completeness_note_keeps_repair_details_private(runtime):
    answer = {'completeness_issues': ['Bind input_cells for the percentage change using SQL columns.']}
    note = runtime['public_completeness_note'](answer)
    assert 'percentage change' in note and 'partial answer' in note
    assert 'SQL' not in note and 'input_cells' not in note


def test_notebook_display_shows_meaning_before_details(runtime, capsys):
    answer = runtime['tier3']('What was our total revenue in 2011?')
    runtime['show'](answer)
    output = capsys.readouterr().out
    assert output.index('What this means:') < output.index('Detailed figures:')
    assert 'Useful next steps:' in output


def test_monthly_breakdown_does_not_pick_an_arbitrary_first_total(runtime):
    answer = {'question': 'Show the monthly revenue breakdown.', 'findings': '', 'claims': [],
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql', 'code': 'SELECT invoice_month, net_revenue FROM dim_month',
                       'rows': [{'invoice_month': '2013-01', 'net_revenue': 120},
                                {'invoice_month': '2013-02', 'net_revenue': 100}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](runtime['recover_evidence_claims'](answer)))
    assert 'breakdown of revenue across the reporting periods' in answer['findings']
    assert '£120' not in answer['findings']
    assert len(runtime['claims_to_show'](answer)) == 2
    assert not runtime['undeclared_numbers'](answer)


def test_unresolved_country_comparison_keeps_both_groups_as_partial_answer(runtime):
    answer = {'question': 'Compare the revenue of France and Germany.', 'findings': '', 'claims': [],
              'completeness_issues': ['The requested difference in pounds is missing.'],
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql',
                       'code': "SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND country IN ('France', 'Germany') GROUP BY country",
                       'rows': [{'country': 'France', 'revenue': 120}, {'country': 'Germany', 'revenue': 100}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](runtime['recover_evidence_claims'](answer)))
    assert 'breakdown of revenue across the markets' in answer['findings']
    assert 'comparison is not yet complete' in answer['interpretation']
    assert len(runtime['claims_to_show'](answer)) == 2
    assert not runtime['undeclared_numbers'](answer)


@pytest.mark.parametrize('projection', [
    "SUM(CASE WHEN country = 'United Kingdom' THEN revenue ELSE 0 END)",
    "SUM(CASE WHEN country = 'United Kingdom' THEN 0 ELSE revenue END)",
])
def test_share_country_comes_from_positive_bound_case_only(runtime, projection):
    answer = {'question': 'What share came from this group?', 'findings': '',
              'claims': [{'value': 75, 'calc': 'share', 'inputs': [300, 400],
                          'input_cells': [{'from_call': 1, 'row': 0, 'column': 'group_revenue'},
                                          {'from_call': 1, 'row': 0, 'column': 'total_revenue'}]}],
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql',
                       'code': 'SELECT ' + projection + ' AS group_revenue, SUM(revenue) AS total_revenue FROM sales WHERE NOT is_cancellation',
                       'rows': [{'group_revenue': 300, 'total_revenue': 400}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](answer))
    if 'THEN revenue' in projection:
        assert answer['findings'].startswith('United Kingdom accounted for 75.00%')
    else:
        assert answer['findings'].startswith('The selected group accounted for 75.00%')
    assert not runtime['undeclared_numbers'](answer)


def test_share_country_comes_from_bound_numerator_country(runtime):
    answer = {'question': 'What share came from this group?', 'findings': '',
              'claims': [{'value': 75, 'calc': 'share', 'inputs': [300, 400],
                          'input_cells': [{'from_call': 1, 'row': 0, 'column': 'revenue'},
                                          {'from_call': 2, 'row': 0, 'column': 'revenue'}]}],
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql',
                       'code': "SELECT SUM(revenue) AS revenue FROM sales WHERE country = 'France' AND NOT is_cancellation",
                       'rows': [{'revenue': 300}]},
                      {'n': 2, 'ok': True, 'tool': 'run_sql',
                       'code': 'SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation',
                       'rows': [{'revenue': 400}]}]}
    answer = runtime['render_verified_answer'](runtime['verify'](answer))
    assert answer['findings'].startswith('France accounted for 75.00%')
    assert not runtime['undeclared_numbers'](answer)
