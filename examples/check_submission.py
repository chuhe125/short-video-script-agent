"""Local submission preflight. Reads secrets only to detect accidental copies; prints no values."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    required = ['README.md', 'src/agent.py', 'src/runtime.py', 'tests/test_agent.py',
                'data/materials.json', 'requirements.txt', '.env.example', 'examples/test-results.txt',
                'docs/01-requirements.md', 'docs/02-solution.md', 'docs/03-evaluation.md',
                'docs/04-ai-usage.md', 'docs/05-retrospective.md']
    missing = [p for p in required if not (root/p).exists()]
    secret_values = []
    env = root/'.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in ('MODEL_API_KEY', 'DEEPSEEK_API_KEY') and value.strip():
                secret_values.append(value.strip().strip('\'"'))
    accidental_files = []
    for path in root.rglob('*'):
        if not path.is_file() or path.name == '.env' or any(part in ('__pycache__', '.git') for part in path.parts):
            continue
        if path.suffix in ('.pyc', '.sqlite3'):
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        if any(secret in text for secret in secret_values):
            accidental_files.append(str(path.relative_to(root)))
    example = (root/'.env.example').read_text(encoding='utf-8')
    example_clean = all(not line.partition('=')[2].strip() for line in example.splitlines()
                        if line.partition('=')[0].strip() in ('MODEL_API_KEY', 'DEEPSEEK_API_KEY'))
    evidence = json.loads((root/'examples/evidence-checks.json').read_text(encoding='utf-8'))
    report = {'missing_required_files': missing, 'key_copies_outside_local_env': accidental_files,
              'example_has_no_key': example_clean,
              'local_env_ignored': '.env' in (root/'.gitignore').read_text(encoding='utf-8').splitlines(),
              'checked_real_entry_cases': len(evidence),
              'technical_artifacts_checked': not missing and not accidental_files and example_clean,
              'final_submission_complete': False,
              'remaining_manual_items': ['本人贡献与实际用时、个人回顾', '提交时核对最终commit SHA',
                                         '私有仓库评审权限（如适用）']}
    (root/'examples/submission-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['technical_artifacts_checked'] and report['local_env_ignored'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
