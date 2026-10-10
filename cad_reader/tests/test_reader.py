from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from ezdxf import units

from cad_reader import analyze_drawing, export_json
from cad_reader.analysis import endpoint_connections, line_intersections, select_entities
from cad_reader.reader import extract_document


class ReaderTests(unittest.TestCase):
    def fixture(self):
        doc = ezdxf.new("R2018", setup=True)
        doc.units = units.MM
        doc.layers.new("구조")
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "구조"})
        msp.add_line((10, 0), (10, 10))
        msp.add_line((5, -5), (5, 5))
        msp.add_circle((3, 4), radius=2)
        msp.add_arc((0, 0), radius=4, start_angle=0, end_angle=90)
        msp.add_lwpolyline([(0, 0, 1), (10, 0, 0)], format="xyb")
        msp.add_polyline3d([(0, 0, 0), (0, 0, 3), (0, 4, 3)])
        msp.add_text("벽체 W1", dxfattribs={"height": 2})
        msp.add_mtext("첫 줄\\P둘째 줄")
        dim = msp.add_linear_dim(base=(0, 2), p1=(0, 0), p2=(10, 0))
        dim.render()
        block = doc.blocks.new("기둥", base_point=(1, 0, 0))
        block.add_line((1, 0), (3, 0))
        block.add_attdef("ID", insert=(1, 0), text="기본")
        insert = msp.add_blockref("기둥", (100, 200), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2, "zscale": 2, "layer": "구조"})
        insert.add_auto_attribs({"ID": "C1"})
        nested = doc.blocks.new("중첩")
        nested.add_blockref("기둥", (10, 0))
        msp.add_blockref("중첩", (0, 100), dxfattribs={"rotation": 90})
        doc.layouts.get("Layout1").add_line((0, 0), (1, 1))
        return doc

    def test_geometry_units_blocks_and_unicode_json(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "한글 도면.dxf"
            self.fixture().saveas(source)
            before = source.read_bytes()
            data = analyze_drawing(source)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(data["source"]["original_unchanged"])
            self.assertAlmostEqual(data["units"]["meters_per_drawing_unit"], .001)
            failed = [w for w in data["warnings"] if w["code"] in ("EXTRACTION_FAILED", "BLOCK_EXPANSION_FAILED")]
            self.assertEqual(failed, [])
            lines = [e for e in select_entities(data, types=["LINE"]) if e["insert_ancestry"]]
            first = next(e for e in lines if e["geometry"]["start"] == [100, 200, 0])
            self.assertAlmostEqual(first["geometry"]["end"][0], 100)
            self.assertAlmostEqual(first["geometry"]["end"][1], 204)
            self.assertEqual(first["effective_layer"], "구조")
            self.assertIsNotNone(first["definition_handle"])
            nested = next(e for e in lines if len(e["insert_ancestry"]) == 2)
            self.assertAlmostEqual(nested["geometry"]["start"][1], 110)
            curved = select_entities(data, types=["LWPOLYLINE"])[0]
            self.assertEqual(curved["geometry"]["segments"][0]["type"], "ARC")
            self.assertAlmostEqual(curved["geometry"]["length"], math.pi * 5)
            poly3d = select_entities(data, types=["POLYLINE"])[0]
            self.assertAlmostEqual(poly3d["geometry"]["length"], 7)
            dimension = select_entities(data, types=["DIMENSION"])[0]
            self.assertAlmostEqual(dimension["geometry"]["measurement"], 10)
            self.assertEqual(dimension["geometry"]["measurement_kind"], "drawing_units")
            output = export_json(data, Path(folder) / "결과.json")
            restored = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("벽체 W1", [e["geometry"].get("text") for e in restored["scene_entities"]])
            with self.assertRaises(FileExistsError):
                export_json(data, output)
            with self.assertRaises(ValueError):
                export_json(data, source, overwrite=True)

    def test_relationships_respect_z_and_layout(self):
        doc = ezdxf.new()
        m = doc.modelspace()
        a = m.add_line((0, 0, 0), (10, 0, 0))
        m.add_line((10, 0, 0), (20, 0, 0))
        m.add_line((5, -5, 0), (5, 5, 0))
        m.add_line((7, -5, 5), (7, 5, 5))
        doc.layouts.get("Layout1").add_line((0, -5, 0), (0, 5, 0))
        data = extract_document(doc, source=Path("test.dxf"))
        contacts = endpoint_connections(data, layout=None)
        self.assertEqual(len(contacts["connections"]), 1)
        intersections = line_intersections(data, layout=None)
        self.assertTrue(any(abs(i["point"][0] - 5) < 1e-9 for i in intersections["intersections"]))
        self.assertFalse(any(abs(i["point"][0] - 7) < 1e-9 for i in intersections["intersections"]))
        self.assertTrue(line_intersections(data, max_pairs=1)["truncated"])

    def test_xref_partial_and_array_recursion(self):
        doc = ezdxf.new()
        doc.add_xref_def("missing.dwg", "외부")
        doc.modelspace().add_blockref("외부", (0, 0))
        doc.modelspace().add_ray((0, 0), (1, 0))
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path([(0, 0), (1, 0), (0, 1)])
        block = doc.blocks.new("배열")
        block.add_line((0, 0), (1, 0))
        doc.modelspace().add_blockref("배열", (0, 0)).grid(size=(2, 2), spacing=(10, 20))
        cycle = doc.blocks.new("순환")
        cycle.add_blockref("순환", (0, 0))
        doc.modelspace().add_blockref("순환", (0, 0))
        data = extract_document(doc, source=Path("test.dwg").resolve())
        codes = {w["code"] for w in data["warnings"]}
        self.assertTrue({"XREF_NOT_LOADED", "UNSUPPORTED_GEOMETRY", "PARTIAL_GEOMETRY", "BLOCK_RECURSION_LIMIT"} <= codes)
        self.assertEqual(len(select_entities(data, types=["LINE"])), 4)
        self.assertFalse(data["external_references"][0]["exists"])
        limited = extract_document(doc, source=Path("test.dwg"), max_scene_entities=2)
        self.assertTrue(limited["coverage"]["scene_truncated"])
        self.assertEqual(len(limited["scene_entities"]), 2)

    def test_ocs_negative_normal_and_nonuniform_scale(self):
        doc = ezdxf.new()
        circle = doc.modelspace().add_circle((10, 0, 0), 2, dxfattribs={"extrusion": (0, 0, -1)})
        block = doc.blocks.new("원")
        block.add_circle((0, 0), 1)
        doc.modelspace().add_blockref("원", (0, 0), dxfattribs={"xscale": 2, "yscale": 1})
        data = extract_document(doc, source=Path("test.dxf"))
        circles = select_entities(data, types=["CIRCLE"])
        self.assertEqual(circles[0]["geometry"]["center"], [-10, 0, 0])
        self.assertEqual(len(select_entities(data, types=["ELLIPSE"])), 1)
        self.assertIn("NONUNIFORM_BLOCK_SCALE", {w["code"] for w in data["warnings"]})

    def test_dwg_conversion_uses_temporary_copy_and_restores_config(self):
        # Exercises the ODA boundary without claiming a real DWG converter test.
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "원본.dwg"
            source.write_bytes(b"AC1032" + b"fixture")
            executable = Path(folder) / "ODAFileConverter.exe"
            executable.touch()
            before = source.read_bytes()
            config = ezdxf.options.get("odafc-addon", "win_exec_path")
            def fake_readfile(copy, **kwargs):
                self.assertNotEqual(Path(copy), source)
                self.assertEqual(Path(copy).read_bytes(), before)
                self.assertFalse(kwargs["audit"])
                return self.fixture()
            with patch("ezdxf.addons.odafc.readfile", side_effect=fake_readfile):
                data = analyze_drawing(source, oda_path=executable)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(data["source"]["conversion"]["temporary_copy"])
            self.assertEqual(config, ezdxf.options.get("odafc-addon", "win_exec_path"))
            self.assertIn("CONVERSION_LOSS_NOT_VERIFIABLE", {w["code"] for w in data["warnings"]})

    def test_export_rejects_hardlink_to_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.dwg"
            source.write_bytes(b"original")
            alias = Path(folder) / "alias.json"
            try:
                alias.hardlink_to(source)
            except OSError:
                self.skipTest("Filesystem does not support hard links")
            with self.assertRaises(ValueError):
                export_json({"source": {"path": str(source)}}, alias, overwrite=True)
            self.assertEqual(source.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
