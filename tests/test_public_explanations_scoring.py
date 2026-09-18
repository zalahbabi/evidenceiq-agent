"""All displayed explanation fields must share the numeric exposure checks."""
from copy import deepcopy

import pytest

from test_notebooks import load_notebook


@pytest.fixture
def runtime():
    return load_notebook('06_evaluation.ipynb')


def answer():
    return {'tier': 2, 'findings': 'France revenue was £120.',
            'claims': [{'text': 'France revenue was £120.', 'value': 120, 'unit': 'GBP',
                        'from_call': 0, 'row': 0, 'column': 'revenue'}],
            'log': [{'n': 0, 'tool': 'run_sql', 'ok': True, 'code': "SELECT 'France' AS country, 120 AS revenue",
                     'rows': [{'country': 'France', 'revenue': 120}]}]}


@pytest.mark.parametrize('field', ['interpretation', 'suggested_next_steps'])
def test_new_prose_fields_cannot_introduce_unsupported_numbers(runtime, field):
    public = answer()
    text = 'There were 999 orders.'
    public[field] = [text] if field == 'suggested_next_steps' else text
    checked = runtime['verify'](deepcopy(public))
    assert 999 in checked['undeclared']
    metrics = runtime['score_answer'](public, {'answerable': True}, [{'country': 'France', 'revenue': 120}])
    assert metrics['correct'] == 0 and metrics['undeclared_displayed_numbers'] == 1


@pytest.mark.parametrize('field', ['interpretation', 'suggested_next_steps'])
def test_new_prose_fields_cannot_relabel_supported_values(runtime, field):
    public = answer()
    text = 'France placed 120 orders.'
    public[field] = [text] if field == 'suggested_next_steps' else text
    metrics = runtime['score_answer'](public, {'answerable': True}, [{'country': 'France', 'revenue': 120}])
    assert metrics['correct'] == 0 and metrics['prose_conflicts']


def test_equal_trading_days_can_reuse_period_labels_from_findings(runtime):
    rows = [{'invoice_month': '2011-10', 'trading_days': 26},
            {'invoice_month': '2011-11', 'trading_days': 26}]
    public = {'tier': 2, 'findings': 'October 2011 had 26 trading days. November 2011 had 26 trading days.',
              'interpretation': 'Both periods had 26 trading days, so their totals cover equal numbers of trading days.',
              'suggested_next_steps': ['Inspect the products behind the difference.'],
              'claims': [{'text': f"{row['invoice_month']} had 26 trading days.", 'value': 26,
                          'unit': 'days', 'from_call': 0, 'row': index, 'column': 'trading_days'}
                         for index, row in enumerate(rows)],
              'log': [{'n': 0, 'tool': 'run_sql', 'ok': True, 'code': 'SELECT invoice_month,trading_days FROM dim_month', 'rows': rows}]}
    metrics = runtime['score_answer'](public, {'answerable': True}, rows)
    assert metrics['correct'] == 1 and metrics['undeclared_displayed_numbers'] == 0


def test_number_free_interpretation_and_suggestions_preserve_factual_score(runtime):
    public = answer()
    public.update(interpretation='This is recorded sales revenue; it does not establish profitability.',
                  suggested_next_steps=['Review the products contributing to this total.'])
    original = deepcopy(public)
    metrics = runtime['score_answer'](public, {'answerable': True}, [{'country': 'France', 'revenue': 120}])
    assert metrics['correct'] == 1 and public == original


def test_unexpected_suggestion_string_is_still_checked(runtime):
    public = answer()
    public['suggested_next_steps'] = 'Target a 15% increase.'
    assert 15 in runtime['undeclared_numbers'](public)


def test_hidden_tier3_claim_cannot_support_a_displayed_explanation(runtime):
    public = runtime['verify'](answer())
    public['tier'] = 3
    public['claims'].append({'text': '999 orders', 'value': 999, 'status': 'unsupported'})
    public['interpretation'] = 'There were 999 orders.'
    metrics = runtime['score_answer'](public, {'answerable': True}, [{'country': 'France', 'revenue': 120}])
    assert metrics['correct'] == 0 and metrics['undeclared_displayed_numbers'] == 1


@pytest.mark.parametrize('field', ['interpretation', 'suggested_next_steps'])
def test_correct_findings_do_not_excuse_wrong_country_in_explanations(runtime, field):
    public = answer()
    text = 'Germany revenue was £120.'
    public[field] = [text] if field == 'suggested_next_steps' else text
    metrics = runtime['score_answer'](public, {'answerable': True}, [{'country': 'France', 'revenue': 120}])
    assert metrics['correct'] == 0 and metrics['prose_conflicts']
