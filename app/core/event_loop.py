"""
app/core/event_loop.py — Ensure asyncio uses SelectorEventLoop on Windows for psycopg v3.
"""

import asyncio
import sys


def ensure_selector_event_loop() -> None:
    """Switch Windows asyncio policy to SelectorEventLoop so psycopg AsyncConnection works."""
    if sys.platform == "win32":
        policy = asyncio.get_event_loop_policy()
        if not isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
