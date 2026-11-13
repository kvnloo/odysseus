"""Regression for #2829: a download task's ⋮ menu must survive its own log scrolling.

The menu is fixed-positioned, so it closes on scroll. It listened in the capture
phase on window, which also sees scroll events from any inner scroller. A running
download appends output and pins its log to the bottom on every poll, so the menu
closed a moment after it opened. Only scrolls that move the ⋮ button (the page or
one of its ancestors) should close it.

Runs the real static/js modules in headless Chromium with the API stubbed.
"""
import json
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://cookbook.test'
TASK = {
    'sessionId': 'odysseus-dl-test', 'name': 'Qwen/Qwen3-0.6B', 'type': 'download', 'status': 'running',
    'payload': {'repo_id': 'Qwen/Qwen3-0.6B'},
    'output': '\n'.join(f'Downloading shard {i}' for i in range(200)),
}
PAGE = """<html><body>
<div id="cookbook-modal" style="height:600px;overflow:auto"><div class="cookbook-body">
  <div class="cookbook-tabs"></div></div></div>
</body></html>"""

OPEN_MENU = """async (task) => {
  window.fetch = async () => new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}});
  localStorage.setItem('cookbook-tasks', JSON.stringify([{...task, startedAt: Date.now()}]));
  await import('/static/js/cookbook.js');  // the app's entry point; it wires cookbookRunning.js
  const m = await import('/static/js/cookbookRunning.js');
  m._renderRunningTab();
  const card = document.querySelector('.cookbook-task[data-task-id="' + task.sessionId + '"]');
  card.querySelector('.cookbook-task-menu-btn').click();
  await new Promise(r => setTimeout(r, 50));
  return !!document.querySelector('.cookbook-task-dropdown');
}"""

SCROLL = """async (target) => {
  const el = target === 'log'
    ? document.querySelector('.cookbook-output-pre')
    : document.getElementById('cookbook-modal');
  el.style.maxHeight = '120px'; el.style.overflow = 'auto';
  el.scrollTop = el.scrollHeight;
  await new Promise(r => setTimeout(r, 100));
  return !!document.querySelector('.cookbook-task-dropdown');
}"""


@pytest.fixture
def page():
    if sync_playwright is None:
        pytest.skip('playwright not installed')
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=['--no-sandbox'])
        except Exception as exc:  # browser binaries missing
            pytest.skip(f'chromium unavailable: {exc}')
        page = browser.new_page(viewport={'width': 1200, 'height': 800})

        def serve(route):
            relative = route.request.url.split(ORIGIN + '/', 1)[1].split('?', 1)[0]
            if not relative:
                route.fulfill(body=PAGE, content_type='text/html')
            elif (ROOT / relative).is_file():
                route.fulfill(path=str(ROOT / relative))
            else:
                route.fulfill(status=404, body='Not found')

        page.route(ORIGIN + '/**', serve)
        page.goto(ORIGIN + '/')
        yield page
        browser.close()


def test_menu_stays_open_when_the_task_log_scrolls(page):
    assert page.evaluate(OPEN_MENU, TASK)
    assert page.evaluate(SCROLL, 'log'), 'the ⋮ menu closed when only the task log scrolled'


def test_menu_still_closes_when_its_button_scrolls_away(page):
    assert page.evaluate(OPEN_MENU, TASK)
    assert not page.evaluate(SCROLL, 'container'), 'the ⋮ menu stayed open after its button moved'
