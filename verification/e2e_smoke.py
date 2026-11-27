"""
verification/e2e_smoke.py — Opt-in live Playwright E2E smoke test (@pytest.mark.slow).

Run once the full Compose stack is up (`docker compose up -d --build`):
    pip install playwright && playwright install chromium
    FINSIGHT_E2E_URL=http://localhost:5173 pytest verification/e2e_smoke.py -m slow -v

Use http://localhost:8080 for the production Compose stack.
"""

from __future__ import annotations

import os
import re

import pytest


@pytest.mark.slow
def test_live_workspace_e2e_smoke():
    sync_api = pytest.importorskip("playwright.sync_api")
    base_url = os.getenv("FINSIGHT_E2E_URL", "http://localhost:5173").rstrip("/")
    username = os.getenv("FINSIGHT_E2E_USER", "admin")
    password = os.getenv("FINSIGHT_E2E_PASSWORD", "admin123")

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(f"{base_url}/login", wait_until="networkidle")
            page.get_by_label("Username", exact=True).fill(username)
            # exact=True: the "Show password" toggle also matches a loose /password/ label.
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).click()
            page.wait_for_url("**/chat", timeout=20000)

            prompt_box = page.get_by_label("Ask your AI assistant")
            prompt_box.fill("Hello FinSight")
            prompt_box.press("Enter")
            page.get_by_text(re.compile(r"FinSight", re.I)).first.wait_for(timeout=15000)

            page.goto(f"{base_url}/evaluation", wait_until="networkidle")
            page.get_by_role("tab", name=re.compile(r"Audit & Observability", re.I)).click()
            page.get_by_text(re.compile(r"Immutable Compliance Audit Trail", re.I)).wait_for(
                timeout=10000
            )
        finally:
            context.close()
            browser.close()
