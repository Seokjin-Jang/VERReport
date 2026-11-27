"""도구별 상세 페이지 화면 모델. 계층: 스위트/모듈 → 파일(또는 테스트 그룹) → 함수/항목."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .aggregate import Report
from .models import COVERAGE_METRICS, CoverageMetric, Status
from .view import METRIC_LABELS, SUITE_LABELS, Badge

STATUS_TEXT = {Status.PASS: "성공", Status.FAIL: "실패", Status.SKIP: "건너뜀"}
STATUS_CLASS = {Status.PASS: "pass", Status.FAIL: "fail", Status.SKIP: "skip"}
SEVERITY_CLASS = {"error": "sev-error", "warning": "sev-warning"}


def _anchor(*parts: str) -> str:
    raw = "-".join(parts)
    return "".join(c if c.isalnum() else "-" for c in raw).strip("-").lower()


# ------------------------------------------------------------------ 공통: 커버리지 셀
@dataclass
class Cell:
    """커버리지 표의 한 칸. total 이 0 이면 측정 대상 없음."""

    covered: int
    total: int
    percent: float
    below: bool = False
    gate: bool = False

    @property
    def empty(self) -> bool:
        return self.total == 0


def _cell(m: CoverageMetric | None, gate_min: float | None = None, gate: bool = False) -> Cell:
    if m is None:
        return Cell(0, 0, 0.0)
    below = gate and gate_min is not None and m.total > 0 and m.covered * 100 < gate_min * m.total
    return Cell(m.covered, m.total, m.percent, below, gate)


# ------------------------------------------------------------------ GTest
def gtest_page(r: Report) -> dict:
    suites = []
    for s in r.suites:
        t = s.tests
        groups = []
        for g in t.groups:
            cases = [
                {
                    "name": c.name,
                    "status": STATUS_TEXT[c.status],
                    "cls": STATUS_CLASS[c.status],
                    "time": c.time_sec,
                    "loc": f"{c.file}:{c.line}" if c.file else "",
                    "message": c.message,
                }
                for c in sorted(g.cases, key=lambda c: (c.status is not Status.FAIL, c.status is not Status.SKIP, c.name))
            ]
            groups.append({"name": g.name, "counts": g.counts, "cases": cases, "open": g.counts.failed > 0,
                           "id": _anchor("t", s.name, g.name)})
        groups.sort(key=lambda g: (-g["counts"].failed, g["name"]))
        suites.append(
            {
                "name": s.name,
                "label": SUITE_LABELS.get(s.name, s.name),
                "id": _anchor("suite", s.name),
                "available": t.available,
                "badge": Badge.of(t.judgement.verdict),
                "counts": t.counts,
                "reasons": t.judgement.reasons,
                "groups": groups,
                "failures": [
                    {"suite": c.suite, "name": c.name, "loc": f"{c.file}:{c.line}" if c.file else "",
                     "id": _anchor("t", s.name, c.suite)}
                    for c in t.failures
                ],
            }
        )
    return {"suites": suites}


# ------------------------------------------------------------------ 커버리지
@dataclass
class CovFunction:
    name: str
    lines: str
    count: int
    regions: Cell
    branches: Cell
    uncovered: bool


@dataclass
class CovFile:
    file: str
    id: str
    cells: list[Cell]
    functions: list[CovFunction]
    below: bool


@dataclass
class CovModule:
    name: str
    id: str
    cells: list[Cell]
    files: list[CovFile]
    below: bool


def coverage_page(r: Report) -> dict:
    suites = []
    for s in r.suites:
        cv = s.coverage
        metrics = [m for m in COVERAGE_METRICS if m in cv.totals]
        gate_on = bool(cv.gate_metric) and cv.gate_min is not None

        def cells(ms: dict[str, CoverageMetric]) -> list[Cell]:
            return [_cell(ms.get(m), cv.gate_min, gate_on and m == cv.gate_metric) for m in metrics]

        def gate_pct(ms: dict[str, CoverageMetric]) -> float:
            g = ms.get(cv.gate_metric) if gate_on else None
            return g.percent if g and g.total else 101.0

        modules = []
        for mod in cv.modules:
            files = []
            for f in sorted(mod.files, key=lambda f: (gate_pct(f.metrics), f.file)):
                fcells = cells(f.metrics)
                fns = [
                    CovFunction(
                        fn.name,
                        f"{fn.start_line}–{fn.end_line}" if fn.start_line else "",
                        fn.count,
                        _cell(fn.regions),
                        _cell(fn.branches),
                        fn.count == 0,
                    )
                    for fn in f.functions
                ]
                files.append(CovFile(f.file, _anchor("cov", s.name, f.file), fcells, fns, any(c.below for c in fcells)))
            mcells = cells(mod.metrics)
            modules.append(
                CovModule(mod.name, _anchor("cov", s.name, "mod", mod.name), mcells, files,
                          any(c.below for c in mcells) or any(f.below for f in files))
            )
        suites.append(
            {
                "name": s.name,
                "label": SUITE_LABELS.get(s.name, s.name),
                "id": _anchor("suite", s.name),
                "available": cv.available,
                "badge": Badge.of(cv.judgement.verdict),
                "reasons": cv.judgement.reasons,
                "gate": f"{METRIC_LABELS.get(cv.gate_metric, cv.gate_metric)} ≥ {cv.gate_min:g}%" if gate_on else "기준 없음 (보고만)",
                "headers": [METRIC_LABELS[m] for m in metrics],
                "gate_index": metrics.index(cv.gate_metric) if gate_on and cv.gate_metric in metrics else -1,
                "totals": cells(cv.totals),
                "modules": modules,
            }
        )
    return {"suites": suites}


# ------------------------------------------------------------------ Cppcheck
def cppcheck_page(r: Report) -> dict:
    cp = r.cppcheck
    th = r.config.thresholds
    gated_ids = {id(v) for v in cp.gated}
    modules = []
    for m in cp.modules:
        files = []
        for f in m.files:
            rows = [
                {
                    "line": v.line,
                    "column": v.column,
                    "severity": v.severity,
                    "sev_cls": SEVERITY_CLASS.get(v.severity, "sev-other"),
                    "rule": v.rule_id,
                    "message": v.message,
                    "verbose": v.verbose if v.verbose and v.verbose != v.message else "",
                    "cwe": v.cwe,
                    "inconclusive": v.inconclusive,
                    "gated": id(v) in gated_ids,
                }
                for v in sorted(f.items, key=lambda v: (v.line, v.column))
            ]
            gated = sum(row["gated"] for row in rows)
            files.append({"file": f.file or "(위치 없음)", "rows": rows, "gated": gated,
                          "id": _anchor("cpp", f.file or "global")})
        files.sort(key=lambda f: (-f["gated"], -len(f["rows"]), f["file"]))
        gated = sum(f["gated"] for f in files)
        modules.append({"name": m.name, "count": m.count, "gated": gated, "open": gated > 0, "files": files,
                        "by_severity": m.by_severity, "id": _anchor("cpp", "mod", m.name)})
    modules.sort(key=lambda m: (-m["gated"], -m["count"], m["name"]))
    rules = Counter(v.rule_id for v in r.data.violations)
    rule_sev = {v.rule_id: v.severity for v in r.data.violations}
    return {
        "available": cp.available,
        "verdict_badge": Badge.of(cp.judgement.verdict),
        "reasons": cp.judgement.reasons,
        "total": cp.total,
        "gated": len(cp.gated),
        "gate_paths": ", ".join(th.cppcheck_gate_paths),
        "ignored": ", ".join(th.cppcheck_ignore_severities),
        "by_severity": list(cp.by_severity.items()),
        "rules": [{"rule": k, "count": n, "severity": rule_sev[k], "sev_cls": SEVERITY_CLASS.get(rule_sev[k], "sev-other")}
                  for k, n in rules.most_common()],
        "modules": modules,
    }


# ------------------------------------------------------------------ Lizard
def lizard_page(r: Report) -> dict:
    lz = r.lizard
    th = r.config.thresholds

    def row(i):
        f = i.fn
        return {"name": f.name, "file": f.file, "line": f.line, "ccn": f.ccn, "nloc": f.nloc,
                "length": f.length, "params": f.params, "ccn_over": i.ccn_over, "length_over": i.length_over}

    modules = []
    for m in lz.modules:
        files = [{"file": f.file, "rows": [row(i) for i in sorted(f.items, key=lambda i: i.fn.line)],
                  "id": _anchor("liz", f.file)} for f in m.files]
        files.sort(key=lambda f: (-len(f["rows"]), f["file"]))
        modules.append({"name": m.name, "count": m.count, "files": files, "id": _anchor("liz", "mod", m.name)})
    modules.sort(key=lambda m: (-m["count"], m["name"]))
    return {
        "available": lz.available,
        "verdict_badge": Badge.of(lz.judgement.verdict),
        "reasons": lz.judgement.reasons,
        "ccn_limit": th.lizard_ccn,
        "length_limit": th.lizard_length,
        "count": len(lz.items),
        "ccn_over": lz.ccn_over,
        "length_over": lz.length_over,
        "modules": modules,
        "all": [row(i) for i in sorted(lz.items, key=lambda i: (-i.fn.ccn, -i.fn.length, i.fn.file))],
    }
