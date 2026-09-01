# -*- coding: utf-8 -*-
"""Shared environment variable helpers."""


def env_bool(value, default=False):
    if value is None or value == '':
        return default
    return str(value).lower() in ('1', 'true', 'yes', 'on')


def env_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
