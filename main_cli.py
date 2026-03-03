#!/usr/bin/env python3
"""
KnowEmail - Terminal-only Email Verifier
Entry point for CLI version

This is a terminal-only version of KnowEmail that provides the same
functionality as the GUI version without requiring PyQt5.

Usage:
    python main_cli.py                           # Interactive mode
    python main_cli.py -e user@example.com       # Single email
    python main_cli.py -f emails.txt             # Bulk from file
    python main_cli.py -f emails.txt -o out.csv  # Bulk with export
"""

import sys
import os

# Add the current directory to the path so we can import from lib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.cli import main

if __name__ == '__main__':
    main()
