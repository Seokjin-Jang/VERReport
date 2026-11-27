"""Google Test XML (--gtest_output=xml:) 파서."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from ..models import Status, TestCase
from . import ParseError, to_float, to_int

_SKIP_RESULTS = {"skipped", "suppressed"}


def _status(tc: ET.Element) -> Status:
    if tc.find("failure") is not None or tc.find("error") is not None:
        return Status.FAIL
    if (
        tc.get("status") == "notrun"
        or tc.get("result") in _SKIP_RESULTS
        or tc.find("skipped") is not None
    ):
        return Status.SKIP
    return Status.PASS


def _message(tc: ET.Element) -> str:
    parts = []
    for tag in ("failure", "error", "skipped"):
        for el in tc.findall(tag):
            text = (el.text or "").strip() or el.get("message", "")
            if text:
                parts.append(text)
    return "\n\n".join(parts)


_LOCATION = re.compile(r"^(?P<file>[^\s:][^:\n]*?|[A-Za-z]:[^:\n]+?)[:(](?P<line>\d+)\)?:?")


def _failure_location(tc: ET.Element) -> tuple[str, int]:
    """구버전 GTest XML 은 testcase 에 file/line 속성이 없다. 실패 본문 첫 줄 'path:line' 에서 보완한다."""
    if tc.get("file"):
        return tc.get("file", ""), to_int(tc.get("line"))
    for el in tc.findall("failure") + tc.findall("error"):
        m = _LOCATION.match((el.text or "").strip())
        if m:
            return m["file"], int(m["line"])
    return "", 0


def parse(path: Path, norm: Callable[[str], str] = str) -> tuple[list[TestCase], str]:
    """반환: (테스트 케이스 목록, testsuites timestamp 문자열)."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ParseError(path, f"XML 파싱 실패: {e}") from e
    if root.tag not in ("testsuites", "testsuite"):
        raise ParseError(path, f"GTest XML 이 아님 (root=<{root.tag}>)")

    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    cases: list[TestCase] = []
    for ts in suites:
        for tc in ts.findall("testcase"):
            file, line = _failure_location(tc)
            cases.append(
                TestCase(
                    suite=tc.get("classname") or ts.get("name", ""),
                    name=tc.get("name", ""),
                    status=_status(tc),
                    time_sec=to_float(tc.get("time")),
                    message=_message(tc),
                    file=norm(file),
                    line=line,
                )
            )
    return cases, root.get("timestamp", "")
