"""Regression for issue #2342: an auto-discovered model with no `gguf_sources`
is listed as llama.cpp-ready in "What Fits?", but the only hint that it can't
be downloaded is the error toast after clicking Download.

The expanded row now shows the same actionable message up front. The GGUF
source helpers live in cookbookGgufSource.js, a pure module, so they run under
node here (cookbookDownload.js pulls in browser-only modules and can't load).
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HWFIT = _REPO / "static/js/cookbook-hwfit.js"


@pytest.fixture(scope="module")
def node_available():
    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")


def _notes() -> dict:
    script = textwrap.dedent("""
        const { missingGgufNote } = await import('./static/js/cookbookGgufSource.js');
        const discovered = { name: 'Alibaba-NLP/Tongyi-DeepResearch-30B-A3B', quant: 'Q4_K_M', _discovered: true };
        const withSource = { ...discovered, gguf_sources: [{ repo: 'unsloth/Tongyi-DeepResearch-30B-A3B-GGUF' }] };
        const ggufRepo = { name: 'bartowski/Qwen3-8B-GGUF', quant: 'Q4_K_M' };
        console.log(JSON.stringify({
          discovered: missingGgufNote(discovered, 'llamacpp'),
          withSource: missingGgufNote(withSource, 'llamacpp'),
          ggufRepo: missingGgufNote(ggufRepo, 'llamacpp'),
          vllm: missingGgufNote(discovered, 'vllm'),
        }));
    """)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO, capture_output=True, timeout=15, text=True,
    )
    assert res.returncode == 0, f"node failed:\n{res.stderr}"
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_llamacpp_row_without_gguf_source_gets_the_download_hint(node_available):
    note = _notes()["discovered"]
    assert "No GGUF source is configured for Alibaba-NLP/Tongyi-DeepResearch-30B-A3B" in note
    assert "paste the GGUF repo in Download" in note


def test_rows_that_can_download_get_no_hint(node_available):
    out = _notes()
    assert out["withSource"] == ""
    assert out["ggufRepo"] == ""
    assert out["vllm"] == ""


def test_expanded_row_renders_the_hint():
    src = _HWFIT.read_text(encoding="utf-8")
    body = src.split("export function _expandModelRow", 1)[1].split("row.insertAdjacentHTML", 1)[0]
    assert "missingGgufNote(modelData, backend)" in body
