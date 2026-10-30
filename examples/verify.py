"""Verify saved evidence offline; this does not call a model or certify general accuracy."""
import hashlib
import json
from pathlib import Path
from src.runtime import dumps, storyboard_markdown

EXPECTED = {'normal': 'completed', 'revised': 'completed', 'tool_failure': 'completed',
            'no_material': 'incomplete', 'missing': 'needs_input', 'impossible': 'incomplete',
            'changed_materials': 'completed'}


def main():
    checks = []
    for name, status in EXPECTED.items():
        path = Path(f'examples/real-{name}.output.json')
        output = json.loads(path.read_text(encoding='utf-8'))
        assert output['mode'] == 'real', name
        assert output['status'] == status, (name, output['status'])
        result = output['result']
        if status == 'completed':
            duration, review = result['duration_check'], result['rule_check']
            assert duration['within_limit'] and review['passed'], name
            scenes = [{k: s[k] for k in ('source_id', 'narration', 'visual', 'hold_seconds')}
                      for s in result['scenes']]
            signature = hashlib.sha256(dumps(scenes).encode()).hexdigest()
            assert signature == duration['script_hash'] == review['script_hash'], name
            assert round(sum(s['estimated_seconds'] for s in result['scenes']), 2) == duration['total_seconds'], name
            sources = {s['id']: s for s in result['sources']}
            for scene in result['scenes']:
                source = sources[scene['source_id']]
                assert scene['narration'] in [source['fact']] + source.get('approved_lines', []), name
                assert scene['source_quote'] == source['fact'], name
        if name == 'revised':
            estimates = [s['observation'] for s in output['trace'] if s['action'] == 'estimate']
            assert any(not e['within_limit'] for e in estimates) and estimates[-1]['within_limit'], name
            assert len(result['revisions']) >= 2, name
        if name == 'tool_failure':
            errors = [t for t in output['trace'] if t['observation'].get('error') == 'injected_once_failure']
            assert len(errors) == 1 and result['scenes'] and result['sources'], name
        calls = output.get('execution', {}).get('model_calls', [])
        if status != 'needs_input':
            assert output['model'] == 'deepseek-flash' and calls, name
            assert len(calls) == len(output['trace']), name
            for call, step in zip(calls, output['trace']):
                # Native response provenance: the executed action must be what the model proposed first.
                native = call['action_content'][0]
                assert native['name'] == step['action'], name
                arguments = json.loads(native['arguments'])
                reason = arguments.pop('reason')
                assert arguments == step['args'] and reason == step['reason'], name
        Path(f'examples/real-{name}.script.md').write_text(storyboard_markdown(output), encoding='utf-8')
        checks.append({'case': name, 'status': status, 'model_calls': len(calls), 'evidence_checked': True})
    Path('examples/evidence-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
