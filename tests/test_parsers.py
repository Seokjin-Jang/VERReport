import pytest

from verreport.models import Status
from verreport.parsers import ParseError, cppcheck, gtest, lizard, llvmcov
from verreport.paths import PathNormalizer


# ---------------- paths ----------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("src/core/calc.cpp", "src/core/calc.cpp"),
        ("./src/core/calc.cpp", "src/core/calc.cpp"),
        ("src\\core\\calc.cpp", "src/core/calc.cpp"),
        ("/workspace/src/core/calc.cpp", "src/core/calc.cpp"),
        ("/var/jenkins_home/workspace/job/tests/unit/a.cpp", "tests/unit/a.cpp"),
        ("/usr/include/stdio.h", "usr/include/stdio.h"),
        ("", ""),
    ],
)
def test_path_normalizer(raw, expected):
    assert PathNormalizer()(raw) == expected


def test_path_normalizer_source_root(tmp_path):
    norm = PathNormalizer(tmp_path)
    assert norm(str(tmp_path / "lib" / "x.c")) == "lib/x.c"


# ---------------- gtest ----------------
def test_gtest_sample(samples):
    cases, stamp = gtest.parse(samples / "unit" / "results.xml")
    assert stamp == "2026-11-27T10:00:00"
    by = {c.name: c for c in cases}
    assert len(cases) == 4
    assert by["Add"].status is Status.PASS
    assert by["Div"].status is Status.FAIL
    assert "src/core/calc.cpp:42" in by["Div"].message
    assert (by["Div"].file, by["Div"].line) == ("src/core/calc.cpp", 42)  # 실패 본문에서 위치 보완
    assert by["Add"].file == ""
    assert by["Read"].status is Status.SKIP
    assert by["Read"].suite == "IoTest"


def test_gtest_new_format_skip_and_location(write):
    p = write("r.xml", """<testsuites><testsuite name="S">
      <testcase name="A" file="/workspace/tests/unit/a.cpp" line="7" status="run" result="skipped" time="0" classname="S">
        <skipped message="not ready"/></testcase>
      <testcase name="B" status="run" result="completed" time="0.5" classname="S"/>
    </testsuite></testsuites>""")
    cases, _ = gtest.parse(p, PathNormalizer())
    assert cases[0].status is Status.SKIP and cases[0].message == "not ready"
    assert (cases[0].file, cases[0].line) == ("tests/unit/a.cpp", 7)
    assert cases[1].status is Status.PASS and cases[1].time_sec == 0.5


@pytest.mark.parametrize(
    "text, loc",
    [
        ("/workspace/tests/unit/a.cpp:12\nExpected", ("tests/unit/a.cpp", 12)),
        ("C:\\w\\tests\\unit\\a.cpp(12): error: x", ("tests/unit/a.cpp", 12)),
        ("Expected equality", ("", 0)),
    ],
)
def test_gtest_failure_location(write, text, loc):
    p = write("r.xml", f"""<testsuites><testsuite name="S"><testcase name="A" status="run" classname="S">
      <failure message="m"><![CDATA[{text}]]></failure></testcase></testsuite></testsuites>""")
    (case,), _ = gtest.parse(p, PathNormalizer())
    assert (case.file, case.line) == loc


def test_gtest_rejects_other_xml(write):
    with pytest.raises(ParseError):
        gtest.parse(write("r.xml", "<results/>"))
    with pytest.raises(ParseError):
        gtest.parse(write("b.xml", "<testsuites"))


# ---------------- llvm-cov ----------------
def test_llvmcov_sample(samples):
    files, totals = llvmcov.parse(samples / "unit" / "export.json", use_demangler=False)
    assert totals["mcdc"].covered == 5 and totals["mcdc"].total == 12
    calc = next(f for f in files if f.file == "src/core/calc.cpp")
    assert calc.metrics["lines"].percent == pytest.approx(85.0)
    assert [f.name for f in calc.functions] == ["add", "div"]
    div = calc.functions[1]
    assert (div.start_line, div.end_line, div.count) == (10, 20, 0)
    assert div.regions.covered == 0 and div.regions.total == 1


def test_llvmcov_functions_detail(write):
    p = write("e.json", """{"data":[{"files":[{"filename":"/workspace/src/a.cpp","summary":{
        "lines":{"count":10,"covered":5}}}],
      "functions":[
        {"name":"/workspace/src/a.cpp:helper","count":3,"filenames":["/workspace/src/a.cpp"],
         "regions":[[1,1,9,2,3,0,0,0],[4,5,4,9,0,0,0,0],[2,1,2,5,9,1,0,1]],
         "branches":[[3,7,3,12,3,0,0,0,4],[5,7,5,12,1,2,0,0,4]]},
        {"name":"_Z5otherv","count":0,"filenames":["/usr/include/x.h"],"regions":[]}],
      "totals":{"lines":{"count":10,"covered":5}}}]}""")
    files, totals = llvmcov.parse(p, PathNormalizer(), use_demangler=False)
    assert [f.file for f in files] == ["src/a.cpp"]
    (fn,) = files[0].functions  # 제외된 파일의 함수는 버림
    assert fn.name == "helper"  # static 접두어 제거
    assert (fn.start_line, fn.end_line) == (1, 9)
    assert (fn.regions.covered, fn.regions.total) == (1, 2)  # 다른 fileID 영역 제외
    assert (fn.branches.covered, fn.branches.total) == (3, 4)
    assert totals["lines"].percent == 50.0


def test_llvmcov_rejects_bad_json(write):
    with pytest.raises(ParseError):
        llvmcov.parse(write("e.json", "{}"))
    with pytest.raises(ParseError):
        llvmcov.parse(write("e.json", "{not json"))


def test_demangle_without_tool(monkeypatch):
    monkeypatch.setattr(llvmcov.shutil, "which", lambda _: None)
    assert llvmcov.demangle(["_Z3addii", "main"]) == {"_Z3addii": "_Z3addii", "main": "main"}


# ---------------- cppcheck ----------------
def test_cppcheck_sample(samples):
    vs = cppcheck.parse(samples / "cppcheck.xml")
    assert len(vs) == 4
    v = vs[0]
    assert (v.severity, v.rule_id, v.file, v.line, v.column) == ("error", "nullPointer", "src/core/calc.cpp", 57, 9)
    assert {v.file for v in vs} >= {"tests/unit/helper.cpp"}


def test_cppcheck_global_and_ignored(write):
    p = write("c.xml", """<results version="2"><cppcheck version="2.13"/><errors>
      <error id="missingIncludeSystem" severity="information" msg="m"/>
      <error id="checkersReport" severity="information" msg="Active checkers"/>
      <error id="knownConditionTrueFalse" severity="style" msg="x" cwe="570" inconclusive="true">
        <location file="/workspace/src/a.c" line="3" column="4"/><location file="src/a.c" line="1"/></error>
    </errors></results>""")
    vs = cppcheck.parse(p, PathNormalizer())
    assert [v.rule_id for v in vs] == ["missingIncludeSystem", "knownConditionTrueFalse"]
    assert vs[0].file == ""
    assert (vs[1].file, vs[1].line, vs[1].cwe, vs[1].inconclusive) == ("src/a.c", 3, 570, True)


def test_cppcheck_rejects_v1(write):
    with pytest.raises(ParseError):
        cppcheck.parse(write("c.xml", "<results><error file='a' line='1' id='x' severity='style' msg='m'/></results>"))


# ---------------- lizard ----------------
def test_lizard_sample(samples):
    fs = lizard.parse(samples / "lizard.xml")
    parse = next(f for f in fs if f.name == "parse")
    assert (parse.file, parse.line, parse.ccn, parse.nloc, parse.length, parse.params) == (
        "src/io/reader.cpp", 20, 14, 95, 112, 3
    )


@pytest.mark.parametrize(
    "msg, name, ccn, length",
    [
        ("Ns::Cls::run has 12 NLOC, 11 CCN, 80 token, 0 PARAM, 15 length", "Ns::Cls::run", 11, 15),
        ("operator ( ) has 90 NLOC, 2 CCN, 400 token, 1 PARAM, 95 length, 2 ND", "operator ( )", 2, 95),
    ],
)
def test_lizard_message(msg, name, ccn, length):
    n, s = lizard.parse_message(msg)
    assert (n, s["CCN"], s["LENGTH"]) == (name, ccn, length)


def test_lizard_empty_and_bad(write):
    assert lizard.parse(write("l.xml", '<checkstyle version="4.3"/>')) == []
    bad = write("b.xml", '<checkstyle><file name="a.c"><error line="1" message="??" source="lizard"/></file></checkstyle>')
    with pytest.raises(ParseError):
        lizard.parse(bad)
