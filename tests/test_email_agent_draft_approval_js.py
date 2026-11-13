"""Agent email drafts must be reachable and approvable from the UI (#5884).

With ``agent_email_confirm`` on (the default), ``send_email`` stages the
message as an ``agent_draft`` row and nothing else ever sends it: the only way
out is ``POST /api/email/pending/{id}/approve``. Email > Scheduled is where
queued sends already live, so it must list those drafts with Approve/Discard.

The test runs the shipped ``_loadScheduled`` in Chromium with the email API
routed, so it exercises the real rendering and the real request it sends.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = ROOT / "static" / "js" / "emailLibrary" / "index.js"


def _load_scheduled_source():
    source = INDEX_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadScheduled(grid, sp)")
    end = source.index("\nfunction _emailDateBucketLabel(", start)
    return source[start:end]


def _run(scenario):
    script = r"""
      import { chromium } from 'playwright';
      const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
      const scenario = JSON.parse(process.env.SCENARIO);
      const browser = await chromium.launch({ headless: true });
      const requests = [];
      try {
        const page = await browser.newPage();
        await page.route('**/api/email/**', async route => {
          const req = route.request();
          const url = new URL(req.url());
          requests.push({ method: req.method(), path: url.pathname });
          if (url.pathname === '/api/email/scheduled') return route.fulfill({ json: { scheduled: scenario.scheduled } });
          if (url.pathname === '/api/email/pending') return route.fulfill({ json: { pending: scenario.pending } });
          return route.fulfill({ json: { success: true } });
        });
        await page.goto(origin + '/static/css/00-tokens.css');
        await page.setContent('<div id="email-lib-stats"></div><div id="grid"></div>');
        const pageErrors = [];
        page.on('pageerror', e => pageErrors.push(String(e)));
        await page.addScriptTag({ content: `
          const API_BASE = '';
          const _esc = s => String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
          const _setEmailSyncStatus = () => {};
          window.__reloads = 0;
          const _loadEmails = () => { window.__reloads++; };
          ${process.env.LOAD_SCHEDULED}
          window._loadScheduled = _loadScheduled;
        ` });
        await page.evaluate(() => window._loadScheduled(document.getElementById('grid'), null));
        const out = {
          text: await page.locator('#grid').innerText(),
          stats: await page.locator('#email-lib-stats').innerText(),
          approveButtons: await page.locator('#grid [data-agent-draft-action="approve"]').count(),
        };
        if (out.approveButtons) {
          await page.locator('#grid [data-agent-draft-action="approve"]').first().click();
          await page.waitForFunction(() => window.__reloads > 0, null, { timeout: 5000 }).catch(() => {});
        }
        out.reloads = await page.evaluate(() => window.__reloads);
        out.requests = requests;
        out.pageErrors = pageErrors;
        console.log(JSON.stringify(out));
      } finally { await browser.close(); }
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=90,
        env={**os.environ, "SCENARIO": json.dumps(scenario), "LOAD_SCHEDULED": _load_scheduled_source()},
    )
    assert result.returncode == 0, result.stderr[-1500:]
    return json.loads(result.stdout.strip().splitlines()[-1])


DRAFT = {
    "id": "a1b2c3d4e5f60718", "to_addr": "pat@example.com", "subject": "Quarterly numbers",
    "body": "Hi Pat,\nNumbers attached.\nThanks,", "created_at": "2026-11-13T20:00:00", "account_id": None,
}

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is required for the Chromium check")


def test_scheduled_view_lists_agent_draft_awaiting_approval():
    out = _run({"scheduled": [], "pending": [DRAFT]})
    assert out["pageErrors"] == []
    assert {"method": "GET", "path": "/api/email/pending"} in out["requests"]
    assert "Quarterly numbers" in out["text"]
    assert "pat@example.com" in out["text"]
    assert "No scheduled emails" not in out["text"]
    assert out["approveButtons"] == 1


def test_approve_sends_the_draft_through_the_approve_endpoint():
    out = _run({"scheduled": [], "pending": [DRAFT]})
    assert {"method": "POST", "path": f"/api/email/pending/{DRAFT['id']}/approve"} in out["requests"]
    assert out["reloads"] == 1


def test_scheduled_view_without_drafts_is_unchanged():
    scheduled = [{"id": "s1", "to": "lee@example.com", "subject": "Later", "send_at": "2026-11-20T09:00:00",
                  "status": "pending", "error": None}]
    out = _run({"scheduled": scheduled, "pending": []})
    assert out["pageErrors"] == []
    assert "Later" in out["text"]
    assert out["approveButtons"] == 0
    assert out["stats"] == "1 scheduled"
