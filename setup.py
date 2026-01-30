#!/usr/bin/env python3
"""
Setup configuration for Riverpod 3.0 Safety Scanner

This file provides backward compatibility for older pip versions.
Modern installations should use pyproject.toml.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

setup(
    name="riverpod-3-scanner",
    version="1.3.0",
    author="Steven Day",
    author_email="support@daylightcreative.tech",
    description="Comprehensive static analysis tool for detecting Riverpod 3.0 async safety violations in Flutter/Dart projects",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner",
    project_urls={
        "Documentation": "https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/GUIDE.md",
        "Source": "https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner",
        "Issues": "https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/issues",
        "Changelog": "https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/CHANGELOG.md",
    },
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: Console",
    ],
    python_requires=">=3.7",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "riverpod-3-scanner=riverpod_3_scanner.scanner:main",
        ],
    },
    keywords=[
        "riverpod",
        "flutter",
        "dart",
        "static-analysis",
        "linter",
        "code-quality",
        "async-safety",
        "riverpod-3",
        "safety-checker",
    ],
    include_package_data=True,
)
