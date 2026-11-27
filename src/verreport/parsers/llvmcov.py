"""llvm-cov export -format=text (JSON) 파서.

- 파일 단위: summary 의 lines/functions/branches/mcdc/regions 를 그대로 사용한다.
- 함수 단위: regions(코드 영역)와 branches 로 영역/분기 커버리지, 호출 횟수, 라인 범위를 계산한다.
  (llvm-cov 는 함수별 라인/MC/DC 요약을 내보내지 않는다.)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..models import COVERAGE_METRICS, CoverageMetric, FileCoverage, FunctionCoverage
from . import ParseError, to_int

# region: [lineStart, colStart, lineEnd, colEnd, count, fileID, expandedFileID, kind]
_CODE_REGION = 0
# branch: [lineStart, colStart, lineEnd, colEnd, trueCount, falseCount, fileID, expandedFileID, kind]
_STATIC_PREFIX = re.compile(r"^(?:[A-Za-z]:)?[^:]*\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inc):(.+)$")


def _metric(d: dict | None) -> CoverageMetric:
    d = d or {}
    return CoverageMetric(covered=to_int(d.get("covered")), total=to_int(d.get("count")))


def demangle(names: list[str]) -> dict[str, str]:
    """llvm-cxxfilt 또는 c++filt 가 있으면 일괄 디맹글한다. 없으면 원래 이름을 유지한다."""
    mangled = sorted({n for n in names if n.startswith(("_Z", "?"))})
    result = {n: n for n in names}
    tool = shutil.which("llvm-cxxfilt") or shutil.which("c++filt")
    if not mangled or not tool:
        return result
    try:
        out = subprocess.run(
            [tool], input="\n".join(mangled), capture_output=True, text=True, timeout=30, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return result
    if len(out) == len(mangled):
        result.update(zip(mangled, out))
    return result


def _function(fn: dict, file: str, display: str) -> FunctionCoverage:
    regions = [r for r in fn.get("regions", []) if len(r) >= 8 and r[5] == 0 and r[7] == _CODE_REGION]
    branches = [b for b in fn.get("branches", []) if len(b) >= 7 and b[6] == 0]
    return FunctionCoverage(
        name=display,
        file=file,
        start_line=min((r[0] for r in regions), default=0),
        end_line=max((r[2] for r in regions), default=0),
        count=to_int(fn.get("count")),
        regions=CoverageMetric(covered=sum(1 for r in regions if r[4] > 0), total=len(regions)),
        branches=CoverageMetric(
            covered=sum((b[4] > 0) + (b[5] > 0) for b in branches), total=2 * len(branches)
        ),
        mangled=fn.get("name", ""),
    )


def parse(
    path: Path, norm: Callable[[str], str] = str, use_demangler: bool = True
) -> tuple[list[FileCoverage], dict[str, CoverageMetric]]:
    """반환: (파일별 커버리지, 전체 합계)."""
    try:
        with open(path, encoding="utf-8-sig") as f:  # BOM 허용
            doc = json.load(f)
        data = doc["data"][0]
    except json.JSONDecodeError as e:
        raise ParseError(path, f"JSON 파싱 실패: {e}") from e
    except (KeyError, IndexError, TypeError) as e:
        raise ParseError(path, "llvm-cov export JSON 이 아님 (data[0] 없음)") from e

    files: dict[str, FileCoverage] = {}
    for fe in data.get("files", []):
        name = norm(fe.get("filename", ""))
        summary = fe.get("summary", {})
        files[name] = FileCoverage(
            file=name, metrics={m: _metric(summary[m]) for m in COVERAGE_METRICS if m in summary}
        )

    raw_fns = data.get("functions", [])
    stripped = []
    for fn in raw_fns:
        n = fn.get("name", "")
        m = _STATIC_PREFIX.match(n)  # static 함수는 "path/file.cpp:name" 형태
        stripped.append(m.group(1) if m else n)
    names = demangle(stripped) if use_demangler else {n: n for n in stripped}

    for fn, short in zip(raw_fns, stripped):
        fnames = fn.get("filenames") or [""]
        file = norm(fnames[0])
        if file in files:  # -ignore-filename-regex 로 제외된 파일의 함수는 버린다
            files[file].functions.append(_function(fn, file, names.get(short, short)))

    for fc in files.values():
        fc.functions.sort(key=lambda f: (f.start_line, f.name))

    totals = data.get("totals", {})
    return list(files.values()), {m: _metric(totals[m]) for m in COVERAGE_METRICS if m in totals}
