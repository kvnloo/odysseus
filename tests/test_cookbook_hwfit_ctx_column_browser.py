"""Regression for #3098: the Cookbook Ctx column must say when it is not the model's max.

Each row is estimated at the Ctx filter target (or less when memory is tight),
so the same model and quant shows 8k with the filter at 8k and 32k at Max. The
cell gave no hint, so it read as two different models. When the shown context is
below the model's own max, the cell now carries a marker class and a tooltip
with both numbers; at the model's max it stays plain.

Runs the real static/js modules in headless Chromium with the API stubbed.
"""
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://hwfit.test'
ROW = {'name': 'Qwen/QwQ-32B', 'quant': 'Q4_K_M', 'fit_level': 'good', 'run_mode': 'gpu',
       'params_b': 32.8, 'required_gb': 20.1, 'speed_tps': 30.2, 'score': 80.1, 'context_length': 32768}

RENDER = """async (rows) => {
  window.fetch = async () => new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}});
  await import('/static/js/cookbook.js');
  const m = await import('/static/js/cookbook-hwfit.js');
  const el = document.getElementById('list');
  m._hwfitRenderList(el, rows);
  return [...el.querySelectorAll('.hwfit-row:not(.hwfit-header) .hwfit-c-ctx')].map(c => ({
    text: c.textContent, capped: c.classList.contains('hwfit-ctx-capped'), title: c.getAttribute('title') || '',
  }));
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
        page = browser.new_page()

        def serve(route):
            relative = route.request.url.split(ORIGIN + '/', 1)[1].split('?', 1)[0]
            if not relative:
                route.fulfill(body='<html><body><div id="list"></div></body></html>', content_type='text/html')
            elif (ROOT / relative).is_file():
                route.fulfill(path=str(ROOT / relative))
            else:
                route.fulfill(status=404, body='Not found')

        page.route(ORIGIN + '/**', serve)
        page.goto(ORIGIN + '/')
        yield page
        browser.close()


def test_ctx_below_model_max_is_marked_with_both_numbers(page):
    (cell,) = page.evaluate(RENDER, [{**ROW, 'context': 8192, 'target_context': 8192}])
    assert cell['text'] == '8k'
    assert cell['capped'], cell
    assert '8k' in cell['title'] and '32k' in cell['title'], cell


def test_ctx_at_model_max_stays_plain(page):
    (cell,) = page.evaluate(RENDER, [{**ROW, 'context': 32768}])
    assert cell == {'text': '32k', 'capped': False, 'title': ''}
