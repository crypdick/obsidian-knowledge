#!/usr/bin/env python3
"""Deprecated Stop-hook alias for the consolidated capture decision."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib.capture import build_reason, main

__all__ = ["build_reason", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
