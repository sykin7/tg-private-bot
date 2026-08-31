# -*- coding: utf-8 -*-
"""Sync learned spam features into remote rule files (GitHub / Cloudflare R2)."""

import base64
import hashlib
import hmac
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from env_utils import env_float as _env_float, env_int as _env_int

GITHUB_REPO = (os.environ.get('RULE_SYNC_GITHUB_REPO') or '').strip()
GITHUB_PATH = (os.environ.get('RULE_SYNC_GITHUB_PATH') or '').strip().lstrip('/')
GITHUB_BRANCH = (os.environ.get('RULE_SYNC_GITHUB_BRANCH') or 'main').strip() or 'main'
GITHUB_TOKEN = os.environ.get('RULE_SYNC_GITHUB_TOKEN') or ''

R2_ENDPOINT = (os.environ.get('RULE_SYNC_R2_ENDPOINT') or '').strip().rstrip('/')
R2_BUCKET = (os.environ.get('RULE_SYNC_R2_BUCKET') or '').strip()
R2_KEY = (os.environ.get('RULE_SYNC_R2_KEY') or '').strip().lstrip('/')
R2_REGION = (os.environ.get('RULE_SYNC_R2_REGION') or 'auto').strip() or 'auto'
R2_ACCESS_KEY = os.environ.get('RULE_SYNC_R2_ACCESS_KEY') or ''
R2_SECRET_KEY = os.environ.get('RULE_SYNC_R2_SECRET_KEY') or ''

R2_USAGE_PATH = (os.environ.get('R2_USAGE_PATH') or '').strip() or '/app/data/r2_usage.db'
R2_LOCAL_RULES_PATH = (os.environ.get('R2_LOCAL_RULES_PATH') or '').strip() or R2_USAGE_PATH
R2_FETCH_INTERVAL = 10800  # 3 hours
R2_MAX_CLASS_A_MONTHLY = 900000
R2_MAX_CLASS_B_MONTHLY = 9000000
R2_RATE_LIMIT_COOLDOWN = 3600
R2_MIRROR_INTERVAL = 10800  # 3 hours
R2_SYNC_INTERVAL = 10800  # 3 hours


R2_FETCH_INTERVAL = _env_int(os.environ.get('R2_FETCH_INTERVAL'), R2_FETCH_INTERVAL)
R2_MAX_CLASS_A_MONTHLY = _env_int(os.environ.get('R2_MAX_CLASS_A_MONTHLY'), R2_MAX_CLASS_A_MONTHLY)
R2_MAX_CLASS_B_MONTHLY = _env_int(os.environ.get('R2_MAX_CLASS_B_MONTHLY'), R2_MAX_CLASS_B_MONTHLY)
R2_RATE_LIMIT_COOLDOWN = _env_int(os.environ.get('R2_RATE_LIMIT_COOLDOWN'), R2_RATE_LIMIT_COOLDOWN)
R2_MIRROR_INTERVAL = _env_int(os.environ.get('R2_MIRROR_INTERVAL'), R2_MIRROR_INTERVAL)
R2_SYNC_INTERVAL = _env_int(os.environ.get('R2_SYNC_INTERVAL'), R2_SYNC_INTERVAL)
R2_MAX_STORAGE_GB = _env_float(os.environ.get('R2_MAX_STORAGE_GB'), 10)
# R2 free storage hard guard: stop PUT before the 9 GB threshold is exceeded.
# Use decimal GB (10^9 bytes) so the guard stays below the 10 GB free cap.
R2_STORAGE_WARN_RATIO = _env_float(os.environ.get('R2_STORAGE_WARN_RATIO'), 0.9)
R2_MAX_STORAGE_BYTES = int(R2_MAX_STORAGE_GB * 1000 ** 3)
R2_STORAGE_WARN_BYTES = int(R2_MAX_STORAGE_BYTES * R2_STORAGE_WARN_RATIO)


def _env_r2_account(index):
    suffix = f'_{index}'
    endpoint = (os.environ.get(f'RULE_SYNC_R2_ENDPOINT{suffix}') or '').strip().rstrip('/')
    bucket = (os.environ.get(f'RULE_SYNC_R2_BUCKET{suffix}') or '').strip()
    key = (os.environ.get(f'RULE_SYNC_R2_KEY{suffix}') or '').strip().lstrip('/')
    region = (os.environ.get(f'RULE_SYNC_R2_REGION{suffix}') or 'auto').strip() or 'auto'
    access_key = os.environ.get(f'RULE_SYNC_R2_ACCESS_KEY{suffix}') or ''
    secret_key = os.environ.get(f'RULE_SYNC_R2_SECRET_KEY{suffix}') or ''
    if not (endpoint and bucket and key and access_key and secret_key):
        return None
    return {
        'id': str(index),
        'endpoint': endpoint,
        'bucket': bucket,
        'key': key,
        'region': region,
        'access_key': access_key,
        'secret_key': secret_key,
    }


def _r2_legacy_account():
    if not (R2_ENDPOINT and R2_BUCKET and R2_KEY and R2_ACCESS_KEY and R2_SECRET_KEY):
        return None
    return {
        'id': '1',
        'endpoint': R2_ENDPOINT,
        'bucket': R2_BUCKET,
        'key': R2_KEY,
        'region': R2_REGION,
        'access_key': R2_ACCESS_KEY,
        'secret_key': R2_SECRET_KEY,
    }


def _r2_accounts():
    accounts = []
    legacy = _r2_legacy_account()
    if legacy:
        accounts.append(legacy)
    start = 2 if legacy else 1
    seen_ids = {account['id'] for account in accounts}
    for index in range(start, 21):
        account = _env_r2_account(index)
        if account is None:
            continue
        if account['id'] in seen_ids:
            continue
        accounts.append(account)
        seen_ids.add(account['id'])
    return accounts

_URL_RE = re.compile(r'https?://([^\s/?#]+)', re.IGNORECASE)
_DOMAIN_RE = re.compile(r'(?<![@\w])(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+)', re.IGNORECASE)
_TG_LINK_RE = re.compile(r'(?:t\.me/|telegram\.me/)([a-zA-Z0-9_/+]{4,40})', re.IGNORECASE)
_TG_MENTION_RE = re.compile(r'@([a-zA-Z0-9_]{4,32})')
_CONTACT_RE = re.compile(r'(?:微信|weixin|wechat|wx|vx|v信|qq|q群)\s*[:：]?\s*([a-zA-Z0-9_-]{4,32})', re.IGNORECASE)
_MIXED_TOKEN_RE = re.compile(r'(?<![@\w])[a-zA-Z0-9_-]{6,40}(?![@\w])')
_PLAIN_DOMAIN_RE = re.compile(r'(?:https?://)?(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+')


def categorize_rule(rule):
    """Classify a rule line for grouped dedup and storage statistics."""
    value = str(rule or '').strip().lower()
    if not value:
        return 'empty'
    if value.startswith(('t.me/', 'telegram.me/')):
        return 'telegram_link'
    if value.startswith('@'):
        return 'mention'
    if value.startswith(('http://', 'https://')):
        if 't.me/' in value or 'telegram.me/' in value:
            return 'telegram_link'
        return 'url'
    if _CONTACT_RE.search(value):
        return 'contact'
    if _PLAIN_DOMAIN_RE.fullmatch(value):
        return 'domain'
    return 'token'


def extract_rule_terms(content):
    """Extract precise, low-false-positive features from an ad sample."""
    if not content:
        return set()
    text = re.sub(r'\s+', ' ', content).strip()
    terms = set()
    for match in _URL_RE.finditer(text):
        host = match.group(1).lower().rstrip('.,;:')
        terms.add(host)
        terms.add('https://' + host)
    for match in _TG_LINK_RE.finditer(text):
        terms.add('t.me/' + match.group(1))
    for match in _TG_MENTION_RE.finditer(text):
        terms.add('@' + match.group(1))
    for match in _CONTACT_RE.finditer(text):
        terms.add(match.group(1).strip())
    for match in _DOMAIN_RE.finditer(text):
        host = match.group(1).lower().rstrip('.,;:')
        terms.add(host)
    for match in _MIXED_TOKEN_RE.finditer(text):
        token = match.group(0)
        if re.search(r'\d', token) and re.search(r'[a-zA-Z]', token):
            terms.add(token)
    return {term for term in terms if 4 <= len(term) <= 60}


def merge_rule_text(existing_text, new_lines):
    """Append new rule lines without duplicating existing ones."""
    if not new_lines:
        return None
    existing = []
    seen = set()
    for line in (existing_text or '').splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            existing.append(line)
    additions = []
    for line in new_lines:
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            additions.append(line)
    if not additions:
        return None
    return '\n'.join(existing + additions) + '\n'


def github_config_enabled():
    return bool(GITHUB_REPO and GITHUB_PATH and GITHUB_TOKEN)


def github_merge_and_write(new_lines, session=None):
    if not github_config_enabled():
        return False, None
    http = session or requests
    api = (
        f'https://api.github.com/repos/{quote(GITHUB_REPO, safe="/")}'
        f'/contents/{quote(GITHUB_PATH, safe="/")}'
    )
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    try:
        existing = http.get(api, headers=headers, params={'ref': GITHUB_BRANCH}, timeout=20)
        sha = None
        base_text = ''
        if existing.status_code == 200:
            data = existing.json()
            sha = data.get('sha')
            base_text = base64.b64decode(data.get('content') or '').decode('utf-8', errors='replace')
        elif existing.status_code != 404:
            logging.warning(f"GitHub rules read failed: HTTP {existing.status_code}")
            return False, None
        merged = merge_rule_text(base_text, new_lines)
        if merged is None:
            return True, base_text
        payload = {
            'message': 'bot: sync learned spam rules',
            'content': base64.b64encode(merged.encode('utf-8')).decode('ascii'),
            'branch': GITHUB_BRANCH,
        }
        if sha:
            payload['sha'] = sha
        resp = http.put(api, json=payload, headers=headers, timeout=20)
        if resp.status_code in (200, 201):
            logging.info(f"GitHub rules synced: {GITHUB_REPO}/{GITHUB_PATH}")
            return True, merged
        logging.warning(f"GitHub rules write failed: HTTP {resp.status_code}")
        return False, None
    except Exception as e:
        logging.warning(f"GitHub rules sync failed: {e}")
        return False, None


def r2_config_enabled():
    return bool(_r2_accounts())


class R2UsageStore:
    """Persist R2 operation counts so the bot can honor the free tier with a safety margin."""

    def __init__(self, path=None):
        self.path = (path or R2_USAGE_PATH).strip()
        self.lock = threading.Lock()
        self._data = {}
        self._meta = {}
        self._load()

    @staticmethod
    def _day_key(account_id, day):
        account_id = str(account_id or '1')
        if account_id == '1':
            return day
        return f'{account_id}:{day}'

    @staticmethod
    def _day_in_month(day_key, account_id, month):
        account_id = str(account_id or '1')
        if account_id == '1':
            return day_key.startswith(month) or day_key.startswith('1:' + month)
        return day_key.startswith(f'{account_id}:' + month)

    @staticmethod
    def _meta_key(account_id, key):
        account_id = str(account_id or '1')
        if account_id == '1':
            return key
        return f'{account_id}:{key}'

    def _connect(self):
        if not self.path:
            return None
        try:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS r2_usage ("
                "day TEXT PRIMARY KEY, class_a INTEGER NOT NULL DEFAULT 0, "
                "class_b INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS r2_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            return conn
        except Exception as e:
            logging.warning(f"R2 usage SQLite unavailable ({self.path}): {e}")
            return None

    def _load(self):
        conn = self._connect()
        if conn is None:
            return
        try:
            for day, class_a, class_b, _ in conn.execute(
                "SELECT day, class_a, class_b, updated_at FROM r2_usage"
            ).fetchall():
                self._data[day] = {'class_a': int(class_a or 0), 'class_b': int(class_b or 0)}
            for key, value in conn.execute("SELECT key, value FROM r2_meta").fetchall():
                self._meta[key] = value
        except Exception as e:
            logging.warning(f"R2 usage load failed: {e}")
        finally:
            conn.close()

    def record_operation(self, method, account_id='1'):
        is_class_a = str(method or '').upper() == 'PUT'
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        day_key = self._day_key(account_id, day)
        with self.lock:
            entry = self._data.setdefault(day_key, {'class_a': 0, 'class_b': 0})
            if is_class_a:
                entry['class_a'] += 1
            else:
                entry['class_b'] += 1
            self._persist(day_key, entry)

    def _persist(self, day, entry):
        conn = self._connect()
        if conn is None:
            return
        try:
            exists = conn.execute("SELECT 1 FROM r2_usage WHERE day=?", (day,)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE r2_usage SET class_a=?, class_b=?, updated_at=? WHERE day=?",
                    (entry['class_a'], entry['class_b'], time.time(), day),
                )
            else:
                conn.execute(
                    "INSERT INTO r2_usage (day, class_a, class_b, updated_at) VALUES (?, ?, ?, ?)",
                    (day, entry['class_a'], entry['class_b'], time.time()),
                )
            conn.commit()
        except Exception as e:
            logging.warning(f"R2 usage persist failed: {e}")
        finally:
            conn.close()

    def monthly_usage(self, account_id='1'):
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.lock:
            class_a = sum(
                entry.get('class_a', 0)
                for day, entry in self._data.items()
                if self._day_in_month(day, account_id, month)
            )
            class_b = sum(
                entry.get('class_b', 0)
                for day, entry in self._data.items()
                if self._day_in_month(day, account_id, month)
            )
        return class_a, class_b

    def today_usage(self, account_id='1'):
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        entry = self._data.get(self._day_key(account_id, day), {'class_a': 0, 'class_b': 0})
        return int(entry.get('class_a', 0) or 0), int(entry.get('class_b', 0) or 0)

    def get_meta(self, key, default=None, account_id='1'):
        with self.lock:
            return self._meta.get(self._meta_key(account_id, key), default)

    def set_meta(self, key, value, account_id='1'):
        meta_key = self._meta_key(account_id, key)
        with self.lock:
            self._meta[meta_key] = str(value)
        conn = self._connect()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT INTO r2_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (meta_key, str(value)),
            )
            conn.commit()
        except Exception as e:
            logging.warning(f"R2 meta persist failed: {e}")
        finally:
            conn.close()

    def reset(self):
        with self.lock:
            self._data.clear()
            self._meta.clear()


class LocalRuleStore:
    """SQLite-backed local R2 rule mirror with dedup and category grouping."""

    def __init__(self, path=None):
        self.path = (path if path is not None else R2_LOCAL_RULES_PATH).strip()
        self.lock = threading.Lock()
        self._memory = {}
        if self.path:
            self._connect()

    def _connect(self):
        if not self.path:
            return None
        try:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS r2_rules ("
                "rule TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT 'token', "
                "hit_count INTEGER NOT NULL DEFAULT 1, synced INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_r2_rules_synced ON r2_rules(synced)")
            return conn
        except Exception as e:
            logging.warning(f"R2 local rules SQLite unavailable ({self.path}): {e}")
            return None

    def add_lines(self, lines, synced=False):
        """Insert deduplicated rules; returns the number of new rules."""
        normalized = []
        for raw in lines or []:
            rule = str(raw or '').strip()
            if rule:
                normalized.append((rule, categorize_rule(rule), 1 if synced else 0))
        if not normalized:
            return 0
        added = 0
        with self.lock:
            if self.path:
                conn = self._connect()
                if conn is None:
                    return 0
                try:
                    conn.execute("BEGIN")
                    for rule, category, rule_synced in normalized:
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO r2_rules "
                            "(rule, category, hit_count, synced) VALUES (?, ?, 1, ?)",
                            (rule, category, rule_synced),
                        )
                        if cur.rowcount:
                            added += 1
                        else:
                            conn.execute(
                                "UPDATE r2_rules SET hit_count = hit_count + 1 WHERE rule = ?",
                                (rule,),
                            )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logging.warning(f"R2 local rules write failed: {e}")
                finally:
                    conn.close()
            else:
                for rule, category, rule_synced in normalized:
                    existing = self._memory.get(rule)
                    if existing is None:
                        self._memory[rule] = {
                            'category': category,
                            'hit_count': 1,
                            'synced': rule_synced,
                        }
                        added += 1
                    else:
                        existing['hit_count'] += 1
        return added

    def text(self):
        with self.lock:
            if self.path:
                conn = self._connect()
                if conn is None:
                    return ''
                try:
                    rows = conn.execute("SELECT rule FROM r2_rules ORDER BY rule").fetchall()
                    return '\n'.join(row[0] for row in rows) + ('\n' if rows else '')
                finally:
                    conn.close()
            return '\n'.join(sorted(self._memory)) + ('\n' if self._memory else '')

    def summary(self):
        with self.lock:
            if self.path:
                conn = self._connect()
                if conn is None:
                    return {'count': 0, 'bytes': 0, 'pending': 0, 'categories': 0}
                try:
                    row = conn.execute(
                        "SELECT COUNT(*), "
                        "COALESCE(SUM(LENGTH(CAST(rule AS BLOB))), 0), "
                        "COALESCE(SUM(CASE WHEN synced=0 THEN 1 ELSE 0 END), 0), "
                        "(SELECT COUNT(DISTINCT category) FROM r2_rules) "
                        "FROM r2_rules"
                    ).fetchone()
                    count = int(row[0] or 0)
                    return {
                        'count': count,
                        'bytes': int(row[1] or 0) + count,
                        'pending': int(row[2] or 0),
                        'categories': int(row[3] or 0),
                    }
                finally:
                    conn.close()
            count = len(self._memory)
            return {
                'count': count,
                'bytes': sum(len(rule.encode('utf-8')) for rule in self._memory) + count,
                'pending': sum(1 for item in self._memory.values() if not item['synced']),
                'categories': len({item['category'] for item in self._memory.values()}),
            }

    def count(self):
        return int(self.summary().get('count', 0) or 0)

    def pending_count(self):
        return int(self.summary().get('pending', 0) or 0)

    def db_size(self):
        if not self.path:
            return 0
        total = 0
        for suffix in ('', '-wal', '-shm'):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total

    def import_text(self, text, synced=True):
        return self.add_lines((text or '').splitlines(), synced=synced)

    def add_learned(self, lines):
        return self.add_lines(lines, synced=False)

    def mark_all_synced(self):
        with self.lock:
            if self.path:
                conn = self._connect()
                if conn is None:
                    return
                try:
                    conn.execute("UPDATE r2_rules SET synced=1")
                    conn.commit()
                finally:
                    conn.close()
            else:
                for item in self._memory.values():
                    item['synced'] = 1

    def reset(self):
        with self.lock:
            if self.path:
                conn = self._connect()
                if conn is None:
                    return
                try:
                    conn.execute("DELETE FROM r2_rules")
                    conn.commit()
                finally:
                    conn.close()
            self._memory.clear()


_r2_usage_store = R2UsageStore()
_r2_local_store = LocalRuleStore()
_r2_throttled_until = 0.0
_r2_throttled_by_account = {}
_r2_fetched_at = 0.0
_r2_cached_text = None
_r2_fetched_account = None
_r2_last_mirror_at = 0.0
_r2_mirror_lock = threading.Lock()
r2_limit_notify_handler = None

try:
    _r2_throttled_until = float(_r2_usage_store.get_meta('throttled_until', '0') or 0)
except (TypeError, ValueError):
    _r2_throttled_until = 0.0


def _format_bytes(value):
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _r2_local_loaded_at():
    try:
        return float(_r2_usage_store.get_meta('r2_local_loaded_at', '0') or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2_set_local_loaded_at(when):
    _r2_usage_store.set_meta('r2_local_loaded_at', when)


def r2_local_storage_status():
    """Return a local rules size report, including the R2 10 GB estimate."""
    summary = _r2_local_store.summary()
    if not summary['count']:
        return ''
    storage_bytes = int(summary['bytes'])
    percent = storage_bytes / R2_MAX_STORAGE_BYTES * 100 if R2_MAX_STORAGE_BYTES else 0
    db_bytes = _r2_local_store.db_size()
    return (
        f"R2 本地规则：{summary['count']} 条（{summary['categories']} 类），"
        f"待同步 {summary['pending']} 条，文本约 {_format_bytes(storage_bytes)}，"
        f"本地 DB {_format_bytes(db_bytes)}，R2 免费存储 {percent:.4f}%"
    )


def _r2_find_account(account_id):
    account_id = str(account_id or '1')
    for account in _r2_accounts():
        if account['id'] == account_id:
            return account
    return None


def _r2_get_throttled(account_id):
    account_id = str(account_id or '1')
    if account_id == '1':
        return _r2_throttled_until
    return float(_r2_throttled_by_account.get(account_id, 0.0) or 0.0)


def _r2_set_throttled(account_id, value):
    global _r2_throttled_until
    account_id = str(account_id or '1')
    if account_id == '1':
        _r2_throttled_until = value
    else:
        _r2_throttled_by_account[account_id] = value
    _r2_usage_store.set_meta('throttled_until', value, account_id=account_id)


for _r2_account in _r2_accounts():
    try:
        _throttled_value = float(_r2_usage_store.get_meta(
            'throttled_until', '0', account_id=_r2_account['id']
        ) or 0)
        if _r2_account['id'] == '1':
            _r2_throttled_until = _throttled_value
        else:
            _r2_throttled_by_account[_r2_account['id']] = _throttled_value
    except (TypeError, ValueError):
        pass


def _r2_next_month_utc():
    now = datetime.now(timezone.utc)
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)


def _r2_set_recovery(account_id, when):
    _r2_usage_store.set_meta('recovery', when, account_id=account_id)


def r2_recovery_text(account_id='1'):
    raw = _r2_usage_store.get_meta('recovery', '', account_id=account_id)
    try:
        when = float(raw or 0)
    except (TypeError, ValueError):
        return ''
    if when <= 0:
        return ''
    return datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def _r2_has_recovered_account():
    for account in _r2_accounts():
        raw = _r2_usage_store.get_meta('recovery', '', account_id=account['id'])
        try:
            when = float(raw or 0)
        except (TypeError, ValueError):
            continue
        if when > 0 and time.time() >= when:
            return True
    return False


def _r2_clear_recovery(account_id):
    _r2_usage_store.set_meta('recovery', '', account_id=account_id)


def _r2_last_sync_at():
    try:
        return float(_r2_usage_store.get_meta('last_sync_at', '0') or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2_set_last_sync_at(when):
    _r2_usage_store.set_meta('last_sync_at', when)


def _r2_should_push():
    """Honor the configured sync window unless an R2 account just recovered."""
    if _r2_has_recovered_account():
        return True
    last_sync = _r2_last_sync_at()
    if last_sync <= 0:
        return True
    return time.time() - last_sync >= R2_SYNC_INTERVAL


def _r2_notify_limit_once(meta_key, reason, class_a, class_b, account_id='1'):
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    if _r2_usage_store.get_meta(meta_key, '', account_id=account_id) == month:
        return
    _r2_usage_store.set_meta(meta_key, month, account_id=account_id)
    handler = r2_limit_notify_handler
    if handler:
        try:
            handler(reason, class_a, class_b, account_id)
        except Exception as e:
            logging.warning(f"R2 limit notification failed: {e}")


def _r2_account_allowed(account, method, notify=True):
    account_id = account['id']
    now = time.time()
    throttled_until = _r2_get_throttled(account_id)
    if now < throttled_until:
        if notify:
            _r2_set_recovery(account_id, throttled_until)
            _r2_notify_limit_once('cooldown_notified_month', 'rate_limit', 0, 0, account_id)
            logging.warning(f"R2-{account_id} request skipped: cooldown until {r2_recovery_text(account_id)}")
        return False, 'rate_limit'
    class_a, class_b = _r2_usage_store.monthly_usage(account_id=account_id)
    if method == 'PUT':
        if class_a >= R2_MAX_CLASS_A_MONTHLY:
            recovery_ts = _r2_next_month_utc().timestamp()
            if notify:
                _r2_set_recovery(account_id, recovery_ts)
                _r2_notify_limit_once('quota_notified_month', 'class_a', class_a, class_b, account_id)
                logging.warning(
                    f"R2-{account_id} Class A monthly quota reached "
                    f"({class_a}/{R2_MAX_CLASS_A_MONTHLY}); write paused until {r2_recovery_text(account_id)}."
                )
            return False, 'class_a'
    elif class_b >= R2_MAX_CLASS_B_MONTHLY:
        recovery_ts = _r2_next_month_utc().timestamp()
        if notify:
            _r2_set_recovery(account_id, recovery_ts)
            _r2_notify_limit_once('quota_notified_month', 'class_b', class_a, class_b, account_id)
            logging.warning(
                f"R2-{account_id} Class B monthly quota reached "
                f"({class_b}/{R2_MAX_CLASS_B_MONTHLY}); read paused until {r2_recovery_text(account_id)}."
            )
        return False, 'class_b'
    return True, None


def _r2_allowed(method, account_id='1'):
    account = _r2_find_account(account_id)
    if account is None:
        return False
    allowed, _ = _r2_account_allowed(account, method)
    return allowed


def _r2_pick_account(method):
    for account in _r2_accounts():
        allowed, _ = _r2_account_allowed(account, method)
        if allowed:
            return account
    return None


def r2_quota_status():
    accounts = _r2_accounts()
    if not accounts:
        return ''
    lines = []
    for account in accounts:
        class_a, class_b = _r2_usage_store.monthly_usage(account_id=account['id'])
        today_a, today_b = _r2_usage_store.today_usage(account_id=account['id'])
        line = (
            f"R2-{account['id']}：Class A {class_a}/{R2_MAX_CLASS_A_MONTHLY}，"
            f"今日 {today_a}；Class B {class_b}/{R2_MAX_CLASS_B_MONTHLY}，今日 {today_b}"
        )
        allowed, reason = _r2_account_allowed(account, 'GET', notify=False)
        if not allowed:
            recovery = r2_recovery_text(account['id'])
            suffix = '冷却中' if reason == 'rate_limit' else '已暂停'
            line += f"，{suffix}"
            if recovery:
                line += f"，预计 {recovery} 恢复"
        lines.append(line)
    storage_text = r2_local_storage_status()
    if storage_text:
        lines.append(storage_text)
    return '\n'.join(lines)


def _hmac_sha256(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def _signing_key(secret, date_stamp, region):
    k_date = _hmac_sha256(('AWS4' + secret).encode('utf-8'), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, 's3')
    return _hmac_sha256(k_service, 'aws4_request')


def _sign_headers(method, host, path, payload_text, account, now=None):
    payload_hash = hashlib.sha256((payload_text or '').encode('utf-8')).hexdigest()
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = amz_date[:8]
    canonical_headers = (
        f'host:{host}\n'
        f'x-amz-content-sha256:{payload_hash}\n'
        f'x-amz-date:{amz_date}\n'
    )
    signed_headers = 'host;x-amz-content-sha256;x-amz-date'
    canonical_request = f'{method}\n{path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}'
    scope = f'{date_stamp}/{account["region"]}/s3/aws4_request'
    string_to_sign = (
        f'AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n'
        + hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    )
    signature = hmac.new(_signing_key(account['secret_key'], date_stamp, account['region']),
                         string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    auth = (
        f'AWS4-HMAC-SHA256 Credential={account["access_key"]}/{scope}, '
        f'SignedHeaders={signed_headers}, Signature={signature}'
    )
    return {
        'Authorization': auth,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
    }


def _r2_url(account):
    return f'{account["endpoint"]}/{account["bucket"]}/{quote(account["key"], safe="/")}'


def _r2_request(method, payload_text, session=None, account_id=None):
    if account_id is None:
        account = _r2_pick_account(method)
    else:
        account = _r2_find_account(account_id)
    if account is None:
        return None
    allowed, _ = _r2_account_allowed(account, method)
    if not allowed:
        return None
    if method == 'PUT':
        payload_bytes = len((payload_text or '').encode('utf-8'))
        if payload_bytes > R2_STORAGE_WARN_BYTES:
            _r2_notify_limit_once('storage_notified_month', 'storage', payload_bytes, 0, account['id'])
            logging.warning(
                f"R2-{account['id']} rules size {_format_bytes(payload_bytes)} "
                f"exceeds {_format_bytes(R2_STORAGE_WARN_BYTES)}; write skipped."
            )
            return None
    _r2_usage_store.record_operation(method, account_id=account['id'])
    url = _r2_url(account)
    parsed = urlparse(url)
    headers = _sign_headers(method, parsed.netloc, parsed.path or '/', payload_text, account)
    http = session or requests
    try:
        if method == 'GET':
            resp = http.get(url, headers=headers, timeout=20)
        else:
            resp = http.put(url, data=(payload_text or '').encode('utf-8'), headers=headers, timeout=20)
    except Exception as e:
        logging.warning(f"R2 request failed ({method}): {e}")
        return None
    if getattr(resp, 'status_code', None) in (429, 503):
        throttled_until = time.time() + R2_RATE_LIMIT_COOLDOWN
        _r2_set_throttled(account['id'], throttled_until)
        _r2_set_recovery(account['id'], throttled_until)
        _r2_notify_limit_once('cooldown_notified_month', 'rate_limit', 0, 0, account['id'])
        logging.warning(
            f"R2-{account['id']} rate limit hit (HTTP {resp.status_code}); "
            f"cooldown {R2_RATE_LIMIT_COOLDOWN}s until {r2_recovery_text(account['id'])}"
        )
    return resp


def r2_merge_and_write(new_lines, base_text='', session=None):
    accounts = _r2_accounts()
    if not accounts:
        return False
    if _r2_local_store.count() == 0:
        fetch_r2_rules(session=session)
    if _r2_local_store.count() == 0 and base_text:
        _r2_local_store.import_text(base_text, synced=True)
    safe_base = _r2_local_store.count() > 0 or bool(base_text)
    added = _r2_local_store.add_learned(new_lines)
    if added == 0 and _r2_local_store.pending_count() == 0:
        return True
    if not safe_base:
        logging.warning(
            "R2 rules write skipped: no remote base available; keeping pending locally."
        )
        return False
    if not _r2_should_push():
        logging.info(
            "R2 rules write skipped: within sync interval; keeping pending locally."
        )
        return False
    local_text = _r2_local_store.text()
    push_text = merge_rule_text(base_text, local_text.splitlines())
    if push_text is None:
        push_text = local_text or base_text
    if not push_text:
        return False
    any_written = False
    for account in accounts:
        account_id = account['id']
        allowed, reason = _r2_account_allowed(account, 'PUT')
        if not allowed:
            logging.warning(f"R2-{account_id} rules write skipped: {reason}.")
            continue
        resp = _r2_request('PUT', push_text, session=session, account_id=account_id)
        if resp is not None:
            if resp.status_code in (200, 201, 204):
                logging.info(f"R2-{account_id} rules synced.")
                any_written = True
                _r2_clear_recovery(account_id)
            else:
                logging.warning(f"R2-{account_id} rules write failed: HTTP {resp.status_code}")
        else:
            logging.warning(f"R2-{account_id} rules write skipped (quota or cooldown).")
    if any_written:
        _r2_local_store.mark_all_synced()
        _r2_set_last_sync_at(time.time())
    return any_written


def fetch_r2_rules(session=None):
    """Return local-first R2 rules; only fetch remote on first use or daily refresh."""
    accounts = _r2_accounts()
    global _r2_fetched_at, _r2_cached_text, _r2_fetched_account
    now = time.time()
    local_text = _r2_local_store.text()
    loaded_at = _r2_local_loaded_at()
    if loaded_at and now - loaded_at < R2_FETCH_INTERVAL:
        _r2_fetched_account = None
        return local_text
    if not accounts:
        _r2_fetched_account = None
        return local_text or None
    last_error = None
    for account in accounts:
        resp = _r2_request('GET', '', session=session, account_id=account['id'])
        if resp is None:
            continue
        if resp.status_code == 200:
            _r2_local_store.import_text(resp.text or '', synced=True)
            _r2_set_local_loaded_at(now)
            _r2_fetched_at = now
            _r2_cached_text = _r2_local_store.text()
            _r2_fetched_account = account['id']
            return _r2_cached_text
        last_error = f"HTTP {resp.status_code}"
        logging.warning(f"R2-{account['id']} rules fetch failed: {last_error}")
    if last_error:
        logging.warning(f"R2 rules fetch failed: {last_error}; using cache")
    _r2_fetched_account = None
    return local_text if local_text else _r2_cached_text


def sync_r2_mirrors(session=None, force=False):
    """Keep every available R2 account on the same rule text."""
    accounts = _r2_accounts()
    if len(accounts) < 2:
        return {'synced': False, 'reason': 'single'}
    global _r2_last_mirror_at
    now = time.time()
    with _r2_mirror_lock:
        if (
            not force
            and not _r2_has_recovered_account()
            and _r2_last_mirror_at
            and now - _r2_last_mirror_at < R2_MIRROR_INTERVAL
        ):
            return {'synced': False, 'reason': 'interval'}
        if _r2_local_store.count() == 0:
            fetch_r2_rules(session=session)
        text = _r2_local_store.text()
        if not text:
            return {'synced': False, 'reason': 'no_local'}
        updated = 0
        fetched_from = _r2_fetched_account
        for account in accounts:
            if fetched_from and account['id'] == fetched_from:
                continue
            resp2 = _r2_request('PUT', text, session=session, account_id=account['id'])
            if resp2 is not None and resp2.status_code in (200, 201, 204):
                updated += 1
                _r2_clear_recovery(account['id'])
                logging.info(f"R2 mirror synced to R2-{account['id']}.")
        _r2_last_mirror_at = time.time()
        if updated > 0:
            _r2_set_last_sync_at(time.time())
        return {
            'synced': updated > 0,
            'updated': updated,
            'source': accounts[0]['id'] if accounts else None,
        }


def sync_learned_rules(new_lines, base_text='', session=None):
    """Push learned features to all configured remote rule stores."""
    result = {'github': False, 'r2': False}
    if not new_lines:
        return result
    merged_text = None
    if github_config_enabled():
        ok, merged = github_merge_and_write(new_lines, session=session)
        result['github'] = ok
        if ok and merged:
            merged_text = merged
    if r2_config_enabled():
        result['r2'] = r2_merge_and_write(
            new_lines,
            merged_text if merged_text is not None else base_text,
            session=session,
        )
    return result


def sync_status():
    channels = []
    if github_config_enabled():
        channels.append('GitHub')
    r2_count = len(_r2_accounts())
    if r2_count:
        channels.append('R2 x' + str(r2_count) if r2_count > 1 else 'R2')
    return '、'.join(channels) or '未配置'
