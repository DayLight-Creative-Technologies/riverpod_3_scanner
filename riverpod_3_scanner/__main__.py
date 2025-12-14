"""
Command-line interface for Riverpod 3.0 Safety Scanner

Allows running the scanner as a module:
    python -m riverpod_3_scanner lib
"""

from .scanner import main

if __name__ == "__main__":
    main()
