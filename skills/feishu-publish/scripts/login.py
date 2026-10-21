#!/usr/bin/env python3
"""Compatibility entry for the standalone skill's login command."""
import sys
from publish import main

if __name__ == "__main__":
    sys.exit(main(["login", *sys.argv[1:]]))
