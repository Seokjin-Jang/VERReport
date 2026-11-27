"""파싱 결과(VerificationData)를 화면 단위로 집계하고 합격/불합격을 판정한다.

판정 규칙은 ClaudeClang CI(ci/check_*.py, ci/test.sh)와 같게 맞춘다.
- 테스트   : 실패(failure/error) 0건, 성공률 >= 기준. 실행된 테스트가 0건이면 실패.
- 커버리지 : 지정 지표가 없거나 측정 대상 0건이거나 기준 미달이면 실패.
- Cppcheck : 판정 대상 경로(src/) 안에서 판정 제외 심각도(information)가 아닌 지적 0건.
- Lizard   : CCN 또는 함수 길이 임계값 초과 함수 0건.
결과 파일이 없는 항목은 N/A 로 두고 전체 판정에서 제외한다(경고로 표시).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, TypeVar

from .config import Config
from .models import (
    COVERAGE_METRICS,
    CoverageMetric,
    FileCoverage,
    FunctionComplexity,
    Status,
    TestCase,
    VerificationData,
    Violation,
)

T = TypeVar("T")
GLOBAL = "(전역)"
SEVERITY_ORDER = ("error", "warning", "style", "performance", "portability", "information")


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NA = "na"


@dataclass
class Judgement:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ 모듈 매핑
def _stem(path: str) -> str:
    """확장자를 뗀 경로. src/arbiter.c → src/arbiter"""
    head, _, name = path.rpartition("/")
    base = name.split(".", 1)[0] or name
    return f"{head}/{base}" if head else base


class ModuleMapper:
    """파일 경로 → 모듈 이름.

    1) 설정 [modules] 매핑. 키는 다음 중 하나이며, 가장 긴 키가 우선한다.
       - 디렉터리      "src/core"        → src/core/ 아래 모든 파일
       - 파일          "src/eclp_types.h" → 그 파일
       - 확장자 없는 경로 "src/arbiter"   → src/arbiter.c, src/arbiter.h 등
    2) src/<모듈>/... → <모듈>
       src 바로 아래 파일 → 확장자를 뗀 파일 이름 (src/arbiter.c, src/arbiter.h → arbiter)
    3) 그 외 <a>/<b>/... → "a/b" (예: tests/unit), 1단계 경로 → 첫 디렉터리
    """

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = sorted(
            ((k.replace("\\", "/").strip("/"), v) for k, v in (mapping or {}).items()),
            key=lambda kv: -len(kv[0]),
        )

    def __call__(self, file: str) -> str:
        if not file:
            return GLOBAL
        stem = _stem(file)
        for key, name in self.mapping:
            if file == key or stem == key or file.startswith(key + "/"):
                return name
        parts = file.split("/")
        if len(parts) <= 1:
            return "(root)"
        if parts[0] == "src":
            return parts[1] if len(parts) > 2 else _stem(parts[1])
        return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def group_by(items: Iterable[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    out: dict[str, list[T]] = defaultdict(list)
    for it in items:
        out[key(it)].append(it)
    return dict(sorted(out.items()))


def sum_metrics(items: Iterable[dict[str, CoverageMetric]]) -> dict[str, CoverageMetric]:
    acc = {m: CoverageMetric() for m in COVERAGE_METRICS}
    seen: set[str] = set()
    for metrics in items:
        for k, v in metrics.items():
            acc[k].covered += v.covered
            acc[k].total += v.total
            seen.add(k)
    return {k: v for k, v in acc.items() if k in seen}


# ------------------------------------------------------------------ 테스트
@dataclass
class Counts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    time_sec: float = 0.0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped

    @property
    def executed(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        return 100.0 * self.passed / self.executed if self.executed else 0.0

    @classmethod
    def of(cls, cases: Iterable[TestCase]) -> "Counts":
        c = cls()
        for t in cases:
            if t.status is Status.PASS:
                c.passed += 1
            elif t.status is Status.FAIL:
                c.failed += 1
            else:
                c.skipped += 1
            c.time_sec += t.time_sec
        return c


@dataclass
class TestGroup:
    name: str  # GTest testsuite(클래스) 이름
    counts: Counts
    cases: list[TestCase]


@dataclass
class TestSummary:
    available: bool
    counts: Counts
    judgement: Judgement
    groups: list[TestGroup] = field(default_factory=list)
    failures: list[TestCase] = field(default_factory=list)


# ------------------------------------------------------------------ 커버리지
@dataclass
class ModuleCoverage:
    name: str
    metrics: dict[str, CoverageMetric]
    files: list[FileCoverage]


@dataclass
class CoverageSummary:
    available: bool
    totals: dict[str, CoverageMetric]
    gate_metric: str | None
    gate_min: float | None
    judgement: Judgement
    modules: list[ModuleCoverage] = field(default_factory=list)


@dataclass
class SuiteSummary:
    name: str
    tests: TestSummary
    coverage: CoverageSummary

    @property
    def judgement(self) -> Judgement:
        return combine([self.tests.judgement, self.coverage.judgement])


# ------------------------------------------------------------------ 정적 분석 / 메트릭
@dataclass
class FileItems:
    file: str
    items: list  # Violation 또는 FunctionComplexity


@dataclass
class ModuleItems:
    name: str
    count: int
    files: list[FileItems]
    by_severity: Counter = field(default_factory=Counter)


@dataclass
class CppcheckSummary:
    available: bool
    total: int
    gated: list[Violation]  # 판정 대상 지적
    by_severity: Counter
    by_rule: Counter
    judgement: Judgement
    modules: list[ModuleItems] = field(default_factory=list)


@dataclass
class LizardItem:
    fn: FunctionComplexity
    ccn_over: bool
    length_over: bool


@dataclass
class LizardSummary:
    available: bool
    items: list[LizardItem]
    ccn_over: int
    length_over: int
    judgement: Judgement
    modules: list[ModuleItems] = field(default_factory=list)


# ------------------------------------------------------------------ 전체
@dataclass
class Hotspot:
    file: str
    module: str
    failed_tests: int = 0
    cppcheck: int = 0
    lizard: int = 0
    low_coverage: bool = False

    @property
    def score(self) -> int:
        return 3 * self.failed_tests + 2 * self.cppcheck + self.lizard + (1 if self.low_coverage else 0)


@dataclass
class Report:
    data: VerificationData
    suites: list[SuiteSummary]
    cppcheck: CppcheckSummary
    lizard: LizardSummary
    judgement: Judgement
    hotspots: list[Hotspot]
    warnings: list[str]
    config: Config


def combine(js: Iterable[Judgement]) -> Judgement:
    js = list(js)
    reasons = [r for j in js for r in j.reasons]
    if any(j.verdict is Verdict.FAIL for j in js):
        return Judgement(Verdict.FAIL, reasons)
    if js and all(j.verdict is Verdict.NA for j in js):
        return Judgement(Verdict.NA, reasons)
    return Judgement(Verdict.PASS, reasons)


def _missing(label: str, error: str, warnings: list[str]) -> Judgement:
    """결과가 없을 때: 파일이 없으면 N/A(경고), 파일이 깨졌으면 FAIL. 깨진 결과가 통과로 보이면 안 된다."""
    if error:
        return Judgement(Verdict.FAIL, [f"{label} 결과 파일을 읽지 못했습니다: {error}"])
    warnings.append(f"{label} 결과 파일이 없습니다")
    return Judgement(Verdict.NA)


def _judge_tests(suite: str, c: Counts, min_rate: float) -> Judgement:
    reasons = []
    if c.executed == 0:
        reasons.append(f"[{suite}] 실행된 테스트가 없습니다")
    if c.failed:
        reasons.append(f"[{suite}] 테스트 실패 {c.failed}건")
    if c.executed and c.pass_rate < min_rate:
        reasons.append(f"[{suite}] 성공률 {c.pass_rate:.1f}% < 기준 {min_rate:g}%")
    return Judgement(Verdict.FAIL if reasons else Verdict.PASS, reasons)


def _judge_coverage(suite: str, totals: dict[str, CoverageMetric], metric: str | None, minimum: float | None) -> Judgement:
    if not metric or minimum is None:
        return Judgement(Verdict.PASS)  # 기준 없음: 보고만 한다
    m = totals.get(metric)
    if m is None:
        return Judgement(Verdict.FAIL, [f"[{suite}] 커버리지 지표 '{metric}' 가 결과에 없습니다"])
    if m.total == 0:
        return Judgement(Verdict.FAIL, [f"[{suite}] {metric} 측정 대상이 0건입니다"])
    if m.covered * 100 < minimum * m.total:  # 반올림 없이 비교
        return Judgement(Verdict.FAIL, [f"[{suite}] {metric} {m.percent:.1f}% < 기준 {minimum:g}%"])
    return Judgement(Verdict.PASS)


def summarize(data: VerificationData, cfg: Config) -> Report:
    module_of = ModuleMapper(cfg.modules)
    th = cfg.thresholds
    warnings: list[str] = []
    hot: dict[str, Hotspot] = {}

    def spot(file: str) -> Hotspot:
        return hot.setdefault(file, Hotspot(file, module_of(file)))

    # ---- 스위트 (GTest + 커버리지)
    suites: list[SuiteSummary] = []
    for name, sr in data.suites.items():
        st = th.suites.get(name)
        min_rate = st.pass_rate if st else 100.0

        if sr.tests_available:
            counts = Counts.of(sr.tests)
            tj = _judge_tests(name, counts, min_rate)
            groups = [TestGroup(g, Counts.of(cs), cs) for g, cs in group_by(sr.tests, lambda t: t.suite).items()]
            failures = [t for t in sr.tests if t.status is Status.FAIL]
            for t in failures:
                if t.file:
                    spot(t.file).failed_tests += 1
            if counts.skipped:
                warnings.append(f"[{name}] 건너뛴 테스트 {counts.skipped}건")
        else:
            counts, groups, failures = Counts(), [], []
            tj = _missing(f"[{name}] GTest", sr.tests_error, warnings)
        tests = TestSummary(sr.tests_available, counts, tj, groups, failures)

        metric = st.coverage_metric if st else None
        minimum = st.coverage_min if st else None
        if sr.coverage_available:
            cj = _judge_coverage(name, sr.coverage_totals, metric, minimum)
            modules = [
                ModuleCoverage(mod, sum_metrics(f.metrics for f in fs), sorted(fs, key=lambda f: f.file))
                for mod, fs in group_by(sr.coverage_files, lambda f: module_of(f.file)).items()
            ]
            if metric and minimum is not None:
                for f in sr.coverage_files:
                    m = f.metrics.get(metric)
                    if m and m.total and m.covered * 100 < minimum * m.total:
                        spot(f.file).low_coverage = True
        else:
            modules = []
            cj = _missing(f"[{name}] 커버리지", sr.coverage_error, warnings)
        coverage = CoverageSummary(sr.coverage_available, sr.coverage_totals, metric, minimum, cj, modules)
        suites.append(SuiteSummary(name, tests, coverage))

    # ---- Cppcheck
    gate = tuple(p.rstrip("/") + "/" for p in th.cppcheck_gate_paths)
    ignored = set(th.cppcheck_ignore_severities)
    vs = sorted(data.violations, key=lambda v: (v.file, v.line, v.column))
    gated = [v for v in vs if v.file.startswith(gate) and v.severity not in ignored]
    for v in gated:
        spot(v.file).cppcheck += 1
    if data.cppcheck_available:
        reasons = [f"Cppcheck 지적 {len(gated)}건 ({', '.join(gate)})"] if gated else []
        cpj = Judgement(Verdict.FAIL if gated else Verdict.PASS, reasons)
    else:
        cpj = _missing("Cppcheck", data.cppcheck_error, warnings)
    cpp_modules = [
        ModuleItems(
            mod, len(items),
            [FileItems(f, it) for f, it in group_by(items, lambda v: v.file).items()],
            Counter(v.severity for v in items),
        )
        for mod, items in group_by(vs, lambda v: module_of(v.file)).items()
    ]
    cppcheck = CppcheckSummary(
        data.cppcheck_available, len(vs), gated,
        Counter({s: n for s, n in sorted(Counter(v.severity for v in vs).items(), key=lambda kv: _sev_rank(kv[0]))}),
        Counter(v.rule_id for v in vs), cpj, cpp_modules,
    )

    # ---- Lizard (설정 임계값으로 다시 판정: CI 의 -C/-L 과 다를 수 있음)
    items = []
    for fn in sorted(data.complexity, key=lambda f: (f.file, f.line)):
        it = LizardItem(fn, fn.ccn > th.lizard_ccn, fn.length > th.lizard_length)
        if it.ccn_over or it.length_over:
            items.append(it)
            spot(fn.file).lizard += 1
    if data.lizard_available:
        lj = Judgement(
            Verdict.FAIL if items else Verdict.PASS,
            [f"Lizard 초과 함수 {len(items)}건 (CCN>{th.lizard_ccn} 또는 길이>{th.lizard_length})"] if items else [],
        )
    else:
        lj = _missing("Lizard", data.lizard_error, warnings)
    liz_modules = [
        ModuleItems(mod, len(its), [FileItems(f, x) for f, x in group_by(its, lambda i: i.fn.file).items()])
        for mod, its in group_by(items, lambda i: module_of(i.fn.file)).items()
    ]
    lizard = LizardSummary(
        data.lizard_available, items,
        sum(i.ccn_over for i in items), sum(i.length_over for i in items), lj, liz_modules,
    )

    overall = combine([s.judgement for s in suites] + [cpj, lj])
    hotspots = sorted((h for h in hot.values() if h.score), key=lambda h: (-h.score, h.file))
    return Report(data, suites, cppcheck, lizard, overall, hotspots, warnings, cfg)


def _sev_rank(sev: str) -> int:
    return SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else len(SEVERITY_ORDER)
