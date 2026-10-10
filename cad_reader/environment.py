"""Dependency checks and explicit ODA executable discovery (no conversion)."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import platform
import shutil
import sys

ODA_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"


def find_oda(explicit: str | Path | None = None) -> Path | None:
    override = explicit or os.environ.get("ODA_FILE_CONVERTER")
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"ODA 실행 파일이 없습니다: {path}")
        return path
    candidates = []
    local_tools = Path(__file__).resolve().parent.parent / ".tools" / "oda"
    if local_tools.is_dir():
        candidates.extend(sorted(local_tools.glob("**/ODAFileConverter.exe"), reverse=True))
    for command in ("ODAFileConverter", "ODAFileConverter.exe"):
        if found := shutil.which(command):
            candidates.append(Path(found))
    try:
        import ezdxf
        key = "win_exec_path" if os.name == "nt" else "unix_exec_path"
        configured = ezdxf.options.get("odafc-addon", key)
        if configured:
            candidates.append(Path(configured.strip('"')))
    except (ImportError, KeyError):
        pass
    for env, default in (("ProgramFiles", r"C:\Program Files"),
                         ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                         ("LOCALAPPDATA", "")):
        root = Path(os.environ.get(env, default))
        if str(root) == ".":
            continue
        for pattern in ("ODA/ODAFileConverter*/ODAFileConverter.exe",
                        "ODAFileConverter*/ODAFileConverter.exe",
                        "Programs/ODA/ODAFileConverter*/ODAFileConverter.exe"):
            candidates.extend(sorted(root.glob(pattern), reverse=True))
    return next((p.resolve() for p in candidates if p.is_file()), None)


def check_environment(oda_path: str | Path | None = None) -> dict:
    try:
        version = importlib.metadata.version("ezdxf")
    except importlib.metadata.PackageNotFoundError:
        version = None
    error = None
    try:
        converter = find_oda(oda_path)
    except FileNotFoundError as exc:
        converter, error = None, str(exc)
    return {
        "python": sys.version.split()[0], "python_executable": sys.executable,
        "platform": platform.platform(), "ezdxf": version,
        "oda_executable": str(converter) if converter else None,
        "ready_for_dwg": bool(version and converter), "oda_error": error,
        "installation": {
            "python_dependencies": r".\.venv-cad\Scripts\python.exe -m pip install -r cad_reader\requirements.txt",
            "oda_download": ODA_URL,
            "oda_instructions": "Windows x64 설치 프로그램을 내려받아 설치한 후 doctor를 다시 실행하세요. 사용자 지정 설치는 --oda 또는 ODA_FILE_CONVERTER 환경변수로 지정하세요.",
        },
    }
