#!/usr/bin/env python3
"""The Venture Machine v5. Usage: python vm.py help"""
import sys

from vm.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ("help", "-h", "--help"):
        sys.argv = [sys.argv[0], "--help"]
    main()
