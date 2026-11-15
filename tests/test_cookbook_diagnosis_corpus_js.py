"""Runs the Cookbook diagnosis corpus (tests/cookbookDiagnosisCorpus.test.mjs, #7287) under pytest.

Behavior lives in the node:test file; this wrapper only exists so the Node suite runs in the normal pytest job.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_cookbook_diagnosis_corpus():
    result = subprocess.run(
        ["node", "--test", "tests/cookbookDiagnosisCorpus.test.mjs"],
        cwd=_REPO,
        capture_output=True,
        timeout=60,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"node --test failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
