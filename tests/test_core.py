# -*- coding: utf-8 -*-
"""核心逻辑单元测试：AI 分类器和群聊纯函数。"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ai_classifier import AIClassifier, parse_ai_response


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_args = ()
        self.last_kwargs = {}

    def post(self, *args, **kwargs):
        self.call_count += 1
        self.last_args = args
        self.last_kwargs = kwargs
        return self.response


class AIResponseTest(unittest.TestCase):
    def test_parses_plain_json(self):
        result = parse_ai_response('{"is_spam": true, "reason": "推广USDT"}')
        self.assertTrue(result['is_spam'])
        self.assertEqual(result['reason'], '推广USDT')

    def test_parses_markdown_code_block(self):
        content = '```json\n{"is_spam": false, "reason": "正常聊天"}\n```'
        result = parse_ai_response(content)
        self.assertFalse(result['is_spam'])
        self.assertEqual(result['reason'], '正常聊天')

    def test_parses_embedded_json(self):
        content = 'result: {"is_spam": true, "reason": "广告"}'
        result = parse_ai_response(content)
        self.assertTrue(result['is_spam'])

    def test_accepts_yes_as_true(self):
        result = parse_ai_response('{"is_spam": "yes", "reason": "广告"}')
        self.assertTrue(result['is_spam'])

    def test_rejects_invalid_output(self):
        self.assertIsNone(parse_ai_response('not json at all'))
        self.assertIsNone(parse_ai_response('{"is_spam": 123}'))
        self.assertIsNone(parse_ai_response(''))


class AIClassifierTest(unittest.TestCase):
    def setUp(self):
        self.classifier = AIClassifier(
            base_url='https://example.com/v1',
            api_key='test-key',
            model='test-model',
            timeout=1,
            cache_ttl=300,
        )

    def test_classify_returns_spam_result(self):
        payload = {'choices': [{'message': {'content': '{"is_spam": true, "reason": "广告"}'}}]}
        session = FakeSession(FakeResponse(200, payload))
        self.classifier.session = session
        result = self.classifier.classify('低价出USDT，加微信')
        self.assertTrue(result['is_spam'])
        self.assertEqual(result['source'], 'ai')
        self.assertFalse(result['cached'])
        self.assertEqual(session.call_count, 1)

    def test_classify_uses_cache(self):
        payload = {'choices': [{'message': {'content': '{"is_spam": false, "reason": "正常"}'}}]}
        with mock.patch.object(__import__('ai_classifier').requests, 'post', return_value=FakeResponse(200, payload)) as fake_post:
            first = self.classifier.classify('今天天气不错')
            second = self.classifier.classify('今天天气不错')
            self.assertFalse(first['is_spam'])
            self.assertTrue(second['cached'])
            fake_post.assert_called_once()

    def test_classify_falls_back_on_http_error(self):
        with mock.patch.object(__import__('ai_classifier').requests, 'post', return_value=FakeResponse(500, text='boom')):
            self.assertIsNone(self.classifier.classify('测试内容'))

    def test_classify_falls_back_on_request_exception(self):
        with mock.patch.object(__import__('ai_classifier').requests, 'post', side_effect=RuntimeError('network down')):
            self.assertIsNone(self.classifier.classify('测试内容'))

    def test_classify_disabled_without_api_key(self):
        disabled = AIClassifier(api_key='', model='test-model')
        self.assertFalse(disabled.enabled)
        self.assertIsNone(disabled.classify('测试内容'))

    def test_classify_disabled_when_env_flag_false(self):
        disabled = AIClassifier(
            base_url='https://example.com/v1',
            api_key='test-key',
            model='test-model',
            require_env_flag=False,
        )
        self.assertFalse(disabled.enabled)
        self.assertIsNone(disabled.classify('测试内容'))


class AIProviderRequestTest(unittest.TestCase):
    def _classifier(self, provider, base_url='https://api.example.com',
                    model='model-x', max_tokens=512):
        return AIClassifier(
            base_url=base_url,
            api_key='test-key',
            model=model,
            timeout=1,
            cache_ttl=300,
            provider=provider,
            max_tokens=max_tokens,
        )

    def test_openai_compatible_request_shape(self):
        payload = {'choices': [{'message': {'content': '{"is_spam": false, "reason": "正常"}'}}]}
        session = FakeSession(FakeResponse(200, payload))
        classifier = self._classifier('openai-compatible',
                                      base_url='https://api.deepseek.com/v1')
        classifier.session = session
        result = classifier.classify('你好')
        self.assertFalse(result['is_spam'])
        self.assertTrue(session.last_args[0].endswith('/chat/completions'))
        self.assertEqual(session.last_kwargs['headers']['Authorization'], 'Bearer test-key')
        request = session.last_kwargs['json']
        self.assertEqual(request['model'], 'model-x')
        self.assertEqual(request['max_tokens'], 512)
        self.assertEqual(request['messages'][0]['role'], 'system')
        self.assertEqual(request['messages'][1]['role'], 'user')

    def test_anthropic_request_shape_and_parse(self):
        payload = {'content': [{'type': 'text', 'text': '{"is_spam": true, "reason": "广告"}'}]}
        session = FakeSession(FakeResponse(200, payload))
        classifier = self._classifier('anthropic',
                                      base_url='https://api.anthropic.com',
                                      model='claude-3-5-sonnet-latest')
        classifier.session = session
        result = classifier.classify('低价出U')
        self.assertTrue(result['is_spam'])
        self.assertTrue(session.last_args[0].endswith('/v1/messages'))
        headers = session.last_kwargs['headers']
        self.assertEqual(headers['x-api-key'], 'test-key')
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        request = session.last_kwargs['json']
        self.assertEqual(request['model'], 'claude-3-5-sonnet-latest')
        self.assertIn('你是 Telegram 反垃圾审核助手', request['system'])
        self.assertEqual(request['messages'], [{'role': 'user', 'content': request['messages'][0]['content']}])
        self.assertEqual(request['max_tokens'], 512)

    def test_anthropic_v1_base_url_does_not_duplicate_version(self):
        classifier = self._classifier('anthropic', base_url='https://api.anthropic.com/v1')
        self.assertEqual(classifier._request_url(),
                         'https://api.anthropic.com/v1/messages')

    def test_gemini_request_shape_and_parse(self):
        payload = {'candidates': [{'content': {'parts': [
            {'text': '{"is_spam": false, "reason": "正常"}'}
        ]}}]}
        session = FakeSession(FakeResponse(200, payload))
        classifier = self._classifier('gemini',
                                      base_url='https://generativelanguage.googleapis.com',
                                      model='gemini-2.0-flash')
        classifier.session = session
        result = classifier.classify('今天天气不错', keywords=['广告', 'USDT'])
        self.assertFalse(result['is_spam'])
        self.assertTrue(session.last_args[0].endswith(
            '/v1beta/models/gemini-2.0-flash:generateContent'))
        self.assertEqual(session.last_kwargs['headers']['x-goog-api-key'], 'test-key')
        request = session.last_kwargs['json']
        self.assertEqual(request['contents'][0]['role'], 'user')
        self.assertIn('本地广告规则关键词', request['contents'][0]['parts'][0]['text'])
        self.assertEqual(request['generationConfig']['maxOutputTokens'], 512)

    def test_gemini_v1beta_base_url_keeps_existing_version(self):
        classifier = self._classifier('gemini',
                                      base_url='https://generativelanguage.googleapis.com/v1beta')
        self.assertEqual(classifier._request_url(),
                         'https://generativelanguage.googleapis.com/v1beta/models/model-x:generateContent')

    def test_unknown_provider_disables_classifier(self):
        classifier = AIClassifier(
            base_url='https://api.example.com',
            api_key='test-key',
            model='model-x',
            provider='unknown',
        )
        self.assertFalse(classifier.enabled)
        self.assertIsNone(classifier.classify('测试内容'))

    def test_max_keywords_caps_prompt(self):
        payload = {'choices': [{'message': {'content': '{"is_spam": false, "reason": "正常"}'}}]}
        session = FakeSession(FakeResponse(200, payload))
        classifier = AIClassifier(
            base_url='https://api.example.com/v1',
            api_key='test-key',
            model='model-x',
            timeout=1,
            cache_ttl=300,
            max_keywords=2,
        )
        classifier.session = session
        result = classifier.classify('测试', keywords=['a', 'b', 'c'])
        self.assertFalse(result['is_spam'])
        prompt = session.last_kwargs['json']['messages'][0]['content']
        self.assertIn('a', prompt)
        self.assertIn('b', prompt)
        self.assertNotIn('c', prompt)


class StubTeleBot:
    def __init__(self, token):
        self.token = token

    def message_handler(self, *args, **kwargs):
        return lambda func: func

    def callback_query_handler(self, *args, **kwargs):
        return lambda func: func

    def edited_message_handler(self, *args, **kwargs):
        return lambda func: func

    def chat_join_request_handler(self, *args, **kwargs):
        return lambda func: func

    def get_chat_administrators(self, chat_id):
        return []

    def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status='member')

    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        return SimpleNamespace(message_id=1)

    def edit_message_text(self, text, chat_id, message_id, parse_mode=None, reply_markup=None):
        return True

    def answer_callback_query(self, callback_query_id, text=None):
        return True

    def approve_chat_join_request(self, chat_id, user_id):
        return True

    def decline_chat_join_request(self, chat_id, user_id):
        return True

    def ban_chat_member(self, chat_id, user_id, until_date=None):
        return True

    def unban_chat_member(self, chat_id, user_id):
        return True

    def reply_to(self, message, text, parse_mode=None, reply_markup=None):
        return SimpleNamespace(message_id=1)


def _load_new_module():
    os.environ['BOT_TOKEN'] = '123456:TEST'
    os.environ['ADMIN_ID'] = '111'

    telebot_stub = types.ModuleType('telebot')
    telebot_stub.TeleBot = StubTeleBot

    apihelper_stub = types.ModuleType('telebot.apihelper')
    apihelper_stub.ApiTelegramException = type('ApiTelegramException', (Exception,), {})

    types_stub = types.ModuleType('telebot.types')
    for name in [
        'BotCommand',
        'BotCommandScopeChat',
        'BotCommandScopeDefault',
        'InlineKeyboardButton',
        'InlineKeyboardMarkup',
        'KeyboardButton',
        'MenuButtonCommands',
        'ReplyKeyboardMarkup',
    ]:
        setattr(types_stub, name, type(name, (), {}))

    sys.modules['telebot'] = telebot_stub
    sys.modules['telebot.apihelper'] = apihelper_stub
    sys.modules['telebot.types'] = types_stub

    spec = importlib.util.spec_from_file_location('bot_core_under_test', os.path.join(PROJECT_ROOT, 'new.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NEW_MODULE = _load_new_module()


class GroupLogicTest(unittest.TestCase):
    def test_parse_id_list_ignores_invalid_parts(self):
        self.assertEqual(NEW_MODULE.parse_id_list('1, 2,abc,-3, 444'), {1, 2, -3, 444})
        self.assertEqual(NEW_MODULE.parse_id_list(''), set())

    def test_group_enabled_for_scoped_ids(self):
        module = NEW_MODULE
        module.GROUP_ENABLED = True
        module.GROUP_IDS = {-100123, -100456}
        self.assertTrue(module.group_enabled_for(-100123))
        self.assertFalse(module.group_enabled_for(999))
        self.assertFalse(module.group_enabled_for(None))

    def test_group_enabled_for_all_when_ids_empty(self):
        module = NEW_MODULE
        module.GROUP_ENABLED = True
        module.GROUP_IDS = set()
        self.assertTrue(module.group_enabled_for(999))
        module.GROUP_ENABLED = False
        self.assertFalse(module.group_enabled_for(999))

    def test_is_group_admin(self):
        module = NEW_MODULE
        module.GROUP_ADMIN_IDS = {111, 222}
        self.assertTrue(module.is_group_admin(111))
        self.assertFalse(module.is_group_admin(333))
        self.assertFalse(module.is_group_admin(None))

    def test_select_ai_keywords_only_returns_hits(self):
        module = NEW_MODULE
        module._current_spam_keywords = {'办证', 'usdt', '刷单', '博彩', '贷款'}
        # 命中 usdt 与 博彩，只返回命中的词，不凑数
        hits = module.select_ai_keywords('低价出USDT，博彩包赢', 200)
        self.assertEqual(set(hits), {'usdt', '博彩'})
        # 完全不命中时返回空，不塞无关词
        self.assertEqual(module.select_ai_keywords('今天天气不错出去走走', 200), [])
        # 命中数超过 limit 时截断
        self.assertEqual(len(module.select_ai_keywords('低价出USDT，博彩包赢', 1)), 1)
        # limit<=0 直接返回空
        self.assertEqual(module.select_ai_keywords('usdt', 0), [])

    def test_can_manage_group_static_admin(self):
        module = NEW_MODULE
        module.GROUP_ADMIN_IDS = {111}
        module._group_admin_cache.clear()
        with mock.patch.object(module.bot, 'get_chat_administrators') as get_admins:
            self.assertTrue(module.can_manage_group(111, -100123))
            get_admins.assert_not_called()

    def test_can_manage_group_native_admin(self):
        module = NEW_MODULE
        module.GROUP_ADMIN_IDS = {111}
        module._group_admin_cache.clear()
        admins = [
            SimpleNamespace(status='creator', user=SimpleNamespace(id=222)),
            SimpleNamespace(status='administrator', user=SimpleNamespace(id=333)),
            SimpleNamespace(status='member', user=SimpleNamespace(id=444)),
        ]
        with mock.patch.object(module.bot, 'get_chat_administrators', return_value=admins):
            self.assertTrue(module.can_manage_group(222, -100123))
            self.assertTrue(module.can_manage_group(333, -100123))
            self.assertFalse(module.can_manage_group(444, -100123))
            self.assertFalse(module.can_manage_group(555, -100123))

    def test_can_manage_group_fallback_on_api_error(self):
        module = NEW_MODULE
        module.GROUP_ADMIN_IDS = {111}
        module._group_admin_cache.clear()
        with mock.patch.object(module.bot, 'get_chat_administrators', side_effect=RuntimeError('network')):
            self.assertTrue(module.can_manage_group(111, -100123))
            self.assertFalse(module.can_manage_group(222, -100123))

    def test_reject_spam_join_declines_bans_and_keeps_appeal_channel(self):
        module = NEW_MODULE
        with mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module, 'get_user_lang', return_value='en') as get_lang:
            module.reject_spam_join(-100123, 999)
        called_names = [c.args[0].__name__ for c in safe.call_args_list]
        self.assertEqual(called_names[0], 'decline_chat_join_request')
        self.assertIn('ban_chat_member', called_names)
        self.assertIn('send_message', called_names)
        self.assertIn('message the bot directly', safe.call_args_list[-1].args[2])
        get_lang.assert_called_once_with(999)

    def test_record_remove_group_join_pending(self):
        module = NEW_MODULE
        module.group_join_pending.clear()
        module.record_group_join_pending(-100123, 999, True, 5)
        self.assertIn((-100123, 999), module.group_join_pending)
        self.assertEqual(module.group_join_pending[(-100123, 999)]['notice_message_id'], 5)
        module.remove_group_join_pending(-100123, 999)
        self.assertNotIn((-100123, 999), module.group_join_pending)

    def test_resolve_group_join_pending_uses_rule(self):
        module = NEW_MODULE
        with mock.patch.object(module, 'reject_spam_join') as reject:
            module.resolve_group_join_pending(-100123, 999, True, None)
        reject.assert_called_once_with(-100123, 999)
        with mock.patch.object(module, 'safe_send') as safe:
            module.resolve_group_join_pending(-100123, 999, False, None)
        self.assertEqual(safe.call_args.args[0].__name__, 'approve_chat_join_request')

    def test_user_follows_required_channel_disabled(self):
        module = NEW_MODULE
        module.GROUP_JOIN_REQUIRED_CHANNEL = ''
        self.assertTrue(module.user_follows_required_channel(999))

    def test_user_follows_required_channel_member(self):
        module = NEW_MODULE
        module.GROUP_JOIN_REQUIRED_CHANNEL = 'my_channel'
        module._channel_member_cache.clear()
        with mock.patch.object(module.bot, 'get_chat_member', return_value=SimpleNamespace(status='member')):
            self.assertTrue(module.user_follows_required_channel(999))

    def test_user_follows_required_channel_left(self):
        module = NEW_MODULE
        module.GROUP_JOIN_REQUIRED_CHANNEL = 'my_channel'
        module._channel_member_cache.clear()
        with mock.patch.object(module.bot, 'get_chat_member', side_effect=RuntimeError('not found')):
            self.assertFalse(module.user_follows_required_channel(999))

    def test_handle_chat_join_request_requires_channel_first(self):
        module = NEW_MODULE
        module.GROUP_ENABLED = True
        module.GROUP_JOIN_APPROVE = True
        module.GROUP_IDS = set()
        module.GROUP_JOIN_REQUIRED_CHANNEL = 'my_channel'
        req = SimpleNamespace(
            chat=SimpleNamespace(id=-100123),
            from_user=SimpleNamespace(id=999),
        )
        with mock.patch.object(module, 'user_follows_required_channel', return_value=False), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module, 'judge_join_request_spam') as judge:
            module.handle_chat_join_request(req)
        called = [c.args[0].__name__ for c in safe.call_args_list]
        self.assertIn('decline_chat_join_request', called)
        self.assertNotIn('approve_chat_join_request', called)
        judge.assert_not_called()
        module.GROUP_JOIN_REQUIRED_CHANNEL = ''

    def test_get_user_profile_text(self):
        user = SimpleNamespace(first_name='张三', last_name='', username='zhangsan')
        self.assertEqual(NEW_MODULE.get_user_profile_text(user), '张三  zhangsan')
        self.assertEqual(NEW_MODULE.get_user_profile_text(None), '')

    def test_load_remote_rule_text_combines_github_and_r2(self):
        module = NEW_MODULE
        with mock.patch.object(module, 'safe_requests_get', return_value='github.example.com\n'), \
                mock.patch.object(module, 'fetch_r2_rules', return_value='r2.example.com\n'):
            combined, words = module.load_remote_rule_text()
        self.assertIn('github.example.com', combined)
        self.assertIn('r2.example.com', combined)
        self.assertEqual(words, {'github.example.com', 'r2.example.com'})


class GroupAndPrivateRulesTest(unittest.TestCase):
    def _private_message(self, user_id=222, text='hello', content_type='text'):
        return SimpleNamespace(
            chat=SimpleNamespace(id=user_id, type='private'),
            from_user=SimpleNamespace(
                id=user_id,
                first_name='User',
                last_name='',
                username='user',
                is_bot=False,
            ),
            text=text,
            caption=None,
            content_type=content_type,
            message_id=1,
            media_group_id=None,
        )

    def _group_message(self, user_id=222, text='低价出U', content_type='text'):
        return SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type='supergroup'),
            from_user=SimpleNamespace(
                id=user_id,
                first_name='User',
                last_name='',
                username='user',
                is_bot=False,
            ),
            text=text,
            caption=None,
            content_type=content_type,
            message_id=7,
        )

    def test_whitelisted_temp_banned_private_message_ignored(self):
        module = NEW_MODULE
        message = self._private_message()
        with mock.patch.object(module, 'check_global_limit', return_value=True), \
                mock.patch.object(module, 'db_touch_user'), \
                mock.patch.object(module, 'get_cached_user_status', return_value={
                    'wl': True,
                    'bl': False,
                    'ban_until': time.time() + 3600,
                    'verified': 1,
                    'lang': 'zh',
                }), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module, 'admin_sender') as sender:
            module.handle_incoming(message)
        sender.send.assert_not_called()
        safe.assert_not_called()

    def test_private_spam_analysis_runs_once(self):
        module = NEW_MODULE
        message = self._private_message(text='推广广告')
        analysis = (True, 9, 'ads', '关键词命中')
        with mock.patch.object(module, 'check_global_limit', return_value=True), \
                mock.patch.object(module, 'db_touch_user'), \
                mock.patch.object(module, 'get_cached_user_status', return_value={
                    'wl': False,
                    'bl': False,
                    'ban_until': 0,
                    'verified': 1,
                    'lang': 'zh',
                }), \
                mock.patch.object(module, 'check_flood', return_value=False), \
                mock.patch.object(module, 'analyze_spam_message', return_value=analysis) as analyze, \
                mock.patch.object(module, 'explain_spam_text') as explain, \
                mock.patch.object(module, 'block_spam_message') as block, \
                mock.patch.object(module, 'admin_sender') as sender:
            module.handle_incoming(message)
        analyze.assert_called_once_with(message)
        explain.assert_not_called()
        block.assert_called_once_with(message, 222, analysis=analysis)
        sender.send.assert_not_called()

    def test_group_message_analysis_runs_once(self):
        module = NEW_MODULE
        original = {
            'enabled': module.GROUP_ENABLED,
            'ids': module.GROUP_IDS,
            'admins': module.GROUP_ADMIN_IDS,
            'delete': module.GROUP_DELETE_SPAM,
            'ban': module.GROUP_BAN_ON_SPAM,
            'duration': module.MAX_BAN_DURATION,
        }
        module.GROUP_ENABLED = True
        module.GROUP_IDS = set()
        module.GROUP_ADMIN_IDS = {111}
        module.GROUP_DELETE_SPAM = True
        module.GROUP_BAN_ON_SPAM = True
        module.MAX_BAN_DURATION = 10800
        message = self._group_message()
        analysis = (True, 8, 'ads', '关键词命中')
        try:
            with mock.patch.object(module, 'can_manage_group', return_value=False), \
                    mock.patch.object(module, 'get_cached_user_status', return_value={'bl': False}), \
                mock.patch.object(module, 'analyze_spam_message', return_value=analysis) as analyze, \
                mock.patch.object(module, 'explain_spam_text') as explain, \
                mock.patch.object(module, 'db_add_group_ban'), \
                mock.patch.object(module, 'safe_delete') as safe_delete, \
                mock.patch.object(module.bot, 'ban_chat_member') as ban, \
                    mock.patch.object(module, 'notify_group_spam') as notify:
                module.handle_group_message(message)
            analyze.assert_called_once_with(message)
            explain.assert_not_called()
            safe_delete.assert_called_once_with(-100123, 7)
            ban.assert_called_once()
            self.assertNotIn('until_date', ban.call_args.kwargs)
            notify.assert_called_once_with(-100123, message, 222, '关键词命中', 8, ['删除消息', '永久封禁'])
        finally:
            module.GROUP_ENABLED = original['enabled']
            module.GROUP_IDS = original['ids']
            module.GROUP_ADMIN_IDS = original['admins']
            module.GROUP_DELETE_SPAM = original['delete']
            module.GROUP_BAN_ON_SPAM = original['ban']
            module.MAX_BAN_DURATION = original['duration']

    def test_group_edited_spam_deletes_bans_and_notifies(self):
        module = NEW_MODULE
        original = {
            'delete': module.GROUP_DELETE_SPAM,
            'ban': module.GROUP_BAN_ON_SPAM,
            'duration': module.MAX_BAN_DURATION,
        }
        module.GROUP_DELETE_SPAM = True
        module.GROUP_BAN_ON_SPAM = True
        module.MAX_BAN_DURATION = 10800
        message = self._group_message(text='编辑成广告')
        analysis = (True, 7, 'ads', '内容风险分 7 >= 6')
        try:
            with mock.patch.object(module, 'can_manage_group', return_value=False), \
                mock.patch.object(module, 'get_cached_user_status', return_value={'bl': False}), \
                mock.patch.object(module, 'analyze_spam_message', return_value=analysis), \
                mock.patch.object(module, 'db_add_group_ban'), \
                mock.patch.object(module, 'safe_delete') as safe_delete, \
                mock.patch.object(module.bot, 'ban_chat_member') as ban, \
                    mock.patch.object(module, 'notify_group_spam') as notify:
                module.handle_group_edited_message(message)
            safe_delete.assert_called_once_with(-100123, 7)
            ban.assert_called_once()
            notify.assert_called_once_with(-100123, message, 222, '内容风险分 7 >= 6', 7, ['删除消息', '永久封禁'])
        finally:
            module.GROUP_DELETE_SPAM = original['delete']
            module.GROUP_BAN_ON_SPAM = original['ban']
            module.MAX_BAN_DURATION = original['duration']

    def test_group_edited_normal_message_left_alone(self):
        module = NEW_MODULE
        message = self._group_message(text='正常聊天')
        with mock.patch.object(module, 'can_manage_group', return_value=False), \
                mock.patch.object(module, 'get_cached_user_status', return_value={'bl': False}), \
                mock.patch.object(module, 'analyze_spam_message', return_value=(False, 2, 'normal', '未命中')), \
                mock.patch.object(module, 'safe_delete') as safe_delete, \
                mock.patch.object(module.bot, 'ban_chat_member') as ban, \
                mock.patch.object(module, 'notify_group_spam') as notify:
            module.handle_group_edited_message(message)
        safe_delete.assert_not_called()
        ban.assert_not_called()
        notify.assert_not_called()

    def test_group_help_replies_without_private_menu_flow(self):
        module = NEW_MODULE
        message = self._group_message(text='/help')
        with mock.patch.object(module, 'db_touch_user') as touch, \
                mock.patch.object(module, 'get_user_lang', return_value='zh') as get_lang, \
                mock.patch.object(module, 'safe_reply_to') as reply:
            module.send_welcome_handler(message)
        touch.assert_not_called()
        get_lang.assert_called_once_with(222)
        self.assertIn('群内指令', reply.call_args.args[1])

    def test_group_start_is_ignored(self):
        module = NEW_MODULE
        message = self._group_message(text='/start')
        with mock.patch.object(module, 'safe_reply_to') as reply:
            module.send_welcome_handler(message)
        reply.assert_not_called()

    def test_group_status_and_reload_require_group_admin(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/status')
        with mock.patch.object(module, 'can_manage_group', return_value=False) as manage, \
                mock.patch.object(module, 'send_admin_status') as status:
            module.handle_status_command(message)
        manage.assert_called_once_with(333, -100123)
        status.assert_not_called()

        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'send_admin_status') as status:
            module.handle_status_command(message)
        status.assert_called_once_with(message)

    def test_group_reloadrules_requires_group_admin(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/reloadrules')
        with mock.patch.object(module, 'can_manage_group', return_value=False) as manage, \
                mock.patch.object(module, 'send_admin_reload_rules') as reload_rules:
            module.handle_reload_rules_command(message)
        manage.assert_called_once_with(333, -100123)
        reload_rules.assert_not_called()

    def test_private_status_still_requires_main_admin(self):
        module = NEW_MODULE
        message = self._private_message(user_id=333, text='/status')
        with mock.patch.object(module, 'send_admin_status') as status:
            module.handle_status_command(message)
        status.assert_not_called()

    def test_group_spamtest_is_open_to_normal_users(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/spamtest 低价出U')
        with mock.patch.object(module, 'can_manage_group', return_value=False), \
                mock.patch.object(module, 'get_user_lang', return_value='zh'), \
                mock.patch.object(module, 'explain_spam_text', return_value=(True, 8, 'ads', '命中规则')) as explain, \
                mock.patch.object(module, 'ai_cls', SimpleNamespace(enabled=False)) as ai, \
                mock.patch.object(module, 'safe_reply_to') as reply:
            module.handle_spamtest_command(message)
        explain.assert_called_once_with('低价出U')
        ai.enabled = False
        self.assertIn('会拦截', reply.call_args.args[1])

    def test_group_manual_ban_and_unban_are_scoped(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/ban 999')
        with mock.patch.object(module, 'can_manage_group', return_value=False) as manage, \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module, 'db_add_group_ban') as add_ban:
            module.handle_group_ban_command(message)
        manage.assert_called_once_with(333, -100123)
        safe.assert_not_called()
        add_ban.assert_not_called()

        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module.bot, 'ban_chat_member') as ban_chat_member, \
                mock.patch.object(module, 'safe_reply_to'), \
                mock.patch.object(module, 'db_add_group_ban') as add_ban:
            module.handle_group_ban_command(message)
        self.assertEqual(safe.call_args.args, (ban_chat_member, -100123, 999))
        add_ban.assert_called_once_with(-100123, 999)

        unban_message = self._group_message(user_id=333, text='/unban 999')
        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module.bot, 'unban_chat_member') as unban_chat_member, \
                mock.patch.object(module, 'safe_reply_to'), \
                mock.patch.object(module, 'db_remove_group_ban') as remove_ban:
            module.handle_group_unban_command(unban_message)
        self.assertEqual(safe.call_args.args, (unban_chat_member, -100123, 999))
        remove_ban.assert_called_once_with(-100123, 999)

    def test_group_manual_unban_removes_only_same_group_record(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/unban 999')
        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module.bot, 'unban_chat_member') as unban_chat_member, \
                mock.patch.object(module, 'safe_reply_to'), \
                mock.patch.object(module, 'db_remove_group_ban') as remove_ban:
            module.handle_group_unban_command(message)
        self.assertEqual(safe.call_args.args, (unban_chat_member, -100123, 999))
        remove_ban.assert_called_once_with(-100123, 999)

    def test_group_manual_unban_rejects_non_admin(self):
        module = NEW_MODULE
        message = self._group_message(user_id=333, text='/unban 999')
        with mock.patch.object(module, 'can_manage_group', return_value=False) as manage, \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module, 'db_remove_group_ban') as remove_ban:
            module.handle_group_unban_command(message)
        manage.assert_called_once_with(333, -100123)
        safe.assert_not_called()
        remove_ban.assert_not_called()

    def test_group_join_callback_skips_already_handled(self):
        module = NEW_MODULE
        module.group_join_pending.clear()
        call = SimpleNamespace(
            data='gj_approve:-100123:999',
            id='cb1',
            from_user=SimpleNamespace(id=222),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=5, reply_markup=None),
        )
        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'safe_send') as safe, \
                mock.patch.object(module.bot, 'approve_chat_join_request') as approve:
            module.handle_group_join_callback(call)
        approve.assert_not_called()
        called_names = [c.args[0].__name__ for c in safe.call_args_list]
        self.assertIn('answer_callback_query', called_names)

    def test_group_join_callback_manual_approve_still_works(self):
        module = NEW_MODULE
        module.group_join_pending.clear()
        module.record_group_join_pending(-100123, 999, False, 5)
        call = SimpleNamespace(
            data='gj_approve:-100123:999',
            id='cb2',
            from_user=SimpleNamespace(id=222),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=5, reply_markup=SimpleNamespace()),
        )
        with mock.patch.object(module, 'can_manage_group', return_value=True), \
                mock.patch.object(module, 'safe_send', wraps=module.safe_send) as safe, \
                mock.patch.object(module.bot, 'approve_chat_join_request') as approve:
            module.handle_group_join_callback(call)
        approve.assert_called_once_with(-100123, 999)
        self.assertNotIn((-100123, 999), module.group_join_pending)
        called_names = [getattr(c.args[0], '__name__', None) for c in safe.call_args_list]
        self.assertIn('edit_message_text', called_names)
        self.assertIn('answer_callback_query', called_names)

    def test_private_edited_message_ignored_when_temp_banned(self):
        module = NEW_MODULE
        message = self._private_message()
        with mock.patch.object(module, 'get_cached_user_status', return_value={
            'wl': True,
            'bl': False,
            'ban_until': time.time() + 3600,
            'verified': 1,
            'lang': 'zh',
        }), \
                mock.patch.object(module, 'safe_send') as safe:
            module.handle_edited_message(message)
        safe.assert_not_called()


class JoinRequestJudgementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        NEW_MODULE.load_fallback_spam_rules()

    def test_local_keyword_rejects_spam_profile(self):
        user = SimpleNamespace(first_name='USDT 高价收币', last_name='', username='spam_user')
        is_spam, reason = NEW_MODULE.judge_join_request_spam(user, NEW_MODULE.get_user_profile_text(user), '')
        self.assertTrue(is_spam)
        self.assertIn('本地广告规则', reason)

    def test_ai_rejects_normal_profile_when_ai_flags_it(self):
        class FakeAI:
            enabled = True

            def classify(self, text, keywords=(), profile_text=''):
                return {'is_spam': True, 'reason': '资料疑似广告号'}

        module = NEW_MODULE
        original_ai = module.ai_cls
        original_always = module.AI_ALWAYS_CHECK
        original_profile = module.AI_PROFILE_CHECK
        module.ai_cls = FakeAI()
        module.AI_ALWAYS_CHECK = True
        module.AI_PROFILE_CHECK = True
        try:
            user = SimpleNamespace(first_name='小明', last_name='', username='xiaoming')
            is_spam, reason = module.judge_join_request_spam(user, module.get_user_profile_text(user), '')
            self.assertTrue(is_spam)
            self.assertIn('AI判定', reason)
        finally:
            module.ai_cls = original_ai
            module.AI_ALWAYS_CHECK = original_always
            module.AI_PROFILE_CHECK = original_profile

    def test_keeps_normal_profile_when_ai_clears_it(self):
        class FakeAI:
            enabled = True

            def classify(self, text, keywords=(), profile_text=''):
                return {'is_spam': False, 'reason': '正常'}

        module = NEW_MODULE
        original_ai = module.ai_cls
        original_always = module.AI_ALWAYS_CHECK
        module.ai_cls = FakeAI()
        module.AI_ALWAYS_CHECK = True
        try:
            user = SimpleNamespace(first_name='小红', last_name='', username='xiaohong')
            is_spam, reason = module.judge_join_request_spam(user, module.get_user_profile_text(user), '')
            self.assertFalse(is_spam)
            self.assertIn('未发现广告特征', reason)
        finally:
            module.ai_cls = original_ai
            module.AI_ALWAYS_CHECK = original_always


class SpamFeedbackDBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(os.path.join(self.tmp.name, 'test.db'))
        self.conn.execute('''CREATE TABLE spam_feedback (
            content_hash TEXT PRIMARY KEY,
            features TEXT NOT NULL,
            source TEXT NOT NULL,
            confirmed INTEGER NOT NULL DEFAULT 0,
            synced INTEGER NOT NULL DEFAULT 0,
            created_at DOUBLE PRECISION NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            first_seen DOUBLE PRECISION DEFAULT NULL,
            last_seen DOUBLE PRECISION DEFAULT NULL,
            blocked INTEGER NOT NULL DEFAULT 0,
            auto_learned INTEGER NOT NULL DEFAULT 0
        )''')
        self.conn.commit()
        self.original_get_db = NEW_MODULE.get_db_conn
        self.original_learn_enabled = NEW_MODULE.RULE_LEARN_ENABLED
        self.original_auto_learn_enabled = NEW_MODULE.RULE_AUTO_LEARN_ENABLED
        self.original_auto_learn_threshold = NEW_MODULE.RULE_AUTO_LEARN_THRESHOLD
        NEW_MODULE.RULE_LEARN_ENABLED = True
        NEW_MODULE.RULE_AUTO_LEARN_ENABLED = True
        NEW_MODULE.RULE_AUTO_LEARN_THRESHOLD = 3
        NEW_MODULE.get_db_conn = lambda: self.conn

    def tearDown(self):
        NEW_MODULE.get_db_conn = self.original_get_db
        NEW_MODULE.RULE_LEARN_ENABLED = self.original_learn_enabled
        NEW_MODULE.RULE_AUTO_LEARN_ENABLED = self.original_auto_learn_enabled
        NEW_MODULE.RULE_AUTO_LEARN_THRESHOLD = self.original_auto_learn_threshold
        self.conn.close()
        self.tmp.cleanup()

    def test_feedback_learn_and_sync_flow(self):
        content = '低价出USDT，加微信 wxid8888，https://spam.example.com/buy'
        content_hash = NEW_MODULE.db_save_spam_feedback(content, 'block')
        self.assertTrue(content_hash)
        features = NEW_MODULE.db_feedback_features(content_hash)
        self.assertIn('spam.example.com', features)
        self.assertIn('wxid8888', features)

        NEW_MODULE.db_set_feedback_confirmed(content_hash, True)
        self.assertEqual(set(NEW_MODULE.db_list_learned_features()), set(features))

        hashes, unsynced = NEW_MODULE.db_list_unsynced_features()
        self.assertEqual(hashes, [content_hash])
        self.assertEqual(set(unsynced), set(features))

        NEW_MODULE.db_mark_feedback_synced(hashes)
        self.assertEqual(NEW_MODULE.db_list_unsynced_features(), ([], []))

    def test_feedback_ignore_blocks_sample_without_learning(self):
        content = '扫码进群 https://bad.example.com/join'
        content_hash = NEW_MODULE.db_save_spam_feedback(content, 'group')
        self.assertTrue(content_hash)
        features = NEW_MODULE.db_feedback_features(content_hash)
        NEW_MODULE.db_set_feedback_confirmed(content_hash, False)
        self.assertEqual(NEW_MODULE.db_list_learned_features(), [])
        self.assertEqual(set(NEW_MODULE.db_feedback_features(content_hash)), set(features))
        self.assertEqual(NEW_MODULE.db_list_unsynced_features(), ([], []))

    def test_feedback_auto_learns_after_repeated_hits(self):
        content = '加群 https://auto.example.com/invite'
        with mock.patch.object(NEW_MODULE, 'refresh_learned_rules'):
            content_hash = NEW_MODULE.db_save_spam_feedback(content, 'block')
            for _ in range(NEW_MODULE.RULE_AUTO_LEARN_THRESHOLD - 1):
                NEW_MODULE.db_save_spam_feedback(content, 'block')
        row = self.conn.execute(
            "SELECT confirmed, auto_learned, hit_count FROM spam_feedback WHERE content_hash=?",
            (content_hash,),
        ).fetchone()
        self.assertEqual(row, (1, 1, 3))
        features = NEW_MODULE.db_feedback_features(content_hash)
        self.assertEqual(set(NEW_MODULE.db_list_learned_features()), set(features))

    def test_cleanup_expires_pending_and_blocked_samples(self):
        old_pending = time.time() - 40 * 86400
        old_blocked = time.time() - 10 * 86400
        self.conn.execute(
            "INSERT INTO spam_feedback (content_hash, features, source, confirmed, synced, created_at, hit_count, first_seen, last_seen, blocked, auto_learned) "
            "VALUES (?, ?, ?, 0, 0, ?, 1, ?, ?, 0, 0)",
            ('pending-old', '["old-pending.example.com"]', 'block', old_pending, old_pending, old_pending),
        )
        self.conn.execute(
            "INSERT INTO spam_feedback (content_hash, features, source, confirmed, synced, created_at, hit_count, first_seen, last_seen, blocked, auto_learned) "
            "VALUES (?, ?, ?, 0, 0, ?, 1, ?, ?, 1, 0)",
            ('blocked-old', '["old-blocked.example.com"]', 'block', old_blocked, old_blocked, old_blocked),
        )
        self.conn.commit()
        NEW_MODULE.db_cleanup_spam_feedback()
        remaining = {
            row[0]
            for row in self.conn.execute(
                "SELECT content_hash FROM spam_feedback WHERE content_hash IN (?, ?)",
                ('pending-old', 'blocked-old'),
            ).fetchall()
        }
        self.assertEqual(remaining, set())

    def test_cleanup_caps_feedback_rows(self):
        for index in range(3):
            self.conn.execute(
                "INSERT INTO spam_feedback (content_hash, features, source, confirmed, synced, created_at, hit_count, first_seen, last_seen, blocked, auto_learned) "
                "VALUES (?, ?, ?, 0, 0, ?, 1, ?, ?, 0, 0)",
                (
                    f'cap-{index}',
                    json.dumps([f'cap-{index}.example.com'], ensure_ascii=False),
                    'block',
                    time.time(),
                    time.time(),
                    time.time(),
                ),
            )
        self.conn.commit()
        with mock.patch.object(NEW_MODULE, 'RULE_AUTO_LEARN_MAX_RULES', 2):
            NEW_MODULE.db_cleanup_spam_feedback()
        count = self.conn.execute("SELECT COUNT(*) FROM spam_feedback").fetchone()[0]
        self.assertLessEqual(count, 2)


if __name__ == '__main__':
    unittest.main()
