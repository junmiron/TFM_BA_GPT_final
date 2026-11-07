"""Graph-aware Mermaid splitting for tall process diagrams.

The splitter turns each stage subgraph into its own numbered part, replacing
cross-stage edges with paired off-page connector flags, so no node box is ever
sliced by a page boundary. These tests exercise the pure logic (no mmdc) and
the renderer wiring with a stubbed fragment measurer.

Run with:  python -m pytest -q tests/test_diagram_split.py
"""

import importlib.util
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPLIT = PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "diagram_split.py"
TYPST_RENDER = PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "typst_render.py"


def _load(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FLOW = """flowchart TD
    subgraph S1["Stage 1 - Ordering (FR-001..FR-003)"]
        A1["Place order"] --> A2{"Address valid?"}
        A2 -- "Yes" --> A3["Schedule pickup"]
    end
    subgraph S2["Stage 2 - Collection (FR-004..FR-006)"]
        B1["Driver assigned"] --> B2["Collected"]
    end
    subgraph S3["Stage 3 - Processing (FR-007..FR-009)"]
        C1["Washed"] --> C2["Delivered"]
    end
    A3 --> B1
    B2 --> C1
    C2 --> A1
"""


def test_parse_flowchart_accepts_flowcharts_and_rejects_other_types():
    mod = _load("diagram_split_parse", SPLIT)
    graph = mod.parse_flowchart(FLOW)
    assert graph is not None
    assert len(graph.decls) == 7
    assert len(graph.edges) == 7
    assert "Stage 1 - Ordering (FR-001..FR-003)" in graph.titles["S1"]
    assert mod.parse_flowchart("sequenceDiagram\nA->B: hi") is None
    assert mod.split_flowchart("graph LR\nA --> B") is None  # single group, unsplittable


def test_assign_groups_covers_every_node_exactly_once():
    mod = _load("diagram_split_groups", SPLIT)
    graph = mod.parse_flowchart(FLOW)
    groups = mod.assign_groups(graph)
    assert len(groups) == 3
    seen = [n for group in groups for n in group]
    assert sorted(seen) == sorted(graph.decls)


def test_stage_split_replaces_cross_edges_with_connector_pairs():
    mod = _load("diagram_split_build", SPLIT)
    graph = mod.parse_flowchart(FLOW)
    groups = mod.assign_groups(graph)
    fragments = mod.build_fragments(graph, groups)
    assert len(fragments) == 3

    # Every real node appears exactly once across all fragments.
    real = []
    for frag in fragments:
        parsed = mod.parse_flowchart(frag)
        real.extend(n for n in parsed.decls if not n.startswith(("OUT_", "IN_")))
    assert sorted(real) == sorted(graph.decls), "nodes duplicated or lost"

    # Each of the three cross-stage edges became exactly one OUT and one IN stub.
    for frag in fragments:
        outs = set(re.findall(r"OUT_([A-Z]+)", frag))
        ins = set(re.findall(r"IN_([A-Z]+)", frag))
        assert outs and ins, "cross-stage edges were not flagged"
    refs = mod.refs_for(graph, groups)
    assert len(refs) == 3
    assert all(1 <= frm <= 3 and 1 <= to <= 3 for _, frm, to in refs)


def test_split_for_render_splits_tall_stages_and_fits_page():
    mod = _load("diagram_split_fit", SPLIT)
    max_band = 666.0

    def measure(frag):
        # rank bands are tall: force every stage to be split
        parsed = mod.parse_flowchart(frag)
        return len(parsed.decls) * 300.0

    result = mod.split_for_render(FLOW, measure, max_band, min_scale=0.5, max_parts=24)
    assert result is not None and len(result) >= 3
    for frag in result.fragments:
        assert measure(frag) <= max_band / 0.5, "accepted fragment exceeds the hard limit"


def test_split_for_render_returns_none_when_unsplittable():
    mod = _load("diagram_split_none", SPLIT)

    def measure(frag):
        return 10000.0  # nothing ever fits

    result = mod.split_for_render(FLOW, measure, 666.0, min_scale=0.5, max_parts=4)
    assert result is None


def test_ref_letters_extend_past_z():
    mod = _load("diagram_split_letters", SPLIT)
    assert mod._ref_letter(0) == "A"
    assert mod._ref_letter(25) == "Z"
    assert mod._ref_letter(26) == "AA"


def test_renderer_wires_split_into_fit_diagram_images(tmp_path):
    """With a .clean.mmd next to a tall PNG, _fit_diagram_images must emit
    numbered SVG parts plus a connector index instead of band PNGs."""
    mod = _load("typst_render_split", TYPST_RENDER)
    session = tmp_path / "sess-split"
    session.mkdir()

    from PIL import Image
    Image.new("RGB", (600, 2400), "white").save(session / "process_diagram.png")
    (session / "process_diagram.clean.mmd").write_text(FLOW, encoding="utf-8")

    def stub_render(mmd_text, out_path):
        out_path.write_text("<svg viewBox=\"0 0 100 100\"></svg>", encoding="utf-8")
        return (100.0, 100.0)

    # Stub only the mmdc call: fragments stay small enough to accept.
    original = mod._render_fragment_svg
    mod._render_fragment_svg = stub_render
    try:
        md = "![Process Diagram](process_diagram.png){ width=95% }"
        fixed = mod._fit_diagram_images(md, session)
    finally:
        mod._render_fragment_svg = original

    parts = re.findall(r"\((process_diagram_part_[0-9a-f]+\.svg)\)", fixed)
    assert len(parts) >= 2, "graph split did not fire"
    assert "Cross-part connectors" in fixed
    assert "| Ref | Continues | Appears as |" in fixed
    assert not list(session.glob("process_diagram_band*")), "stale bands must not be produced"
    manifest = session / "process_diagram_parts.json"
    assert manifest.is_file(), "fragment manifest was not written"

    # A second render with an unchanged source must reuse the cached manifest.
    def failing_render(mmd_text, out_path):
        raise AssertionError("cache miss: mmdc should not be called again")
    mod._render_fragment_svg = failing_render
    try:
        fixed2 = mod._fit_diagram_images(md, session)
    finally:
        mod._render_fragment_svg = original
    assert fixed2 == fixed


@pytest.mark.skipif(not __import__("shutil").which("mmdc"),
                    reason="mermaid-cli (mmdc) not installed")
def test_real_mmdc_render_produces_vector_labels():
    """End-to-end sanity check against the installed mermaid-cli: fragments
    render with native <text> labels (no foreignObject), which Typst keeps as
    selectable PDF text."""
    split = _load("diagram_split_mmdc", SPLIT)
    mod = _load("typst_render_mmdc", TYPST_RENDER)
    graph = split.parse_flowchart(FLOW)
    frag = split.build_fragments(graph, split.assign_groups(graph))[0]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / "frag.svg"
        size = mod._render_fragment_svg(frag, svg)
        assert size and size[0] > 0 and size[1] > 0
        text = svg.read_text(encoding="utf-8")
        assert "foreignObject" not in text, "labels should be native SVG text"
        assert "<text" in text
