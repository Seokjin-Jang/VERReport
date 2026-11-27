"""Lizard 결과 파서.

ClaudeClang 은 `lizard -C 10 -L 80 --warnings_only` 출력을 checkstyle XML 로 변환한다(ci/lizard_report.py).
message 형식: "<함수명> has 95 NLOC, 14 CCN, 310 token, 3 PARAM, 112 length, 4 ND"
(ND 는 Lizard 버전에 따라 없을 수 있다.)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from ..models import FunctionComplexity
from . import ParseError, to_int

_MESSAGE = re.compile(r"^(?P<name>.+) has (?P<stats>\d+ \w+(?:, \d+ \w+)*)$")
_STAT = re.compile(r"(\d+) (\w+)")


def parse_message(message: str) -> tuple[str, dict[str, int]] | None:
    m = _MESSAGE.match(message.strip())
    if not m:
        return None
    return m["name"], {k.upper(): int(v) for v, k in _STAT.findall(m["stats"])}


def parse(path: Path, norm: Callable[[str], str] = str) -> list[FunctionComplexity]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ParseError(path, f"XML 파싱 실패: {e}") from e
    if root.tag != "checkstyle":
        raise ParseError(path, f"checkstyle XML 이 아님 (root=<{root.tag}>)")

    out: list[FunctionComplexity] = []
    for f in root.findall("file"):
        file = norm(f.get("name", ""))
        for err in f.findall("error"):
            if err.get("source", "lizard") != "lizard":
                continue
            parsed = parse_message(err.get("message", ""))
            if parsed is None:
                raise ParseError(path, f"Lizard message 형식을 알 수 없음: {err.get('message')!r}")
            name, s = parsed
            out.append(
                FunctionComplexity(
                    name=name,
                    file=file,
                    line=to_int(err.get("line")),
                    ccn=s.get("CCN", 0),
                    nloc=s.get("NLOC", 0),
                    length=s.get("LENGTH", 0),
                    params=s.get("PARAM", 0),
                )
            )
    return out
