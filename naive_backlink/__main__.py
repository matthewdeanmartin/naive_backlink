# Allows the package to be run as a script using `python -m naive_backlink`

from __future__ import annotations

import asyncio
import sys

from naive_backlink.cli import main

if __name__ == "__main__":
    sys.exit(main())
