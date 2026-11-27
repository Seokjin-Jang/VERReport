from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .aggregate import Report, Verdict, summarize
from .loader import load
from .parsers import ParseError
from .render import render


def input_status(cfg: Config) -> list[tuple[str, Path, bool]]:
    rows = []
    for suite in cfg.suites:
        for tool in ("gtest", "llvmcov"):
            p = cfg.suite_input(tool, suite)
            rows.append((f"{suite}/{tool}", p, p.exists()))
    for tool in ("cppcheck", "lizard"):
        p = cfg.input(tool)
        rows.append((tool, p, p.exists()))
    return rows


_MARK = {Verdict.PASS: "PASS", Verdict.FAIL: "FAIL", Verdict.NA: "N/A "}


def print_summary(r: Report) -> None:
    b = r.data.build
    print(f"빌드: {b.project} {b.build_id} @ {b.timestamp:%Y-%m-%d %H:%M:%S}  => {_MARK[r.judgement.verdict]}")
    for s in r.suites:
        c = s.tests.counts
        tests = f"pass {c.passed} / fail {c.failed} / skip {c.skipped}" if s.tests.available else "결과 없음"
        cov = s.coverage
        if cov.available and cov.gate_metric in cov.totals:
            gate = f"{cov.gate_metric} {cov.totals[cov.gate_metric].percent:.1f}% (기준 {cov.gate_min:g}%)"
        elif cov.available:
            gate = "커버리지 기준 없음"
        else:
            gate = "커버리지 없음"
        print(f"  {_MARK[s.judgement.verdict]} [{s.name:11}] {tests} | {gate}")
    cp, lz = r.cppcheck, r.lizard
    print(f"  {_MARK[cp.judgement.verdict]} [cppcheck   ] 판정 대상 {len(cp.gated)}건 / 전체 {cp.total}건")
    print(f"  {_MARK[lz.judgement.verdict]} [lizard     ] CCN 초과 {lz.ccn_over} / 길이 초과 {lz.length_over}")
    for reason in r.judgement.reasons:
        print(f"    - {reason}")
    for w in r.warnings:
        print(f"    ! {w}")


def cmd_build(args) -> int:
    cfg = load_config(args.config, args.reports)
    print(f"reports: {cfg.reports_dir}")
    for label, path, ok in input_status(cfg):
        print(f"  [{label:20}] {'OK' if ok else '없음':4} {path}")
    try:
        data = load(cfg, args.build_id, args.build_time, demangle=not args.no_demangle)
        data.build.commit = args.commit
    except ParseError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    report = summarize(data, cfg)
    print_summary(report)
    pages = render(report, Path(args.output))
    print(f"리포트: {pages[0].resolve()}")
    if args.fail_on_verdict and report.judgement.verdict is Verdict.FAIL:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 파이프/CI 로그에서 한글이 cp949 로 깨지지 않도록 UTF-8 로 출력한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="verreport")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="검증 결과 HTML 리포트 생성")
    b.add_argument("-c", "--config", type=Path, default=None, help="설정 TOML")
    b.add_argument("-r", "--reports", type=Path, default=None, help="reports 디렉터리 (설정보다 우선)")
    b.add_argument("-o", "--output", default="report", help="HTML 출력 디렉터리")
    b.add_argument("--build-id", default="", help="빌드 번호 (예: Jenkins BUILD_NUMBER)")
    b.add_argument("--commit", default="", help="커밋 해시 (예: Jenkins GIT_COMMIT)")
    b.add_argument(
        "--build-time", type=datetime.fromisoformat, default=None,
        help="빌드 시각 ISO 형식. 생략 시 GTest 실행 시각 → reports 수정 시각 순으로 사용",
    )
    b.add_argument("--no-demangle", action="store_true", help="C++ 함수명 디맹글 생략")
    b.add_argument("--fail-on-verdict", action="store_true", help="전체 판정이 FAIL 이면 종료 코드 1")
    b.set_defaults(func=cmd_build)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
