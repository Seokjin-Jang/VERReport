"""설정에 따라 모든 입력을 읽어 VerificationData 를 만든다.

- 결과 파일이 없으면 available=False (리포트에서 N/A).
- 결과 파일이 있는데 읽지 못하면 *_error 에 사유를 남기고 계속 진행한다 (리포트에서 오류 = FAIL).
  strict=True 면 첫 오류에서 ParseError 를 그대로 올린다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from .config import Config
from .models import BuildInfo, SuiteResult, VerificationData
from .parsers import ParseError, cppcheck, gtest, lizard, llvmcov
from .paths import PathNormalizer

T = TypeVar("T")


def _parse_ts(value: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _build_time(gtest_stamps: list[str], cfg: Config) -> datetime:
    """빌드 시각: GTest 실행 시각 중 가장 이른 값 → reports 디렉터리 수정 시각 → 현재 시각."""
    stamps = [t for t in (_parse_ts(s) for s in gtest_stamps) if t]
    if stamps:
        return min(stamps)
    if cfg.reports_dir.exists():
        return datetime.fromtimestamp(cfg.reports_dir.stat().st_mtime)
    return datetime.now()


def _read(path: Path, fn: Callable[[Path], T], strict: bool) -> tuple[T | None, str]:
    """(결과, 오류 사유). 파일이 없으면 (None, "")."""
    if not path.is_file():
        return None, ""
    try:
        return fn(path), ""
    except ParseError as e:
        if strict:
            raise
        return None, e.reason
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, IndexError) as e:
        # 파서가 예상하지 못한 형식/권한 문제. 리포트 생성은 멈추지 않는다.
        if strict:
            raise ParseError(path, f"{type(e).__name__}: {e}") from e
        return None, f"{type(e).__name__}: {e}"


def load(
    cfg: Config,
    build_id: str = "",
    build_time: datetime | None = None,
    demangle: bool = True,
    strict: bool = False,
) -> VerificationData:
    norm = PathNormalizer(cfg.source_root, cfg.path_anchors)
    suites: dict[str, SuiteResult] = {}
    stamps: list[str] = []

    for name in cfg.suites:
        sr = SuiteResult(name)
        res, sr.tests_error = _read(cfg.suite_input("gtest", name), lambda p: gtest.parse(p, norm), strict)
        if res is not None:
            sr.tests, stamp = res
            sr.tests_available = True
            stamps.append(stamp)
        res, sr.coverage_error = _read(
            cfg.suite_input("llvmcov", name), lambda p: llvmcov.parse(p, norm, demangle), strict
        )
        if res is not None:
            sr.coverage_files, sr.coverage_totals = res
            sr.coverage_available = True
        suites[name] = sr

    data = VerificationData(
        build=BuildInfo(cfg.project, build_time or _build_time(stamps, cfg), build_id),
        suites=suites,
    )
    res, data.cppcheck_error = _read(cfg.input("cppcheck"), lambda p: cppcheck.parse(p, norm), strict)
    if res is not None:
        data.violations, data.cppcheck_available = res, True
    res, data.lizard_error = _read(cfg.input("lizard"), lambda p: lizard.parse(p, norm), strict)
    if res is not None:
        data.complexity, data.lizard_available = res, True
    return data
