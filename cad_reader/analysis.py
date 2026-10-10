"""Small, bounded analysis helpers over serialized entities; no CAD dependency."""

from __future__ import annotations

from collections import defaultdict
import math


def select_entities(data: dict, *, layer=None, types=None, layout="Model",
                    include_inserts=False) -> list[dict]:
    """Select placed scene geometry, including transformed block contents."""
    wanted = set(types) if types is not None else None
    return [e for e in data["scene_entities"]
            if (layout is None or e["layout"] == layout)
            and (layer is None or e["effective_layer"] == layer)
            and (wanted is None or e["type"] in wanted)
            and (include_inserts or e["type"] != "INSERT")]


def query_bounds(data: dict, minimum, maximum, *, layout="Model") -> list[dict]:
    """Return bounding-box candidates; overlaps do not imply physical contact."""
    if len(minimum) != 3 or len(maximum) != 3 or any(a > b for a, b in zip(minimum, maximum)):
        raise ValueError("3차원 minimum <= maximum 경계를 지정하세요.")
    return [e for e in select_entities(data, layout=layout)
            if e.get("bounds") and all(e["bounds"]["max"][i] >= minimum[i]
                                      and e["bounds"]["min"][i] <= maximum[i] for i in range(3))]


def _segments(entities):
    for entity in entities:
        geometry = entity.get("geometry", {})
        if entity["type"] in ("LINE", "ARC") and "start" in geometry and "end" in geometry:
            yield {"entity_id": entity["id"], "layout": entity["layout"],
                   "index": 0, "type": entity["type"], **geometry}
        elif entity["type"] in ("POLYLINE", "LWPOLYLINE"):
            for index, segment in enumerate(geometry.get("segments", [])):
                yield {"entity_id": entity["id"], "layout": entity["layout"], "index": index, **segment}


def endpoint_connections(data: dict, *, tolerance: float = 1e-4, layer=None,
                         layout="Model", max_connections: int = 100_000) -> dict:
    """Find 3D endpoint contacts of lines/arcs/polyline segments, using a grid.

    Tolerance is in drawing units. Different layouts are never connected.
    Curve crossings and near-parallel overlaps require separate algorithms.
    """
    if not math.isfinite(tolerance) or tolerance <= 0 or max_connections < 1:
        raise ValueError("양의 유한 tolerance와 max_connections를 지정하세요.")
    bins, contacts = defaultdict(list), []
    for segment in _segments(select_entities(data, layer=layer, layout=layout)):
        for endpoint in ("start", "end"):
            p = segment[endpoint]
            key = tuple(math.floor(v / tolerance) for v in p)
            node = {"entity_id": segment["entity_id"], "segment_index": segment["index"],
                    "endpoint": endpoint, "point": p, "layout": segment["layout"]}
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for other in bins[(segment["layout"], key[0]+dx, key[1]+dy, key[2]+dz)]:
                            if other["entity_id"] == node["entity_id"]:
                                continue
                            distance = math.dist(p, other["point"])
                            if distance <= tolerance:
                                contacts.append({"a": other, "b": node, "distance": distance})
                                if len(contacts) >= max_connections:
                                    return {"connections": contacts, "truncated": True, "tolerance": tolerance}
            bins[(segment["layout"], *key)].append(node)
    return {"connections": contacts, "truncated": False, "tolerance": tolerance,
            "scope": "LINE/ARC/폴리라인 구간의 끝점만, 3D 거리 비교"}


def line_intersections(data: dict, *, tolerance: float = 1e-6, layer=None,
                       layout="Model", max_pairs: int = 1_000_000) -> dict:
    """Straight segment intersections projected on XY, verified at interpolated Z.

    Includes crossing/end contacts. Collinear overlaps and vertical XY-degenerate
    lines are counted as unresolved candidates rather than reported as misses.
    Quadratic comparison is bounded; filter layer/bounds before large analyses.
    """
    if not math.isfinite(tolerance) or tolerance <= 0 or max_pairs < 1:
        raise ValueError("양의 유한 tolerance와 max_pairs를 지정하세요.")
    segments = [s for s in _segments(select_entities(data, layer=layer, layout=layout)) if s["type"] == "LINE"]
    found, checked, unresolved = [], 0, 0
    for i, a in enumerate(segments):
        for b in segments[i+1:]:
            if a["layout"] != b["layout"] or a["entity_id"] == b["entity_id"]:
                continue
            if checked >= max_pairs:
                return {"intersections": found, "pairs_checked": checked, "truncated": True,
                        "unresolved_parallel_or_degenerate_candidates": unresolved}
            checked += 1
            if any(max(a["start"][k], a["end"][k]) + tolerance < min(b["start"][k], b["end"][k])
                   or max(b["start"][k], b["end"][k]) + tolerance < min(a["start"][k], a["end"][k])
                   for k in range(3)):
                continue
            p, q = a["start"], b["start"]
            r = [a["end"][k] - p[k] for k in range(3)]
            s = [b["end"][k] - q[k] for k in range(3)]
            rlen, slen = math.hypot(*r[:2]), math.hypot(*s[:2])
            determinant = r[0]*s[1] - r[1]*s[0]
            if rlen <= tolerance or slen <= tolerance or abs(determinant) <= 1e-12*rlen*slen:
                unresolved += 1
                continue
            delta = [q[k] - p[k] for k in range(2)]
            t = (delta[0]*s[1] - delta[1]*s[0]) / determinant
            u = (delta[0]*r[1] - delta[1]*r[0]) / determinant
            if -tolerance/rlen <= t <= 1+tolerance/rlen and -tolerance/slen <= u <= 1+tolerance/slen:
                t, u = max(0, min(1, t)), max(0, min(1, u))
                pa = [p[k] + t*r[k] for k in range(3)]
                pb = [q[k] + u*s[k] for k in range(3)]
                if math.dist(pa, pb) <= tolerance:
                    found.append({"a": a["entity_id"], "a_segment": a["index"],
                                  "b": b["entity_id"], "b_segment": b["index"], "point": pa})
    return {"intersections": found, "pairs_checked": checked, "truncated": False,
            "unresolved_parallel_or_degenerate_candidates": unresolved,
            "scope": "직선 구간만. 곡선 교차·공선 중첩·자체 교차는 계산하지 않음"}
