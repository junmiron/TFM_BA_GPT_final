"""Split a long Mermaid flowchart into page-sized fragments.

A process flowchart taller than one A4 page is sliced into one fragment per
stage subgraph. Every edge that crosses a fragment boundary becomes a pair of
dark flag-shaped off-page connector nodes ("Ref A: to part 3 - ..." on the
source side, "Ref A: from part 1 - ..." on the target side) with matching Ref
letters, so the reader can follow the flow between pages instead of seeing a
severed line.

A stage that is still taller than one page after the split is subdivided by
topological rank bands until every fragment fits. Fragments that cannot be
subdivided further make the attempt fail, and the caller falls back to the
quiet-row PNG banding in typst_render.

Pure stdlib, deterministic, no rendering: the caller measures fragments with
mmdc and hands the heights to `fit_fragments` as a callback.
"""
from __future__ import annotations

import re
import string
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

_NODE = r"([A-Za-z_][A-Za-z0-9_]*)"
_DECL = (
    r'(?:\[\s*"[^"]*"\s*\]|\{\{\s*"[^"]*"\s*\}\}|\{\s*"[^"]*"\s*\}'
    r"|\(\s*\[\s*\"[^\"]*\"\s*\]\s*\)|@\{\s*shape:\s*[a-z]+,\s*label:\s*\"[^\"]*\"\s*\})"
)
_SUBGRAPH_RE = re.compile(
    r"^\s*subgraph\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[\s*\"([^\"]*)\"\s*\])?\s*$")
_EDGE_RE = re.compile(
    rf"^\s*{_NODE}({_DECL})?\s*"
    r"(?:-->\s*\|([^|]*)\||--\s*\"([^\"]*)\"\s*-->|-->|-\.->|--\.->|==>)\s*"
    rf"{_NODE}({_DECL})?\s*$")
_NODE_DECL_RE = re.compile(rf"^\s*{_NODE}({_DECL})\s*$")
_DIRECTION_RE = re.compile(r"^\s*direction\s+(TD|LR|RL|BT)\s*$")


def _ref_letter(index: int) -> str:
    """Connector reference letters: A..Z then AA..ZZ."""
    if index < 26:
        return string.ascii_uppercase[index]
    return "A" + string.ascii_uppercase[index - 26]


class Graph:
    """Nodes, edges and stage subgraphs of one Mermaid flowchart."""

    def __init__(self) -> None:
        self.decls: OrderedDict[str, Optional[str]] = OrderedDict()  # id -> label decl
        self.edges: List[Tuple[str, str, str]] = []  # (src, label, dst)
        self.titles: Dict[str, str] = {}            # subgraph id -> title
        self.order: List[str] = []                  # subgraph ids, document order
        self.group_of: Dict[str, str] = {}          # node -> stage that declared it
        self.class_defs: List[str] = []
        self.class_asgs: List[Tuple[List[str], str]] = []

    def label_of(self, node: str) -> str:
        decl = self.decls.get(node) or ""
        match = re.search(r'"([^"]*)"', decl)
        return match.group(1) if match else node


def parse_flowchart(source: str) -> Optional[Graph]:
    """Parse a flowchart. Returns None for anything that is not a clean,
    single, line-based flowchart (sequence/state diagrams, multi-line labels,
    unexpected syntax), so the caller can fall back to banding."""
    if not re.search(r"^\s*flowchart\b", source, re.M):
        return None
    graph = Graph()
    stack: List[str] = []

    def declare(node: str, decl: Optional[str]) -> None:
        if decl:
            graph.decls[node] = decl
        else:
            graph.decls.setdefault(node, None)
        if stack and node not in graph.group_of:
            graph.group_of[node] = stack[-1]

    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if re.match(r"^(flowchart|graph)\b", stripped):
            continue
        match = _SUBGRAPH_RE.match(stripped)
        if match:
            stack.append(match.group(1))
            if match.group(1) not in graph.titles:
                graph.order.append(match.group(1))
            graph.titles[match.group(1)] = match.group(2) or match.group(1)
            continue
        if stripped == "end":
            if stack:
                stack.pop()
            continue
        if re.match(r"^flowchart\b", stripped):
            continue
        if _DIRECTION_RE.match(stripped):
            continue
        if stripped.startswith("classDef"):
            graph.class_defs.append(stripped)
            continue
        if stripped.startswith("class "):
            parts = stripped.split()
            if len(parts) == 3:
                graph.class_asgs.append((parts[1].split(","), parts[2]))
            continue
        match = _EDGE_RE.match(stripped)
        if match:
            src, decl_a, lab1, lab2, dst, decl_b = (
                match.group(1), match.group(2), match.group(3),
                match.group(4), match.group(5), match.group(6))
            declare(src, decl_a)
            declare(dst, decl_b)
            graph.edges.append((src, (lab1 or lab2 or "").strip(), dst))
            continue
        match = _NODE_DECL_RE.match(stripped)
        if match:
            declare(match.group(1), match.group(2))
            continue
        return None  # anything else: bail to the banding fallback

    if not graph.decls:
        return None
    return graph


def assign_groups(graph: Graph) -> List[List[str]]:
    """One node list per stage, in document order.

    Nodes declared inside a subgraph belong to it. Nodes outside any stage
    (notifications, the cancellation branch) inherit the stage of their
    nearest upstream assigned node, propagating until stable. Anything still
    unassigned joins the first stage."""
    group_of = dict(graph.group_of)
    for _ in range(len(graph.decls) + 1):  # fixed-point propagation
        changed = False
        for src, _, dst in graph.edges:
            if src in group_of and dst not in group_of:
                group_of[dst] = group_of[src]
                changed = True
        if not changed:
            break
    fallback = graph.order[0]
    members: Dict[str, List[str]] = {gid: [] for gid in graph.order}
    for node in graph.decls:
        gid = group_of.get(node, fallback)
        members.setdefault(gid, []).append(node)
    return [members[gid] for gid in graph.order if members.get(gid)]


def ranks(graph: Graph, nodes: List[str]) -> Dict[str, int]:
    """BFS depth of every node within the fragment (0 for fragment roots).
    Edges leaving the fragment are ignored, so ranks describe only the
    internal layout."""
    inside = set(nodes)
    children: Dict[str, List[str]] = {}
    indeg: Dict[str, int] = {n: 0 for n in inside}
    for src, _, dst in graph.edges:
        if src in inside and dst in inside:
            children.setdefault(src, []).append(dst)
            indeg[dst] += 1
    depth: Dict[str, int] = {}
    queue = [n for n in nodes if indeg[n] == 0] or list(nodes[:1])
    for n in queue:
        depth[n] = 0
    while queue:
        node = queue.pop(0)
        for child in children.get(node, []):
            if child not in depth:
                depth[child] = depth[node] + 1
                queue.append(child)
    for node in nodes:
        depth.setdefault(node, 0)
    return depth


def split_group_by_rank(graph: Graph, nodes: List[str], parts: int) -> List[List[str]]:
    """Partition a stage into `parts` contiguous rank bands, keeping whole
    depth levels together so a band never bisects a decision fork."""
    if parts <= 1 or len(nodes) < 2:
        return [nodes]
    depth = ranks(graph, nodes)
    by_depth: Dict[int, List[str]] = {}
    for node in nodes:
        by_depth.setdefault(depth[node], []).append(node)
    bands: List[List[str]] = []
    remaining = len(nodes)
    for level in sorted(by_depth):
        band = by_depth[level]
        target = max(1, remaining // max(1, parts - len(bands)))
        if bands and len(bands[-1]) + len(band) <= target:
            bands[-1].extend(band)
        else:
            bands.append(list(band))
        remaining -= len(band)
    if len(bands) < 2:
        half = len(nodes) // 2
        if half:
            bands = [nodes[:half], nodes[half:]]
    return bands


def _short(label: str, limit: int = 30) -> str:
    label = label.strip()
    return label if len(label) <= limit else label[: limit - 1] + "\u2026"


def build_fragments(graph: Graph, groups: List[List[str]]) -> List[str]:
    """Emit one valid Mermaid source per fragment, replacing cross-fragment
    edges with paired flag-shaped off-page connectors (A, B, C, ...)."""
    frag_of: Dict[str, int] = {}
    for index, nodes in enumerate(groups):
        for node in nodes:
            frag_of[node] = index

    cross: List[Tuple[int, str, str, str, int, int]] = []
    internal: List[List[Tuple[str, str, str]]] = [[] for _ in groups]
    for order, (src, label, dst) in enumerate(graph.edges):
        fi, fj = frag_of[src], frag_of[dst]
        if fi == fj:
            internal[fi].append((src, label, dst))
        else:
            cross.append((order, src, label, dst, fi, fj))
    cross.sort(key=lambda c: (c[4], c[5]))
    letter_of = {entry[0]: _ref_letter(i) for i, entry in enumerate(cross)}

    def stage_title(index: int) -> str:
        for node in groups[index]:
            gid = graph.group_of.get(node)
            if gid:
                return graph.titles.get(gid, gid)
        return f"Part {index + 1}"

    fragments: List[str] = []
    for index, nodes in enumerate(groups):
        inside = set(nodes)
        outs = [e for e in cross if e[4] == index]
        ins = [e for e in cross if e[5] == index]
        lines = [f"%% Part {index + 1} of {len(groups)} - {stage_title(index)}"]
        lines.append("flowchart TD")
        for node in nodes:
            decl = graph.decls.get(node)
            if decl:
                lines.append(f"    {node}{decl}")
        for order, src, label, dst, fi, fj in outs:
            letter = letter_of[order]
            lines.append(
                f'    OUT_{letter}@{{ shape: flag, label: '
                f'"Ref {letter}: to part {fj + 1} ({_short(graph.label_of(dst))})" }}')
        for order, src, label, dst, fi, fj in ins:
            letter = letter_of[order]
            lines.append(
                f'    IN_{letter}@{{ shape: flag, label: '
                f'"Ref {letter}: from part {fi + 1} ({_short(graph.label_of(src))})" }}')
        lines.append("")

        def fmt(src: str, label: str, dst: str) -> str:
            return f'    {src} -- "{label}" --> {dst}' if label else f"    {src} --> {dst}"

        for src, label, dst in internal[index]:
            lines.append(fmt(src, label, dst))
        for order, src, label, dst, fi, fj in outs:
            lines.append(fmt(src, label, f"OUT_{letter_of[order]}"))
        for order, src, label, dst, fi, fj in ins:
            lines.append(fmt(f"IN_{letter_of[order]}", "", dst))
        if outs or ins:
            lines.append("")
            lines.append("    classDef offpage fill:#374151,stroke:#1f2937,"
                         "stroke-width:1.5px,color:#ffffff")
            conns = sorted({f"OUT_{letter_of[e[0]]}" for e in outs}
                           | {f"IN_{letter_of[e[0]]}" for e in ins})
            lines.append(f"    class {','.join(conns)} offpage")
        for ids, cls in graph.class_asgs:
            keep = [n for n in ids if n in inside]
            if keep:
                lines.append(f"    class {','.join(keep)} {cls}")
        for definition in graph.class_defs:
            lines.append("    " + definition)
        fragments.append("\n".join(lines) + "\n")
    return fragments


def split_flowchart(source: str) -> Optional[List[str]]:
    """Stage split only (no height measurement). None if not splittable."""
    graph = parse_flowchart(source)
    if graph is None:
        return None
    groups = assign_groups(graph)
    if len(groups) < 2:
        return None
    return build_fragments(graph, groups)


def fragment_titles(source: str) -> List[str]:
    """Human-readable stage title per fragment, for figure captions."""
    graph = parse_flowchart(source)
    if graph is None:
        return []
    groups = assign_groups(graph)
    titles = []
    for nodes in groups:
        for node in nodes:
            gid = graph.group_of.get(node)
            if gid:
                titles.append(graph.titles.get(gid, gid))
                break
        else:
            titles.append(f"Part {len(titles) + 1}")
    return titles


def fit_fragments(source: str, measure: Callable[[str], float],
                  max_height_pt: float, max_fragments: int = 24) -> Optional[List[str]]:
    """Split until every fragment fits, using `measure(mmd_text) -> height_pt`.

    Stages taller than the page are subdivided by rank bands and the whole
    set is rebuilt with fresh connector letters. Returns the fragment sources
    (at least two), or None if the diagram cannot be split into fitting
    fragments - then the caller falls back to banding."""
    result = split_for_render(source, measure, max_height_pt)
    return result.fragments if result else None


def titles_for(graph: Graph, groups: List[List[str]]) -> List[str]:
    """Stage title per fragment, in fragment order."""
    titles = []
    for nodes in groups:
        for node in nodes:
            gid = graph.group_of.get(node)
            if gid:
                titles.append(graph.titles.get(gid, gid))
                break
        else:
            titles.append(f"Part {len(titles) + 1}")
    return titles


def refs_for(graph: Graph, groups: List[List[str]]) -> List[Tuple[str, int, int]]:
    """Connector summary matching the letters emitted by build_fragments:
    (Ref letter, source part, target part)."""
    frag_of = {node: index for index, nodes in enumerate(groups) for node in nodes}
    cross = sorted(((order, frag_of[src], frag_of[dst])
                    for order, (src, _, dst) in enumerate(graph.edges)
                    if frag_of[src] != frag_of[dst]),
                   key=lambda c: (c[1], c[2]))
    return [(_ref_letter(i), fi + 1, fj + 1)
            for i, (_, fi, fj) in enumerate(cross)]


class SplitResult:
    """Fragments, titles and connector refs from one successful split."""

    def __init__(self, fragments: List[str], titles: List[str],
                 refs: List[Tuple[str, int, int]]) -> None:
        self.fragments = fragments
        self.titles = titles
        self.refs = refs

    def __len__(self) -> int:
        return len(self.fragments)


def split_for_render(source: str, measure: Callable[[str], float],
                     max_height_pt: float, min_scale: float = 0.55,
                     max_parts: int = 24) -> Optional[SplitResult]:
    """One-call entry point for the renderer.

    `measure(mmd_text)` returns the fragment's rendered height when placed at
    full content width. A fragment is acceptable when it fits the page at 100%
    or can be scaled down to at least `min_scale` without making labels
    unreadable (the existing banding already renders diagrams near that scale).
    Returns a SplitResult (fragments, titles, refs) when the diagram can be
    split into acceptable fragments, else None (caller falls back to banding).
    """
    graph = parse_flowchart(source)
    if graph is None:
        return None
    groups = assign_groups(graph)
    if len(groups) < 2:
        return None
    def _group_title(nodes, index):
        for node in nodes:
            gid = graph.group_of.get(node)
            if gid:
                return graph.titles.get(gid, gid)
        return f"Part {index + 1}"

    titles = [_group_title(grp, i) for i, grp in enumerate(groups)]
    hard_limit = max_height_pt / min_scale
    for _ in range(8):
        fragments = build_fragments(graph, groups)
        heights = [measure(frag) for frag in fragments]
        unfit = [i for i, h in enumerate(heights) if h > hard_limit]
        if not unfit:
            return SplitResult(fragments, titles, refs_for(graph, groups))
        if len(groups) >= max_parts:
            return None
        rebuilt: List[List[str]] = []
        rebuilt_titles: List[str] = []
        for index, nodes in enumerate(groups):
            if index not in unfit:
                rebuilt.append(nodes)
                rebuilt_titles.append(titles[index])
                continue
            parts = int(heights[index] // max_height_pt) + 1
            bands = split_group_by_rank(graph, nodes, parts)
            if len(bands) < 2:
                return None  # unsplittable fragment too tall: band instead
            # Greedily re-pack adjacent bands that still fit together, so parts
            # are as close to a full page as the rank structure allows.
            merged = [bands[0]]
            for j, band in enumerate(bands[1:], start=1):
                candidate = merged[-1] + band
                probe_groups = (groups[:index] + merged[:-1] + [candidate]
                                + groups[index + 1:] + bands[j + 1:])
                probe = build_fragments(graph, probe_groups)[index]
                if measure(probe) <= hard_limit:
                    merged[-1] = candidate
                else:
                    merged.append(band)
            rebuilt.extend(merged)
            rebuilt_titles.extend([titles[index]] * len(merged))
        if len(rebuilt) == len(groups):
            return None
        groups, titles = rebuilt, rebuilt_titles
    return None


def _titles_from_sources(fragments: List[str]) -> List[str]:
    titles = []
    for frag in fragments:
        match = re.search(r"^%% Part \d+ of \d+ - (.*)$", frag, re.M)
        titles.append(match.group(1) if match else f"Part {len(titles) + 1}")
    return titles


def _refs_from_fragments(fragments: List[str]) -> List[Tuple[str, int, int]]:
    refs = []
    seen: Dict[str, Tuple[int, int]] = {}
    for index, frag in enumerate(fragments):
        for match in re.finditer(r"OUT_([A-Z0-9]+)@\{ shape: flag, label: "
                                 rf"\"Ref \1: to part (\d+)", frag):
            seen.setdefault(match.group(1), (index + 1, int(match.group(2))))
    refs = sorted((letter, fi, fj) for letter, (fi, fj) in seen.items())
    return refs
