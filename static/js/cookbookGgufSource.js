// GGUF download-source helpers for the Cookbook. Pure (no DOM, no imports) so
// cookbookDownload.js and cookbook-hwfit.js share them and tests run them under node.

function _firstGgufSource(model) {
  const sources = Array.isArray(model?.gguf_sources) ? model.gguf_sources : [];
  return sources.find(src => src && src.repo) || null;
}

function _looksLikeGgufRepo(model) {
  const haystack = `${model?.quant_repo || ''} ${model?.repo_id || ''} ${model?.path || ''} ${model?.name || ''}`.toLowerCase();
  return !!model?.is_gguf || haystack.includes('gguf') || haystack.includes('.gguf');
}

export function _ggufDownloadSource(model, backend) {
  if (backend !== 'llamacpp') return null;
  const source = _firstGgufSource(model);
  if (source) return source;
  if (_looksLikeGgufRepo(model)) {
    const repo = model?.quant_repo || model?.repo_id || model?.name;
    if (repo) return { repo };
  }
  return null;
}

export function _missingGgufMessage(model) {
  const name = model?.name || 'this model';
  if (/\bnvfp4\b/i.test(name)) {
    return `${name} is an NVIDIA NVFP4 checkpoint, not a GGUF download. Pick the base model row with an Unsloth GGUF source, or paste the GGUF repo directly.`;
  }
  return `No GGUF source is configured for ${name}. Pick a model with a GGUF source, or paste the GGUF repo in Download.`;
}

// Panel note for a llama.cpp row that can't be downloaded as listed (#2342),
// so the user sees the fix before clicking Download. Empty when it can.
export function missingGgufNote(model, backend) {
  if (backend !== 'llamacpp' || _ggufDownloadSource(model, backend)) return '';
  return _missingGgufMessage(model);
}
