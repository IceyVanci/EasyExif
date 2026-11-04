"""Module entry point: delegate to launch.main."""
from __future__ import annotations

from .launch import main

if __name__ == "__main__":
    raise SystemExit(main())
