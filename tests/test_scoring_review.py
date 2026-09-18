"""Regressions for the final-review scoring defects; no model calls required."""
from copy import deepcopy
import json

import pandas as pd
import pytest

from test_notebooks import ROOT, load_notebook


@pytest.fixture
def scoring():
    return load_notebook('06_evaluation.ipynb')


def public_answer(rows, claims, findings='', tier=2):
    return {'tier': tier, 'findings': findings, 'claims': claims,
            'log': [{'n': 0, 'tool': 'run_sql', 'ok': True, 'rows': rows, 'code': 'SELECT 1'}],
            'insufficient_data': False}


def test_q25_identical_answer_binding_is_symmetric(scoring):
    rows = [{'invoice_month': '2011-02', 'revenue': 522545.56}]
    claims = [{'text': 'February 2011', 'value': 201102, 'unit': 'month', 'from_call': 0},
              {'text': '522545.56', 'value': 522545.56, 'unit': 'GBP', 'from_call': 0}]
    answer = public_answer(rows, claims, 'February 2011 had revenue of £522,545.56.')
    question = {'answerable': True}
    original = deepcopy(answer)
    tier2 = scoring['score_answer'](answer, question, rows)
    verified = scoring['verify'](deepcopy(answer))
    verified['tier'] = 3
    tier3 = scoring['score_answer'](verified, question, rows)
    assert tier2['correct'] == tier3['correct'] == 1
    assert answer == original  # scoring must not change the application output
    assert tier2['displayed_claims'] == 2  # the lower tier keeps all of its claims


def test_requested_facts_and_optional_context_are_distinct(scoring):
    rows = [{'invoice_month': '2011-11', 'revenue': 1503866.78, 'trading_days': 26}]
    claims = [{'text': 'November 2011 revenue', 'value': 1503866.78, 'unit': 'GBP'}]
    answer = public_answer(rows, claims)
    assert scoring['score_answer'](answer, {'answerable': True}, rows)['correct'] == 0
    question = {'answerable': True, 'optional_columns': ['trading_days']}
    assert scoring['score_answer'](answer, question, rows)['correct'] == 1
    answer['claims'].append({'text': 'It had 25 trading days', 'value': 25})
    metrics = scoring['score_answer'](answer, question, rows)
    assert metrics['requested_facts_correct'] == 1 and metrics['correct'] == 0


def test_wide_column_country_swaps_cannot_pass(scoring):
    rows = [{'germany': 213472.66, 'france': 200027.06, 'difference': 13445.60}]
    claims = [{'text': 'France revenue', 'value': 213472.66, 'from_call': 0},
              {'text': 'Germany revenue', 'value': 200027.06, 'from_call': 0},
              {'text': 'Difference', 'value': 13445.60}]
    assert not scoring['result_matches'](claims, rows)
    answer = public_answer(rows, claims)
    metrics = scoring['score_answer'](answer, {'answerable': True, 'required_columns': ['difference']}, rows)
    assert metrics['requested_facts_correct'] == 1
    assert metrics['contradicted_claims'] == 2 and metrics['correct'] == 0


def test_extra_invented_claims_fail_without_equating_evidence_to_facts(scoring):
    rows = [{'revenue': 120}]
    claims = [{'text': 'Revenue 120', 'value': 120, 'unit': 'GBP'},
              {'text': 'Profit 999', 'value': 999}]
    metrics = scoring['score_answer'](public_answer(rows, claims), {'answerable': True}, rows)
    assert metrics['requested_facts_correct'] == 1
    assert metrics['correct'] == 0 and metrics['contradicted_claims'] == 1
    claims[1] = {'text': 'There were 999 visitors', 'value': 999}
    metrics = scoring['score_answer'](public_answer(rows, claims), {'answerable': True}, rows)
    assert metrics['unassessed_extra_claims'] == 1 and metrics['correct'] == 0
    # Incorrect provenance metadata can coexist with a factually correct number.
    claims[:] = [{'text': 'Revenue 120', 'value': 120, 'unit': 'GBP', 'calc': 'sum', 'inputs': [999]}]
    metrics = scoring['score_answer'](public_answer(rows, claims), {'answerable': True}, rows)
    assert metrics['correct'] == 1 and metrics['displayed_unsupported'] == 1


def test_customer_labels_accept_integer_rendering_and_lists_need_every_row(scoring):
    rows = [{'customer_id': 14911.0, 'orders': 188}, {'customer_id': 12748.0, 'orders': 175}]
    claims = [{'text': 'Customer 14911 placed 188 orders', 'value': 188}]
    assert not scoring['result_matches'](claims, rows)
    claims.append({'text': 'Customer 12748 placed 175 orders', 'value': 175})
    assert scoring['result_matches'](claims, rows)
    assert not scoring['result_matches']([{'text': 'Not complete', 'value': 0}], [{'is_complete_month': False}])


def test_legacy_scalar_alternatives_cannot_waive_required_percentage(scoring):
    answer = public_answer([], [{'text': 'Difference £352603.05', 'value': 352603.05}])
    question = {'answerable': True, 'gt_value': 30.63, 'also_accept': [352603.05]}
    assert scoring['score_answer'](answer, question, [{'pct_change': 30.63}])['correct'] == 0
    question['alternative_rows'] = [[{'difference': 352603.05}]]
    assert scoring['score_answer'](answer, question, [{'pct_change': 30.63}])['correct'] == 1


def test_query_metrics_include_failed_attempts_only_sql(scoring):
    answer = {'claims': [], 'log': [{'tool': 'run_sql', 'ok': True}], 'attempts': [
        {'answer': {'log': [{'tool': 'run_sql', 'ok': False}, {'tool': 'make_chart', 'ok': True}]}},
        {'answer': {'log': [{'tool': 'run_sql', 'ok': True}, {'tool': 'run_python', 'ok': True}]}}]}
    metrics = scoring['score'](answer)
    assert metrics['queries'] == 2 and metrics['sql_successes'] == 1
    assert metrics['queries_ok'] == .5 and metrics['query_history_complete']
    answer.pop('attempts')
    answer['retries'] = 2
    assert not scoring['score'](answer)['query_history_complete']


def test_chart_denominator_and_tool_selection(scoring):
    answer = {'claims': [], 'log': [{'tool': 'run_sql', 'ok': False}], 'chart': None}
    question = {'answerable': True, 'expected_tool': 'run_sql', 'expected_chart': 'none'}
    metrics = scoring['evaluation_tools'](answer, question)
    assert metrics['tool_selection_correct'] == 1
    assert metrics['chart_correct'] is None and not metrics['chart_applicable']
    question['expected_chart'] = 'bar'
    assert scoring['evaluation_tools'](answer, question)['chart_correct'] == 0
    answer.update(route='rules_refusal', insufficient_data=True, log=[])
    question['answerable'] = False
    assert scoring['evaluation_tools'](answer, question)['tool_selection_correct'] is None


def test_shared_exporter_writes_matching_summary_and_chart(scoring, tmp_path):
    rows = []
    for tier in [1, 2, 3]:
        answer = public_answer([{'revenue': 120}], [{'text': 'Revenue 120', 'value': 120, 'unit': 'GBP'}], tier=tier)
        if tier == 3:
            answer = scoring['verify'](answer)
        metrics = scoring['score_answer'](answer, {'answerable': True}, [{'revenue': 120}])
        rows.append({'tier': tier, 'id': 'test', 'answerable': True, 'seconds': 1, **metrics})
    summary = scoring['export_evaluation'](pd.DataFrame(rows), tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {'all_runs.csv', 'summary.csv', 'comparison.png'}
    assert len(pd.read_csv(tmp_path / 'all_runs.csv')) == 3
    combined = summary[summary.route == 'all']
    assert combined.answerable_cases.tolist() == [1, 1, 1]
    assert combined.required_charts.tolist() == [0, 0, 0]
    assert combined.chart_correct.isna().all()


def test_tool_trace_metadata_is_not_a_business_measurement(scoring):
    rows = [{'orders': 145}]
    answer = public_answer(rows, [{'text': '145 orders', 'value': 145, 'unit': 'orders'}],
                           '[call 1] There were 145 orders. from_call: call 1, calc: 145, inputs: 145')
    metrics = scoring['score_answer'](answer, {'answerable': True}, rows)
    assert metrics['correct'] == 1 and metrics['undeclared_displayed_numbers'] == 0


@pytest.mark.parametrize('tier', [1, 2, 3])
def test_equal_number_with_wrong_measurement_kind_fails(scoring, tier):
    claim = {'text': 'There were 120 orders.', 'value': 120, 'unit': 'orders', 'status': 'supported'}
    answer = public_answer([{'revenue': 120}], [claim], claim['text'], tier)
    metrics = scoring['score_answer'](answer, {'answerable': True}, [{'revenue': 120}])
    assert metrics['correct'] == 0 and metrics['requested_facts_correct'] == 0


@pytest.mark.parametrize('tier', [1, 2, 3])
def test_wrong_country_in_public_prose_fails_despite_correct_claim(scoring, tier):
    row = {'country': 'France', 'revenue': 200027.06}
    claim = {'text': 'France earned £200,027.06.', 'value': 200027.06, 'unit': 'GBP', 'status': 'supported'}
    answer = public_answer([row], [claim], 'Germany earned £200,027.06.', tier)
    metrics = scoring['score_answer'](answer, {'answerable': True}, [row])
    assert metrics['correct'] == 0 and metrics['prose_conflicts']


def test_sql_pointer_does_not_excuse_conflicting_headline_total(scoring):
    claims = [{'text': 'Revenue was 120.', 'value': 120, 'unit': 'GBP'},
              {'text': 'Revenue was also 90.', 'value': 90, 'unit': 'GBP', 'from_call': 0}]
    answer = public_answer([{'revenue': 90}], claims, 'Revenue was 120. Revenue was also 90.')
    metrics = scoring['score_answer'](answer, {'answerable': True}, [{'revenue': 120}])
    assert metrics['requested_facts_correct'] == 1 and metrics['correct'] == 0
    assert metrics['contradicted_claims'] == 1


def test_explicit_breakdown_is_valid_optional_sql_context(scoring):
    claims = [{'text': 'Total revenue was 120.', 'value': 120, 'unit': 'GBP'},
              {'text': 'France revenue was 90.', 'value': 90, 'unit': 'GBP', 'from_call': 0}]
    answer = public_answer([{'country': 'France', 'revenue': 90}], claims,
                           'Total revenue was 120. France revenue was 90.')
    metrics = scoring['score_answer'](answer, {'answerable': True}, [{'revenue': 120}])
    assert metrics['correct'] == 1


def test_consistent_comparison_prose_and_revenue_unit_aliases_pass(scoring):
    rows = [{'germany': 213472.66, 'france': 200027.06, 'difference': 13445.60}]
    claims = [{'text': 'Germany revenue', 'value': 213472.66, 'unit': 'revenue'},
              {'text': 'France revenue', 'value': 200027.06, 'unit': 'revenue'},
              {'text': 'Difference', 'value': 13445.60, 'unit': 'GBP'}]
    answer = public_answer(rows, claims, 'Germany earned £213,472.66, while France earned £200,027.06. The difference was £13,445.60.')
    question = {'answerable': True, 'required_columns': ['difference']}
    assert scoring['score_answer'](answer, question, rows)['correct'] == 1
    answer['findings'] = 'France earned £213,472.66, while Germany earned £200,027.06. The difference was £13,445.60.'
    assert scoring['score_answer'](answer, question, rows)['correct'] == 0


def test_answer_about_requested_month_may_use_it(scoring):
    row = {'invoice_month': '2011-12', 'trading_days': 8, 'is_complete_month': False}
    claims = [{'text': 'The month is incomplete.', 'value': False, 'kind': 'boolean', 'from_call': 0, 'row': 0, 'column': 'is_complete_month'},
              {'text': 'It contains 8 trading days.', 'value': 8, 'unit': 'days', 'from_call': 0, 'row': 0, 'column': 'trading_days'}]
    answer = public_answer([row], claims, 'The month is incomplete. It contains 8 trading days.')
    answer['question'] = 'Is December 2011 a complete month in the dataset?'
    assert scoring['score_answer'](answer, {'answerable': True}, [row])['correct'] == 1


def test_total_and_per_day_amounts_are_distinct_compatible_facts(scoring):
    rows = [{'revenue': 120, 'revenue_per_trading_day': 30}]
    claims = [{'text': 'Total revenue was £120.', 'value': 120, 'unit': 'GBP', 'from_call': 0},
              {'text': 'Revenue per trading day was £30.', 'value': 30, 'unit': 'GBP', 'from_call': 0}]
    answer = public_answer(rows, claims, 'Total revenue was £120, revenue per trading day was £30.')
    assert scoring['score_answer'](answer, {'answerable': True}, rows)['correct'] == 1
    # The daily figure can be useful context when only the total was requested.
    assert scoring['score_answer'](answer, {'answerable': True}, [{'revenue': 120}])['correct'] == 1
    # Unit aliases retain the same dimension; days alone are a different fact.
    for column in ['daily_revenue', 'revenue_per_day', 'per_day_revenue']:
        claim = {'text': 'Revenue per day was £30.', 'value': 30, 'unit': 'GBP'}
        daily = public_answer([{column: 30}], [claim], claim['text'])
        assert scoring['score_answer'](daily, {'answerable': True}, [{column: 30}])['correct'] == 1
