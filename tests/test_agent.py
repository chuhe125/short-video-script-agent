import copy
import json
import unittest
import io
import os
import tempfile
from unittest.mock import patch
from pathlib import Path
from src.agent import Core, MockModel, INSTRUCTION
from src.runtime import run, RemoteModel, load_local_env, storyboard_markdown

DATA = json.loads(Path('data/materials.json').read_text(encoding='utf-8'))
REQUEST = {'theme': '字幕产品', 'audience': '新手创作者', 'platform': '短视频', 'target_seconds': 30, 'style': '简洁'}


class Tests(unittest.TestCase):
    def execute(self, request=None, data=None, **options):
        return run(Core(request or copy.deepcopy(REQUEST), copy.deepcopy(data or DATA)), MockModel(), **options)

    def test_normal(self):
        result = self.execute({**REQUEST, 'target_seconds': 60})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['result']['scenes']), 3)
        self.assertTrue(result['result']['rule_check']['passed'])

    def test_duration_revision(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed')
        estimates = [t['observation'] for t in result['trace'] if t['action'] == 'estimate']
        self.assertGreater(estimates[0]['total_seconds'], 30)
        self.assertLessEqual(estimates[1]['total_seconds'], 30)
        self.assertEqual(sum(t['action'] == 'check' for t in result['trace']), 2)

    def test_missing(self):
        for key in REQUEST:
            request = copy.deepcopy(REQUEST)
            del request[key]
            self.assertEqual(self.execute(request)['status'], 'needs_input')

    def test_no_material(self):
        result = self.execute({**REQUEST, 'theme': '火星旅行'})
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['result']['scenes'], [])

    def test_query_rewrite(self):
        result = self.execute({**REQUEST, 'theme': '字卡'})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(t['action'] == 'search' for t in result['trace']), 2)

    def test_tool_failure(self):
        result = self.execute(fail_once='estimate')
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['result']['tool_errors'])
        self.assertEqual(sum(t['action'] == 'search' for t in result['trace']), 1)

    def test_impossible_duration(self):
        result = self.execute({**REQUEST, 'target_seconds': 0.1})
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['result']['duration_check']['within_limit'])

    def test_invented_claim_rejected(self):
        core = Core(REQUEST, DATA)
        core.tool('search', {'query': '字幕'})
        core.tool('write', {'scenes': [{'source_id': 'P01', 'narration': '效率提升80%',
                                      'visual': '产品画面', 'hold_seconds': 0}]})
        core.tool('estimate', {})
        check = core.tool('check', {})
        self.assertFalse(check['passed'])
        self.assertEqual(core.completion(), 'incomplete')

    def test_edit_invalidates_checks(self):
        core = Core(REQUEST, DATA)
        core.tool('search', {'query': '字幕'})
        scenes = [{'source_id': 'P01', 'narration': '支持字幕', 'visual': '产品画面', 'hold_seconds': 0}]
        core.tool('write', {'scenes': scenes})
        core.tool('estimate', {})
        core.tool('check', {})
        self.assertEqual(core.completion(), 'completed')
        core.tool('write', {'scenes': scenes})
        self.assertEqual(core.completion(), 'incomplete')

    def test_sources_and_total(self):
        result = self.execute()['result']
        for scene in result['scenes']:
            source = next(m for m in DATA['materials'] if m['id'] == scene['source_id'])
            self.assertIn(scene['narration'], [source['fact']] + source.get('approved_lines', []))
            self.assertEqual(source['fact'], scene['source_quote'])
        self.assertAlmostEqual(sum(s['estimated_seconds'] for s in result['scenes']), result['duration_check']['total_seconds'])

    def test_changed_sources(self):
        data = copy.deepcopy(DATA)
        data['materials'] = [data['materials'][0]]
        result = self.execute(data=data)
        self.assertEqual(result['result']['source_ids'], ['P01'])

    def test_revised_script_is_useful_length(self):
        result = self.execute()['result']
        self.assertGreaterEqual(result['duration_check']['total_seconds'], 24)
        self.assertLessEqual(result['duration_check']['total_seconds'], 30)
        self.assertEqual(result['revisions'][-1]['revision'], 2)
        self.assertFalse(result['warnings'])

    def test_audience_platform_style_change_execution(self):
        beginner = self.execute()['result']
        professional = self.execute({**REQUEST, 'audience': '专业剪辑师', 'platform': 'B站', 'style': '活泼'})['result']
        self.assertNotEqual(beginner['editorial_brief']['chars_per_second'], professional['editorial_brief']['chars_per_second'])
        self.assertEqual(professional['editorial_brief']['frame'], '16:9')
        self.assertNotEqual(beginner['scenes'][0]['visual'], professional['scenes'][0]['visual'])
        self.assertNotEqual(beginner['scenes'][0]['shot_note'], professional['scenes'][0]['shot_note'])
        self.assertNotEqual(beginner['title'], professional['title'])

    def test_timeline_matches_estimates(self):
        result = self.execute()['result']
        cursor = 0
        for scene in result['scenes']:
            self.assertAlmostEqual(scene['start_seconds'], cursor)
            cursor = round(cursor + scene['estimated_seconds'], 2)
            self.assertAlmostEqual(scene['end_seconds'], cursor)
        self.assertAlmostEqual(cursor, result['duration_check']['total_seconds'])

    def test_persistent_failure_preserves_candidate_without_success(self):
        result = self.execute(fail_always='estimate')
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['result']['scenes'])
        self.assertTrue(result['result']['source_ids'])
        self.assertIsNone(result['result']['duration_check'])
        self.assertEqual(len(result['result']['tool_errors']), 2)

    def test_step_limit_keeps_explicit_reason(self):
        result = self.execute(limit=4)
        self.assertEqual(result['status'], 'incomplete_step_limit')
        self.assertIn('上限', result['result']['unfinished_reason'])
        self.assertLessEqual(result['execution']['tool_calls'], 4)

    def test_brand_violation_blocks_even_approved_line(self):
        data = copy.deepcopy(DATA)
        data['materials'][0]['approved_lines'] = ['保证效率提升80%']
        core = Core(REQUEST, data)
        core.tool('search', {'query': '字幕'})
        core.tool('write', {'scenes': [{'source_id': 'P01', 'narration': '保证效率提升80%',
                                      'visual': '产品画面', 'hold_seconds': 0}]})
        check = core.tool('check', {})
        self.assertFalse(check['passed'])
        self.assertIn('brand_rule_violation', [r['reason'] for r in check['risks']])

    def test_excessive_silent_padding_rejected(self):
        core = Core(REQUEST, DATA)
        core.tool('search', {'query': '字幕'})
        core.tool('write', {'scenes': [{'source_id': 'P01', 'narration': '支持字幕',
                                      'visual': '产品画面', 'hold_seconds': 20}]})
        self.assertIn('excessive_hold', [r['reason'] for r in core.tool('check', {})['risks']])

    def test_missing_source_rejected(self):
        core = Core(REQUEST, DATA)
        core.tool('write', {'scenes': [{'source_id': 'fake', 'narration': '支持字幕',
                                      'visual': '产品画面', 'hold_seconds': 0}]})
        self.assertFalse(core.tool('check', {})['passed'])

    def test_estimate_uses_configured_speech_rate(self):
        data = copy.deepcopy(DATA)
        data['chars_per_second'] = 2
        result = self.execute(data=data)
        self.assertEqual(result['result']['duration_check']['chars_per_second'], 1.75)
        self.assertLessEqual(result['result']['duration_check']['total_seconds'], 30)

    def test_tool_trace_is_frozen_after_rewrite(self):
        result = self.execute()
        writes = [t for t in result['trace'] if t['action'] == 'write']
        self.assertEqual(writes[0]['args']['scenes'][0]['hold_seconds'], 8)
        self.assertNotEqual(writes[1]['args']['scenes'][0]['hold_seconds'], 8)

    def test_remote_adapter_request_and_response_contract(self):
        body = {'id': 'test-response', 'model': 'deepseek-flash', 'usage': {'total_tokens': 42},
                'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
                    {'function': {'name': 'search', 'arguments':
                     '{"query":"字幕","reason":"先查资料"}'}}]}}]}
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-placeholder', 'MODEL_NAME': 'deepseek-flash',
                                     'MODEL_BASE_URL': 'https://api.deepseek.com'}, clear=True):
            model = RemoteModel(INSTRUCTION)
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())) as transport:
                action = model.choose(REQUEST, [])
            sent = json.loads(transport.call_args.args[0].data)
        self.assertEqual(action['action'], 'search')
        self.assertEqual(sent['thinking'], {'type': 'disabled'})
        self.assertEqual(sent['tool_choice'], 'required')
        self.assertEqual({t['function']['name'] for t in sent['tools']}, {'search', 'write', 'estimate', 'check', 'finish'})
        self.assertEqual(model.calls[0]['usage']['total_tokens'], 42)

    def test_model_failure_retains_partial_results(self):
        class FailingModel:
            mode = 'scripted_test'

            def choose(self, request, trace):
                if len(trace) == 2:
                    raise TimeoutError('test timeout')
                return MockModel().choose(request, trace)
        result = run(Core(REQUEST, DATA), FailingModel())
        self.assertEqual(result['status'], 'model_error')
        self.assertTrue(result['result']['scenes'])
        self.assertEqual(result['trace'][-1]['action'], 'model_error')
        self.assertIn('模型', result['result']['unfinished_reason'])

    def test_provider_final_marker_rejected_and_raw_preserved(self):
        raw = '{"reason":"检查通过"}</final>'
        body = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
            {'function': {'name': 'finish', 'arguments': raw}}]}}]}
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-placeholder'}, clear=True):
            model = RemoteModel(INSTRUCTION)
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(json.JSONDecodeError):
                    model.choose(REQUEST, [])
        self.assertEqual(model.calls[-1]['action_content'][0]['arguments'], raw)

    def test_arbitrary_trailing_content_not_silently_accepted(self):
        raw = '{"reason":"检查通过"} extra text'
        body = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
            {'function': {'name': 'finish', 'arguments': raw}}]}}]}
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-placeholder'}, clear=True):
            model = RemoteModel(INSTRUCTION)
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(json.JSONDecodeError):
                    model.choose(REQUEST, [])

    def test_parallel_calls_are_logged_but_only_first_is_selected(self):
        body = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
            {'function': {'name': name, 'arguments': '{"reason":"检查当前稿"}'}}
            for name in ('estimate', 'check')]}}]}
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-placeholder'}, clear=True):
            model = RemoteModel(INSTRUCTION)
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())):
                action = model.choose(REQUEST, [])
        self.assertEqual(action['action'], 'estimate')
        self.assertEqual(action['unexecuted_calls'], ['check'])
        self.assertEqual(model.calls[-1]['unexecuted_call_count'], 1)

    def test_env_loader_does_not_override_shell_or_evaluate_values(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / 'test.env'
            path.write_text('MODEL_NAME=from-file\nMODEL_API_KEY="literal-test-placeholder"\n',encoding='utf-8')
            with patch.dict(os.environ, {'MODEL_NAME': 'from-shell'}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ['MODEL_NAME'], 'from-shell')
                self.assertEqual(os.environ['MODEL_API_KEY'], 'literal-test-placeholder')

    def test_markdown_export_keeps_failure_status(self):
        output = self.execute(fail_always='estimate')
        markdown = storyboard_markdown(output)
        self.assertIn('incomplete', markdown)
        self.assertIn('未完成原因', markdown)
        self.assertIn('P01', markdown)

    def test_model_cannot_skip_current_checks(self):
        class SkipChecks:
            mode = 'scripted_test'
            def choose(self, request, trace):
                if len(trace) < 2:
                    return MockModel().choose(request, trace)
                return {'action': 'finish', 'args': {}, 'reason': '试图跳过检查'}
        result = run(Core(REQUEST, DATA), SkipChecks())
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['result']['rule_check'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
