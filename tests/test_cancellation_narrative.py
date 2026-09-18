"""Invoice explanations must reflect the population selected by their query."""
import pytest

from test_notebooks import load_notebook


@pytest.fixture(params=['05_tier3_verification.ipynb', '06_evaluation.ipynb'])
def runtime(request):
    namespace = load_notebook(request.param)
    namespace['ask_gemma'] = lambda *args: pytest.fail('Count wording must not call a model')
    return namespace


def render_count(runtime, alias='orders', predicate='is_cancellation', distinct=True):
    # The rows are a fixture: the test probes how exact SQL-bound evidence is
    # described, independently of the historical dataset's particular counts.
    distinct_sql = 'DISTINCT ' if distinct else ''
    where = ' WHERE ' + predicate if predicate else ''
    sql = f'SELECT COUNT({distinct_sql}invoice_no) AS {alias} FROM sales{where}'
    answer = {'question': 'Show the recorded invoice count.', 'claims': [], 'findings': '',
              'log': [{'n': 1, 'ok': True, 'tool': 'run_sql', 'code': sql,
                       'rows': [{alias: 17}]}]}
    return runtime['render_verified_answer'](
        runtime['verify'](runtime['recover_evidence_claims'](answer)))


@pytest.mark.parametrize('alias', ['orders', 'invoices', 'invoice_count'])
def test_cancellation_only_counts_are_not_called_completed_orders(runtime, alias):
    answer = render_count(runtime, alias)
    assert answer['findings'] == 'There were 17 cancellation invoices.'
    assert answer['claims'][0]['text'] == 'Cancellation invoices: 17.'
    assert answer['claims'][0]['unit'] == 'invoices'
    assert answer['claims'][0]['status'] == 'supported'
    assert 'distinct cancellation invoice' in answer['interpretation']
    assert 'do not identify which original orders' in answer['interpretation']
    assert 'completed orders' not in answer['interpretation']
    assert 'What was the value of cancelled sales across the available dataset?' in answer['suggested_next_steps']
    assert not runtime['undeclared_numbers'](answer)


@pytest.mark.parametrize('predicate', ['is_cancellation = TRUE', 'is_cancellation IS TRUE',
                                       'NOT (is_cancellation = FALSE)'])
def test_equivalent_cancellation_filters_keep_the_correct_population(runtime, predicate):
    answer = render_count(runtime, predicate=predicate)
    assert '17 cancellation invoices' in answer['findings']
    assert answer['claims'][0]['text'] == 'Cancellation invoices: 17.'


@pytest.mark.parametrize('predicate', ['NOT is_cancellation', 'is_cancellation = FALSE'])
def test_completed_only_counts_keep_normal_order_explanation(runtime, predicate):
    answer = render_count(runtime, predicate=predicate)
    assert '17 completed orders' in answer['findings']
    assert answer['claims'][0]['text'] == 'Completed orders: 17.'
    assert 'Each completed invoice counts as an order' in answer['interpretation']
    assert not runtime['undeclared_numbers'](answer)


@pytest.mark.parametrize('predicate', ['', 'is_cancellation OR quantity > 0'])
def test_uncertain_population_uses_neutral_invoice_wording(runtime, predicate):
    answer = render_count(runtime, predicate=predicate)
    assert answer['findings'] == 'There were 17 distinct invoices.'
    assert answer['claims'][0]['text'] == 'Invoices: 17.'
    assert 'does not establish a completed-only or cancellation-only population' in answer['interpretation']


def test_non_distinct_count_does_not_claim_to_count_completed_orders(runtime):
    answer = render_count(runtime, predicate='NOT is_cancellation', distinct=False)
    assert answer['findings'].startswith('The returned count was 17.')
    assert answer['claims'][0]['text'] == 'Count: 17.'
    assert 'does not establish a count of distinct' in answer['interpretation']


def test_real_completed_order_and_revenue_patterns_keep_their_meaning(runtime):
    orders = runtime['tier3']('How many orders did we take in 2011?')
    assert '20,362 completed orders' in orders['findings']
    assert 'Each completed invoice counts as an order' in orders['interpretation']
    revenue = runtime['tier3']('What was our total revenue in 2011?')
    assert revenue['findings'] == 'Revenue was £9,809,614.01. Cancellations are excluded.'
