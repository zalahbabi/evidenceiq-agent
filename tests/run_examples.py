"""Run bounded live examples, or rescore saved answers without calling a model.

Examples: python tests/run_examples.py --full
          python tests/run_examples.py --benchmark eval/held_out.yaml --full
          python tests/run_examples.py --rescore eval/results/older_report.json
Every report gets its own CSV/summary/chart exports. --publish explicitly updates
what the dashboard shows, preserving the previous files in an archive first.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import shutil
import time

import pandas as pd
import yaml

from test_notebooks import load_notebook

ROOT = Path(__file__).resolve().parents[1]


def source_manifest(benchmark):
    """Identify the exact code and rubric used; notebook output changes do not count."""
    paths = [ROOT / 'notebooks/06_evaluation.ipynb', ROOT / 'requirements.txt',
             ROOT / 'tests/run_examples.py', benchmark]
    hashes = {}
    for path in paths:
        content = path.read_bytes()
        if path.suffix == '.ipynb':
            notebook = json.loads(content)
            content = '\n'.join(''.join(cell['source']) for cell in notebook['cells']
                                if cell['cell_type'] == 'code').encode()
        hashes[str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)] = hashlib.sha256(content).hexdigest()
    return hashes


def run_one(connection, tier, question, tier2_retries=0):
    """Only the question enters inference; expected answers stay in the parent."""
    started = time.monotonic()
    try:
        runtime = load_notebook('06_evaluation.ipynb')
        original = runtime['ask_gemma']
        calls = []

        def traced(system, prompt, shape):
            stage = next((name for name in ['PLAN', 'SQL', 'PYTHON', 'CHART', 'ANSWER']
                          if runtime.get(name + '_SHAPE') is shape), 'MODEL')
            print(f'  Tier {tier}: {stage.lower()}', flush=True)
            response = original(system, prompt, shape)
            calls.append({'stage': stage, 'response': response})
            return response

        runtime['ask_gemma'] = traced
        if tier == 2 and tier2_retries:
            answer = runtime['tier2_with_retries'](question, max_retries=tier2_retries)
        else:
            answer = runtime[f'tier{tier}'](question)
        visible = runtime['claims_to_show'](answer) if tier == 3 else answer.get('claims', [])
        connection.send({'answer': answer, 'visible_claims': visible, 'model_calls': calls,
                         'elapsed_seconds': round(time.monotonic() - started, 2)})
    except Exception as error:
        connection.send({'error': f'{type(error).__name__}: {error}',
                         'elapsed_seconds': round(time.monotonic() - started, 2)})
    finally:
        connection.close()


def judge(case, result, expected, runtime=None):
    """Use exactly the same factual rubric as notebook evaluation and exports."""
    runtime = runtime or load_notebook('06_evaluation.ipynb')
    if result.get('error'):
        return 'FAIL', [result['error']]
    answer = result['answer']
    metrics = runtime['score_answer'](answer, case, expected)
    if not case['answerable']:
        passed = metrics['refusal_correct'] == 1
        return ('PASS' if passed else 'FAIL'), ['Expected an explicit refusal without unsupported numerical claims.']
    if metrics['correct']:
        return 'PASS', ['Requested facts match; additional numerical claims passed the stated checks.']
    notes = []
    if not metrics['requested_facts_correct']:
        notes.append('Missing or incorrect requested facts, labels, or list entries.')
    if metrics['contradicted_claims']:
        notes.append('Contradictory additional claim(s): ' + '; '.join(metrics['factual_errors']))
    if metrics['unassessed_extra_claims']:
        notes.append('Additional measurements could not be assessed: ' + '; '.join(metrics['unassessed_claims']))
    if metrics['undeclared_displayed_numbers']:
        notes.append('Public prose contains undeclared measurements.')
    return 'FAIL', notes or ['Refused an answerable question.']


def write_report(report, output):
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2, default=str) + '\n')
    temporary.replace(output)


def result_entry(runtime, case, result, expected, timeout):
    answer = dict(result.get('answer') or {}, tier=case['tier'])
    if result.get('error'):
        answer['error'] = result['error']
    metrics = runtime['score_answer'](answer, case, expected)
    metrics.update(answerable=case['answerable'], difficulty=case.get('difficulty'),
                   seconds=result.get('elapsed_seconds', timeout), error=result.get('error'),
                   reviewed_by=case.get('reviewed_by'), usefulness_rating=None)
    status, notes = judge(case, result, expected, runtime)
    return {'id': case['id'], 'tier': case['tier'], 'question': case['question'],
            'expected': expected, 'status': status, 'notes': notes,
            **result, 'metrics': metrics}


def publish_exports(directory):
    """Publish only on request, retaining the exact previous dashboard artifacts."""
    current = ROOT / 'eval/results'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    archive = current / 'archive' / ('before_publish_' + stamp)
    names = ['all_runs.csv', 'summary.csv', 'comparison.png']
    existing = [name for name in names if (current / name).exists()]
    if existing:
        archive.mkdir(parents=True)
        for name in existing:
            shutil.copy2(current / name, archive / name)
    for name in names:
        shutil.copy2(directory / name, current / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=240, help='Maximum seconds per example')
    parser.add_argument('--full', action='store_true', help='Run every selected-benchmark question across --tiers')
    parser.add_argument('--tiers', nargs='+', type=int, choices=[1, 2, 3], default=None)
    parser.add_argument('--ids', nargs='+', help='Question IDs for a focused run')
    parser.add_argument('--benchmark', default='eval/benchmark.yaml', help='Development or held-out YAML benchmark')
    parser.add_argument('--rescore', help='Existing JSON report; no inference calls are made')
    parser.add_argument('--tier2-retries', type=int, default=0, help='Optional execution-retry control; separate from normal Tier 2')
    parser.add_argument('--output', help='New report path; existing files are never overwritten')
    parser.add_argument('--publish', action='store_true', help='Update dashboard exports after a complete main-benchmark run')
    args = parser.parse_args()
    if args.timeout <= 0 or args.tier2_retries < 0:
        parser.error('Timeout must be positive and retries cannot be negative.')
    benchmark = (ROOT / args.benchmark).resolve()
    questions = yaml.safe_load(benchmark.read_text())['questions']
    by_id = {q['id']: q for q in questions}
    runtime = load_notebook('06_evaluation.ipynb')
    if args.rescore:
        source = (ROOT / args.rescore).resolve()
        previous = json.loads(source.read_text())
        selected = [(record['tier'], record['id']) for record in previous['results']]
    elif args.full:
        selected = [(tier, q['id']) for q in questions for tier in (args.tiers or [1, 2, 3])]
    elif args.ids:
        selected = [(tier, qid) for qid in args.ids for tier in (args.tiers or [3])]
    elif benchmark != (ROOT / 'eval/benchmark.yaml').resolve():
        selected = [(tier, q['id']) for q in questions for tier in (args.tiers or [3])]
    else:
        selected = [(3, qid) for qid in ['q01', 'q04', 'q07', 'q11', 'q20', 'q13', 'q14', 'q15', 'q29', 'q30']]
        selected += [(1, 'q01'), (2, 'q01')]
    missing = sorted({qid for _, qid in selected} - by_id.keys())
    if missing:
        parser.error('Unknown question IDs: ' + ', '.join(missing))
    complete = len(selected) == len(questions) * 3 and set(selected) == {(tier, q['id']) for q in questions for tier in (1, 2, 3)}
    if args.publish and (not complete or args.tier2_retries or (args.rescore and previous.get('tier2_retries', 0)) or benchmark != (ROOT / 'eval/benchmark.yaml').resolve()):
        parser.error('--publish requires all main-benchmark questions and tiers, with normal Tier 2.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    output = ROOT / (args.output or f'eval/results/{"rescored" if args.rescore else "example_checks"}_{stamp}.json')
    if output.exists():
        parser.error('Output already exists; choose a new path to preserve previous results.')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'model': 'gemma3:4b',
              'timeout_seconds': args.timeout, 'benchmark': str(benchmark),
              'tier2_retries': args.tier2_retries, 'scoring_version': 'facts-and-exposure-v4',
              'packages': {name: importlib.metadata.version(name) for name in
                           ['duckdb', 'pandas', 'streamlit', 'sqlglot', 'ollama']},
              'scope': 'Full benchmark; independent human review pending.' if complete else 'Selected examples; not a full benchmark.',
              'results': []}
    report['source_hashes'] = source_manifest(benchmark)
    report['environment'] = {'python': platform.python_version(), 'system': platform.system(),
                             'release': platform.release(), 'architecture': platform.machine()}
    if not args.rescore:
        try:
            import ollama
            model = next(model for model in ollama.list().models if model.model == report['model'])
            report['model_digest'] = model.digest
        except Exception:
            report['model_digest'] = None
    if args.rescore:
        report.update(source_report=str(source), original_started_at=previous.get('started_at'),
                      inference_rerun=False, tier2_retries=previous.get('tier2_retries', 0))
    for index, (tier, qid) in enumerate(selected):
        case = dict(by_id[qid], tier=tier)
        expected = runtime['evaluation_expectations'](case)
        print(f'START tier {tier} {qid}: {case["question"]}', flush=True)
        if args.rescore:
            original = previous['results'][index]
            result = {key: original[key] for key in ('answer', 'visible_claims', 'model_calls', 'elapsed_seconds', 'error') if key in original}
        else:
            parent, child = multiprocessing.Pipe(duplex=False)
            process = multiprocessing.Process(target=run_one, args=(child, tier, case['question'], args.tier2_retries))
            process.start()
            child.close()
            if parent.poll(args.timeout):
                try:
                    result = parent.recv()
                except EOFError:
                    result = {'error': 'Example process exited without an answer.'}
            else:
                result = {'error': f'Exceeded {args.timeout}s per-example limit.'}
            if process.is_alive():
                process.join(2)
            if process.is_alive():
                process.terminate()
            process.join()
            parent.close()
        entry = result_entry(runtime, case, result, expected, args.timeout)
        report['results'].append(entry)
        write_report(report, output)
        print(entry['status'], qid, '; '.join(entry['notes']), flush=True)
        if result.get('answer'):
            print('  Findings:', result['answer'].get('findings'), flush=True)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    report['code_unchanged'] = report['source_hashes'] == source_manifest(benchmark)
    report['exports'] = str(output.with_suffix(''))
    write_report(report, output)
    frame = pd.DataFrame([{'id': r['id'], 'tier': r['tier'], **r['metrics']} for r in report['results']])
    runtime['export_evaluation'](frame, output.with_suffix(''))
    if args.publish:
        if not report['code_unchanged']:
            raise RuntimeError('Code or rubric changed during the run; the dashboard was not updated.')
        publish_exports(output.with_suffix(''))
    print('Saved:', output, flush=True)
    print('CSV, summary and chart:', output.with_suffix(''), flush=True)


if __name__ == '__main__':
    main()
