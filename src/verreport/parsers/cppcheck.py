"""Cppcheck XML (--xml --xml-version=2) 파서."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from ..models import Violation
from . import ParseError, to_int

# 검사기 실행 현황 보고로, 코드 지적이 아니다.
_IGNORED_IDS = {"checkersReport"}


def parse(path: Path, norm: Callable[[str], str] = str) -> list[Violation]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ParseError(path, f"XML 파싱 실패: {e}") from e
    if root.tag != "results" or root.get("version") != "2":
        raise ParseError(path, "Cppcheck XML v2 가 아님 (--xml-version=2 필요)")

    out: list[Violation] = []
    for err in root.iter("error"):
        rule = err.get("id", "")
        if rule in _IGNORED_IDS:
            continue
        loc = err.find("location")  # 첫 location 이 주 위치
        out.append(
            Violation(
                severity=err.get("severity", ""),
                rule_id=rule,
                message=err.get("msg", ""),
                file=norm(loc.get("file", "")) if loc is not None else "",
                line=to_int(loc.get("line")) if loc is not None else 0,
                column=to_int(loc.get("column")) if loc is not None else 0,
                cwe=to_int(err.get("cwe")),
                inconclusive=err.get("inconclusive") == "true",
                verbose=err.get("verbose", ""),
            )
        )
    return out
