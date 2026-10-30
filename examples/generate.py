import copy
import json
from pathlib import Path
from src.agent import Core, MockModel
from src.runtime import run, storyboard_markdown


def write(name, value):
    Path('examples/' + name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    data = json.loads(Path('data/materials.json').read_text(encoding='utf-8'))
    base = {'theme': '字幕产品', 'audience': '新手创作者', 'platform': '短视频', 'target_seconds': 30, 'style': '简洁'}
    cases = {'normal': {**base, 'target_seconds': 60}, 'revised': base,
             'missing': {k: v for k, v in base.items() if k != 'audience'}, 'no_material': {**base, 'theme': '火星旅行'},
             'query_rewrite': {**base, 'theme': '字卡'}, 'tool_failure': base,
             'impossible': {**base, 'target_seconds': 0.1}, 'changed_materials': base,
             'persistent_failure': base, 'step_limit': base,
             'profile_change': {**base, 'audience': '专业剪辑师', 'platform': 'B站', 'style': '活泼'}}
    for name, request in cases.items():
        local = copy.deepcopy(data)
        if name == 'changed_materials':
            local['materials'] = [local['materials'][0]]
            write(name + '.data.json', local)
        write(name + '.input.json', request)
        output = run(Core(request, local), MockModel(),
              fail_once='estimate' if name == 'tool_failure' else None,
              fail_always='estimate' if name == 'persistent_failure' else None,
              limit=4 if name == 'step_limit' else 16)
        write(name + '.output.json', output)
        if name in ('revised', 'profile_change'):
            Path(f'examples/{name}.script.md').write_text(storyboard_markdown(output),encoding='utf-8')


if __name__ == '__main__':
    main()
