"""Explicit online evaluation; only synthetic inputs/data, keys never enter output."""
import argparse
import json
from pathlib import Path
from src.agent import Core, INSTRUCTION
from src.runtime import RemoteModel, load_local_env, run, storyboard_markdown

CASES = {'normal': 'completed', 'revised': 'completed', 'tool_failure': 'completed',
         'no_material': 'incomplete', 'missing': 'needs_input', 'impossible': 'incomplete',
         'changed_materials': 'completed'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', nargs='+', choices=list(CASES), default=['normal', 'revised', 'tool_failure'])
    parser.add_argument('--env-file', default='.env')
    args = parser.parse_args()
    load_local_env(args.env_file)
    data = json.loads(Path('data/materials.json').read_text(encoding='utf-8'))
    summary = []
    for name in args.cases:
        request = json.loads(Path(f'examples/{name}.input.json').read_text(encoding='utf-8'))
        alternate = Path(f'examples/{name}.data.json')
        local = json.loads(alternate.read_text(encoding='utf-8')) if alternate.exists() else data
        # Empty-corpus test makes the absent-material condition independent of model wording.
        if name == 'no_material':
            local = {**local, 'materials': []}
            Path('examples/no_material.data.json').write_text(json.dumps(local,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        model = RemoteModel(INSTRUCTION)
        result = run(Core(request, local), model, fail_once='estimate' if name == 'tool_failure' else None)
        Path(f'examples/real-{name}.output.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        Path(f'examples/real-{name}.script.md').write_text(storyboard_markdown(result),encoding='utf-8')
        estimates = [t['observation'].get('total_seconds') for t in result['trace'] if t['action']=='estimate']
        record = {'case': name, 'status': result['status'], 'expected': CASES[name],
                  'matches_expected': result['status'] == CASES[name], 'estimates': estimates,
                  'model_calls': len(model.calls), 'error': result.get('error')}
        summary.append(record)
        print(json.dumps(record,ensure_ascii=True),flush=True)
    Path('examples/real-latest-run.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if all(r['matches_expected'] for r in summary) else 1


if __name__ == '__main__':
    raise SystemExit(main())
