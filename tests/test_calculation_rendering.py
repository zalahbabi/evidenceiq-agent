"""A supported calculation must not inherit unverified units or direction."""
import pytest

from test_notebooks import load_notebook


@pytest.fixture(params=['05_tier3_verification.ipynb', '06_evaluation.ipynb'])
def runtime(request):
    return load_notebook(request.param)


def calculation_answer(inputs, values, operation='pct_change', question='Describe the checked calculation.'):
    return {'question': question, 'log': [{'n': 3, 'tool': 'run_sql', 'ok': True,
             'code': "SELECT invoice_month, net_revenue, net_revenue / trading_days AS revenue_per_day FROM dim_month WHERE invoice_month IN ('2010-03', '2010-04')",
             'rows': [{'invoice_month': '2010-03', 'net_revenue': 100, 'revenue_per_day': 10},
                      {'invoice_month': '2010-04', 'net_revenue': 120, 'revenue_per_day': 12}]}],
            'claims': [{'value': (values[0] - values[1]) / values[1] * 100 if operation == 'pct_change' else values[0] - values[1],
                        'calc': operation, 'inputs': values, 'input_cells': inputs,
                        'unit': 'invented units', 'text': 'Invented meaning', 'result_name': 'Profit from promotions'}]}


def test_calculation_and_direct_units_are_replaced_for_public_captions(runtime):
    answer = calculation_answer([{'from_call': 3, 'row': 1, 'column': 'net_revenue'},
                                 {'from_call': 3, 'row': 0, 'column': 'net_revenue'}], [120, 100], operation='difference')
    checked = runtime['verify'](answer)
    public = runtime['render_verified_answer'](checked)
    assert public['claims'][0]['unit'] == 'GBP'
    assert 'difference of £20.00' in public['findings']
    assert 'invented' not in public['findings'].lower() and 'promotions' not in public['findings']
    answer['claims'] = [{'from_call': 3, 'row': 1, 'column': 'revenue_per_day', 'value': 12,
                         'unit': 'people', 'calc': 'none', 'text': 'revenue per day'}]
    public = runtime['render_verified_answer'](runtime['verify'](answer))
    assert public['claims'][0]['unit'] == 'GBP per trading day'
    assert 'people' not in public['findings']


def test_reversed_calculation_does_not_emit_wrong_yes_no(runtime):
    question = 'Did April 2010 beat March 2010 in the recorded monthly values?'
    answer = calculation_answer([{'from_call': 3, 'row': 0, 'column': 'net_revenue'},
                                 {'from_call': 3, 'row': 1, 'column': 'net_revenue'}], [100, 120], question=question)
    public = runtime['render_verified_answer'](runtime['verify'](answer))
    assert public['claims'][0]['status'] == 'supported'
    assert 'No.' not in public['findings'] and 'Yes.' not in public['findings']
    assert 'lower in March 2010 than in April 2010' in public['findings']
    assert '-16.67%' in public['findings']
    correct = calculation_answer([{'from_call': 3, 'row': 1, 'column': 'net_revenue'},
                                  {'from_call': 3, 'row': 0, 'column': 'net_revenue'}], [120, 100], question=question)
    assert runtime['render_verified_answer'](runtime['verify'](correct))['findings'].startswith('Yes.')


def test_mixed_total_and_daily_inputs_are_not_called_daily_change(runtime):
    answer = calculation_answer([{'from_call': 3, 'row': 1, 'column': 'net_revenue'},
                                 {'from_call': 3, 'row': 0, 'column': 'revenue_per_day'}], [120, 10])
    public = runtime['render_verified_answer'](runtime['verify'](answer))
    assert 'Per-trading-day' not in public['findings']
    assert public['claims'][0]['unit'] == '%'
    daily = calculation_answer([{'from_call': 3, 'row': 1, 'column': 'revenue_per_day'},
                                {'from_call': 3, 'row': 0, 'column': 'revenue_per_day'}], [12, 10])
    public = runtime['render_verified_answer'](runtime['verify'](daily))
    assert 'Revenue per trading day was higher in April 2010 than in March 2010' in public['findings']
    assert '20.00%' in public['findings']
    assert public['claims'][0]['unit'] == '%'


def test_direct_calculation_citation_drops_model_name_and_unit(runtime):
    answer = calculation_answer(
        [{'from_call': 3, 'row': 1, 'column': 'net_revenue'},
         {'from_call': 3, 'row': 0, 'column': 'net_revenue'}], [120, 100], operation='difference')
    answer['log'].append({'n': 4, 'tool': 'run_python', 'ok': True, 'code': '120 - 100',
                          'rows': [{'value': 20, 'operation': 'difference', 'inputs': [120, 100],
                                    'unit': 'people', 'result_name': 'Profit from promotions'}]})
    answer['claims'] = [{'value': 20, 'calc': 'none', 'from_call': 4, 'unit': 'people',
                         'text': 'Profit from promotions'}]
    public = runtime['render_verified_answer'](runtime['verify'](answer))
    assert public['claims'][0]['status'] == 'supported'
    assert public['claims'][0]['unit'] == 'GBP'
    assert 'Difference: £20.00' in public['findings']
    assert 'people' not in public['findings'] and 'Profit' not in public['findings']
