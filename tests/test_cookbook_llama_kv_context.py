"""Behavioral GGUF/GQA auto-context regressions for #7295 (llama.cpp)."""
import json
import os
import shutil
import struct
import subprocess
import sys

import pytest

from routes.cookbook_helpers import _cached_model_scan_script


def _entry(key, kind, data):
    raw = key.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + struct.pack("<I", kind) + data


def _gguf(layers, kv_heads, key_dim=128, value_dim=128):
    fields = [
        _entry("general.architecture", 8, struct.pack("<Q", 5) + b"qwen2"),
        # A metadata array before architecture fields must not confuse offsets.
        _entry("general.sample", 9, struct.pack("<IQ", 0, 3) + b"abc"),
    ]
    for name, value in [
        ("qwen2.block_count", layers),
        ("qwen2.attention.head_count", 28),
        ("qwen2.attention.head_count_kv", kv_heads),
        ("qwen2.attention.key_length", key_dim),
        ("qwen2.attention.value_length", value_dim),
    ]:
        fields.append(_entry(name, 4, struct.pack("<I", value)))
    return struct.pack("<4sIQQ", b"GGUF", 3, 0, len(fields)) + b"".join(fields)


def test_cached_model_scanner_reads_selected_gguf_attention_layout(tmp_path):
    root = tmp_path / "models"
    for name, data in [
        ("qwen7", _gguf(28, 4)),
        ("qwen14", _gguf(48, 8)),
        ("invalid", b"NOT_A_GGUF"),
    ]:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "model-q6.gguf").write_bytes(data)

    env = os.environ.copy()
    env.update({"HOME": str(tmp_path / "home"), "HF_HOME": str(tmp_path / "empty-hf"),
                "PATH": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, "-"], input=_cached_model_scan_script([str(root)]),
        capture_output=True, text=True, env=env, timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    records = {row["repo_id"]: row for row in json.loads(proc.stdout)}
    assert records["qwen7"]["gguf_files"][0]["kv_bytes_per_token_f16"] == 57344
    assert records["qwen14"]["gguf_files"][0]["kv_bytes_per_token_f16"] == 196608
    assert "kv_bytes_per_token_f16" not in records["invalid"]["gguf_files"][0]


_NODE = r"""
import fs from 'node:fs';
const source = fs.readFileSync('static/js/cookbookServe.js', 'utf8');
function section(start, next) {
  const a = source.indexOf(start);
  const b = source.indexOf(next, a + start.length);
  if (a === -1 || b === -1) throw Error('Cookbook estimator function not found');
  return source.slice(a, b);
}
const kvSource = section('function _llamaKvGbPerToken(', 'function _selectedGgufSizeGb(');
const fitSource = section('function _estimateLlamaContextFit(', 'function _estimateMlxContextFit(');
// Exercise the actual production function bodies; supply only their pure
// collaborators rather than importing the DOM-heavy serve module.
const load = new Function('_runnableGgufFiles', '_modelSizeGb',
  '_modelContextMaxForServe', '_hwfitCache',
  kvSource + fitSource + 'return {kv: _llamaKvGbPerToken, fit: _estimateLlamaContextFit};');
const {kv, fit} = load(
  model => model.gguf_files || [],
  (model, explicit = 0) => Number(explicit || model.size_gb || 0),
  (model, explicit = 0) => Number(explicit || 32768),
  {system: {}}
);
const system = {gpu_vram_gb: 11, gpu_count: 1, gpu_groups: []};
const fields = {backend: 'llamacpp', llama_mode: 'gpu', gpus: '0',
  gguf_file: 'q6.gguf', cache_type: 'f16'};
const seven = {size_gb: 6.2,
  gguf_files: [{rel_path: 'q6.gguf', kv_bytes_per_token_f16: 57344}]};
const unknown = {size_gb: 6.2, gguf_files: [{rel_path: 'q6.gguf'}]};
const tooLarge = {size_gb: 12.2,
  gguf_files: [{rel_path: 'q6.gguf', kv_bytes_per_token_f16: 196608}]};
const twoFiles = {size_gb: 6.2, gguf_files: [
  {rel_path: 'q4.gguf', kv_bytes_per_token_f16: 196608},
  {rel_path: 'q6.gguf', kv_bytes_per_token_f16: 57344}
]};
console.log(JSON.stringify({
  seven: fit(seven, fields, 32768, 0, system),
  unknown: fit(unknown, fields, 32768, 0, system),
  tooLarge: fit(tooLarge, fields, 32768, 0, system),
  selected: kv(twoFiles, 'q6.gguf', 'f16', 6.2),
  q8: kv(seven, 'q6.gguf', 'q8_0', 6.2)
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_auto_context_uses_gqa_kv_and_does_not_recommend_oversized_models():
    proc = subprocess.run(
        ["node", "--input-type=module"], input=_NODE, capture_output=True,
        text=True, cwd=os.path.dirname(os.path.dirname(__file__)), timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["seven"]["ctx"] == 32768
    assert result["seven"]["kvGbPerToken"] * 1024 ** 3 == pytest.approx(57344)
    assert "GGUF metadata" in result["seven"]["reason"]
    assert result["unknown"]["ctx"] < 32768  # Missing metadata keeps fallback.
    assert result["unknown"]["kvGbPerToken"] > result["seven"]["kvGbPerToken"]
    assert result["tooLarge"]["doesNotFit"] is True
    assert result["tooLarge"]["ctx"] == 0  # No false Auto 8192.
    assert result["selected"]["gbPerToken"] * 1024 ** 3 == pytest.approx(57344)
    assert result["q8"]["gbPerToken"] * 1024 ** 3 == pytest.approx(57344 * 17 / 32)
