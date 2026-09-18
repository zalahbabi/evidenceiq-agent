"""Regression tests run the actual notebook definitions, without executing demos."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import duckdb
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_notebook(name):
    namespace = {'__name__': 'notebook_test'}
    nodes = []
    constants = {'DB','MODEL','TOLERANCE','FORBIDDEN','OPERATIONS','CHART_TYPES',
                 'SCHEMA','RULES','EXAMPLES','SYSTEM','PLAN_PROMPT','ANSWER_PROMPT'}
    for cell in json.loads((ROOT/'notebooks'/name).read_text())['cells']:
        if cell['cell_type'] != 'code':
            continue
        for node in ast.parse(''.join(cell['source'])).body:
            if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom)):
                nodes.append(node)
            elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and
                    (t.id in constants or t.id.endswith('_SHAPE')) for t in node.targets):
                nodes.append(node)
    exec(compile(ast.Module(body=nodes,type_ignores=[]), name, 'exec'), namespace)
    namespace['DB'] = str(ROOT/'data/processed/evidenceiq.duckdb')
    return namespace


@pytest.fixture(params=['05_tier3_verification.ipynb','06_evaluation.ipynb'])
def runtime(request):
    return load_notebook(request.param)


def answer(value=120, calc='none', inputs=None, findings='Revenue was 120.'):
    return {'findings':findings,'claims':[{'text':findings,'value':value,'calc':calc,'inputs':inputs or []}],
            'log':[{'n':7,'tool':'run_sql','code':'SELECT revenue FROM sales WHERE NOT is_cancellation','ok':True,'rows':[{'a':120,'b':100}], 'error':None}]}


def test_calculation_cannot_launder_invented_inputs(runtime):
    log = answer()['log']
    assert not runtime['run_python']({'operation':'sum','values':[888]},log)['ok']
    assert runtime['run_python']({'operation':'difference','values':[120,100]},log)['ok']
    # Even a forged successful calculation log must be rechecked against SQL roots.
    log.append({'n':90,'tool':'run_python','ok':True,'rows':[{'value':888,'operation':'sum','inputs':[888]}]})
    assert 888 not in [value for _,value in runtime['numbers_in_log'](log)]


@pytest.mark.parametrize('bad',[None,True,float('nan'),float('inf'),'garbage',{},[]])
def test_malformed_claims_do_not_crash_or_pass(runtime,bad):
    checked=runtime['verify'](answer(value=bad))
    assert checked['claims'][0]['status']=='unsupported'
    assert runtime['claims_to_show'](checked)==[]


def test_supported_arithmetic_and_aliases(runtime):
    for calc,value in [('difference',20),('diff',20),('mean',110),('pct_change',20),('sum',220)]:
        checked=runtime['verify'](answer(value,calc,[120,100]))
        assert checked['claims'][0]['status']=='supported'
    bad=runtime['verify'](answer(120,'mystery',[120]))
    assert bad['claims'][0]['status']=='unsupported'
    assert runtime['verify'](answer(120,'sum',[999]))['claims'][0]['status']=='unsupported'


def test_citation_and_failed_query(runtime):
    a=answer();a['claims'][0]['from_call']=90
    assert runtime['verify'](a)['claims'][0]['status']=='unsupported'
    a=answer();a['log'][0]['ok']=False
    assert runtime['verify'](a)['claims'][0]['status']=='unsupported'


def test_redaction_including_small_counts_and_scaled_amounts(runtime):
    a=answer(findings='Revenue was 120, growth 12%, margin £9, forecast 1.2m in 2011.')
    checked=runtime['verify'](a)
    assert runtime['clean_findings'](checked)=='Revenue was 120, growth [unverified]%, margin £[unverified], forecast [unverified] in 2011.'
    assert runtime['write_feedback'](checked)
    a=answer(12,'none', findings='12 and 120 are different.')
    a=runtime['verify'](a)
    assert runtime['clean_findings'](a)=='[unverified] and [unverified] are different.'


def test_flagged_claims_and_model_kpis_are_not_displayed(runtime):
    a=answer(120,'difference',[120,100])
    a['kpis']={'profit':999}
    runtime['tier2']=lambda *args: deepcopy(a)
    checked=runtime['tier3']('test',max_retries=0)
    assert checked['claims'][0]['status']=='flagged'
    assert runtime['claims_to_show'](checked)==[]
    assert 'could not verify' in checked['findings']
    assert checked['kpis']=={}


def test_undeclared_only_failure_retries(runtime):
    calls=[]
    def fake_tier2(*args):
        calls.append(args)
        return answer(findings='Revenue 120 and growth 12%.')
    runtime['tier2']=fake_tier2
    checked=runtime['tier3']('test', max_retries=2)
    assert len(calls)==3
    assert checked['retries']==2
    assert '12' not in checked['findings'] .replace('120','')


def test_partial_shares_do_not_need_to_add_to_100(runtime):
    a=answer()
    a['log'][0]['rows']=[{'a':40,'b':30,'total':100}]
    a['claims']=[{'value':40,'calc':'share','inputs':[40,100]}, {'value':30,'calc':'share','inputs':[30,100]}]
    checked=runtime['verify'](a)
    assert not checked['reconciliation']
    assert all(c['status']=='supported' for c in checked['claims'])


def test_chart_metadata_is_not_evidence(runtime):
    a=answer(998)
    a['log'].append({'n':8,'tool':'make_chart','ok':True,'rows':[{'source_tool_call':998}]})
    assert runtime['verify'](a)['claims'][0]['status']=='unsupported'
    assert not runtime['make_chart']({'type':'bar','source_tool_call':7,'x':'invented','y':'a'}, a['log'])['ok']


def test_sql_guards_and_database_values():
    runtime=load_notebook('04_tier2_agent.ipynb')
    for sql in ['-- comment only','SELECT 1; DELETE FROM sales','DROP TABLE sales',None]:
        assert runtime['check_sql'](sql)
    assert runtime['check_sql']('SELECT updated_at FROM sales') is None
    if not Path(runtime['DB']).exists():
        pytest.skip('local dataset unavailable')
    log=[]
    assert not runtime['run_sql']("SELECT * FROM read_csv('/etc/passwd')",log)['ok']
    assert not runtime['run_sql']('SELECT * FROM sales',log)['ok']
    call=runtime['run_sql']('SELECT 12.34::DECIMAL(10,2) AS amount FROM sales LIMIT 1',log)
    assert call['rows']==[{'amount':12.34}]
    assert runtime['run_sql']('SELECT count(*) AS n FROM sales', log)['rows'][0]['n']==1033030


def test_all_benchmark_ground_truths():
    database=ROOT/'data/processed/evidenceiq.duckdb'
    if not database.exists():
        pytest.skip('local dataset unavailable')
    questions=yaml.safe_load((ROOT/'eval/benchmark.yaml').read_text())['questions']
    with duckdb.connect(str(database), read_only=True, config={'enable_external_access':'false'}) as con:
        numeric=[q for q in questions if q['answerable']]
        assert len(numeric)==25
        for q in numeric:
            result=con.execute(q['gt_sql']).fetchall()
            values=[float(v) for row in result for v in row if isinstance(v,(float,int)) and not isinstance(v,bool)]
            assert any(abs(v-q['gt_value'])<=.011 for v in values), q['id']


def test_notebook_copies_stay_in_sync():
    notebooks=[load_notebook(name) for name in ['04_tier2_agent.ipynb','05_tier3_verification.ipynb','06_evaluation.ipynb']]
    for function in ['run_sql','run_python','numbers_in_log','make_chart','tier2','ask_gemma']:
        assert notebooks[0][function].__code__.co_code==notebooks[1][function].__code__.co_code==notebooks[2][function].__code__.co_code
    for function in ['verify','tier3','claims_to_show','clean_findings','score']:
        assert notebooks[1][function].__code__.co_code==notebooks[2][function].__code__.co_code


def test_evaluation_baseline_api_and_scoring():
    runtime=load_notebook('06_evaluation.ipynb')
    calls=[]
    def model(system, question, shape):
        calls.append((system,question,shape))
        return {'findings':'No data','claims':[],'insufficient_data':True}
    runtime['ask_gemma']=model
    result=runtime['tier1']('question')
    assert result['tier']==1 and result['log']==[] and result['plan']==[]
    assert len(calls)==1
    assert '1,033,030' not in calls[0][0]
    assert runtime['is_correct']({'answerable':True,'gt_value':120,'values':[120],'refused':True})==0
    assert runtime['is_correct']({'answerable':True,'gt_value':120,'values':[120],'error':'crashed'})==0


def test_known_data_gaps_refuse_before_model(runtime):
    runtime['ask_gemma']=lambda *args: pytest.fail('Known missing data should not call the model')
    for question in ['What was our profit margin in 2011?', 'What was our cost of goods sold in 2011?',
                     'Which promotion generated the most revenue?', 'What will our revenue be next quarter?',
                     'How did December 2011 compare with November 2011?']:
        result=runtime['tier2'](question)
        assert result['insufficient_data'] and result['log']==[]
    assert runtime['data_gap_reason']('What was revenue in December 2011?') is None
    assert runtime['data_gap_reason']('Compare December 2011 with November per trading day') is None


def test_failed_rebuild_preserves_existing_database(tmp_path):
    import importlib.util
    import pandas as pd
    spec=importlib.util.spec_from_file_location('builder',ROOT/'src/build_db.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    destination=tmp_path/'evidenceiq.duckdb'; destination.write_bytes(b'original database')
    builder.DB=str(destination)
    with pytest.raises(duckdb.Error):
        builder.build_tables(pd.DataFrame({'revenue':[1]}))
    assert destination.read_bytes()==b'original database'
    assert list(tmp_path.iterdir())==[destination]


def test_explicit_year_is_not_lost(runtime):
    log=[]
    result=runtime['run_sql']('SELECT SUM(revenue) FROM sales WHERE NOT is_cancellation',log,'What was revenue in 2011?')
    assert not result['ok'] and 'checked KPI query pattern' in result['error']
    question = 'Revenue in 2011?'
    assert runtime['query_scope_problem'](runtime['question_contract'](question)['sql'], question) is None


def test_broken_prose_falls_back_to_supported_claims(runtime):
    a=answer(); a['findings']=':[{'
    runtime['tier2']=lambda *args: deepcopy(a)
    result = runtime['tier3']('test')
    assert 'A: 120.' in result['findings']
    assert ':[{' not in result['findings'] and 'Revenue was' not in result['findings']


def test_notebook_product_return_rate_uses_matching_populations():
    import ast
    notebook=json.loads((ROOT/'notebooks/02_build_database.ipynb').read_text())
    source=''.join(notebook['cells'][30]['source'])
    sql=next(node.value for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Constant) and isinstance(node.value,str) and 'SELECT' in node.value)
    database=ROOT/'data/processed/evidenceiq.duckdb'
    if not database.exists(): pytest.skip('local dataset unavailable')
    with duckdb.connect(str(database),read_only=True,config={'enable_external_access':'false'}) as con:
        result=con.execute(sql).fetchone()
    assert result==(8.35,2.36)


def test_evaluation_loop_keeps_errors_and_excludes_hidden_values(tmp_path,monkeypatch):
    import pandas as pd
    n=load_notebook('06_evaluation.ipynb')
    def good(question):
        a=answer(); a.update(question=question,tier=3,insufficient_data=False,retries=0,seconds=.1)
        a=n['verify'](a)
        a['claims'].append({'value':999,'status':'unsupported'})
        return a
    def failed(question):
        raise RuntimeError('test model failure')
    n.update(tier1=good,tier2=failed,tier3=good)
    n['questions']=[{'id':'test','question':'Revenue?','answerable':True,'difficulty':'easy','gt_value':120}]
    (tmp_path/'notebooks').mkdir();monkeypatch.chdir(tmp_path/'notebooks')
    notebook=json.loads((ROOT/'notebooks/06_evaluation.ipynb').read_text())
    exec(''.join(notebook['cells'][5]['source']), n)
    frame=n['df']
    assert len(frame)==3
    assert frame.loc[frame.tier==2,'correct'].iloc[0]==0
    assert frame.loc[frame.tier==3,'values'].iloc[0]==[120]
    assert frame.error.notna().sum()==1
    saved=pd.read_csv(tmp_path/'eval/results/notebook_run/all_runs.csv')
    assert len(saved)==3 and 'correct' in saved


def test_boolean_facts_require_exact_typed_cells(runtime):
    a=answer()
    a['log'][0]['rows']=[{'is_complete_month':False,'trading_days':8}]
    fact={'text':'The month is incomplete.','value':False,'kind':'boolean','row':0,
          'column':'is_complete_month','from_call':7,'calc':'none','inputs':[]}
    a['claims']=[fact]
    assert runtime['verify'](deepcopy(a))['claims'][0]['status']=='supported'
    for changes in [{'value':0}, {'value':True}, {'column':'trading_days'}, {'row':1}, {'kind':'number'}]:
        broken=deepcopy(a);broken['claims'][0].update(changes)
        assert runtime['verify'](broken)['claims'][0]['status']=='unsupported'


def test_labels_do_not_exempt_unrelated_numbers(runtime):
    a=answer(findings='REGENCY CAKESTAND 3 TIER earned 120. There were 3 buyers.')
    a['log'][0]['rows'][0]['description']='REGENCY CAKESTAND 3 TIER'
    checked=runtime['verify'](a)
    assert runtime['clean_findings'](checked)=='REGENCY CAKESTAND 3 TIER earned 120. There were [unverified] buyers.'
    assert checked['undeclared']==[3,3]  # paragraph and claim text


def test_binding_rejects_wrong_row_column_unit_and_calculation(runtime):
    a=answer()
    a['log'][0]['rows']=[{'revenue':120,'trading_days':100},{'revenue':100,'trading_days':120}]
    a['claims'][0].update(row=0,column='revenue',from_call=7,unit='GBP')
    assert runtime['verify'](deepcopy(a))['claims'][0]['status']=='supported'
    for changes in [{'row':1}, {'column':'trading_days'}, {'unit':'USD'}]:
        broken=deepcopy(a);broken['claims'][0].update(changes)
        assert runtime['verify'](broken)['claims'][0]['status']=='unsupported'
    a=answer(20,'difference',[120,100])
    a['claims'][0]['input_cells']=[{'from_call':7,'row':0,'column':'b'}, {'from_call':7,'row':0,'column':'a'}]
    assert runtime['verify'](a)['claims'][0]['status']=='unsupported'


def test_retry_keeps_best_supported_attempt(runtime):
    first=answer(findings='Revenue was 120. Unsupported growth 77%.')
    last=answer(999,findings='Revenue was 999.')
    attempts=iter([first,last,last])
    runtime['tier2']=lambda *args:deepcopy(next(attempts))
    checked=runtime['tier3']('test')
    assert checked['retries']==2
    assert runtime['claims_to_show'](checked)[0]['value']==120
    assert '999' not in checked['findings']


def test_chart_repairs_clear_axes_and_rejects_bad_measurement(runtime):
    log=answer()['log'];log[0]['rows']=[{'description':'CAKESTAND 3 TIER','revenue':120}]
    chart=runtime['make_chart']({'type':'bar','source_tool_call':7},log)
    assert chart['ok'] and chart['rows'][0]['x']=='description' and chart['rows'][0]['y']=='revenue'
    assert not runtime['make_chart']({'type':'bar','source_tool_call':7,'x':'revenue','y':'description'},log)['ok']
    log[0]['rows'][0]['units']=20
    assert not runtime['make_chart']({'type':'bar','source_tool_call':7},log)['ok']


def test_query_patterns_preserve_scope_and_reject_extra_filters(runtime):
    for question in ['Top 3 products in 2010?', 'What was our total revenue in 2010?',
                     'Did October 2010 beat September 2010 on revenue, and by what percentage?']:
        contract=runtime['question_contract'](question)
        assert contract and '2010' in contract['sql'] and '2011' not in contract['sql']
        assert runtime['query_scope_problem'](contract['sql'],question) is None
    assert runtime['question_contract']('Top 3 products in 2010 in France?') is None
    assert runtime['question_contract']('Top 0 products in 2010?') is None
    assert runtime['query_scope_problem']('SELECT SUM(revenue) FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2011 AND is_product', 'What is revenue for 2011 overall?')
    wrong=answer();wrong['question']='What was our total revenue in 2011?'
    assert runtime['verify'](wrong)['claims'][0]['status']=='unsupported'


def test_fixed_examples_end_to_end_and_different_inputs(runtime):
    runtime['ask_gemma']=lambda *args:pytest.fail('Recognised query patterns should not need model inference')
    questions=yaml.safe_load((ROOT/'eval/benchmark.yaml').read_text())['questions']
    evaluator=load_notebook('06_evaluation.ipynb')
    for q in questions:
        if q['id'] not in ('q01','q02','q03','q04','q05','q07','q11','q20','q21'):continue
        checked=runtime['tier3'](q['question'])
        assert checked['route']=='query_pattern'
        assert checked['retries']==0 and not checked['undeclared']
        assert not checked['scope_errors'] and all(c['status']=='supported' for c in checked['claims'])
        expected=evaluator['evaluation_expectations'](q)
        assert evaluator['result_matches'](checked['claims'],expected,checked['log']), q['id']
        if q['expected_chart']!='none':
            assert checked['chart']['type']==q['expected_chart']
    checked=runtime['tier3']('Top 3 products in 2010?')
    assert len(checked['claims'])==3 and checked['retries']==0
    complete=runtime['tier3']('Is November 2010 a complete month in the dataset?')
    assert complete['claims'][0]['value'] is True
    decline=runtime['tier3']('Did October 2011 beat November 2011 on revenue, and by what percentage?')
    change = next(c for c in decline['claims'] if c.get('calc') == 'pct_change')
    assert change['value'] < 0 and not decline['undeclared']
    missing=runtime['tier3']('Is December 2099 a complete month in the dataset?')
    assert not missing['claims'] and 'No usable data' in missing['findings']


def test_complete_result_scoring_rejects_partial_lists_and_wrong_labels():
    n=load_notebook('06_evaluation.ipynb')
    expected=[{'stock_code':'A','description':'FIRST','revenue':120}, {'stock_code':'B','description':'SECOND','revenue':100}]
    claims=[{'text':'FIRST earned 120','value':120}]
    assert not n['result_matches'](claims,expected)
    claims.append({'text':'SECOND earned 100','value':100})
    assert n['result_matches'](claims,expected)
    claims[1]['text']='FIRST earned 100'
    assert not n['result_matches'](claims,expected)
    assert not n['result_matches']([{'value':0}], [{'is_complete_month':False}])
    assert not n['result_matches']([{'value':120.9}], [{'revenue':120}])


def test_chart_cannot_leak_withheld_values(runtime):
    a=answer();a['log'][0]['rows']=[{'description':'Safe','revenue':120},{'description':'Unverified','revenue':999}]
    a['question'] = 'Revenue from products in 2011?'
    # These rows lack the requested date restriction; recovery must not turn
    # out-of-scope SQL into facts or let its chart reach the public answer.
    a['chart']={'type':'bar','source_tool_call':7,'x':'description','y':'revenue'}
    runtime['tier2']=lambda *args:deepcopy(a)
    checked=runtime['tier3']('test',max_retries=0)
    assert checked['chart'] is None and 'chart was withheld' in checked['limitations']


def test_wrong_label_and_material_rounding_are_rejected(runtime):
    a=answer();a['log'][0]['rows']=[{'country':'France','revenue':120}]
    a['claims'][0].update(unit='GBP',text='Germany revenue was 120.')
    assert runtime['verify'](a)['claims'][0]['status']=='unsupported'
    assert not runtime['about_equal'](120,120.9)
    assert runtime['about_equal'](30.6349,30.63)


def test_foreign_market_pattern_and_typed_fallback(runtime):
    q='Which country outside the UK generated the most revenue in 2011, and how much was it?'
    checked=runtime['tier3'](q)
    assert checked['claims'][0]['value']==276661.86
    assert 'Netherlands' in checked['findings'] and checked['retries']==0
    assert checked['usage']=={'model_calls':0,'input_tokens':0,'output_tokens':0}
    log=[{'n':0,'tool':'run_sql','ok':True,'code':"SELECT invoice_month, trading_days, is_complete_month FROM dim_month WHERE invoice_month='2011-12'",
          'rows':[{'invoice_month':'2011-12','trading_days':8,'is_complete_month':False}]}]
    a={'claims':runtime['claims_from_log'](log),'log':log,'findings':'The month is incomplete.'}
    assert all(c['status']=='supported' for c in runtime['verify'](a)['claims'])


def test_usage_unknown_is_not_zero(runtime):
    assert runtime['model_usage']([{}])['input_tokens'] is None
    assert runtime['model_usage']([{'model_calls':1,'input_tokens':10,'output_tokens':20}])['input_tokens']==10


def test_all_shared_notebook_functions_match():
    """Intentional notebook duplication must not change one tier's arithmetic."""
    definitions=[]
    for name in ['04_tier2_agent','05_tier3_verification','06_evaluation']:
        notebook=json.loads((ROOT/'notebooks'/f'{name}.ipynb').read_text())
        found={}
        for cell in notebook['cells']:
            if cell['cell_type']=='code':
                found.update({node.name:ast.dump(node,include_attributes=False)
                              for node in ast.parse(''.join(cell['source'])).body if isinstance(node,ast.FunctionDef)})
        definitions.append(found)
    for left,right in zip(definitions,definitions[1:]):
        for name in left.keys() & right.keys():
            assert left[name]==right[name], name


def test_cancellation_rate_uses_completed_order_denominator(runtime):
    q='What was our cancellation rate in 2011?'
    checked=runtime['tier3'](q)
    assert checked['claims'][0]['value']==17.24
    assert checked['claims'][0]['unit']=='%'
    assert 'Cancellations are excluded' not in checked['findings']
    wrong=deepcopy(checked)
    wrong['log'][0]['code']='SELECT 20.18 AS cancellation_rate FROM sales WHERE year(invoice_date)=2011 LIMIT 1'
    assert runtime['verify'](wrong)['claims'][0]['status']=='unsupported'


def test_trace_markers_are_removed_without_hiding_measurements(runtime):
    a=answer(findings='[call 7] Revenue was 120, with growth of 12%.')
    checked=runtime['verify'](a)
    assert runtime['clean_findings'](checked)=='Revenue was 120, with growth of [unverified]%.'
    assert 7 not in checked['undeclared']


def test_order_lines_are_not_orders_and_filtered_ids_are_labels(runtime):
    question='How many orders did customer 18102 place across the whole dataset?'
    bad='SELECT COUNT(invoice_no) AS orders FROM sales WHERE customer_id = 18102 AND quantity > 0'
    assert runtime['query_scope_problem'](bad,question)
    good='SELECT COUNT(DISTINCT invoice_no) AS orders FROM sales WHERE customer_id = 18102 AND NOT is_cancellation'
    assert runtime['query_scope_problem'](good,question) is None
    a=answer(value=145, findings='Customer 18102 placed 145 orders, with 18 extra orders.')
    a['log'][0].update(code=good,rows=[{'orders':145}])
    checked=runtime['verify'](a)
    assert runtime['clean_findings'](checked)=='Customer 18102 placed 145 orders, with [unverified] extra orders.'


def test_customer_identifiers_are_labels_not_measurements(runtime):
    a=answer(value=188,findings='Customer 14911 placed 188 orders.')
    a['log'][0]['rows']=[{'customer_id':14911,'orders':188}]
    checked=runtime['verify'](a)
    assert not checked['undeclared']
    assert runtime['clean_findings'](checked)=='Customer 14911 placed 188 orders.'
    assert 14911 not in [v for _,v in runtime['numbers_in_log'](a['log'])]


def test_customer_order_ranking_requires_matching_population(runtime):
    q='Which five customers placed the most orders in 2011?'
    base='SELECT customer_id, COUNT(DISTINCT invoice_no) AS orders FROM sales WHERE NOT is_cancellation AND year(invoice_date)=2011'
    tail=' GROUP BY customer_id ORDER BY orders DESC LIMIT 5'
    assert runtime['query_scope_problem'](base+tail,q)
    assert runtime['query_scope_problem'](base+' AND customer_id IS NOT NULL AND is_product AND NOT is_outlier'+tail,q)
    assert runtime['query_scope_problem'](base+' AND customer_id IS NOT NULL'+tail,q) is None


def test_refusal_flag_does_not_excuse_invented_figures():
    n=load_notebook('06_evaluation.ipynb')
    refused={'tier':1,'insufficient_data':True,'findings':'I cannot answer. Forecast: 8750.',
             'claims':[{'value':8750,'text':'Forecast 8750','calc':'none'}],'log':[]}
    assert not n['refusal_is_correct'](refused)
    refused.update(findings='No cost data is available.',claims=[])
    assert n['refusal_is_correct'](refused)
    context=answer(value=8,findings='December 2011 is incomplete, with 8 trading days.')
    context.update(tier=2,insufficient_data=True)
    context['log'][0]['rows']=[{'trading_days':8}]
    context['claims'][0]['unit']='days'
    assert n['refusal_is_correct'](context)
