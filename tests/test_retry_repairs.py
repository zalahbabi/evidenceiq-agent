"""Exercise repair feedback and attempt history without requiring Ollama."""
from copy import deepcopy

import pytest

from test_notebooks import load_notebook


@pytest.fixture(params=['05_tier3_verification.ipynb', '06_evaluation.ipynb'])
def runtime(request):
    return load_notebook(request.param)


def failed_answer():
    return {'question': 'Revenue for France?', 'tier': 2, 'route': 'model_tools',
            'findings': 'The query could not be made to run.', 'claims': [],
            'insufficient_data': False, 'limitations': 'Unknown column revnue',
            'failure': 'Unknown column revnue', 'chart': None,
            'log': [{'n': 0, 'tool': 'run_sql', 'code': 'SELECT revnue FROM sales',
                     'ok': False, 'rows': [], 'error': 'Unknown column revnue'}],
            'usage': {'model_calls': 3, 'input_tokens': 100, 'output_tokens': 30}}


def successful_answer():
    return {'question': 'Revenue for France?', 'tier': 2, 'route': 'model_tools',
            'findings': 'France revenue was 120.', 'insufficient_data': False,
            'limitations': '', 'chart': None,
            'claims': [{'text': 'France revenue was 120.', 'value': 120, 'unit': 'GBP',
                        'from_call': 0, 'calc': 'none', 'inputs': [], 'row': 0, 'column': 'revenue'}],
            'log': [{'n': 0, 'tool': 'run_sql', 'code': "SELECT country, SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation AND country='France' GROUP BY country",
                     'ok': True, 'rows': [{'country': 'France', 'revenue': 120}], 'error': None}],
            'usage': {'model_calls': 3, 'input_tokens': 110, 'output_tokens': 40}}


def test_failed_query_with_no_claims_triggers_repair(runtime):
    calls = []
    def fake(question, log, feedback):
        calls.append(feedback)
        return deepcopy(failed_answer() if len(calls) == 1 else successful_answer())
    runtime['tier2'] = fake
    result = runtime['tier3']('Revenue for France?')
    assert len(calls) == 2
    assert 'SELECT revnue' in calls[1] and 'Unknown column' in calls[1]
    assert result['selected_attempt'] == 1 and result['retries'] == 1
    assert len(result['attempts']) == 2
    assert not result['attempts'][0]['answer']['log'][0]['ok']
    assert result['log'][0]['ok']
    assert result['usage'] == {'model_calls': 6, 'input_tokens': 210, 'output_tokens': 70}
    assert 'France' in result['findings'] and '120' in result['findings']


def test_repeated_query_failure_stops_at_budget(runtime):
    calls = []
    def fake(*args):
        calls.append(args)
        return deepcopy(failed_answer())
    runtime['tier2'] = fake
    result = runtime['tier3']('Revenue for France?', max_retries=2)
    assert len(calls) == 3 and result['retries'] == 2
    assert len(result['attempts']) == 3
    assert runtime['claims_to_show'](result) == []


def test_equal_budget_control_does_not_verify(runtime):
    attempts = iter([failed_answer(), successful_answer()])
    runtime['tier2'] = lambda *args: deepcopy(next(attempts))
    runtime['verify'] = lambda *args: pytest.fail('The Tier 2 control must not use verification')
    result = runtime['tier2_with_retries']('Revenue for France?', max_retries=2)
    assert result['control'] == 'execution_retries_without_verification'
    assert result['retries'] == 1
    assert 'status' not in result['claims'][0]


def test_known_data_gap_does_not_retry(runtime):
    runtime['ask_gemma'] = lambda *args: pytest.fail('Known data gaps do not need model calls')
    result = runtime['tier3']('What was our profit margin in 2011?')
    assert result['route'] == 'rules_refusal'
    assert result['insufficient_data'] and result['retries'] == 0


def test_successful_sql_repair_does_not_count_as_unresolved(runtime):
    result = successful_answer()
    result['log'].insert(0, failed_answer()['log'][0])
    assert runtime['execution_feedback'](result) == ''


def test_false_planner_refusal_receives_another_attempt(runtime):
    refusal = failed_answer()
    refusal.update(log=[], insufficient_data=True, failure=None,
                   findings='No data available.', limitations='No data available.')
    attempts = iter([refusal, successful_answer()])
    runtime['tier2'] = lambda *args: deepcopy(next(attempts))
    result = runtime['tier3']('Revenue for France?')
    assert result['retries'] == 1 and not result['insufficient_data']


def test_reporting_year_is_not_mistaken_for_a_measurement(runtime):
    text = '84.05% of our 2011 revenue came from the UK.'
    start = text.index('2011')
    assert runtime['is_date_context'](text, start, start+4)
    text = 'We shipped 2011 items.'
    start = text.index('2011')
    assert not runtime['is_date_context'](text, start, start+4)


def test_explicit_cancellation_exclusion_cannot_disable_revenue_guard(runtime):
    query = 'SELECT SUM(revenue) AS revenue FROM sales'
    assert runtime['query_scope_problem'](query, 'Show overall revenue excluding cancellations.')
    assert runtime['query_scope_problem'](query + ' WHERE NOT is_cancellation', 'Show overall revenue excluding cancellations.') is None


def test_share_chart_requires_a_real_nonnegative_breakdown(runtime):
    log = [{'n': 0, 'tool': 'run_sql', 'ok': True,
            'rows': [{'country': 'France', 'revenue': 20}, {'country': 'Other', 'revenue': 80}]}]
    spec = {'type': 'pie', 'source_tool_call': 0, 'x': 'country', 'y': 'revenue'}
    assert runtime['make_chart'](spec, deepcopy(log))['ok']
    log[0]['rows'][1]['revenue'] = -10
    assert not runtime['make_chart'](spec, log)['ok']


def test_generation_abort_is_recorded_for_bounded_repair(runtime, monkeypatch):
    import ollama
    class AbortingClient:
        def __init__(self, **kwargs):
            pass
        def chat(self, **kwargs):
            raise ollama.ResponseError('prediction aborted, token repeat limit reached', 500)
    monkeypatch.setattr(ollama, 'Client', AbortingClient)
    result = runtime['ask_gemma']('system', 'question', {})
    assert result['broken_json'] and 'prediction aborted' in result['error']
    assert result['_usage'] == {'model_calls': 1, 'input_tokens': None, 'output_tokens': None}
