"""Isolated conversion, extraction, provenance and completeness reporting."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .environment import ODA_URL, find_oda


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_drawing(filename: str | Path, *, oda_path: str | Path | None = None,
                    max_depth: int = 32, max_scene_entities: int = 500_000) -> dict:
    """Return JSON-compatible dictionaries. No source save/repair is performed.

    DWG conversion is restricted to a temporary copy. Layouts and block definitions
    are retained; scene_entities expands INSERTs in the containing layout's WCS.
    Xrefs are inventoried, never implicitly loaded or bound.
    """
    try:
        import ezdxf
        from ezdxf.addons import odafc
    except ImportError as exc:
        raise RuntimeError("ezdxf 설치가 필요합니다. cad_reader/requirements.txt를 설치하세요.") from exc
    if max_depth < 1 or max_scene_entities < 1:
        raise ValueError("max_depth와 max_scene_entities는 양수여야 합니다.")
    source = Path(filename).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in (".dwg", ".dxf"):
        raise ValueError("DWG 또는 DXF 파일을 지정하세요.")
    before = _sha256(source)
    converter = None
    if source.suffix.lower() == ".dwg":
        converter = find_oda(oda_path)
        if converter is None:
            raise RuntimeError(f"ODA File Converter가 설치되지 않았습니다. {ODA_URL} 에서 Windows x64 버전을 설치하세요. --oda로 실행 파일 경로를 지정할 수 있습니다.")
        option = "win_exec_path" if os.name == "nt" else "unix_exec_path"
        previous = ezdxf.options.get("odafc-addon", option)
        # odafc's configuration is process-global: concurrent calls need separate processes.
        try:
            ezdxf.options.set("odafc-addon", option, str(converter))
            with tempfile.TemporaryDirectory(prefix="cad-reader-") as temporary:
                copy = Path(temporary) / "input.dwg"
                shutil.copyfile(source, copy)
                if _sha256(copy) != before:
                    raise RuntimeError("원본이 복사 중 변경되었습니다. 도면 저장을 마친 뒤 다시 실행하세요.")
                doc = odafc.readfile(copy, version="R2018", audit=False)
        finally:
            ezdxf.options.set("odafc-addon", option, previous)
    else:
        doc = ezdxf.readfile(source)
    result = extract_document(doc, source=source, max_depth=max_depth,
                              max_scene_entities=max_scene_entities)
    after = _sha256(source)
    result["source"] = {
        "path": str(source), "format": source.suffix[1:].upper(),
        "sha256_before": before, "sha256_after": after, "original_unchanged": before == after,
        "conversion": {"engine": "ODA File Converter" if converter else None,
                       "executable": str(converter) if converter else None,
                       "temporary_copy": bool(converter), "target_version": "R2018" if converter else None,
                       "audit_repair": False},
    }
    if before != after:
        result["warnings"].append({"code": "SOURCE_CHANGED", "message": "원본 해시가 달라졌습니다. 외부 프로그램의 저장 여부를 확인하세요."})
    if converter:
        result["warnings"].append({"code": "CONVERSION_LOSS_NOT_VERIFIABLE", "message": "변환된 DXF에서 확인되는 객체만 조사했습니다. DWG에만 존재하는 사용자 정의 데이터의 변환 누락은 ezdxf만으로 완전히 검증할 수 없습니다."})
    return result


def extract_document(doc, *, source: Path, max_depth: int = 32,
                     max_scene_entities: int = 500_000) -> dict:
    import ezdxf
    from ezdxf import units
    from .geometry import entity_geometry, entity_bounds, json_value

    warnings, definitions, layouts, scene, references = [], [], [], [], []
    all_records = []
    issues = Counter()

    def warn(code, message, **details):
        warnings.append({"code": code, "message": message, **details})

    def record(entity, identity, coordinate_system, inherited_layer=None, track=True):
        kind = entity.dxftype()
        layer = entity.dxf.get("layer", "0")
        entry = {"id": identity, "handle": entity.dxf.get("handle", None),
                 "type": kind, "layer": layer,
                 "effective_layer": inherited_layer if layer == "0" and inherited_layer else layer,
                 "coordinate_system": coordinate_system,
                 "dxf": json_value(entity.dxf.all_existing_dxf_attribs())}
        try:
            entry["geometry"], entry["support"] = entity_geometry(entity)
        except Exception as exc:
            entry.update(geometry={}, support="failed")
            warn("EXTRACTION_FAILED", str(exc), entity_id=identity, type=kind)
        if entry["support"] in ("unsupported", "partial"):
            issues[f"{kind}:{entry['support']}"] += 1
            if track:
                warn("UNSUPPORTED_GEOMETRY" if entry["support"] == "unsupported" else "PARTIAL_GEOMETRY",
                     "원시 속성은 보존했으나 전체 기하학 해석은 지원하지 않습니다.", entity_id=identity, type=kind)
        try:
            entry["bounds"] = entity_bounds(entity) if entry["support"] == "full" else None
        except Exception as exc:
            entry["bounds"] = None
            warn("BOUNDS_FAILED", str(exc), entity_id=identity)
        if entity.xdata is not None:
            entry["xdata"] = {name: [{"code": tag.code, "value": json_value(tag.value)}
                                      for tag in entity.get_xdata(name)]
                              for name in entity.xdata.data}
        if getattr(entity, "xtags", None) is not None:
            entry["raw_tags"] = [{"code": tag.code, "value": json_value(tag.value)}
                                 for subclass in entity.xtags.subclasses for tag in subclass]
        if track:
            all_records.append(entry)
        return entry

    insunits = int(doc.header.get("$INSUNITS", 0))
    unit_name = units.unit_name(insunits)
    try:
        meters_per_unit = units.conversion_factor(insunits, units.M) if insunits else None
    except (ValueError, TypeError):
        meters_per_unit = None
    if meters_per_unit is None:
        warn("UNITS_UNKNOWN", "$INSUNITS가 없거나 유효하지 않습니다. mm/m를 임의로 가정하지 않습니다.")
    layers = [{"name": layer.dxf.name, "dxf": json_value(layer.dxf.all_existing_dxf_attribs()),
               "off": layer.is_off(), "frozen": layer.is_frozen(), "locked": layer.is_locked()}
              for layer in doc.layers]
    for layout in doc.layouts:
        records = [record(e, f"layout:{layout.name}/{e.dxf.handle}", "layout_wcs") for e in layout]
        layouts.append({"name": layout.name, "is_modelspace": layout.name == "Model",
                        "entities": records})
    layout_handles = {layout.block_record_handle for layout in doc.layouts}
    xref_names = set()
    for block in doc.blocks:
        if block.block_record.dxf.handle in layout_handles:
            continue
        name = block.name
        flags = block.block.dxf.get("flags", 0)
        is_xref = bool(flags & (4 | 8))
        records = [record(e, f"block:{name}/{e.dxf.handle}", "block_local_wcs") for e in block]
        definitions.append({"name": name, "base_point": json_value(block.block.dxf.base_point),
                            "flags": flags, "is_xref": is_xref,
                            "xref_path": block.block.dxf.get("xref_path", ""),
                            "units": block.block_record.dxf.get("units", 0), "entities": records})
        if is_xref:
            xref_names.add(name.casefold())
            raw = block.block.dxf.get("xref_path", "")
            ref = _external_reference(raw, source, "xref", name)
            ref.update(overlay=bool(flags & 8), loaded_by_reader=False,
                       embedded_entity_count=len(records))
            references.append(ref)
            warn("XREF_NOT_LOADED", "외부 참조 파일의 실제 내용은 자동으로 읽지 않습니다. 파일 존재 여부와 경로를 확인하세요.",
                 block=name, path=raw, exists=ref["exists"])

    # Attach each flattened entity to its root layout entity and INSERT ancestry.
    scene_by_root = defaultdict(list)
    truncated = False

    def walk(entity, root_id, layout_name, ancestry=(), inherited_layer=None,
             block_stack=(), identity=None):
        nonlocal truncated
        if len(scene) >= max_scene_entities:
            if not truncated:
                warn("SCENE_LIMIT", "객체 수 상한으로 블록 확장을 중단했습니다. 원본 레이아웃·블록 정의는 보존됩니다.", limit=max_scene_entities)
            truncated = True
            return
        identity = identity or root_id
        entry = record(entity, identity, "layout_wcs", inherited_layer, track=False)
        source_entity = getattr(entity, "source_of_copy", None)
        entry.update(root_entity_id=root_id, layout=layout_name,
                     parent_insert_id=ancestry[-1] if ancestry else None,
                     insert_ancestry=list(ancestry),
                     definition_handle=source_entity.dxf.get("handle", None) if source_entity else entry["handle"])
        scene.append(entry)
        scene_by_root[root_id].append(identity)
        if entity.dxftype() != "INSERT":
            return
        name = entity.dxf.name
        scale = [abs(entity.dxf.get(k, 1)) for k in ("xscale", "yscale", "zscale")]
        if max(scale) - min(scale) > 1e-9:
            warn("NONUNIFORM_BLOCK_SCALE", "비균일 축척 블록입니다. 문자 변환은 부정확할 수 있으며 지원되지 않는 변환은 별도로 보고됩니다.", entity_id=identity)
        if name.casefold() in xref_names:
            entry["expansion_status"] = "xref_not_loaded"
            return
        if name.casefold() in block_stack or len(ancestry) >= max_depth:
            entry["expansion_status"] = "cycle_or_depth_limit"
            warn("BLOCK_RECURSION_LIMIT", "순환 참조 또는 깊이 제한으로 블록 확장을 중단했습니다.", entity_id=identity, block=name)
            return
        if entity.block() is None:
            entry["expansion_status"] = "missing_definition"
            warn("MISSING_BLOCK", "블록 정의가 없습니다.", entity_id=identity, block=name)
            return
        if entity.has_extension_dict:
            dictionary = entity.get_extension_dict()
            if "ACAD_FILTER" in dictionary:
                warn("XCLIP_NOT_APPLIED", "블록의 XCLIP 경계를 적용하지 않았습니다. 경계 밖 객체도 분석에 포함됩니다.", entity_id=identity)

        skipped = []
        def skipped_callback(child, reason):
            skipped.append({"handle": child.dxf.get("handle", None), "type": child.dxftype(), "reason": reason})
        try:
            # Each MINSERT cell has its own transform and ancestry; definitions stay intact.
            if entity.mcount > 1:
                entry["expansion_status"] = "array"
                for index, cell in enumerate(entity.multi_insert()):
                    walk(cell, root_id, layout_name, ancestry + (identity,), entry["effective_layer"],
                         block_stack, f"{identity}/cell:{index}")
            else:
                entry["expansion_status"] = "expanded"
                for index, child in enumerate(entity.virtual_entities(skipped_entity_callback=skipped_callback)):
                    walk(child, root_id, layout_name, ancestry + (identity,), entry["effective_layer"],
                         block_stack + (name.casefold(),), f"{identity}/child:{index}")
                # Attached attributes have already been placed in the containing layout WCS.
                for index, attribute in enumerate(entity.attribs):
                    walk(attribute, root_id, layout_name, ancestry + (identity,), entry["effective_layer"],
                         block_stack, f"{identity}/attribute:{index}")
        except Exception as exc:
            entry["expansion_status"] = "failed"
            warn("BLOCK_EXPANSION_FAILED", str(exc), entity_id=identity, block=name)
        if skipped:
            entry["skipped_entities"] = skipped
            warn("BLOCK_ENTITIES_SKIPPED", "블록 변환 중 일부 객체가 생략되었습니다. 블록 정의에서 원본 속성을 확인하세요.", entity_id=identity, skipped=skipped)

    for layout in doc.layouts:
        for entity in layout:
            walk(entity, f"layout:{layout.name}/{entity.dxf.handle}", layout.name)
    for obj in doc.objects:
        kind = obj.dxftype()
        if kind in ("IMAGEDEF", "PDFDEFINITION", "DWFDEFINITION", "DGNDEFINITION"):
            raw = obj.dxf.get("filename", "")
            references.append(_external_reference(raw, source, kind, obj.dxf.handle))
            warn("EXTERNAL_ASSET_NOT_LOADED", "외부 이미지·언더레이 내용은 분석하지 않습니다.", type=kind, path=raw)
        elif kind == "ACAD_PROXY_OBJECT":
            warn("PROXY_OBJECT", "프록시 OBJECTS 데이터의 의미를 해석하지 못합니다.", handle=obj.dxf.handle)

    # Graphical entities outside layouts/blocks are inventoried rather than silently lost.
    recorded = {r["handle"] for r in all_records}
    orphaned = []
    from ezdxf.entities import DXFGraphic
    for entity in doc.entitydb.values():
        if (entity.is_alive and isinstance(entity, DXFGraphic)
                and entity.dxf.handle not in recorded
                and entity.dxftype() not in ("VERTEX", "ATTRIB", "SEQEND", "BLOCK", "ENDBLK")):
            orphaned.append(record(entity, f"unplaced:{entity.dxf.handle}", "unknown"))
    if orphaned:
        warn("UNPLACED_ENTITIES", "레이아웃·블록에 배치되지 않은 그래픽 객체가 있습니다.", count=len(orphaned))
    entities_by_layer, entities_by_type = defaultdict(list), defaultdict(list)
    for item in scene:
        entities_by_layer[item["effective_layer"]].append(item["id"])
        entities_by_type[item["type"]].append(item["id"])
    for name in entities_by_layer:
        if name.casefold() not in {layer["name"].casefold() for layer in layers}:
            warn("MISSING_LAYER", "객체가 참조하는 레이어 정의가 없습니다.", layer=name)
    warn("DISPLAY_LIMITATIONS", "BYBLOCK 색상·선종류, 뷰포트·주석 축척, 글꼴 렌더링은 재현하지 않습니다. 텍스트 경계는 근삿값이며 레이어 off/frozen 객체도 포함됩니다.")
    return {
        "schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "ezdxf_version": ezdxf.__version__, "dxf_version": doc.dxfversion,
        "units": {"insunits": insunits, "name": unit_name, "meters_per_drawing_unit": meters_per_unit,
                  "header": {key: json_value(doc.header.get(key)) for key in
                             ("$INSUNITS", "$MEASUREMENT", "$LUNITS", "$LUPREC", "$AUNITS", "$AUPREC", "$INSBASE", "$UCSORG", "$UCSXDIR", "$UCSYDIR")},
                  "coordinate_policy": "길이·좌표는 원래 도면 단위. geometry는 해당 레이아웃/블록 WCS, dxf는 원시 OCS/WCS 혼합 속성. 자동 단위 환산 없음."},
        "layers": layers, "layouts": layouts, "blocks": definitions,
        "scene_entities": scene, "unplaced_entities": orphaned, "external_references": references,
        "tables": {"dimension_styles": [json_value(v.dxf.all_existing_dxf_attribs()) for v in doc.dimstyles],
                   "text_styles": [json_value(v.dxf.all_existing_dxf_attribs()) for v in doc.styles]},
        "relationships": {"entities_by_layer": dict(entities_by_layer), "entities_by_type": dict(entities_by_type),
                          "scene_entities_by_root": dict(scene_by_root)},
        "coverage": {"layout_entity_count": sum(len(v["entities"]) for v in layouts),
                     "block_definition_entity_count": sum(len(v["entities"]) for v in definitions),
                     "scene_entity_count": len(scene), "scene_truncated": truncated,
                     "source_entity_types": dict(Counter(v["type"] for v in all_records)),
                     "scene_entity_types": dict(Counter(v["type"] for v in scene)),
                     "support_issues": dict(issues),
                     "full_dwg_fidelity_verified": False,
                     "object_section_types": dict(Counter(v.dxftype() for v in doc.objects)),
                     "classes": [json_value(v.dxf.all_existing_dxf_attribs()) for v in doc.classes]},
        "warnings": warnings,
    }


def _external_reference(raw: str, source: Path, kind: str, identifier: str) -> dict:
    resolved = None
    if raw:
        path = Path(raw)
        resolved = (path if path.is_absolute() else source.parent / path).resolve()
    return {"kind": kind, "id": identifier, "stored_path": raw,
            "resolved_path": str(resolved) if resolved else None,
            "exists": resolved.is_file() if resolved else False,
            "contents_extracted": False}


def export_json(data: dict, filename: str | Path, *, overwrite: bool = False) -> Path:
    """Only .json destinations; refuse original path, aliases and existing outputs."""
    output = Path(filename).expanduser().resolve()
    if output.suffix.lower() != ".json":
        raise ValueError("출력 파일 확장자는 .json이어야 합니다.")
    if source_name := data.get("source", {}).get("path"):
        source = Path(source_name).resolve()
        if output == source or (output.exists() and source.exists() and output.samefile(source)):
            raise ValueError("원본 도면에 덮어쓸 수 없습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create prevents accidental overwrite; serialize before opening the target.
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    if not overwrite:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                             suffix=".tmp", delete=False) as stream:
                temporary_name = stream.name
                stream.write(payload)
            os.replace(temporary_name, output)
        finally:
            if temporary_name and Path(temporary_name).exists():
                Path(temporary_name).unlink()
    return output
