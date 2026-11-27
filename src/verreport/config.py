"""설정(TOML) 로딩. 상대 경로는 설정 파일 위치 기준으로 해석한다."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

from .models import COVERAGE_METRICS

DEFAULT_SUITES = ("unit", "integration", "system", "tdd")
DEFAULT_PATTERNS = {
    "gtest": "{suite}/results.xml",
    "llvmcov": "{suite}/export.json",
    "cppcheck": "cppcheck.xml",
    "lizard": "lizard.xml",
}


@dataclass
class SuiteThreshold:
    pass_rate: float = 100.0
    coverage_metric: str | None = None  # lines / functions / branches / mcdc / regions
    coverage_min: float | None = None


@dataclass
class Thresholds:
    lizard_ccn: int = 10
    lizard_length: int = 80
    # Cppcheck 은 이 경로 아래 지적만 판정에 쓰고(전체는 보고), 아래 심각도는 판정에서 뺀다 (ClaudeClang ci/check_cppcheck.py)
    cppcheck_gate_paths: tuple[str, ...] = ("src/",)
    cppcheck_ignore_severities: tuple[str, ...] = ("information",)
    suites: dict[str, SuiteThreshold] = field(default_factory=dict)


@dataclass
class Config:
    project: str = "Project"
    source_root: Path = Path(".")
    # 다른 머신/컨테이너의 절대 경로를 이 디렉터리 이름부터 잘라 상대 경로로 만든다
    path_anchors: tuple[str, ...] = ("src", "tests")
    # GTest 시각(시간대 없음)이 기록된 시간대. None 이면 이 컴퓨터의 현지 시각으로 본다.
    test_timezone: tzinfo | None = None
    reports_dir: Path = Path("reports")
    suites: tuple[str, ...] = DEFAULT_SUITES
    patterns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PATTERNS))
    thresholds: Thresholds = field(default_factory=Thresholds)
    modules: dict[str, str] = field(default_factory=dict)

    def suite_input(self, tool: str, suite: str) -> Path:
        return self.reports_dir / self.patterns[tool].format(suite=suite)

    def input(self, tool: str) -> Path:
        return self.reports_dir / self.patterns[tool]


class ConfigError(ValueError):
    """설정 값이 잘못된 경우. 오타가 조용히 기본값으로 바뀌어 다른 기준으로 판정되는 일을 막는다."""


_SECTIONS = {"project", "inputs", "thresholds", "modules"}
_PROJECT_KEYS = {"name", "source_root", "path_anchors", "test_timezone"}
_OFFSET = re.compile(r"^(?:UTC)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


def parse_timezone(value: str) -> tzinfo:
    """"UTC", "+09:00"/"UTC+9:00" 같은 고정 오프셋, 또는 IANA 이름("Asia/Seoul")."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"project.test_timezone 은 문자열이어야 합니다 (현재: {value!r})")
    v = value.strip()
    if v.upper() in ("UTC", "Z", "GMT"):
        return timezone.utc
    m = _OFFSET.match(v)
    if m:
        sign, hh, mm = m.groups()
        delta = timedelta(hours=int(hh), minutes=int(mm or 0))
        if delta > timedelta(hours=14):
            raise ConfigError(f"project.test_timezone 오프셋이 범위를 벗어났습니다: {value!r}")
        return timezone(delta if sign == "+" else -delta)
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        return ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(
            f"project.test_timezone 을 알 수 없습니다: {value!r}. "
            '"UTC" 나 "+09:00" 형식을 쓰거나, IANA 이름은 Windows 에서 tzdata 패키지가 필요합니다'
        ) from e
_INPUT_KEYS = set(DEFAULT_PATTERNS) | {"reports_dir", "suites"}
_THRESHOLD_KEYS = {"lizard_ccn", "lizard_length", "cppcheck_gate_paths", "cppcheck_ignore_severities", "suites"}


def _check_keys(where: str, d: dict, allowed: set[str]) -> None:
    unknown = set(d) - allowed
    if unknown:
        raise ConfigError(f"[{where}] 알 수 없는 키: {', '.join(sorted(unknown))} (허용: {', '.join(sorted(allowed))})")


def _number(where: str, v, lo: float, hi: float | None = None, integer: bool = False):
    ok_type = isinstance(v, int) if integer else isinstance(v, (int, float))
    if isinstance(v, bool) or not ok_type or v < lo or (hi is not None and v > hi):
        rng = f"{lo} 이상" + (f" {hi} 이하" if hi is not None else "")
        raise ConfigError(f"{where} 는 {'정수' if integer else '숫자'} {rng} 이어야 합니다 (현재: {v!r})")
    return v


def _str_list(where: str, v) -> tuple[str, ...]:
    if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) and x for x in v):
        raise ConfigError(f"{where} 는 문자열 목록이어야 합니다 (현재: {v!r})")
    return tuple(v)


def _suite_threshold(name: str, vals: dict) -> SuiteThreshold:
    where = f"thresholds.suites.{name}"
    if not isinstance(vals, dict):
        raise ConfigError(f"[{where}] 는 테이블이어야 합니다")
    _check_keys(where, vals, set(SuiteThreshold.__dataclass_fields__))
    st = SuiteThreshold(**vals)
    _number(f"{where}.pass_rate", st.pass_rate, 0, 100)
    if (st.coverage_metric is None) != (st.coverage_min is None):
        raise ConfigError(f"[{where}] coverage_metric 과 coverage_min 은 함께 지정해야 합니다")
    if st.coverage_metric is not None:
        if st.coverage_metric not in COVERAGE_METRICS:
            raise ConfigError(
                f"{where}.coverage_metric 은 {', '.join(COVERAGE_METRICS)} 중 하나여야 합니다 (현재: {st.coverage_metric!r})"
            )
        _number(f"{where}.coverage_min", st.coverage_min, 0, 100)
    return st


def load_config(path: Path | None, reports_dir: Path | None = None) -> Config:
    raw: dict = {}
    base = Path.cwd()
    if path is not None:
        path = Path(path)
        with path.open("rb") as f:
            raw = tomllib.load(f)
        base = path.parent.resolve()

    def rel(p: str | Path) -> Path:
        q = Path(p)
        return q if q.is_absolute() else (base / q).resolve()

    _check_keys("최상위", raw, _SECTIONS)
    proj = raw.get("project", {})
    inp = dict(raw.get("inputs", {}))
    th = raw.get("thresholds", {})
    _check_keys("project", proj, _PROJECT_KEYS)
    _check_keys("inputs", inp, _INPUT_KEYS)
    _check_keys("thresholds", th, _THRESHOLD_KEYS)

    patterns = dict(DEFAULT_PATTERNS)
    patterns.update({k: v for k, v in inp.items() if k in DEFAULT_PATTERNS})
    for tool in ("gtest", "llvmcov"):
        if "{suite}" not in patterns[tool]:
            raise ConfigError(f"inputs.{tool} 경로에는 {{suite}} 가 있어야 합니다 (현재: {patterns[tool]!r})")

    suites = _str_list("inputs.suites", inp.get("suites", list(DEFAULT_SUITES)))
    if not suites:
        raise ConfigError("inputs.suites 가 비어 있습니다")
    suite_th = {name: _suite_threshold(name, vals) for name, vals in th.get("suites", {}).items()}
    unknown_suites = set(suite_th) - set(suites)
    if unknown_suites:
        raise ConfigError(f"thresholds.suites 에 inputs.suites 에 없는 스위트가 있습니다: {', '.join(sorted(unknown_suites))}")
    _number("thresholds.lizard_ccn", th.get("lizard_ccn", 10), 1, integer=True)
    _number("thresholds.lizard_length", th.get("lizard_length", 80), 1, integer=True)

    return Config(
        project=proj.get("name", "Project"),
        source_root=rel(proj.get("source_root", ".")),
        path_anchors=_str_list("project.path_anchors", proj.get("path_anchors", ["src", "tests"])),
        test_timezone=parse_timezone(proj["test_timezone"]) if "test_timezone" in proj else None,
        reports_dir=Path(reports_dir).resolve() if reports_dir else rel(inp.get("reports_dir", "reports")),
        suites=suites,
        patterns=patterns,
        thresholds=Thresholds(
            lizard_ccn=th.get("lizard_ccn", 10),
            lizard_length=th.get("lizard_length", 80),
            cppcheck_gate_paths=_str_list("thresholds.cppcheck_gate_paths", th.get("cppcheck_gate_paths", ["src/"])),
            cppcheck_ignore_severities=_str_list(
                "thresholds.cppcheck_ignore_severities", th.get("cppcheck_ignore_severities", ["information"])
            ),
            suites=suite_th,
        ),
        modules={str(k): str(v) for k, v in raw.get("modules", {}).items()},
    )
