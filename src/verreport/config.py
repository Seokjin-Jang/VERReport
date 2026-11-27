"""설정(TOML) 로딩. 상대 경로는 설정 파일 위치 기준으로 해석한다."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SUITES = ("unit", "integration", "tdd")
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
    reports_dir: Path = Path("reports")
    suites: tuple[str, ...] = DEFAULT_SUITES
    patterns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PATTERNS))
    thresholds: Thresholds = field(default_factory=Thresholds)
    modules: dict[str, str] = field(default_factory=dict)

    def suite_input(self, tool: str, suite: str) -> Path:
        return self.reports_dir / self.patterns[tool].format(suite=suite)

    def input(self, tool: str) -> Path:
        return self.reports_dir / self.patterns[tool]


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

    proj = raw.get("project", {})
    inp = dict(raw.get("inputs", {}))
    th = raw.get("thresholds", {})

    patterns = dict(DEFAULT_PATTERNS)
    unknown = set(inp) - set(DEFAULT_PATTERNS) - {"reports_dir", "suites"}
    if unknown:
        raise ValueError(f"알 수 없는 inputs 키: {sorted(unknown)}")
    patterns.update({k: v for k, v in inp.items() if k in DEFAULT_PATTERNS})

    suite_th = {
        name: SuiteThreshold(**{k: v for k, v in vals.items() if k in SuiteThreshold.__dataclass_fields__})
        for name, vals in th.get("suites", {}).items()
    }
    return Config(
        project=proj.get("name", "Project"),
        source_root=rel(proj.get("source_root", ".")),
        path_anchors=tuple(proj.get("path_anchors", ("src", "tests"))),
        reports_dir=Path(reports_dir).resolve() if reports_dir else rel(inp.get("reports_dir", "reports")),
        suites=tuple(inp.get("suites", DEFAULT_SUITES)),
        patterns=patterns,
        thresholds=Thresholds(
            lizard_ccn=th.get("lizard_ccn", 10),
            lizard_length=th.get("lizard_length", 80),
            cppcheck_gate_paths=tuple(th.get("cppcheck_gate_paths", ("src/",))),
            cppcheck_ignore_severities=tuple(th.get("cppcheck_ignore_severities", ("information",))),
            suites=suite_th,
        ),
        modules=dict(raw.get("modules", {})),
    )
