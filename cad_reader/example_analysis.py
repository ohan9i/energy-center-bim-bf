"""Run from the project root: python -m cad_reader.example_analysis drawing.dwg."""

import argparse
import json

from cad_reader import analyze_drawing, export_json
from cad_reader.analysis import endpoint_connections, line_intersections, select_entities


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("drawing")
    parser.add_argument("--layer", help="연결·교차 검사 대상 레이어")
    parser.add_argument("--oda")
    parser.add_argument("--output", default="cad_output/analysis.json")
    args = parser.parse_args()
    data = analyze_drawing(args.drawing, oda_path=args.oda)
    data["analysis"] = {
        "endpoint_connections": endpoint_connections(data, layer=args.layer, tolerance=0.01),
        "line_intersections": line_intersections(data, layer=args.layer, max_pairs=100_000),
    }
    print("도면 단위:", data["units"]["name"])
    print("모델 공간 직선 수:", len(select_entities(data, types=["LINE"])))
    print("경고 코드:", sorted({w["code"] for w in data["warnings"]}))
    print("출력:", export_json(data, args.output))


if __name__ == "__main__":
    main()
