// Diagnosis Bingo (#7287): run real error excerpts from public issues through
// the shipped `_diagnose` and score which ERROR_PATTERNS entry wins.
//
// cookbook-diagnosis.js imports browser-only modules (cookbook.js, ui.js,
// spinner.js). Those imports are stubbed with a resolve hook; `_diagnose` and
// `ERROR_PATTERNS` themselves run unchanged.
//
// Each fixture records its current outcome in index.json (`baseline`) and the
// message of the entry that wins today (`baseline_message`, null for none):
//   correct  - the expected entry wins (or no entry, when none is expected)
//   wrong    - some other entry wins (worse than no diagnosis)
//   none     - nothing matches although a diagnosis is expected
// The test fails when either changes, so a pattern fix updates the
// baseline in the same PR and the score in the output moves with it.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import test from 'node:test';

const STUBS = {
  './cookbook.js': `export const _envState = {};
    export function _loadTasks() {} export function _removeTask() {}
    export function _launchServeTask() {} export function _buildEnvPrefix() { return ''; }
    export function _sshCmd() { return ''; } export function _setPanelField() {}
    export function _setPanelCheckbox() {} export function _copyText() {}
    export function _persistEnvState() {} export function _tmuxCmd() { return ''; }
    export function _serveAutoRetry() {} export function _serveAutoRetryReplace() {}
    export function _serveAutoRetryRemove() {} export function _serveAutoFix() {}`,
  './ui.js': 'export default { showToast() {} };',
  './spinner.js': 'export default {};',
};

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (context.parentURL?.includes('/static/js/cookbook-diagnosis.js')) {
      const stub = STUBS[specifier.split('?')[0]];
      if (stub !== undefined) {
        return { url: `data:text/javascript,${encodeURIComponent(stub)}`, shortCircuit: true };
      }
    }
    return nextResolve(specifier, context);
  },
});

const { _diagnose } = await import('../static/js/cookbook-diagnosis.js');
const DIR = new URL('./fixtures/cookbook_diagnosis/', import.meta.url);
const index = JSON.parse(readFileSync(new URL('index.json', DIR), 'utf8'));

function outcome(fixture, hit) {
  const got = hit ? hit.message : null;
  if (!fixture.gap && got === fixture.expected_message) return 'correct';
  if (got === null) return 'none';
  return 'wrong';
}

test('Diagnosis Bingo: every fixture keeps its recorded outcome', () => {
  const score = { correct: 0, wrong: 0, none: 0 };
  const changed = [];
  for (const fixture of index) {
    const text = readFileSync(new URL(fixture.file, DIR), 'utf8');
    const hit = _diagnose(text);
    const result = outcome(fixture, hit);
    score[result] += 1;
    console.log(`#${fixture.source_issue} ${fixture.file}: ${result}` +
      (hit ? ` <- "${hit.message.slice(0, 80)}"` : ''));
    const got = hit ? hit.message : null;
    if (result !== fixture.baseline || got !== fixture.baseline_message) {
      changed.push(`${fixture.file}: ${fixture.baseline} -> ${result} (${got?.slice(0, 60) ?? 'no entry'})`);
    }
  }
  console.log(`Diagnosis Bingo: ${score.correct}/${index.length} correct, ` +
    `${score.wrong} wrong, ${score.none} none`);
  assert.deepEqual(changed, [], 'outcome changed; update `baseline` in index.json');
});

test('every fixture file is indexed with a source issue', () => {
  for (const fixture of index) {
    assert.ok(Number.isInteger(fixture.source_issue), fixture.file);
    assert.ok(['correct', 'wrong', 'none'].includes(fixture.baseline), fixture.file);
    readFileSync(new URL(fixture.file, DIR), 'utf8');
  }
});
