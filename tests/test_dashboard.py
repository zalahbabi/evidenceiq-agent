"""Exercise filtering, empty states and navigation without a running model."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def start():
    return AppTest.from_file(str(ROOT/'app/dashboard.py'),default_timeout=40).run()


def assert_healthy(app):
    assert not app.exception, [e.message for e in app.exception]
    assert not app.error, [e.value for e in app.error]


def test_overview_filters_and_products():
    app=start(); assert_healthy(app)
    assert app.metric[0].value=='£9,171,806'
    assert len(app.dataframe[0].value)==5
    app.toggle[0].set_value(False).run(); assert_healthy(app)
    assert app.metric[0].value=='£9,809,614'
    assert any('December 2011' in warning.value for warning in app.warning)
    app.selectbox(key='market').set_value('France').run(); assert_healthy(app)
    assert app.metric[0].value=='£200,027'
    app.selectbox(key='year').set_value(2009).run(); assert_healthy(app)
    app.selectbox(key='market').set_value('Saudi Arabia').run(); assert_healthy(app)
    assert any('No transactions' in info.value for info in app.info)


def test_navigation_evaluation_and_analyst():
    app=start()
    app.sidebar.radio[0].set_value('Evaluation').run(); assert_healthy(app)
    assert app.metric[0].value=='30'
    assert app.metric[1].value=='25'
    assert app.metric[2].value=='0'
    assert any(len(table.value)==30 and 'Question' in table.value for table in app.dataframe)
    app.sidebar.radio[0].set_value('Ask the analyst').run(); assert_healthy(app)
    assert app.text_area[0].value=='What was our total revenue in 2011?'
    app.selectbox[0].set_value('What was our profit margin in 2011?').run(); assert_healthy(app)
    assert app.text_area[0].value=='What was our profit margin in 2011?'
    app.text_area[0].set_value(' ')
    app.button[0].click().run(); assert_healthy(app)
    assert any('Enter a business question' in warning.value for warning in app.warning)


def test_analyst_product_chart_and_boolean_answer():
    app=start()
    app.sidebar.radio[0].set_value('Ask the analyst').run(); assert_healthy(app)
    app.selectbox[0].set_value('Which five products generated the most revenue in 2011?').run()
    app.button[0].click().run(); assert_healthy(app)
    answer=app.session_state['answer']
    assert len(answer['claims'])==5
    assert answer['chart']['x']=='description'
    assert 'REGENCY CAKESTAND 3 TIER' in answer['findings']
    assert '[unverified]' not in answer['findings']
    assert len(app.get('vega_lite_chart'))==1
    app.selectbox[0].set_value('Is December 2011 a complete month in the dataset?').run()
    app.button[0].click().run(); assert_healthy(app)
    answer=app.session_state['answer']
    assert answer['claims'][0]['value'] is False
    assert 'incomplete' in answer['findings'] and '8 trading days' in answer['findings']


def test_current_evaluation_shows_routes_and_applicable_metrics(monkeypatch):
    """The new CSV format must render its real denominators without a model."""
    import pandas as pd
    from test_notebooks import load_notebook
    runtime = load_notebook('06_evaluation.ipynb')
    answer = {'tier': 3, 'route': 'query_pattern', 'question': 'Revenue?',
              'findings': 'Revenue was 120.', 'insufficient_data': False,
              'claims': [{'text': 'Revenue was 120.', 'value': 120, 'unit': 'GBP',
                          'from_call': 0, 'calc': 'none', 'inputs': []}],
              'log': [{'n': 0, 'tool': 'run_sql', 'ok': True,
                       'code': 'SELECT SUM(revenue) AS revenue FROM sales WHERE NOT is_cancellation',
                       'rows': [{'revenue': 120}]}]}
    answer = runtime['verify'](answer)
    metrics = runtime['score_answer'](answer, {'answerable': True, 'expected_chart': 'none'}, [{'revenue': 120}])
    frame = pd.DataFrame([{'id': 'example', 'tier': 3, 'answerable': True,
                           'seconds': 0.5, 'error': None, 'usefulness_rating': None, **metrics}])
    original = pd.read_csv
    monkeypatch.setattr(pd, 'read_csv', lambda path, *args, **kwargs:
                        frame.copy() if str(path).endswith('all_runs.csv') else original(path, *args, **kwargs))
    app = start()
    app.sidebar.radio[0].set_value('Evaluation').run()
    assert_healthy(app)
    tables = [table.value for table in app.dataframe]
    routes = next(table for table in tables if 'route' in table)
    assert routes.answerable_cases.tolist() == [1]
    evidence = next(table for table in tables if 'required_charts' in table)
    assert evidence.required_charts.tolist() == [0]
    assert evidence.chart_correct.isna().all()
    assert any('Human usefulness ratings: 0 / 1' in caption.value for caption in app.caption)
    assert not app.get('vega_lite_chart')


def test_helpful_answer_and_follow_up_fill_the_form():
    app = start()
    app.sidebar.radio[0].set_value('Ask the analyst').run()
    app.button[0].click().run()
    assert_healthy(app)
    answer = app.session_state['answer']
    assert answer['interpretation'] and answer['suggested_next_steps']
    assert any(heading.value == 'What this means' for heading in app.subheader)
    assert any('See all checked figures' in item.label for item in app.expander)
    suggestions = [button for button in app.button if str(button.key).startswith('follow_up_')]
    assert suggestions
    question = suggestions[0].label
    suggestions[0].click().run()
    assert_healthy(app)
    assert app.text_area[0].value == question
    app.run()
    assert app.text_area[0].value == question
    # Choosing a suggestion must not quietly run another analysis.
    assert app.session_state['answer']['question'] == answer['question']
