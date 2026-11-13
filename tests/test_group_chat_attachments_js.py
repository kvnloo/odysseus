"""Group chat must send composer attachments to every participant (#6348).

group.js is driven under `node --input-type=module` with its browser-only
imports swapped for stubs (same approach as
test_copy_message_strips_thinking_js.py); fetch is faked and records each
/api/chat_stream form. Skips when `node` is not installed.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_GROUP = _REPO / "static" / "js" / "group.js"
_APP = _REPO / "static" / "app.js"

_HARNESS = r"""
import fs from 'node:fs';
let src = fs.readFileSync(process.argv[1], 'utf8');
const stubs = `
const _any = new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : k === Symbol.toPrimitive ? () => '' : _any, apply: () => _any });
const uiModule = _any, markdownModule = _any, chatRenderer = _any, spinnerModule = _any;
const providerLogo = () => '', PROMPT_TEMPLATES = [], getUserTemplates = () => [];
const sortModelObjects = (x) => x;
const Storage = { getJSON: (k, d) => d };
`;
src = src.replace(/^import [^\n]*\n/gm, '');
src = stubs + src.replace(/setTimeout\(_initGroupTab, 500\);/, '');

const el = () => ({ appendChild() {}, querySelector: () => el(), querySelectorAll: () => [],
  classList: { add() {}, remove() {}, toggle() {} }, dataset: {}, style: {}, set innerHTML(v) {}, remove() {} });
globalThis.document = { getElementById: () => el(), createElement: () => el(), querySelectorAll: () => [] };
globalThis.window = {};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const streams = [];
let nextId = 0;
globalThis.fetch = async (url, opts = {}) => {
  if (url.endsWith('/api/chat_stream')) {
    streams.push({ session: opts.body.get('session'), attachments: opts.body.get('attachments') });
    return { ok: true, body: { getReader: () => ({ read: async () => ({ done: true }) }) } };
  }
  return { ok: true, json: async () => ({ id: 'sess-' + (nextId++) }) };
};

const mod = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
const models = [{ mid: 'a', display: 'A', url: 'http://a' }, { mid: 'b', display: 'B', url: 'http://b' }];
await mod.startGroup(models, 'parent');
const ids = JSON.parse(process.argv[2]);
await (ids === null ? mod.sendMessage('hi') : mod.sendMessage('hi', ids));
console.log(JSON.stringify(streams));
"""


def _run(ids):
    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")
    r = subprocess.run(["node", "--input-type=module", "-e", _HARNESS, str(_GROUP), json.dumps(ids)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_group_send_forwards_attachment_ids_to_every_participant():
    streams = _run(["att-1", "att-2"])
    assert len(streams) == 2
    for s in streams:
        assert json.loads(s["attachments"] or "null") == ["att-1", "att-2"]


def test_group_send_without_attachments_sends_no_attachments_field():
    streams = _run(None)
    assert len(streams) == 2
    assert all(s["attachments"] is None for s in streams)


def test_app_group_submit_uploads_pending_attachments_before_sending():
    src = _APP.read_text()
    m = re.search(r"if \(groupModule && groupModule\.isActive\(\)\) \{(.*?)\n    \}\n", src, re.S)
    assert m, "group submit branch not found"
    branch = m.group(1)
    assert "fileHandlerModule.uploadPending(" in branch
    assert re.search(r"groupModule\.sendMessage\(msg, \w+\)", branch)
    assert branch.index("uploadPending(") < branch.index("groupModule.sendMessage(")
