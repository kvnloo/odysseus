"""Regression: canceling a device import must release its temporary file input."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent

_NODE_CASE = r"""
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(process.env.ODY_IMPORT_MODULE, 'utf8');
const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const { _importFromDevice } = await import(moduleUrl);

const inputs = [];
class FilePicker {
  constructor() {
    this.style = {};
    this.files = [];
    this.handlers = new Map();
    this.attached = false;
  }
  addEventListener(event, listener) {
    const listeners = this.handlers.get(event) || [];
    listeners.push(listener);
    this.handlers.set(event, listeners);
  }
  click() {}
  remove() { this.attached = false; }
  async dispatch(event) {
    for (const listener of this.handlers.get(event) || []) {
      await listener({ type: event, target: this });
    }
  }
}

globalThis.document = {
  createElement(tag) {
    assert.equal(tag, 'input');
    return new FilePicker();
  },
  body: {
    appendChild(node) {
      assert.equal(node.attached, false);
      node.attached = true;
      inputs.push(node);
    },
  },
};

_importFromDevice();
assert.equal(inputs.length, 1, 'one temporary file picker must be mounted');
const picker = inputs[0];
assert.equal(picker.attached, true);
await picker.dispatch(process.env.ODY_FILE_EVENT);
assert.equal(
  picker.attached,
  false,
  'cancelled or empty selection must release the temporary file input',
);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
@pytest.mark.parametrize(
    "source_path",
    [
        "frontend/src/features/documents/ui/importFromDevice.js",
        "static/js/document/ui/importFromDevice.js",
    ],
)
@pytest.mark.parametrize("file_event", ["cancel", "change"])
def test_cancelled_device_import_removes_file_input(source_path, file_event):
    env = os.environ.copy()
    env["ODY_IMPORT_MODULE"] = str(ROOT / source_path)
    env["ODY_FILE_EVENT"] = file_event
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=_NODE_CASE,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, (
        f"{source_path}: {file_event} failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
