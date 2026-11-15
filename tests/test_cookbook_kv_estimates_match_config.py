"""KV-cache estimates should match the model's attention layout (#7286).

Cookbook estimates KV-cache memory in four places. For a model whose config is
known, each should agree with the size derived from that config:
2 (K and V) x num_hidden_layers x num_key_value_heads x head_dim x bytes per element.

Qwen3-8B (https://huggingface.co/Qwen/Qwen3-8B/blob/main/config.json):
36 layers, 8 KV heads, head_dim 128 -> 147,456 bytes per token at f16/bf16.
The default cache type is f16 for llama.cpp and the model dtype (bf16) for vLLM.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.hwfit.models import estimate_memory_gb
from services.hwfit.profiles import _kv_gb

_REPO = Path(__file__).resolve().parent.parent

QWEN3_8B_CONFIG = {"num_hidden_layers": 36, "num_key_value_heads": 8, "head_dim": 128}
CONFIG_KV_BYTES_F16 = 2 * 36 * 8 * 128 * 2  # 147,456 bytes = 147.456 KB per token
QWEN3_8B = {"name": "Qwen/Qwen3-8B", "parameter_count": "8.19B", **QWEN3_8B_CONFIG}
WEIGHTS_GB = 8.19 * 0.58  # Q4_K_M
TOLERANCE = 0.10

# Runs the two non-exported serve-panel estimators from static/js/cookbookServe.js
# with its browser imports stubbed, and prints kvGbPerToken for each case.
_NODE = r"""
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
globalThis.document = { addEventListener() {} };
globalThis.window = globalThis;
const SERVE = new URL('static/js/cookbookServe.js', `file://${process.cwd()}/`).href;
registerHooks({
  resolve(specifier, context, next) {
    if (context.parentURL === SERVE && specifier.startsWith('./')) {
      return { url: `stub:${specifier}`, shortCircuit: true };
    }
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url.startsWith('stub:')) {
      return { format: 'module', shortCircuit: true, source: STUB };
    }
    if (url === SERVE) {
      const source = readFileSync(new URL(url), 'utf8')
        + '\nexport { _estimateVllmContextFit, _estimateLlamaContextFit };\n';
      return { format: 'module', shortCircuit: true, source };
    }
    return next(url, context);
  },
});
const { _estimateVllmContextFit: vllm, _estimateLlamaContextFit: llama } = await import(SERVE);
const [model, weightsGb] = JSON.parse(process.argv[1]);
const sys = { gpu_vram_gb: 24, gpu_count: 1 };
console.log(JSON.stringify({
  vllm_auto: vllm(model, { gpus: '0' }, 40960, weightsGb, sys).kvGbPerToken,
  llama_blank: llama(model, { backend: 'llamacpp', gpus: '0' }, 40960, weightsGb, sys).kvGbPerToken,
  llama_f16: llama(model, { backend: 'llamacpp', gpus: '0', cache_type: 'f16' }, 40960, weightsGb, sys).kvGbPerToken,
}));
"""
_STUB = """const noop = () => {}; const proxy = new Proxy(noop, { get: () => proxy, apply: () => proxy });
export default proxy; export const bindMenuDismiss = noop, dismissOrRemove = noop,
bindExpandedCardDismiss = noop, unbindExpandedCardDismiss = noop, providerLogo = noop,
modelColor = noop, openCookbookDependencies = noop, _hwfitCache = null, topPortalZ = noop;"""


def _js_estimates():
    script = _NODE.replace("source: STUB", f"source: {json.dumps(_STUB)}")
    model = {"repo_id": "Qwen/Qwen3-8B", "quant": "Q4_K_M", **QWEN3_8B_CONFIG}
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps([model, WEIGHTS_GB])],
        cwd=_REPO, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _hwfit_card_bytes():
    gb = estimate_memory_gb(QWEN3_8B, "Q4_K_M", 1000) - estimate_memory_gb(QWEN3_8B, "Q4_K_M", 0)
    return gb / 1000 * 1e9


def _profile_f16_bytes():
    return _kv_gb(QWEN3_8B, 1, "f16") * 1e9


PY_CASES = {
    "services/hwfit/models.py estimate_memory_gb (HW Fit card)": _hwfit_card_bytes,
    "services/hwfit/profiles.py _kv_gb f16 (llama.cpp profiles)": _profile_f16_bytes,
}
JS_CASES = {
    "cookbookServe.js vLLM auto context (kv dtype auto)": "vllm_auto",
    "cookbookServe.js llama.cpp auto context (cache type blank = f16)": "llama_blank",
    "cookbookServe.js llama.cpp auto context (cache type f16)": "llama_f16",
}


def _assert_close(label, got_bytes):
    ratio = got_bytes / CONFIG_KV_BYTES_F16
    assert abs(ratio - 1) <= TOLERANCE, (
        f"{label}: {got_bytes / 1000:.1f} KB/token vs {CONFIG_KV_BYTES_F16 / 1000:.3f} KB/token "
        f"from config.json ({ratio:.2f}x)"
    )


def test_config_kv_reference_value():
    assert CONFIG_KV_BYTES_F16 == 147_456


@pytest.mark.parametrize("label", list(PY_CASES))
def test_python_kv_estimate_matches_config(label):
    _assert_close(label, PY_CASES[label]())


@pytest.mark.skipif(shutil.which("node") is None, reason="node binary not on PATH")
@pytest.mark.parametrize("label", list(JS_CASES))
def test_serve_panel_kv_estimate_matches_config(label):
    _assert_close(label, _js_estimates()[JS_CASES[label]] * 1e9)
