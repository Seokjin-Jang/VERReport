"""집계 결과(Report)를 템플릿이 바로 쓸 수 있는 화면 모델로 바꾼다. 템플릿에는 계산을 두지 않는다."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .aggregate import Judgement, Report, Verdict, combine

METRIC_LABELS = {
    "lines": "라인",
    "functions": "함수",
    "branches": "분기",
    "mcdc": "MC/DC",
    "regions": "영역",
}
DASHBOARD_METRICS = ("lines", "functions", "branches", "mcdc")
SEVERITY_LABELS = {
    "error": "error",
    "warning": "warning",
    "style": "style",
    "performance": "performance",
    "portability": "portability",
    "information": "information",
}
SUITE_LABELS = {"unit": "단위 테스트", "integration": "통합 테스트", "system": "시스템 테스트", "tdd": "TDD 테스트"}
VERDICT_TEXT = {Verdict.PASS: "PASS", Verdict.FAIL: "FAIL", Verdict.NA: "N/A"}
VERDICT_ICON = {Verdict.PASS: "✔", Verdict.FAIL: "✖", Verdict.NA: "–"}

PAGES = {
    "gtest": "gtest.html",
    "coverage": "coverage.html",
    "cppcheck": "cppcheck.html",
    "lizard": "lizard.html",
}


def absent(j: Judgement) -> str:
    """결과가 없을 때 표시할 말. 결과가 없는데 FAIL 이면 파일이 깨진 경우다 (aggregate._missing)."""
    return "결과 파일 오류" if j.verdict is Verdict.FAIL else "결과 없음"


@dataclass
class Badge:
    verdict: str  # pass / fail / na  (CSS 클래스)
    text: str
    icon: str

    @classmethod
    def of(cls, v: Verdict) -> "Badge":
        return cls(v.value, VERDICT_TEXT[v], VERDICT_ICON[v])


@dataclass
class Segment:
    cls: str  # CSS 클래스 (good / critical / warning)
    label: str
    value: int
    x: float = 0.0  # 0~100
    width: float = 0.0


@dataclass
class StackRow:
    label: str
    total: int
    segments: list[Segment]
    available: bool = True
    badge: Badge | None = None
    absent: str = "결과 없음"


@dataclass
class BarRow:
    label: str
    value: float  # 0~100 으로 정규화된 막대 길이
    text: str  # 막대 옆에 표시할 값
    tooltip: str
    threshold: float | None = None  # 0~100, 기준선
    below: bool = False  # 기준 미달
    emphasis: bool = False  # 판정 지표


@dataclass
class CoverageBlock:
    name: str
    label: str
    badge: Badge
    available: bool
    gate: str  # "MC/DC ≥ 100%" 또는 "기준 없음"
    rows: list[BarRow] = field(default_factory=list)
    absent: str = "결과 없음"


@dataclass
class SummaryRow:
    label: str
    badge: Badge
    value: str
    criterion: str
    page: str


def _stack(label: str, parts: list[tuple[str, str, int]], badge: Badge | None) -> StackRow:
    total = sum(v for _, _, v in parts)
    segs, x = [], 0.0
    for cls, name, v in parts:
        w = 100.0 * v / total if total else 0.0
        segs.append(Segment(cls, name, v, x, w))
        x += w
    return StackRow(label, total, [s for s in segs if s.value], True, badge)


MODULE_BARS = 8  # 대시보드 모듈별 막대 최대 개수. 나머지는 "외 N개 모듈" 한 줄로 접는다.


def _count_rows(counter: Counter, labels: dict[str, str] | None = None, top: int | None = None) -> list[BarRow]:
    """top 이 있으면 건수 내림차순 상위 top 개 + 나머지 합계 한 줄. 없으면 counter 순서 그대로."""
    items = list(counter.items())
    rest: list[tuple[str, int]] = []
    if top is not None:
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        items, rest = items[:top], items[top:]
    peak = max((n for _, n in items), default=0)
    rows = [
        BarRow((labels or {}).get(k, k), 100.0 * n / peak if peak else 0.0, f"{n}", f"{k}: {n}건")
        for k, n in items
    ]
    if rest:
        n = sum(v for _, v in rest)
        # 합계 막대는 상위 항목과 비교 대상이 아니므로 막대 없이 숫자만 표시한다
        rows.append(BarRow(f"외 {len(rest)}개 모듈", 0.0, f"{n}", f"나머지 {len(rest)}개 모듈 합계: {n}건"))
    return rows


def dashboard(r: Report) -> dict:
    summary: list[SummaryRow] = []

    # ---- 테스트
    test_rows = []
    for s in r.suites:
        label = SUITE_LABELS.get(s.name, s.name)
        badge = Badge.of(s.tests.judgement.verdict)
        if not s.tests.available:
            test_rows.append(StackRow(label, 0, [], False, badge, absent(s.tests.judgement)))
            summary.append(SummaryRow(f"{label} · GTest", badge, absent(s.tests.judgement), "", PAGES["gtest"]))
            continue
        c = s.tests.counts
        test_rows.append(
            _stack(label, [("good", "성공", c.passed), ("critical", "실패", c.failed), ("warning", "건너뜀", c.skipped)], badge)
        )
        st_rate = f"성공률 ≥ {_th_rate(r, s.name):g}%"
        summary.append(
            SummaryRow(
                f"{label} · GTest", badge,
                f"{c.passed}/{c.executed} 성공 ({c.pass_rate:.1f}%)" + (f", 건너뜀 {c.skipped}" if c.skipped else ""),
                st_rate, PAGES["gtest"],
            )
        )

    # ---- 커버리지
    cov_blocks = []
    for s in r.suites:
        cv = s.coverage
        label = SUITE_LABELS.get(s.name, s.name)
        badge = Badge.of(cv.judgement.verdict)
        has_gate = bool(cv.gate_metric) and cv.gate_min is not None
        gate = f"{METRIC_LABELS.get(cv.gate_metric, cv.gate_metric)} ≥ {cv.gate_min:g}%" if has_gate else "기준 없음 (보고만)"
        block = CoverageBlock(s.name, label, badge, cv.available, gate, absent=absent(cv.judgement))
        for m in DASHBOARD_METRICS:
            mt = cv.totals.get(m)
            if mt is None:
                continue
            is_gate = has_gate and m == cv.gate_metric
            below = is_gate and mt.covered * 100 < cv.gate_min * mt.total
            block.rows.append(
                BarRow(
                    METRIC_LABELS[m], mt.percent, f"{mt.percent:.1f}%",
                    f"{label} {METRIC_LABELS[m]}: {mt.covered}/{mt.total} ({mt.percent:.1f}%)",
                    cv.gate_min if is_gate else None, below, is_gate,
                )
            )
        cov_blocks.append(block)
        if has_gate:
            mt = cv.totals.get(cv.gate_metric)
            value = f"{mt.percent:.1f}% ({mt.covered}/{mt.total})" if mt else ("지표 없음" if cv.available else absent(cv.judgement))
        else:
            value = absent(cv.judgement) if not cv.available else "보고만 함"
        summary.append(SummaryRow(f"{label} · 커버리지", badge, value, gate, PAGES["coverage"]))

    # ---- Cppcheck
    cp = r.cppcheck
    cp_badge = Badge.of(cp.judgement.verdict)
    gate_paths = ", ".join(r.config.thresholds.cppcheck_gate_paths)
    summary.append(
        SummaryRow(
            "Cppcheck", cp_badge,
            f"판정 대상 {len(cp.gated)}건 / 전체 {cp.total}건" if cp.available else absent(cp.judgement),
            f"{gate_paths} 지적 0건", PAGES["cppcheck"],
        )
    )
    cppcheck = {
        "badge": cp_badge,
        "available": cp.available,
        "absent": absent(cp.judgement),
        "total": cp.total,
        "gated": len(cp.gated),
        "severity_rows": _count_rows(cp.by_severity, SEVERITY_LABELS),
        "rule_rows": _count_rows(Counter(dict(cp.by_rule.most_common(5)))),
        "module_rows": _count_rows(Counter({m.name: m.count for m in cp.modules}), top=MODULE_BARS),
    }

    # ---- Lizard
    lz = r.lizard
    lz_badge = Badge.of(lz.judgement.verdict)
    th = r.config.thresholds
    summary.append(
        SummaryRow(
            "Lizard", lz_badge,
            f"초과 함수 {len(lz.items)}개 (CCN {lz.ccn_over} · 길이 {lz.length_over})" if lz.available else absent(lz.judgement),
            f"CCN ≤ {th.lizard_ccn}, 길이 ≤ {th.lizard_length}", PAGES["lizard"],
        )
    )
    worst = sorted(lz.items, key=lambda i: (-i.fn.ccn, -i.fn.length))[:5]
    lizard = {
        "badge": lz_badge,
        "available": lz.available,
        "absent": absent(lz.judgement),
        "count": len(lz.items),
        "ccn_over": lz.ccn_over,
        "length_over": lz.length_over,
        "ccn_limit": th.lizard_ccn,
        "length_limit": th.lizard_length,
        "module_rows": _count_rows(Counter({m.name: m.count for m in lz.modules}), top=MODULE_BARS),
        "worst": worst,
    }

    tests_badge = Badge.of(combine([s.tests.judgement for s in r.suites]).verdict)
    test_table = [
        {
            "label": SUITE_LABELS.get(s.name, s.name),
            "available": s.tests.available,
            "absent": absent(s.tests.judgement),
            "counts": s.tests.counts,
            "badge": Badge.of(s.tests.judgement.verdict),
        }
        for s in r.suites
    ]
    failures = [
        {"suite": SUITE_LABELS.get(s.name, s.name), "case": t}
        for s in r.suites
        for t in s.tests.failures
    ]

    return {
        "tests_badge": tests_badge,
        "test_table": test_table,
        "failures": failures[:5],
        "failures_total": len(failures),
        "overall": Badge.of(r.judgement.verdict),
        "reasons": r.judgement.reasons,
        "warnings": r.warnings,
        "summary": summary,
        "test_rows": test_rows,
        "coverage": cov_blocks,
        "cppcheck": cppcheck,
        "lizard": lizard,
        "hotspots": r.hotspots[:10],
    }


def _th_rate(r: Report, suite: str) -> float:
    st = r.config.thresholds.suites.get(suite)
    return st.pass_rate if st else 100.0
