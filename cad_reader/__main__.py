from __future__ import annotations

import argparse
from collections import Counter
import json
import sys

from .environment import check_environment
from .reader import analyze_drawing, export_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DWG/DXF 읽기 전용 분석. 원본은 저장하지 않습니다.")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Python/ezdxf/ODA 설치 확인")
    doctor.add_argument("--oda", help="ODAFileConverter.exe 경로")
    inspect = commands.add_parser("inspect", help="도면 추출 및 요약")
    inspect.add_argument("drawing")
    inspect.add_argument("--oda")
    inspect.add_argument("--json", dest="output", help="선택적 .json 출력 경로")
    inspect.add_argument("--overwrite", action="store_true", help="기존 JSON 출력 덮어쓰기")
    inspect.add_argument("--max-depth", type=int, default=32)
    inspect.add_argument("--max-scene-entities", type=int, default=500_000)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            environment = check_environment(args.oda)
            print(json.dumps(environment, ensure_ascii=False, indent=2))
            return 0 if environment["ready_for_dwg"] else 2
        data = analyze_drawing(args.drawing, oda_path=args.oda,
                               max_depth=args.max_depth, max_scene_entities=args.max_scene_entities)
        if args.output:
            output = export_json(data, args.output, overwrite=args.overwrite)
            print(f"JSON: {output}")
        print(f"원본 변경 없음: {data['source']['original_unchanged']}")
        print(f"단위: {data['units']['name']} ($INSUNITS={data['units']['insunits']})")
        print(f"레이어: {len(data['layers'])}, 블록 정의: {len(data['blocks'])}")
        print(json.dumps(data["coverage"], ensure_ascii=False, indent=2))
        for code, count in Counter(w["code"] for w in data["warnings"]).items():
            example = next(w["message"] for w in data["warnings"] if w["code"] == code)
            print(f"주의 [{code}] {count}건: {example}")
        if data["external_references"]:
            print(json.dumps(data["external_references"], ensure_ascii=False, indent=2))
        return 0 if data["source"]["original_unchanged"] else 1
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
