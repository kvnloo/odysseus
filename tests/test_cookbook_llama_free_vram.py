"""Selected-GPU free-VRAM context estimator regression for #7295."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


_NODE = r"""
import fs from 'node:fs';
const source = fs.readFileSync('static/js/cookbookServe.js', 'utf8');
function section(start, next) {
  const a = source.indexOf(start);
  const b = source.indexOf(next, a + start.length);
  if (a < 0 || b < 0) throw Error('Production estimator not found');
  return source.slice(a, b);
}
const kv = section('function _llamaKvGbPerToken(', 'function _selectedGgufSizeGb(');
const estimator = section('function _estimateLlamaContextFit(', 'function _estimateMlxContextFit(');
const fit = new Function('_runnableGgufFiles', '_modelSizeGb',
  '_modelContextMaxForServe', '_hwfitCache',
  kv + estimator + 'return _estimateLlamaContextFit;')(
    m => m.gguf_files || [],
    (m, explicit = 0) => Number(explicit || m.size_gb || 0),
    (m, explicit = 0) => Number(explicit || 32768),
    {system: {}}
  );
const model = {size_gb: 6.2, gguf_files: [
  {rel_path: 'q6.gguf', kv_bytes_per_token_f16: 57344}
]};
const fields = {backend: 'llamacpp', llama_mode: 'gpu',
  gpus: '1', host: '', gguf_file: 'q6.gguf', cache_type: 'f16'};
const gpu = (index, free_mb) => ({index, free_mb, total_mb: 11264});
const base = {gpu_vram_gb: 11, gpu_count: 2, gpu_groups: []};
const system = (gpus, host = '') => ({...base, gpu_live: {host, gpus}});
const busy = gpu(0, 512);
const free = gpu(1, 10240);
const estimate = (f, sys) => fit(model, f, 32768, 0, sys);
console.log(JSON.stringify({
  selected: estimate(fields, system([busy, free])),
  busy: estimate({...fields, gpus: '0'}, system([busy, free])),
  zero: estimate(fields, system([busy, gpu(1, 0)])),
  multi: estimate({...fields, gpus: '0,1'}, system([busy, free])),
  missing: estimate({...fields, gpus: '2'}, system([busy, free])),
  invalid: estimate(fields, system([busy, gpu(1, 'n/a')])),
  staleHost: estimate({...fields, host: 'remote'}, system([busy, free])),
  unprobed: estimate(fields, base),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_llama_auto_context_uses_selected_gpu_live_free_memory():
    proc = subprocess.run(
        ["node", "--input-type=module"], input=_NODE, text=True,
        capture_output=True, cwd=Path(__file__).resolve().parents[1],
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    cases = json.loads(proc.stdout)
    assert cases["selected"]["ctx"] == 32768
    assert "selected GPU live free VRAM" in cases["selected"]["reason"]
    assert cases["busy"]["doesNotFit"] is True
    assert cases["busy"]["ctx"] == 0
    assert cases["zero"]["doesNotFit"] is True
    assert cases["zero"]["ctx"] == 0
    assert cases["multi"]["ctx"] == 32768
    assert cases["missing"]["needsHardwareScan"] is True
    assert "ctx" not in cases["missing"]
    assert cases["invalid"]["needsHardwareScan"] is True
    assert "ctx" not in cases["invalid"]
    assert cases["staleHost"]["ctx"] == 32768
    assert "total VRAM estimate" in cases["staleHost"]["reason"]
    assert cases["unprobed"]["ctx"] == 32768
    assert "total VRAM estimate" in cases["unprobed"]["reason"]
