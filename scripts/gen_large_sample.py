#!/usr/bin/env python3
"""성능 확인용 대용량 reports/ 를 만든다 (실제 도구 출력과 같은 형식).

사용법: python scripts/gen_large_sample.py <출력 디렉터리> [--modules 50] [--files 40] [--funcs 15]
         [--tests 3000] [--cppcheck 5000] [--lizard 800]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from xml.sax.saxutils import quoteattr

SUITES = ("unit", "integration", "tdd")
SEVERITIES = ("error", "warning", "style", "performance", "portability", "information")
RULES = ("nullPointer", "unusedVariable", "passedByValue", "knownConditionTrueFalse", "constParameter",
         "shadowVariable", "uninitvar", "missingIncludeSystem", "unreadVariable", "variableScope")


def files_of(n_mod: int, n_file: int) -> list[str]:
    return [f"/workspace/src/mod{m:02d}/file{f:03d}.cpp" for m in range(n_mod) for f in range(n_file)]


def metric(rng: random.Random, total: int, lo: float) -> dict:
    covered = int(total * rng.uniform(lo, 1.0))
    return {"count": total, "covered": covered, "percent": 100.0 * covered / total if total else 0.0}


def gen_coverage(path: Path, files: list[str], n_func: int, rng: random.Random, lo: float) -> None:
    fentries, funcs = [], []
    totals = {k: [0, 0] for k in ("lines", "functions", "branches", "mcdc", "regions")}
    for fname in files:
        summary = {
            "lines": metric(rng, rng.randint(80, 600), lo),
            "functions": metric(rng, n_func, lo),
            "branches": metric(rng, rng.randint(10, 120), lo),
            "mcdc": metric(rng, rng.randint(4, 60), lo),
            "regions": metric(rng, rng.randint(20, 200), lo),
        }
        for k, v in summary.items():
            totals[k][0] += v["count"]
            totals[k][1] += v["covered"]
        fentries.append({"filename": fname, "summary": summary})
        line = 1
        for i in range(n_func):
            count = rng.choice((0, 1, 3, 10, 120))
            regions = [[line + j * 3, 1, line + j * 3 + 2, 2, count if j % 3 else 0, 0, 0, 0] for j in range(6)]
            branches = [[line + j, 5, line + j, 9, rng.randint(0, 3), rng.randint(0, 3), 0, 0, 4] for j in range(4)]
            funcs.append({"name": f"_ZN5mod{i:02d}9function{i:02d}Ev", "count": count, "regions": regions,
                          "branches": branches, "filenames": [fname]})
            line += 25
    doc = {"type": "llvm.coverage.json.export", "version": "2.0.1", "data": [{
        "files": fentries, "functions": funcs,
        "totals": {k: {"count": c, "covered": v, "percent": 100.0 * v / c if c else 0.0} for k, (c, v) in totals.items()},
    }]}
    path.write_text(json.dumps(doc), encoding="utf-8")


def gen_gtest(path: Path, n_tests: int, rng: random.Random, files: list[str]) -> None:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites tests="{n_tests}" name="AllTests" timestamp="2026-11-27T10:00:00">']
    per = 25
    for s in range(0, n_tests, per):
        out.append(f'  <testsuite name="Suite{s // per:04d}">')
        for t in range(min(per, n_tests - s)):
            r = rng.random()
            attrs = f'name="Case{t:02d}" classname="Suite{s // per:04d}" time="{rng.random() / 100:.4f}"'
            if r < 0.01:
                f = rng.choice(files)
                out.append(f'    <testcase {attrs} status="run"><failure message="boom"><![CDATA[{f}:{rng.randint(1, 500)}\n'
                           f'Expected equality of these values:\n  a\n    Which is: 1\n  b\n    Which is: 2]]></failure></testcase>')
            elif r < 0.02:
                out.append(f'    <testcase {attrs} status="notrun" result="suppressed"/>')
            else:
                out.append(f'    <testcase {attrs} status="run"/>')
        out.append("  </testsuite>")
    out.append("</testsuites>")
    path.write_text("\n".join(out), encoding="utf-8")


def gen_cppcheck(path: Path, n: int, rng: random.Random, files: list[str]) -> None:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<results version="2">', '  <cppcheck version="2.13"/>', "  <errors>"]
    for _ in range(n):
        f = rng.choice(files) if rng.random() < 0.9 else "/workspace/tests/unit/test_x.cpp"
        msg = quoteattr(f"Message for {rng.choice(RULES)} with detail {rng.randint(0, 9999)}")
        out.append(f'    <error id="{rng.choice(RULES)}" severity="{rng.choice(SEVERITIES)}" msg={msg} verbose={msg}>'
                   f'<location file="{f}" line="{rng.randint(1, 600)}" column="{rng.randint(1, 40)}"/></error>')
    out += ["  </errors>", "</results>"]
    path.write_text("\n".join(out), encoding="utf-8")


def gen_lizard(path: Path, n: int, rng: random.Random, files: list[str]) -> None:
    by_file: dict[str, list[str]] = {}
    for i in range(n):
        f = rng.choice(files).replace("/workspace/", "")
        ccn, length = rng.randint(5, 40), rng.randint(20, 300)
        by_file.setdefault(f, []).append(
            f'<error line="{rng.randint(1, 600)}" column="0" severity="error" '
            f'message="ns::Cls::method{i} has {length - 5} NLOC, {ccn} CCN, {length * 6} token, {rng.randint(0, 6)} PARAM, {length} length" source="lizard"/>'
        )
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<checkstyle version="4.3">']
    for f, errs in by_file.items():
        out.append(f'  <file name="{f}">')
        out += [f"    {e}" for e in errs]
        out.append("  </file>")
    out.append("</checkstyle>")
    path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--modules", type=int, default=50)
    ap.add_argument("--files", type=int, default=40)
    ap.add_argument("--funcs", type=int, default=15)
    ap.add_argument("--tests", type=int, default=3000)
    ap.add_argument("--cppcheck", type=int, default=5000)
    ap.add_argument("--lizard", type=int, default=800)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    files = files_of(a.modules, a.files)
    for i, s in enumerate(SUITES):
        d = a.out / s
        d.mkdir(parents=True, exist_ok=True)
        gen_gtest(d / "results.xml", a.tests, rng, files)
        gen_coverage(d / "export.json", files, a.funcs, rng, lo=(0.5, 0.8, 0.1)[i])
    gen_cppcheck(a.out / "cppcheck.xml", a.cppcheck, rng, files)
    gen_lizard(a.out / "lizard.xml", a.lizard, rng, files)
    print(f"생성: {a.out} (파일 {len(files)}개, 함수 {len(files) * a.funcs}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
