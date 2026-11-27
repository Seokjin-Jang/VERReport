"""도구 공통 데이터 모델. 파서는 이 모델로 변환하고 집계/렌더링은 이것만 사용한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class BuildInfo:
    project: str
    timestamp: datetime
    build_id: str = ""
    commit: str = ""


@dataclass
class TestCase:
    __test__ = False  # pytest 수집 대상 아님

    suite: str
    name: str
    status: Status
    time_sec: float = 0.0
    message: str = ""
    file: str = ""
    line: int = 0


@dataclass
class CoverageMetric:
    covered: int = 0
    total: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.total if self.total else 0.0


@dataclass
class FunctionCoverage:
    name: str  # 디맹글된 이름 (가능한 경우)
    file: str
    start_line: int = 0
    end_line: int = 0
    count: int = 0  # 호출 횟수
    regions: CoverageMetric = field(default_factory=CoverageMetric)
    branches: CoverageMetric = field(default_factory=CoverageMetric)  # 분기 방향(true/false) 단위
    mangled: str = ""


COVERAGE_METRICS = ("lines", "functions", "branches", "mcdc", "regions")


@dataclass
class FileCoverage:
    file: str
    # llvm-cov export summary 키 그대로: lines / functions / branches / mcdc / regions
    metrics: dict[str, CoverageMetric] = field(default_factory=dict)
    functions: list[FunctionCoverage] = field(default_factory=list)


@dataclass
class Violation:
    severity: str  # error / warning / style / performance / portability / information
    rule_id: str
    message: str
    file: str  # 위치가 없는 전역 지적은 ""
    line: int = 0
    column: int = 0
    cwe: int = 0
    inconclusive: bool = False
    verbose: str = ""


@dataclass
class FunctionComplexity:
    """Lizard 임계값 초과 함수 (lizard.xml 은 초과 함수만 담는다)."""

    name: str
    file: str
    line: int
    ccn: int
    nloc: int
    length: int  # 함수 전체 라인 수
    params: int = 0


@dataclass
class SuiteResult:
    """테스트 스위트(unit/integration/tdd) 하나의 GTest + 커버리지 결과."""

    name: str
    tests_available: bool = False
    coverage_available: bool = False
    tests: list[TestCase] = field(default_factory=list)
    coverage_files: list[FileCoverage] = field(default_factory=list)
    coverage_totals: dict[str, CoverageMetric] = field(default_factory=dict)
    tests_error: str = ""  # 결과 파일은 있으나 읽지 못한 경우 사유
    coverage_error: str = ""


@dataclass
class VerificationData:
    build: BuildInfo
    suites: dict[str, SuiteResult] = field(default_factory=dict)
    cppcheck_available: bool = False
    cppcheck_error: str = ""
    violations: list[Violation] = field(default_factory=list)
    lizard_available: bool = False
    lizard_error: str = ""
    complexity: list[FunctionComplexity] = field(default_factory=list)
