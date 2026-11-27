"""설정에 따라 모든 입력을 읽어 VerificationData 를 만든다. 없는 입력은 available=False 로 둔다."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import Config
from .models import BuildInfo, SuiteResult, VerificationData
from .parsers import cppcheck, gtest, lizard, llvmcov
from .paths import PathNormalizer


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _build_time(gtest_stamps: list[str], cfg: Config) -> datetime:
    """빌드 시각: GTest 실행 시각 중 가장 이른 값 → reports 디렉터리 수정 시각 → 현재 시각."""
    stamps = [t for t in (_parse_ts(s) for s in gtest_stamps) if t]
    if stamps:
        return min(stamps)
    if cfg.reports_dir.exists():
        return datetime.fromtimestamp(cfg.reports_dir.stat().st_mtime)
    return datetime.now()


def load(
    cfg: Config, build_id: str = "", build_time: datetime | None = None, demangle: bool = True
) -> VerificationData:
    norm = PathNormalizer(cfg.source_root, cfg.path_anchors)
    suites: dict[str, SuiteResult] = {}
    stamps: list[str] = []

    for name in cfg.suites:
        sr = SuiteResult(name)
        p: Path = cfg.suite_input("gtest", name)
        if p.exists():
            sr.tests, stamp = gtest.parse(p, norm)
            sr.tests_available = True
            stamps.append(stamp)
        p = cfg.suite_input("llvmcov", name)
        if p.exists():
            sr.coverage_files, sr.coverage_totals = llvmcov.parse(p, norm, demangle)
            sr.coverage_available = True
        suites[name] = sr

    data = VerificationData(
        build=BuildInfo(cfg.project, build_time or _build_time(stamps, cfg), build_id),
        suites=suites,
    )
    p = cfg.input("cppcheck")
    if p.exists():
        data.violations = cppcheck.parse(p, norm)
        data.cppcheck_available = True
    p = cfg.input("lizard")
    if p.exists():
        data.complexity = lizard.parse(p, norm)
        data.lizard_available = True
    return data
