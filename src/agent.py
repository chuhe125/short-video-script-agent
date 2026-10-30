"""Evidence-grounded storyboard tools; model decisions stay outside the executor."""
import hashlib
import math
from .runtime import BaseCore, cli, decision, dumps

INSTRUCTION = '''Create an editable short-video script using tool evidence and editorial_brief.
Choose one business action through its matching native function. Actions and business arguments:
search {query:string}: returns product facts, approved_lines and versioned IDs;
write {scenes:[{source_id:string,narration:string,visual:string,hold_seconds:number}]}:
stores 1..10 scenes. narration must EXACTLY equal that source's fact or one of its approved_lines.
visual must be one of editorial_brief.allowed_visuals. hold_seconds is extra silent demonstration
footage, not narration duration. Match the brief's pace and preferred visual to audience/platform/style.
estimate {}: returns CURRENT script durations, overrun and recommended_hold_total;
check {}: checks CURRENT facts, brand rules and per-shot hold bounds;
finish {}: ends with a guarded result. Read sources before writing. No results: rewrite query once
or request facts. Never invent effects, numbers, performance, capabilities or source IDs.
After EVERY write, estimate AND check again. If too long reduce holds using the observed trim
budget, shorten narration to source facts or remove lower priority facts, then re-estimate and check.
Aim near 90% of target when useful footage is justified; don't pad beyond max_hold_seconds.
If rules fail repair using retrieved facts or stop. On tool errors preserve earlier sources/script,
retry the failed tool at most once or stop. No publication or video rendering.
Each native function also requires a reason argument with a short observable decision basis.'''


def editorial_brief(request, data):
    audience, platform, style = (request.get(k, '') for k in ('audience', 'platform', 'style'))
    beginner = any(w in audience for w in ('新手', '入门', '初学'))
    tutorial = any(w in style for w in ('教程', '教学', '详细'))
    lively = any(w in style for w in ('活泼', '轻松', '快节奏'))
    landscape = any(w in platform.lower() for w in ('b站', 'bilibili', '横屏'))
    rate = data['chars_per_second'] * (0.875 if beginner else 1.125 if '专业' in audience else 1)
    return {'chars_per_second': round(rate, 3), 'frame': '16:9' if landscape else '9:16',
            'preferred_visual': '操作演示' if tutorial or beginner else '字幕展示' if lively else '产品画面',
            'reading_note': '逐项展示，字幕留出阅读时间' if beginner else '聚焦功能，直接展示关键区域',
            'editing_note': '分步演示并保留操作停顿' if tutorial else '短镜头切换，字幕突出重点' if lively else '干净切换，突出单一功能',
            'title': '跟着画面了解功能' if tutorial else '一起看看这些功能' if lively else '产品功能演示',
            'initial_hold_seconds': 9 if tutorial else 6 if lively else 8,
            'max_hold_seconds': 12 if tutorial else 8 if lively else 10,
            'desired_fill_ratio': 0.9, 'allowed_visuals': list(data['allowed_visuals']),
            'voiceover_method': '按字符数粗估，未实际配音'}


class Core(BaseCore):
    schema = {'search': ['query'], 'write': ['scenes'], 'estimate': [], 'check': []}

    def __init__(self, request, data, state=None):
        super().__init__()
        self.request, self.data = request, data
        self.sources, self.scenes, self.duration, self.review = {}, [], None, None
        self.errors, self.revisions, self.brief = [], [], None

    def validate(self):
        missing = [k for k in ('theme', 'audience', 'platform', 'style')
                   if not isinstance(self.request.get(k), str) or not self.request[k].strip()]
        duration = self.request.get('target_seconds')
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or duration <= 0 or duration > 600):
            missing.append('target_seconds_in_0_to_600')
        if not missing:
            rate = self.data.get('chars_per_second')
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
                raise ValueError('data chars_per_second must be positive and finite')
            self.brief = editorial_brief(self.request, self.data)
        return missing

    def model_input(self):
        return {**self.request, 'editorial_brief': self.brief,
                'brand_forbidden_terms': self.data['forbidden']}

    def record_failure(self, action, args, result):
        self.errors.append({'action': action, 'args': args, 'result': result})

    def signature(self):
        return hashlib.sha256(dumps(self.scenes).encode()).hexdigest()

    def tool(self, action, args):
        if self.brief is None and self.validate():
            return {'ok': False, 'error': 'missing_input'}
        if action == 'search':
            query = args['query']
            if not isinstance(query, str) or not query.strip():
                return {'ok': False, 'error': 'empty_query'}
            found = [m for m in self.data['materials'] if any(t in query for t in m['tags'])]
            self.sources.update({m['id']: m for m in found})
            return {'ok': True, 'materials': found}
        if action == 'write':
            scenes = args['scenes']
            if not isinstance(scenes, list) or not 1 <= len(scenes) <= 10:
                return {'ok': False, 'error': 'one_to_ten_scenes_required'}
            for scene in scenes:
                if not isinstance(scene, dict) or set(scene) != {'source_id', 'narration', 'visual', 'hold_seconds'}:
                    return {'ok': False, 'error': 'invalid_scene_fields'}
                if any(not isinstance(scene[k], str) for k in ('source_id', 'narration', 'visual')):
                    return {'ok': False, 'error': 'invalid_scene_text'}
                seconds = scene['hold_seconds']
                if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
                        or not 0 <= seconds <= 600):
                    return {'ok': False, 'error': 'invalid_hold_seconds'}
            self.scenes = [dict(s) for s in scenes]
            self.duration, self.review = None, None
            self.revisions.append({'revision': len(self.revisions) + 1, 'script_hash': self.signature(),
                                   'scene_count': len(scenes)})
            return {'ok': True, **self.revisions[-1]}
        if not self.scenes:
            return {'ok': False, 'error': 'write_script_first'}
        if action == 'estimate':
            rate = self.brief['chars_per_second']
            spoken = [round(len(s['narration']) / rate, 2) for s in self.scenes]
            per_scene = [round(seconds + scene['hold_seconds'], 2) for seconds, scene in zip(spoken, self.scenes)]
            total, target = round(sum(per_scene), 2), self.request['target_seconds']
            budget = math.floor(max(0, target * self.brief['desired_fill_ratio'] - sum(spoken)) * 100) / 100
            self.duration = {'ok': True, 'script_hash': self.signature(), 'scene_seconds': per_scene,
                             'spoken_seconds': spoken, 'chars_per_second': rate,
                             'total_seconds': total, 'target_seconds': target,
                             'overrun_seconds': round(max(0, total - target), 2),
                             'recommended_hold_total': budget, 'within_limit': total <= target}
            return self.duration
        if action != 'check':
            return {'ok': False, 'error': 'unknown_action'}
        risks = []
        for index, scene in enumerate(self.scenes):
            source = self.sources.get(scene['source_id'])
            permitted = ([source['fact']] + source.get('approved_lines', [])) if source else []
            if scene['narration'] not in permitted:
                risks.append({'scene': index + 1, 'reason': 'unsupported_product_claim'})
            if scene['visual'] not in self.data['allowed_visuals']:
                risks.append({'scene': index + 1, 'reason': 'unapproved_visual'})
            if any(word in scene['narration'] for word in self.data['forbidden']):
                risks.append({'scene': index + 1, 'reason': 'brand_rule_violation'})
            if scene['hold_seconds'] > self.brief['max_hold_seconds']:
                risks.append({'scene': index + 1, 'reason': 'excessive_hold',
                              'max_hold_seconds': self.brief['max_hold_seconds']})
        self.review = {'ok': True, 'script_hash': self.signature(), 'passed': not risks, 'risks': risks}
        return self.review

    def completion(self):
        signature = self.signature()
        return 'completed' if (self.duration and self.review and self.duration['script_hash'] == signature
                               and self.review['script_hash'] == signature and self.duration['within_limit']
                               and self.review['passed']) else 'incomplete'

    def result(self):
        scenes, cursor = [], 0
        for i, scene in enumerate(self.scenes):
            source = self.sources.get(scene['source_id'])
            seconds = self.duration['scene_seconds'][i] if self.duration else None
            scenes.append({**scene, 'index': i + 1, 'estimated_seconds': seconds,
                           'start_seconds': round(cursor, 2) if seconds is not None else None,
                           'end_seconds': round(cursor + seconds, 2) if seconds is not None else None,
                           'caption': source['fact'] if source else None,
                           'source_version': source['version'] if source else None,
                           'source_quote': source['fact'] if source else None,
                           'shot_note': f"{self.brief['frame']}；{self.brief['reading_note']}；{self.brief['editing_note']}"
                           if self.brief else None})
            if seconds is not None:
                cursor += seconds
        warnings, gaps = [], []
        if not self.sources:
            gaps.append('需要可检索的产品事实或素材来源')
        if self.duration and self.duration['total_seconds'] < self.request['target_seconds'] * 0.7:
            warnings.append('脚本明显短于目标；素材不足时应补充资料，避免无依据扩写或长时间空镜')
        if self.duration and not self.duration['within_limit']:
            gaps.append('需压缩分镜或增加目标时长')
        if self.review and not self.review['passed']:
            gaps.append('需修复事实、品牌或镜头停留风险')
        if self.scenes and not self.duration:
            gaps.append('当前版本尚未完成时长估算')
        if self.scenes and not self.review:
            gaps.append('当前版本尚未完成规则检查')
        return {'title': self.brief['title'] if self.brief else None,
                'audience': self.request.get('audience'), 'platform': self.request.get('platform'),
                'style': self.request.get('style'), 'editorial_brief': self.brief, 'scenes': scenes,
                'source_ids': sorted({s['source_id'] for s in self.scenes}),
                'sources': list(self.sources.values()), 'duration_check': self.duration,
                'rule_check': self.review, 'revisions': self.revisions, 'tool_errors': self.errors,
                'warnings': warnings, 'gaps': gaps,
                'unfinished_reason': None if self.completion() == 'completed' else
                '；'.join(gaps) or '工具或模型尚未完成任务，请查看Trace'}


class MockModel:
    """Explicit offline simulator, not evidence of real model decisions."""
    mode = 'mock'

    def choose(self, request, trace):
        brief = request['editorial_brief']
        if not trace:
            return decision('search', '先检索产品事实与获准表达', query=request['theme'])
        last = trace[-1]
        if last['observation'].get('error'):
            count = sum(t['action'] == last['action'] and bool(t['observation'].get('error')) for t in trace)
            if count < 2:
                return decision(last['action'], '保留脚本与来源，仅重试失败工具', **last['args'])
            return decision('finish', '工具未恢复，保留部分结果并说明未完成')
        materials = {}
        for t in trace:
            if t['action'] == 'search':
                materials.update({m['id']: m for m in t['observation'].get('materials', [])})
        if not materials:
            if sum(t['action'] == 'search' for t in trace) < 2:
                return decision('search', '首次检索为空，改写关键词再查', query=request['theme'].replace('字卡', '字幕'))
            return decision('finish', '补查仍无素材，请提供产品事实')
        writes = [i for i, t in enumerate(trace) if t['action'] == 'write' and t['observation'].get('ok')]
        if not writes:
            scenes = [{'source_id': m['id'], 'narration': (m.get('approved_lines') or [m['fact']])[0],
                       'visual': brief['preferred_visual'], 'hold_seconds': brief['initial_hold_seconds']}
                      for m in materials.values()]
            return decision('write', '结合受众语速、平台画幅和风格形成首稿分镜', scenes=scenes)
        current = trace[writes[-1] + 1:]
        estimates = [t['observation'] for t in current if t['action'] == 'estimate' and t['observation'].get('ok')]
        checks = [t['observation'] for t in current if t['action'] == 'check' and t['observation'].get('ok')]
        if not estimates:
            return decision('estimate', '估算当前版本旁白和演示画面总时长')
        if not checks:
            return decision('check', '核对当前版本事实、品牌与镜头停留规则')
        if not checks[-1]['passed']:
            return decision('finish', '事实或品牌规则不通过，停止并暴露风险')
        if not estimates[-1]['within_limit']:
            if len(writes) >= 2:
                return decision('finish', '修正后仍超时长，明确未完成')
            selected, used = [], 0
            for scene in trace[writes[-1]]['args']['scenes']:
                line = scene['narration']
                spoken = round(len(line) / brief['chars_per_second'], 2)
                if used + spoken > request['target_seconds'] * 0.9:
                    line = materials[scene['source_id']]['fact']
                    spoken = round(len(line) / brief['chars_per_second'], 2)
                if used + spoken <= request['target_seconds']:
                    selected.append({**scene, 'narration': line, 'hold_seconds': 0})
                    used = round(used + spoken, 2)
            if not selected:
                return decision('finish', '最短事实片段也无法满足时长，请调整要求')
            available = min(max(0, request['target_seconds'] * 0.9 - used),
                            len(selected) * brief['max_hold_seconds'])
            cents = max(0, math.floor(round(available, 6) * 100))
            base, remainder = divmod(cents, len(selected))
            for i, scene in enumerate(selected):
                scene['hold_seconds'] = (base + (1 if i < remainder else 0)) / 100
            return decision('write', '观察到超时长，缩短演示停顿并保留约九成目标时长，随后重查', scenes=selected)
        return decision('finish', '当前版本时长与规则均通过，结束')


if __name__ == '__main__':
    raise SystemExit(cli(Core, MockModel, INSTRUCTION))
