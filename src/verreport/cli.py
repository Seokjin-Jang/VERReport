from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, load_config
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


EXIT_OK, EXIT_VERDICT_FAIL, EXIT_ERROR = 0, 1, 2


def _error(msg: str) -> int:
    print(f"오류: {msg}", file=sys.stderr)
    return EXIT_ERROR


def cmd_build(args) -> int:
    try:
        cfg = load_config(args.config, args.reports)
    except FileNotFoundError as e:
        return _error(f"설정 파일이 없습니다: {e.filename}")
    except tomllib.TOMLDecodeError as e:
        return _error(f"설정 파일 TOML 문법 오류 ({args.config}): {e}")
    except ConfigError as e:
        return _error(f"설정 오류 ({args.config}): {e}")

    print(f"reports: {cfg.reports_dir}")
    if not cfg.reports_dir.is_dir():
        print(f"경고: reports 디렉터리가 없습니다. 모든 항목이 N/A 로 표시됩니다: {cfg.reports_dir}", file=sys.stderr)
    for label, path, ok in input_status(cfg):
        print(f"  [{label:20}] {'OK' if ok else '없음':4} {path}")

    try:
        data = load(cfg, args.build_id, args.build_time, demangle=not args.no_demangle, strict=args.strict)
    except ParseError as e:
        return _error(str(e))
    data.build.commit = args.commit

    report = summarize(data, cfg)
    print_summary(report)
    try:
        pages = render(report, Path(args.output))
    except OSError as e:
        return _error(f"리포트를 쓰지 못했습니다 ({args.output}): {e}")
    print(f"리포트: {pages[0].resolve()}")
    if args.fail_on_verdict and report.judgement.verdict is Verdict.FAIL:
        return EXIT_VERDICT_FAIL
    return EXIT_OK


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
    b.add_argument(
        "--strict", action="store_true",
        help="결과 파일을 읽지 못하면 리포트를 만들지 않고 종료 코드 2 (기본: 해당 항목을 오류/FAIL 로 표시하고 계속)",
    )
    b.set_defaults(func=cmd_build)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
