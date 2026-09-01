# -*- coding: utf-8 -*-
"""规则同步模块单元测试：特征提取、规则合并、GitHub / R2 推送。"""

import base64
import os
import sys
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import rule_sync


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, get_status=200, get_payload=None, get_text='', put_status=200):
        self.get_status = get_status
        self.get_payload = get_payload
        self.get_text = get_text
        self.put_status = put_status
        self.get_calls = []
        self.put_calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append({'url': url, 'headers': headers, 'params': params, 'timeout': timeout})
        return FakeResponse(self.get_status, self.get_payload, self.get_text)

    def put(self, url, json=None, data=None, headers=None, timeout=None):
        self.put_calls.append({
            'url': url,
            'json': json,
            'data': data,
            'headers': headers,
            'timeout': timeout,
        })
        return FakeResponse(self.put_status)


class ExtractRuleTermsTest(unittest.TestCase):
    def test_extracts_domains_links_mentions_contacts(self):
        content = '低价出USDT，加微信 wxid8888，进群 https://t.me/joinchat/abc123，找 @spamuser，官网 https://spam.example.com/buy'
        terms = rule_sync.extract_rule_terms(content)
        self.assertIn('spam.example.com', terms)
        self.assertIn('t.me/joinchat/abc123', terms)
        self.assertIn('@spamuser', terms)
        self.assertIn('wxid8888', terms)

    def test_ignores_short_or_plain_tokens(self):
        terms = rule_sync.extract_rule_terms('今天天气不错，abc 123')
        self.assertEqual(terms, set())

    def test_returns_empty_for_empty_input(self):
        self.assertEqual(rule_sync.extract_rule_terms(''), set())


class MergeRuleTextTest(unittest.TestCase):
    def test_appends_new_lines_without_duplicates(self):
        merged = rule_sync.merge_rule_text('old.example.com\n', ['old.example.com', 'new.example.com'])
        self.assertIn('new.example.com', merged)
        self.assertEqual(merged.count('old.example.com'), 1)

    def test_returns_none_when_no_new_lines(self):
        self.assertIsNone(rule_sync.merge_rule_text('old.example.com\n', ['old.example.com']))
        self.assertIsNone(rule_sync.merge_rule_text('old.example.com\n', []))


class GitHubSyncTest(unittest.TestCase):
    def test_github_merge_and_write_existing_file(self):
        existing_text = 'old.example.com\n'
        payload = {
            'sha': 'abc123',
            'content': base64.b64encode(existing_text.encode('utf-8')).decode('ascii'),
        }
        session = FakeSession(get_status=200, get_payload=payload, put_status=200)
        with mock.patch.object(rule_sync, 'GITHUB_REPO', 'user/rules'), \
                mock.patch.object(rule_sync, 'GITHUB_PATH', 'spam.txt'), \
                mock.patch.object(rule_sync, 'GITHUB_BRANCH', 'main'), \
                mock.patch.object(rule_sync, 'GITHUB_TOKEN', 'ghp_test'):
            ok, merged = rule_sync.github_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        self.assertIn('new.example.com', merged)
        self.assertEqual(session.put_calls[0]['json']['sha'], 'abc123')
        decoded = base64.b64decode(session.put_calls[0]['json']['content']).decode('utf-8')
        self.assertIn('new.example.com', decoded)

    def test_github_creates_missing_file(self):
        session = FakeSession(get_status=404, put_status=201)
        with mock.patch.object(rule_sync, 'GITHUB_REPO', 'user/rules'), \
                mock.patch.object(rule_sync, 'GITHUB_PATH', 'spam.txt'), \
                mock.patch.object(rule_sync, 'GITHUB_BRANCH', 'main'), \
                mock.patch.object(rule_sync, 'GITHUB_TOKEN', 'ghp_test'):
            ok, merged = rule_sync.github_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        self.assertIn('new.example.com', merged)
        self.assertNotIn('sha', session.put_calls[0]['json'])

    def test_github_disabled_without_token(self):
        session = FakeSession(get_status=200, put_status=200)
        with mock.patch.object(rule_sync, 'GITHUB_REPO', 'user/rules'), \
                mock.patch.object(rule_sync, 'GITHUB_PATH', 'spam.txt'), \
                mock.patch.object(rule_sync, 'GITHUB_TOKEN', ''):
            ok, merged = rule_sync.github_merge_and_write(['new.example.com'], session=session)
        self.assertFalse(ok)
        self.assertIsNone(merged)
        self.assertEqual(session.get_calls, [])
        self.assertEqual(session.put_calls, [])


class R2SyncTest(unittest.TestCase):
    def setUp(self):
        self.original_notify_handler = rule_sync.r2_limit_notify_handler
        self.original_usage_path = rule_sync._r2_usage_store.path
        self.original_local_store_path = rule_sync._r2_local_store.path
        self.original_throttled_by_account = dict(rule_sync._r2_throttled_by_account)
        self.original_last_mirror_at = rule_sync._r2_last_mirror_at
        rule_sync._r2_usage_store.path = ''
        rule_sync._r2_usage_store.reset()
        rule_sync._r2_local_store.path = ''
        rule_sync._r2_local_store.reset()
        rule_sync._r2_throttled_until = 0.0
        rule_sync._r2_throttled_by_account = {}
        rule_sync._r2_fetched_at = 0.0
        rule_sync._r2_cached_text = None
        rule_sync._r2_last_mirror_at = 0.0

    def tearDown(self):
        rule_sync.r2_limit_notify_handler = self.original_notify_handler
        rule_sync._r2_usage_store.path = self.original_usage_path
        rule_sync._r2_usage_store.reset()
        rule_sync._r2_local_store.path = self.original_local_store_path
        rule_sync._r2_local_store.reset()
        rule_sync._r2_throttled_until = 0.0
        rule_sync._r2_throttled_by_account = self.original_throttled_by_account
        rule_sync._r2_fetched_at = 0.0
        rule_sync._r2_cached_text = None
        rule_sync._r2_last_mirror_at = self.original_last_mirror_at

    @staticmethod
    def _legacy_r2_patch():
        return [
            mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://legacy.r2.cloudflarestorage.com'),
            mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules-1'),
            mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'),
            mock.patch.object(rule_sync, 'R2_REGION', 'auto'),
            mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_1'),
            mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_1'),
        ]

    @staticmethod
    def _env_r2_patch(index):
        suffix = f'_{index}'
        return mock.patch.dict(rule_sync.os.environ, {
            f'RULE_SYNC_R2_ENDPOINT{suffix}': f'https://acct{index}.r2.cloudflarestorage.com',
            f'RULE_SYNC_R2_BUCKET{suffix}': f'bot-rules-{index}',
            f'RULE_SYNC_R2_KEY{suffix}': 'spam.txt',
            f'RULE_SYNC_R2_REGION{suffix}': 'auto',
            f'RULE_SYNC_R2_ACCESS_KEY{suffix}': f'ak_{index}',
            f'RULE_SYNC_R2_SECRET_KEY{suffix}': f'sk_{index}',
        })

    def test_fetch_r2_rules(self):
        session = FakeSession(get_status=200, get_text='learned.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            text = rule_sync.fetch_r2_rules(session=session)
        self.assertEqual(text, 'learned.example.com\n')

    def test_fetch_r2_rules_disabled(self):
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', ''), \
                mock.patch.object(rule_sync, 'R2_BUCKET', ''), \
                mock.patch.object(rule_sync, 'R2_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', ''):
            self.assertIsNone(rule_sync.fetch_r2_rules())

    def test_r2_merge_and_write(self):
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        put_call = session.put_calls[0]
        self.assertIn('Authorization', put_call['headers'])
        self.assertIn('x-amz-date', put_call['headers'])
        self.assertIn(b'new.example.com', put_call['data'])

    def test_r2_disabled_without_config(self):
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', ''), \
                mock.patch.object(rule_sync, 'R2_BUCKET', ''), \
                mock.patch.object(rule_sync, 'R2_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', ''):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertFalse(ok)
        self.assertEqual(session.get_calls, [])
        self.assertEqual(session.put_calls, [])

    def test_r2_quota_pauses_requests(self):
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'), \
                mock.patch.object(rule_sync, 'R2_MAX_CLASS_A_MONTHLY', 0), \
                mock.patch.object(rule_sync, 'R2_MAX_CLASS_B_MONTHLY', 0):
            self.assertIsNone(rule_sync.fetch_r2_rules(session=session))
            self.assertFalse(rule_sync.r2_merge_and_write(['new.example.com'], session=session))
        self.assertEqual(session.get_calls, [])
        self.assertEqual(session.put_calls, [])

    def test_r2_rate_limit_cooldown_skips_requests(self):
        session = FakeSession(get_status=429, get_text='', put_status=429)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            rule_sync._r2_request('GET', '', session=session)
            self.assertGreater(rule_sync._r2_throttled_until, time.time())
            rule_sync._r2_request('GET', '', session=session)
        self.assertEqual(len(session.get_calls), 1)

    def test_r2_notify_limit_once_sends_once_per_month(self):
        calls = []

        def handler(reason, class_a, class_b, account_id):
            calls.append((reason, class_a, class_b, account_id))

        rule_sync.r2_limit_notify_handler = handler
        try:
            rule_sync._r2_notify_limit_once('quota_notified_month', 'class_a', 900000, 5)
            rule_sync._r2_notify_limit_once('quota_notified_month', 'class_a', 900000, 5)
        finally:
            rule_sync.r2_limit_notify_handler = None
        self.assertEqual(calls, [('class_a', 900000, 5, '1')])

    def test_r2_quota_notifies_handler_once(self):
        calls = []
        rule_sync._r2_usage_store.record_operation('PUT')
        rule_sync._r2_usage_store.record_operation('GET')
        rule_sync.r2_limit_notify_handler = lambda reason, class_a, class_b, account_id: calls.append(
            (reason, class_a, class_b, account_id)
        )
        try:
            with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                    mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                    mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                    mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                    mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                    mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'), \
                    mock.patch.object(rule_sync, 'R2_MAX_CLASS_A_MONTHLY', 0), \
                    mock.patch.object(rule_sync, 'R2_MAX_CLASS_B_MONTHLY', 0):
                self.assertFalse(rule_sync._r2_allowed('PUT'))
                self.assertFalse(rule_sync._r2_allowed('GET'))
        finally:
            rule_sync.r2_limit_notify_handler = None
        self.assertEqual(calls, [('class_a', 1, 1, '1')])

    def test_r2_rate_limit_notifies_handler(self):
        calls = []
        session = FakeSession(get_status=429, get_text='', put_status=429)
        rule_sync.r2_limit_notify_handler = lambda reason, class_a, class_b, account_id: calls.append(
            (reason, class_a, class_b, account_id)
        )
        try:
            with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                    mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                    mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                    mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                    mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                    mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
                rule_sync._r2_request('GET', '', session=session)
        finally:
            rule_sync.r2_limit_notify_handler = None
        self.assertEqual(calls, [('rate_limit', 0, 0, '1')])

    def test_r2_accounts_reads_multiple_env_accounts(self):
        patches = self._legacy_r2_patch() + [self._env_r2_patch(2)]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            accounts = rule_sync._r2_accounts()
        self.assertEqual([account['id'] for account in accounts], ['1', '2'])

    def test_r2_pick_account_switches_when_first_unavailable(self):
        rule_sync._r2_set_throttled('1', time.time() + 3600)
        patches = self._legacy_r2_patch() + [self._env_r2_patch(2)]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            picked = rule_sync._r2_pick_account('GET')
        self.assertIsNotNone(picked)
        self.assertEqual(picked['id'], '2')

    def test_sync_r2_mirrors_writes_all_other_accounts(self):
        session = FakeSession(get_status=200, get_text='mirror.example.com\n', put_status=200)
        patches = self._legacy_r2_patch() + [self._env_r2_patch(2)]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = rule_sync.sync_r2_mirrors(session=session, force=True)
        self.assertTrue(result['synced'])
        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['source'], '1')
        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(len(session.put_calls), 1)
        self.assertIn(b'mirror.example.com', session.put_calls[0]['data'])
        self.assertGreater(rule_sync._r2_last_sync_at(), 0)

    def test_sync_r2_mirrors_after_recovery_clears_written_account_recovery(self):
        rule_sync._r2_set_recovery('1', time.time() - 10)
        rule_sync._r2_set_recovery('2', time.time() - 10)
        session = FakeSession(get_status=200, get_text='mirror.example.com\n', put_status=200)
        patches = self._legacy_r2_patch() + [self._env_r2_patch(2)]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = rule_sync.sync_r2_mirrors(session=session)
        self.assertTrue(result['synced'])
        self.assertEqual(rule_sync._r2_usage_store.get_meta('recovery', '', account_id='2'), '')

    def test_r2_quota_recovery_resumes_requests(self):
        rule_sync._r2_set_throttled('1', time.time() - 10)
        patches = self._legacy_r2_patch()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            self.assertTrue(rule_sync._r2_allowed('GET'))

    def test_r2_fetch_uses_cache_on_failure(self):
        session_ok = FakeSession(get_status=200, get_text='cached.example.com\n', put_status=200)
        session_fail = FakeSession(get_status=500, get_text='', put_status=500)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            first = rule_sync.fetch_r2_rules(session=session_ok)
            rule_sync._r2_fetched_at = 0.0
            rule_sync._r2_set_local_loaded_at(0.0)
            second = rule_sync.fetch_r2_rules(session=session_fail)
        self.assertEqual(first, 'cached.example.com\n')
        self.assertEqual(second, 'cached.example.com\n')
        self.assertEqual(len(session_fail.get_calls), 1)

    def test_fetch_r2_rules_local_first_skips_remote_within_interval(self):
        session_ok = FakeSession(get_status=200, get_text='local.example.com\n', put_status=200)
        session_spy = FakeSession(get_status=500, get_text='', put_status=500)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            first = rule_sync.fetch_r2_rules(session=session_ok)
            second = rule_sync.fetch_r2_rules(session=session_spy)
        self.assertEqual(first, 'local.example.com\n')
        self.assertEqual(second, 'local.example.com\n')
        self.assertEqual(session_spy.get_calls, [])

    def test_r2_merge_and_write_local_first_skips_get_when_local_ready(self):
        rule_sync._r2_local_store.import_text('old.example.com\n', synced=True)
        session = FakeSession(get_status=200, get_text='remote.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        self.assertEqual(session.get_calls, [])
        self.assertEqual(len(session.put_calls), 1)
        self.assertIn(b'new.example.com', session.put_calls[0]['data'])

    def test_r2_merge_and_write_respects_daily_interval(self):
        rule_sync._r2_set_last_sync_at(time.time() - 60)
        rule_sync._r2_local_store.import_text('old.example.com\n', synced=True)
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertFalse(ok)
        self.assertEqual(session.get_calls, [])
        self.assertEqual(session.put_calls, [])
        self.assertIn('new.example.com', rule_sync._r2_local_store.text())

    def test_r2_merge_and_write_pushes_after_daily_interval(self):
        rule_sync._r2_set_last_sync_at(time.time() - rule_sync.R2_SYNC_INTERVAL - 1)
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        self.assertEqual(len(session.put_calls), 1)

    def test_r2_merge_and_write_pushes_after_recovery(self):
        rule_sync._r2_set_last_sync_at(time.time() - 60)
        rule_sync._r2_set_recovery('1', time.time() - 10)
        session = FakeSession(get_status=200, get_text='old.example.com\n', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertTrue(ok)
        self.assertEqual(len(session.put_calls), 1)
        self.assertEqual(rule_sync._r2_usage_store.get_meta('recovery', '', account_id='1'), '')

    def test_r2_merge_and_write_keeps_pending_when_no_base_and_fetch_fails(self):
        session = FakeSession(get_status=500, get_text='', put_status=500)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            ok = rule_sync.r2_merge_and_write(['new.example.com'], session=session)
        self.assertFalse(ok)
        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(session.put_calls, [])
        self.assertEqual(rule_sync._r2_local_store.pending_count(), 1)

    def test_r2_local_store_dedup_and_categories(self):
        store = rule_sync.LocalRuleStore(path='')
        store.import_text(
            'https://spam.example.com/x\nt.me/joinchat/abc\n@spamuser\n',
            synced=True,
        )
        store.add_learned(['https://spam.example.com/x', 'new.example.com', 'new.example.com'])
        summary = store.summary()
        self.assertEqual(summary['count'], 4)
        self.assertEqual(summary['pending'], 1)
        self.assertEqual(summary['categories'], 4)

    def test_r2_usage_store_today_usage(self):
        rule_sync._r2_usage_store.record_operation('PUT')
        rule_sync._r2_usage_store.record_operation('GET')
        self.assertEqual(rule_sync._r2_usage_store.today_usage(), (1, 1))

    def test_r2_usage_store_reset_clears_usage(self):
        rule_sync._r2_usage_store.record_operation('PUT')
        rule_sync._r2_usage_store.record_operation('GET')
        self.assertEqual(rule_sync._r2_usage_store.monthly_usage(), (1, 1))
        rule_sync._r2_usage_store.reset()
        self.assertEqual(rule_sync._r2_usage_store.monthly_usage(), (0, 0))

    def test_r2_quota_status_reports_usage(self):
        rule_sync._r2_usage_store.record_operation('PUT')
        rule_sync._r2_usage_store.record_operation('GET')
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'), \
                mock.patch.object(rule_sync, 'R2_MAX_CLASS_A_MONTHLY', 900000), \
                mock.patch.object(rule_sync, 'R2_MAX_CLASS_B_MONTHLY', 9000000):
            status = rule_sync.r2_quota_status()
        self.assertIn('Class A', status)
        self.assertIn('Class B', status)
        self.assertNotIn('<code>', status)

    def test_r2_storage_hard_limit_blocks_oversized_put(self):
        session = FakeSession(get_status=200, get_text='', put_status=200)
        with mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'), \
                mock.patch.object(rule_sync, 'R2_STORAGE_WARN_BYTES', 10):
            resp = rule_sync._r2_request('PUT', 'x' * 64, session=session)
        self.assertIsNone(resp)
        self.assertEqual(session.put_calls, [])


class SyncLearnedRulesTest(unittest.TestCase):
    def test_sync_learned_rules_pushes_both_channels(self):
        session = FakeSession(
            get_status=200,
            get_payload={'sha': 'abc', 'content': base64.b64encode(b'old.example.com\n').decode('ascii')},
            get_text='old.example.com\n',
            put_status=200,
        )
        with mock.patch.object(rule_sync, 'GITHUB_REPO', 'user/rules'), \
                mock.patch.object(rule_sync, 'GITHUB_PATH', 'spam.txt'), \
                mock.patch.object(rule_sync, 'GITHUB_BRANCH', 'main'), \
                mock.patch.object(rule_sync, 'GITHUB_TOKEN', 'ghp_test'), \
                mock.patch.object(rule_sync, 'R2_ENDPOINT', 'https://abc.r2.cloudflarestorage.com'), \
                mock.patch.object(rule_sync, 'R2_BUCKET', 'bot-rules'), \
                mock.patch.object(rule_sync, 'R2_KEY', 'spam.txt'), \
                mock.patch.object(rule_sync, 'R2_REGION', 'auto'), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', 'ak_test'), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', 'sk_test'):
            result = rule_sync.sync_learned_rules(['new.example.com'], session=session)
        self.assertEqual(result, {'github': True, 'r2': True})

    def test_sync_status_lists_configured_channels(self):
        with mock.patch.object(rule_sync, 'GITHUB_REPO', ''), \
                mock.patch.object(rule_sync, 'GITHUB_PATH', ''), \
                mock.patch.object(rule_sync, 'GITHUB_TOKEN', ''), \
                mock.patch.object(rule_sync, 'R2_ENDPOINT', ''), \
                mock.patch.object(rule_sync, 'R2_BUCKET', ''), \
                mock.patch.object(rule_sync, 'R2_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_ACCESS_KEY', ''), \
                mock.patch.object(rule_sync, 'R2_SECRET_KEY', ''):
            self.assertEqual(rule_sync.sync_status(), '未配置')


if __name__ == '__main__':
    unittest.main()
