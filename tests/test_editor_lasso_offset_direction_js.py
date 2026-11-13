"""Regression for #2125 (lasso item): positive Edge stroke must move the lasso outline outward.

`lassoOffsetPoints(points, grow)` drives the live lasso overlay: the dashed outline
follows the Edge stroke slider and the Feather halo is drawn at `grow + offset`.
Its contract (and the baked mask in `buildLassoMask`) is "positive = expand", but
the normal sign pointed inward in canvas (y-down) space, so the preview shrank
when the slider said Expand and the feather halo was drawn inside the selection.
"""
import json
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LASSO_MODULE = (ROOT / "static/js/editor/tools/lasso-mask.js").as_uri()

SQUARE = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 100}]


def corner_distances(points, grow):
    script = textwrap.dedent(
        f"""
        import {{ lassoOffsetPoints }} from {json.dumps(LASSO_MODULE)};
        const pts = {json.dumps(points)};
        const out = lassoOffsetPoints(pts, {grow});
        console.log(JSON.stringify(out.map(p => Math.hypot(p.x - 50, p.y - 50))));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("winding", ["clockwise", "counter-clockwise"])
def test_positive_grow_expands_outline(winding):
    pts = SQUARE if winding == "clockwise" else SQUARE[::-1]
    base = 50 * 2 ** 0.5
    for d in corner_distances(pts, 10):
        assert d > base, f"grow=+10 moved a {winding} corner inward: {d:.2f} <= {base:.2f}"


@pytest.mark.parametrize("winding", ["clockwise", "counter-clockwise"])
def test_negative_grow_contracts_outline(winding):
    pts = SQUARE if winding == "clockwise" else SQUARE[::-1]
    base = 50 * 2 ** 0.5
    for d in corner_distances(pts, -10):
        assert d < base, f"grow=-10 moved a {winding} corner outward: {d:.2f} >= {base:.2f}"
