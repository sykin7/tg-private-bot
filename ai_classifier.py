# -*- coding: utf-8 -*-
"""Multi-provider AI classifier used for smart spam detection.

Supports OpenAI-compatible Chat Completions, Anthropic Messages API and
Google Gemini generateContent through the AI_PROVIDER setting.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time

import requests

from env_utils import env_bool as _env_bool, env_int as _env_int

AI_ENABLED = _env_bool(os.environ.get('AI_ENABLED'))
AI_BASE_URL = (os.environ.get('AI_BASE_URL') or 'https://api.openai.com/v1').rstrip('/')
AI_API_KEY = os.environ.get('AI_API_KEY') or ''
AI_MODEL = os.environ.get('AI_MODEL') or 'gpt-4o-mini'
AI_TIMEOUT = _env_int(os.environ.get('AI_TIMEOUT'), 20)
AI_MIN_SCORE = _env_int(os.environ.get('AI_MIN_SCORE'), 5)
AI_ALWAYS_CHECK = _env_bool(os.environ.get('AI_ALWAYS_CHECK'))
AI_PROFILE_CHECK = _env_bool(os.environ.get('AI_PROFILE_CHECK'), True)
AI_CACHE_TTL = _env_int(os.environ.get('AI_CACHE_TTL'), 300)
AI_PROVIDER = (os.environ.get('AI_PROVIDER') or 'openai-compatible').strip().lower()
AI_MAX_TOKENS = _env_int(os.environ.get('AI_MAX_TOKENS'), 300)
AI_RESPONSE_FORMAT = _env_bool(os.environ.get('AI_RESPONSE_FORMAT'))
AI_KEYWORDS_LIMIT = _env_int(os.environ.get('AI_KEYWORDS_LIMIT'), 2000)
AI_MAX_KEYWORDS = _env_int(os.environ.get('AI_MAX_KEYWORDS'), AI_KEYWORDS_LIMIT)


_PROVIDER_ALIASES = {
    'openai': 'openai-compatible',
    'openai-compatible': 'openai-compatible',
    'openai_compatible': 'openai-compatible',
    'anthropic': 'anthropic',
    'claude': 'anthropic',
    'gemini': 'gemini',
    'google': 'gemini',
    'google-gemini': 'gemini',
    'google_gemini': 'gemini',
}


def normalize_provider(provider):
    """Return the canonical provider name, or None when unsupported."""
    key = (provider or '').strip().lower()
    return _PROVIDER_ALIASES.get(key)

_SYSTEM_PROMPT = (
    "你是 Telegram 反垃圾审核助手。你的任务是判断一条用户消息或用户资料是否属于广告、"
    "垃圾信息、诈骗、引流或黑灰产内容。\n"
    "判定标准：是否在推广商品、服务、资金盘、博彩、兼职刷单、代开发票、虚拟货币交易、"
    "色情裸聊、办证、定位监听、引流到站外等。正常聊天、求助、寒暄不属于广告。\n"
    "只输出 JSON，不要输出其他文字，格式："
    '{"is_spam": true 或 false, "reason": "简短中文原因"}'
)

JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*(.*?)```', re.DOTALL | re.IGNORECASE)


def parse_ai_response(content):
    """Extract the structured classification result from model output."""
    if not content:
        return None
    text = content.strip()
    match = JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        start = text.find('{')
        end = text.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    is_spam = data.get('is_spam')
    if isinstance(is_spam, str):
        is_spam = is_spam.strip().lower() in ('true', '1', 'yes')
    if not isinstance(is_spam, bool):
        return None
    return {
        'is_spam': is_spam,
        'reason': str(data.get('reason') or ('广告' if is_spam else '正常'))[:200],
        'source': 'ai',
    }


class AIClassifier:
    def __init__(self, base_url=None, api_key=None, model=None, timeout=None,
                 cache_ttl=None, session=None, provider=None, max_tokens=None,
                 response_format=None, max_keywords=None, require_env_flag=None):
        self.base_url = (base_url or AI_BASE_URL).rstrip('/')
        self.api_key = api_key if api_key is not None else AI_API_KEY
        self.model = model or AI_MODEL
        self.timeout = timeout if timeout is not None else AI_TIMEOUT
        self.cache_ttl = cache_ttl if cache_ttl is not None else AI_CACHE_TTL
        self.provider = normalize_provider(provider or AI_PROVIDER)
        self.max_tokens = max_tokens if max_tokens is not None else AI_MAX_TOKENS
        self.response_format = (response_format if response_format is not None
                                else AI_RESPONSE_FORMAT)
        self.max_keywords = max_keywords if max_keywords is not None else AI_MAX_KEYWORDS
        self.require_env_flag = (require_env_flag if require_env_flag is not None
                                 else True)
        self.session = session
        self._cache = {}
        self._cache_lock = threading.Lock()
        if not self.provider:
            logging.warning("Unsupported AI_PROVIDER=%r, AI classification disabled.",
                            provider or AI_PROVIDER)

    @property
    def enabled(self):
        return bool(self.require_env_flag and self.provider and self.base_url
                    and self.api_key and self.model)

    def _cache_get(self, key):
        with self._cache_lock:
            item = self._cache.get(key)
            if item and time.time() - item[0] < self.cache_ttl:
                return item[1]
            if item:
                self._cache.pop(key, None)
            return None

    def _cache_set(self, key, value):
        with self._cache_lock:
            if len(self._cache) > 1000:
                now = time.time()
                self._cache = {k: v for k, v in self._cache.items()
                               if now - v[0] < self.cache_ttl}
            self._cache[key] = (time.time(), value)

    @staticmethod
    def _cache_key(text, profile_text, keywords, max_keywords=AI_MAX_KEYWORDS):
        payload = '\n'.join([
            text[:2000],
            profile_text[:300],
            '|'.join(keywords[:max_keywords]),
        ])
        return hashlib.sha256(payload.encode('utf-8', errors='ignore')).hexdigest()

    def _request_url(self):
        if self.provider == 'anthropic':
            base = (self.base_url[:-3]
                    if self.base_url.endswith('/v1') else self.base_url)
            return f'{base}/v1/messages'
        if self.provider == 'gemini':
            if self.base_url.endswith(('/v1', '/v1beta')):
                base = self.base_url
            else:
                base = f'{self.base_url}/v1beta'
            return f'{base}/models/{self.model}:generateContent'
        return f'{self.base_url}/chat/completions'

    def _openai_payload(self, system_prompt, user_prompt):
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0,
        }
        if self.max_tokens > 0:
            payload['max_tokens'] = self.max_tokens
        if self.response_format:
            payload['response_format'] = {'type': 'json_object'}
        return payload

    def _anthropic_payload(self, system_prompt, user_prompt):
        return {
            'model': self.model,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': user_prompt}],
            'max_tokens': self.max_tokens or 300,
            'temperature': 0,
        }

    def _gemini_payload(self, system_prompt, user_prompt):
        generation_config = {
            'temperature': 0,
            'maxOutputTokens': self.max_tokens or 300,
        }
        if self.response_format:
            generation_config['responseMimeType'] = 'application/json'
        return {
            'contents': [{
                'role': 'user',
                'parts': [{'text': f'{system_prompt}\n\n{user_prompt}'}],
            }],
            'generationConfig': generation_config,
        }

    def _build_request(self, system_prompt, user_prompt):
        headers = {'Content-Type': 'application/json'}
        if self.provider == 'anthropic':
            headers.update({
                'x-api-key': self.api_key,
                'anthropic-version': '2023-06-01',
            })
            payload = self._anthropic_payload(system_prompt, user_prompt)
        elif self.provider == 'gemini':
            headers['x-goog-api-key'] = self.api_key
            payload = self._gemini_payload(system_prompt, user_prompt)
        else:
            headers['Authorization'] = f'Bearer {self.api_key}'
            payload = self._openai_payload(system_prompt, user_prompt)
        return self._request_url(), headers, payload

    def _extract_response_text(self, data):
        try:
            if self.provider == 'anthropic':
                content = data.get('content') or []
                for block in content:
                    if isinstance(block, dict) and block.get('text'):
                        return block.get('text')
            elif self.provider == 'gemini':
                candidates = data.get('candidates') or []
                if candidates:
                    parts = (candidates[0].get('content') or {}).get('parts') or []
                    if parts and isinstance(parts[0], dict):
                        return parts[0].get('text')
            else:
                return data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            return None
        return None

    def classify(self, text, keywords=(), profile_text=''):
        """Return a dict with is_spam/reason, or None when unavailable."""
        if not self.enabled:
            return None
        text = (text or '').strip()
        if not text:
            return None
        profile_text = (profile_text or '').strip()
        keywords = [k for k in (keywords or ()) if k and isinstance(k, str)]
        if self.max_keywords > 0:
            keywords = keywords[:self.max_keywords]
        cache_key = self._cache_key(text, profile_text, keywords, self.max_keywords)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return dict(cached, cached=True)

        system_prompt = _SYSTEM_PROMPT
        if keywords:
            system_prompt += f"\n本地广告规则关键词（仅作参考）：{', '.join(keywords)}"
        user_prompt = f"待判断消息：\n{text}"
        if profile_text:
            user_prompt += f"\n\n用户资料：\n{profile_text}"

        url, headers, payload = self._build_request(system_prompt, user_prompt)
        http = self.session or requests
        try:
            resp = http.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logging.warning(f"AI classify HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            content = self._extract_response_text(data)
            result = parse_ai_response(content)
            if result is None:
                logging.warning("AI classify returned unparseable content.")
                return None
            self._cache_set(cache_key, result)
            return dict(result, cached=False)
        except Exception as e:
            logging.warning(f"AI classify request failed: {e}")
            return None


ai_classifier = AIClassifier(require_env_flag=AI_ENABLED)
