import re
from datetime import datetime

import pytest

from verreport.aggregate import summarize
from verreport.cli import main
from verreport.config import load_config
from verreport.loader import load
from verreport.render import render

from conftest import ROOT

CONFIG = ROOT / "verreport.toml"


@pytest.fixture
def out(tmp_path):
    cfg = load_config(CONFIG)
    data = load(cfg, build_id="128", demangle=False)
    data.build.commit = "3f2a9c1"
    render(summarize(data, cfg), tmp_path)
    return tmp_path


def test_outputs(out):
    names = {p.name for p in out.iterdir()}
    assert {"index.html", "gtest.html", "coverage.html", "cppcheck.html", "lizard.html", "assets"} <= names
    assert (out / "assets" / "style.css").stat().st_size > 0


def test_csp_safe(out):
    """Jenkins HTML Publisher 기본 CSP: 스크립트, 인라인 style, 외부 리소스 금지."""
    for page in out.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "<script" not in html, page.name
        assert not re.search(r"\sstyle=", html), page.name
        assert "<style" not in html, page.name
        assert not re.search(r"(src|href)=\"(https?:)?//", html), page.name


def test_dashboard_content(out):
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "2026-11-27 10:00:00" in html  # 빌드 일시
    assert "#128" in html and "3f2a9c1" in html
    assert "badge-fail" in html and "전체 판정" in html
    assert html.count("상세 결과 보기") == 4
    for page in ("gtest.html", "coverage.html", "cppcheck.html", "lizard.html"):
        assert f'href="{page}"' in html
    assert "CalcTest.Div" in html  # 실패 테스트 목록
    assert "src/core/calc.cpp" in html  # 조치 필요 파일
    assert html.count('<svg class="bar') >= 10  # 차트


def test_gtest_page(out):
    html = (out / "gtest.html").read_text(encoding="utf-8")
    for anchor in ('id="suite-unit"', 'id="suite-integration"', 'id="suite-tdd"'):
        assert anchor in html
    # 실패가 있는 그룹(CalcTest)은 펼쳐지고, 없는 그룹은 접힌다
    assert re.search(r'<details class="node" id="t-unit-calctest" open>', html)
    assert re.search(r'<details class="node" id="t-integration-pipelinetest">', html)
    assert "Expected equality" in html and "src/core/calc.cpp:42" in html


def test_coverage_page(out):
    html = (out / "coverage.html").read_text(encoding="utf-8")
    # coverage.html: 모듈 → 파일, 파일은 모듈 페이지의 함수 상세로 연결
    assert "core" in html and "src/core/calc.cpp" in html
    assert 'href="cov/unit-core.html#cov-unit-src-core-calc-cpp"' in html
    assert '<span class="fn">' not in html  # 함수 상세는 모듈 페이지에만
    assert "is-below" in html  # unit MC/DC 미달
    # 기준 미달 모듈은 펼침, 통합 테스트(통과)의 모듈은 접힘
    assert 'id="cov-unit-mod-core" open' in html
    assert 'id="cov-integration-mod-core">' in html

    # 모듈 페이지: 파일 → 함수
    mod = (out / "cov" / "unit-core.html").read_text(encoding="utf-8")
    assert 'id="cov-unit-src-core-calc-cpp"' in mod
    assert '<span class="fn">div</span>' in mod
    assert 'class="row-fail"' in mod  # 호출 0회 함수
    assert 'href="../assets/style.css"' in mod and 'href="../index.html"' in mod
    pages = sorted(p.name for p in (out / "cov").glob("*.html"))
    assert pages == [
        "integration-core.html", "integration-io.html", "system-core.html", "system-io.html",
        "tdd-core.html", "unit-core.html", "unit-io.html",
    ]


def test_stale_module_pages_removed(tmp_path):
    cfg = load_config(CONFIG)
    (tmp_path / "cov").mkdir()
    (tmp_path / "cov" / "unit-removed.html").write_text("old", encoding="utf-8")
    (tmp_path / "cov" / "keep.txt").write_text("not ours", encoding="utf-8")
    render(summarize(load(cfg, demangle=False), cfg), tmp_path)
    assert not (tmp_path / "cov" / "unit-removed.html").exists()
    assert (tmp_path / "cov" / "keep.txt").exists()


def test_module_bars_folded():
    from collections import Counter

    from verreport.view import _count_rows

    rows = _count_rows(Counter({f"m{i}": i for i in range(1, 13)}), top=8)
    assert [r.label for r in rows][:2] == ["m12", "m11"]  # 건수 내림차순
    assert rows[-1].label == "외 4개 모듈" and rows[-1].text == str(1 + 2 + 3 + 4)
    assert len(rows) == 9
    assert len(_count_rows(Counter({"a": 1, "b": 2}), top=8)) == 2  # 접을 것이 없으면 그대로


def test_module_page_ascii_names():
    from verreport.detail import _file_slug

    assert _file_slug("unit", "core") == "unit-core"
    assert _file_slug("unit", "tests/unit") == "unit-tests-unit"
    a, b = _file_slug("unit", "C-ARB 판정기"), _file_slug("unit", "C-ARB 판독기")
    assert a.isascii() and a.startswith("unit-c-arb-") and a != b  # 한글만 다른 이름도 구분
    assert _file_slug("unit", "공통").isascii()


def test_module_page_name_collision():
    from verreport.detail import _unique

    used: set[str] = set()
    assert [_unique("cov/unit-a-b", used) for _ in range(3)] == ["cov/unit-a-b", "cov/unit-a-b-2", "cov/unit-a-b-3"]
    assert _unique("cov/UNIT-A-B", used) == "cov/UNIT-A-B-4"  # 대소문자만 다른 이름도 충돌로 본다


def test_cppcheck_page(out):
    html = (out / "cppcheck.html").read_text(encoding="utf-8")
    assert "nullPointer" in html and "57:9" in html
    assert "tests/unit/helper.cpp" in html
    assert html.count('<span class="chip chip-fail">대상</span>') == 3  # src/ 판정 대상
    assert html.count('<span class="muted">참고</span>') == 1  # tests/ 참고용


def test_lizard_page(out):
    html = (out / "lizard.html").read_text(encoding="utf-8")
    assert "parse" in html and "classify" in html
    assert html.count("is-over") == 3 * 2  # (parse CCN·길이, classify CCN) × 모듈 표/전체 표


def test_escaping(tmp_path):
    cfg = load_config(CONFIG)
    data = load(cfg, demangle=False)
    evil = "<img src=x onerror=alert(1)>"
    data.complexity[0].name = evil
    data.violations[0].message = evil
    data.suites["unit"].tests[1].message = evil
    render(summarize(data, cfg), tmp_path)
    for page in ("index.html", "lizard.html", "cppcheck.html", "gtest.html"):
        html = (tmp_path / page).read_text(encoding="utf-8")
        assert "<img src=x" not in html and "&lt;img src=x" in html, page


def test_render_without_inputs(tmp_path):
    cfg = load_config(CONFIG, reports_dir=tmp_path / "none")
    render(summarize(load(cfg, build_time=datetime(2026, 1, 1)), cfg), tmp_path / "out")
    html = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "결과 없음" in html and "badge-na" in html


def test_cli_writes_report(tmp_path, capsys):
    assert main(["build", "-c", str(CONFIG), "-o", str(tmp_path / "r")]) == 0
    assert (tmp_path / "r" / "index.html").exists()
    assert "리포트:" in capsys.readouterr().out
