import pytest

from verreport.aggregate import GLOBAL, ModuleMapper, Verdict, summarize
from verreport.config import load_config
from verreport.loader import load
from verreport.models import (
    BuildInfo,
    CoverageMetric,
    FileCoverage,
    FunctionComplexity,
    Status,
    SuiteResult,
    TestCase,
    VerificationData,
    Violation,
)

from conftest import ROOT

CONFIG = ROOT / "verreport.toml"


@pytest.fixture
def cfg():
    return load_config(CONFIG)


def _data(**kw) -> VerificationData:
    from datetime import datetime

    d = VerificationData(build=BuildInfo("P", datetime(2026, 1, 1)))
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def _suite(name, tests=None, totals=None, files=None) -> SuiteResult:
    return SuiteResult(
        name,
        tests_available=tests is not None,
        coverage_available=totals is not None,
        tests=tests or [],
        coverage_totals=totals or {},
        coverage_files=files or [],
    )


def _ok(name="A", suite="S"):
    return TestCase(suite, name, Status.PASS)


# ---------------- module mapping ----------------
@pytest.mark.parametrize(
    "file, module",
    [
        ("src/core/calc.cpp", "core"),
        ("src/core/sub/x.cpp", "core"),
        ("src/main.c", "main"),
        ("src/arbiter.h", "arbiter"),  # src 바로 아래: .c/.h 를 파일 이름으로 묶음
        ("src/a.b.c", "a"),
        ("tests/unit/a.cpp", "tests/unit"),
        ("include/a.h", "include"),
        ("main.c", "(root)"),
        ("", GLOBAL),
    ],
)
def test_module_default(file, module):
    assert ModuleMapper()(file) == module


def test_module_mapping_longest_prefix():
    m = ModuleMapper({"src": "all", "src/core/": "Core"})
    assert m("src/core/a.c") == "Core"
    assert m("src/io/a.c") == "all"
    assert m("srcx/a.c") == "srcx"  # prefix 는 디렉터리 경계로만 매칭


# ---------------- samples end-to-end ----------------
def test_summarize_samples(cfg):
    r = summarize(load(cfg, demangle=False), cfg)
    s = {x.name: x for x in r.suites}

    assert s["unit"].tests.counts.failed == 1
    assert s["unit"].judgement.verdict is Verdict.FAIL  # 실패 1건 + mcdc 미달
    assert s["integration"].judgement.verdict is Verdict.PASS  # functions 100%
    assert s["tdd"].judgement.verdict is Verdict.PASS  # 커버리지 기준 없음

    # Cppcheck: tests/ 지적은 보고만, src/ 3건이 판정 대상
    assert r.cppcheck.total == 4 and len(r.cppcheck.gated) == 3
    assert list(r.cppcheck.by_severity) == ["error", "style", "performance"]
    assert [m.name for m in r.cppcheck.modules] == ["core", "io", "tests/unit"]

    assert (r.lizard.ccn_over, r.lizard.length_over) == (2, 1)
    assert r.judgement.verdict is Verdict.FAIL
    assert any("skip" in w or "건너뛴" in w for w in r.warnings)

    cov = s["unit"].coverage
    assert [m.name for m in cov.modules] == ["core", "io"]
    assert cov.modules[0].metrics["lines"].covered == 34

    # calc: 실패 1(x3) + cppcheck 1(x2) + lizard 1 + 커버리지 미달 1 = 7
    # reader: cppcheck 2(x2) + lizard 1 + 커버리지 미달 1 = 6
    assert [(h.file, h.score) for h in r.hotspots] == [("src/core/calc.cpp", 7), ("src/io/reader.cpp", 6)]


# ---------------- judgement rules ----------------
def test_all_pass(cfg):
    full = {"mcdc": CoverageMetric(4, 4), "functions": CoverageMetric(2, 2)}
    d = _data(
        suites={n: _suite(n, [_ok()], full) for n in ("unit", "integration", "tdd")},
        cppcheck_available=True,
        violations=[Violation("information", "missingInclude", "m", "src/a.c", 1)],  # 판정 제외 심각도
        lizard_available=True,
        complexity=[FunctionComplexity("f", "src/a.c", 1, ccn=10, nloc=80, length=80)],  # 경계값은 통과
    )
    r = summarize(d, cfg)
    assert r.judgement.verdict is Verdict.PASS, r.judgement.reasons
    assert r.lizard.items == [] and r.hotspots == []


def test_coverage_rules(cfg):
    def verdict(totals):
        r = summarize(_data(suites={"unit": _suite("unit", [_ok()], totals)}), cfg)
        return r.suites[0].coverage.judgement

    assert verdict({"mcdc": CoverageMetric(999, 1000)}).verdict is Verdict.FAIL  # 99.9% 는 반올림 없이 실패
    assert verdict({"lines": CoverageMetric(1, 1)}).verdict is Verdict.FAIL  # 지표 없음
    j = verdict({"mcdc": CoverageMetric(0, 0)})
    assert j.verdict is Verdict.FAIL and "0건" in j.reasons[0]


def test_test_rules(cfg):
    def j(tests):
        return summarize(_data(suites={"tdd": _suite("tdd", tests)}), cfg).suites[0].tests.judgement

    assert j([]).verdict is Verdict.FAIL  # 실행 0건
    assert j([TestCase("S", "a", Status.SKIP)]).verdict is Verdict.FAIL  # 전부 skip = 실행 0건
    assert j([_ok(), TestCase("S", "b", Status.SKIP)]).verdict is Verdict.PASS
    assert j([_ok(), TestCase("S", "b", Status.FAIL, file="src/a.c")]).verdict is Verdict.FAIL


def test_missing_inputs_are_na(cfg):
    r = summarize(_data(suites={"unit": _suite("unit")}), cfg)
    assert r.suites[0].judgement.verdict is Verdict.NA
    assert r.cppcheck.judgement.verdict is Verdict.NA
    assert r.judgement.verdict is Verdict.NA
    assert len(r.warnings) == 4


def test_partial_na_does_not_fail(cfg):
    r = summarize(_data(cppcheck_available=True), cfg)
    assert r.judgement.verdict is Verdict.PASS


def test_lizard_thresholds_from_config(cfg):
    cfg.thresholds.lizard_ccn = 20
    d = _data(lizard_available=True, complexity=[FunctionComplexity("f", "src/a.c", 1, ccn=14, nloc=10, length=20)])
    assert summarize(d, cfg).lizard.judgement.verdict is Verdict.PASS


def test_coverage_module_files_and_hotspot(cfg):
    files = [
        FileCoverage("src/a/x.c", {"mcdc": CoverageMetric(1, 2)}),
        FileCoverage("src/a/y.c", {"mcdc": CoverageMetric(2, 2)}),
    ]
    r = summarize(_data(suites={"unit": _suite("unit", [_ok()], {"mcdc": CoverageMetric(3, 4)}, files)}), cfg)
    (mod,) = r.suites[0].coverage.modules
    assert (mod.name, mod.metrics["mcdc"].covered, mod.metrics["mcdc"].total) == ("a", 3, 4)
    assert [h.file for h in r.hotspots] == ["src/a/x.c"]


def test_module_mapping_file_and_stem():
    """ClaudeClang 처럼 src 바로 아래 파일을 아키텍처 컴포넌트로 묶는 매핑."""
    m = ModuleMapper({
        "src/arbiter": "C-ARB",           # 확장자 없는 경로: .c, .h 모두
        "src/controller": "C-CTL",
        "src/result_format": "C-CTL",
        "src/eclp_types.h": "공통",        # 파일 하나
    })
    assert m("src/arbiter.c") == m("src/arbiter.h") == "C-ARB"
    assert m("src/result_format.c") == m("src/controller.h") == "C-CTL"
    assert m("src/eclp_types.h") == "공통"
    assert m("src/arbiter_util.c") == "arbiter_util"  # 이름이 접두어로만 겹치면 매칭하지 않음
    assert m("src/state_manager.c") == "state_manager"  # 매핑 없음: 기본 규칙
