#!/usr/bin/env python3
"""Backward-compatibility shim for legacy tooling.

All package metadata lives in pyproject.toml; the version's single source of
truth is riverpod_3_scanner/__init__.py (read via tool.setuptools.dynamic).
This file intentionally declares nothing.
"""

from setuptools import setup

setup()
