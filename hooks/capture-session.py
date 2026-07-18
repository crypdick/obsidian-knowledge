#!/usr/bin/env python3
"""Stop hook: make one selective durable-knowledge capture decision."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib.capture import build_reason, main

__all__ = ["build_reason", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
