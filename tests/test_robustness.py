"""예외 상황: 깨진/빈 결과 파일, 잘못된 설정, 없는 디렉터리."""
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from verreport.aggregate import Verdict, summarize
from verreport.cli import main
from verreport.config import ConfigError, load_config
from verreport.loader import load
from verreport.parsers import ParseError
from verreport.render import render

from conftest import ROOT, SAMPLES

CONFIG = ROOT / "verreport.toml"


@pytest.fixture
def reports(tmp_path):
    """샘플 reports 를 복사한 디렉터리 (파일을 망가뜨려도 원본은 그대로)."""
    dst = tmp_path / "reports"
    shutil.copytree(SAMPLES, dst)
    return dst


def _report(reports, **kw):
    cfg = load_config(CONFIG, reports_dir=reports)
    return summarize(load(cfg, demangle=False, **kw), cfg)


# ---------------- 깨진 결과 파일 ----------------
@pytest.mark.parametrize(
    "target, content",
    [
        ("unit/results.xml", "<testsuites><testsuite"),  # 잘린 XML
        ("unit/results.xml", ""),  # 빈 파일
        ("unit/export.json", '{"data": []}'),  # 형식 다름
        ("unit/export.json", b"\xff\xfe\x00garbage"),  # 인코딩 깨짐
        ("cppcheck.xml", "<results version='1'/>"),  # v1 형식
        ("lizard.xml", "not xml at all"),
    ],
)
def test_broken_input_is_fail_not_crash(reports, target, content):
    p = reports / target
    p.write_bytes(content if isinstance(content, bytes) else content.encode())
    r = _report(reports)
    assert r.judgement.verdict is Verdict.FAIL
    assert any("읽지 못했습니다" in x for x in r.judgement.reasons)
    # 다른 도구 결과는 그대로 집계된다
    if not target.startswith("unit/results"):
        assert r.suites[0].tests.available


def test_broken_input_rendered(reports, tmp_path):
    (reports / "lizard.xml").write_text("oops", encoding="utf-8")
    render(_report(reports), tmp_path / "out")
    html = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "결과 파일 오류" in html and "Lizard 결과 파일을 읽지 못했습니다" in html
    liz = (tmp_path / "out" / "lizard.html").read_text(encoding="utf-8")
    assert "읽지 못했습니다" in liz and "결과 파일이 없습니다" not in liz


def test_strict_raises(reports):
    (reports / "cppcheck.xml").write_text("<x", encoding="utf-8")
    cfg = load_config(CONFIG, reports_dir=reports)
    with pytest.raises(ParseError):
        load(cfg, strict=True)


def test_strict_cli_exit_code(reports, tmp_path, capsys):
    (reports / "cppcheck.xml").write_text("<x", encoding="utf-8")
    args = ["build", "-c", str(CONFIG), "-r", str(reports), "-o", str(tmp_path / "o")]
    assert main(args) == 0  # 기본: 오류 항목만 FAIL 로 표시하고 리포트 생성
    assert main(args + ["--fail-on-verdict"]) == 1
    assert main(args + ["--strict"]) == 2
    assert "cppcheck.xml" in capsys.readouterr().err


def test_bom_json(reports):
    p = reports / "unit" / "export.json"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    assert _report(reports).suites[0].coverage.available


def test_timezone_timestamp(reports):
    p = reports / "unit" / "results.xml"
    p.write_text(p.read_text(encoding="utf-8").replace("2026-11-27T10:00:00", "2026-11-27T09:00:00+09:00"), encoding="utf-8")
    cfg = load_config(CONFIG, reports_dir=reports)
    # 시각에 시간대가 있으면 그대로 쓴다 (같은 순간인지 비교)
    expected = datetime(2026, 11, 27, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    assert load(cfg, demangle=False).build.timestamp == expected


@pytest.mark.parametrize(
    "tz, offset",
    [("UTC", 0), ("+09:00", 9), ("UTC+9", 9), ("UTC-5", -5), ("-05:30", -5.5), ("Mars/Olympus", None), ("+15:00", None)],
)
def test_test_timezone(reports, tmp_path, tz, offset):
    """UTC 컨테이너에서 돌린 GTest 시각(시간대 없음)을 test_timezone 으로 해석한다."""
    p = tmp_path / "c.toml"
    p.write_text("[project]\n" f'test_timezone = "{tz}"\n', encoding="utf-8")
    if offset is None:
        with pytest.raises(ConfigError, match="test_timezone"):
            load_config(p)
        return
    cfg = load_config(p, reports_dir=reports)
    ts = load(cfg, demangle=False).build.timestamp
    assert ts == datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone(timedelta(hours=offset)))
    assert ts.utcoffset() == datetime.now().astimezone().utcoffset()  # 표시는 이 컴퓨터의 현지 시각


def test_tz_label():
    from verreport.render import tz_label

    assert tz_label(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9)))) == "(UTC+09:00)"
    assert tz_label(datetime(2026, 1, 1, tzinfo=timezone(-timedelta(hours=5, minutes=30)))) == "(UTC-05:30)"
    assert tz_label(datetime(2026, 1, 1)) == ""


def test_missing_reports_dir(tmp_path, capsys):
    rc = main(["build", "-c", str(CONFIG), "-r", str(tmp_path / "nope"), "-o", str(tmp_path / "o")])
    assert rc == 0
    assert "reports 디렉터리가 없습니다" in capsys.readouterr().err
    assert (tmp_path / "o" / "index.html").exists()


# ---------------- 설정 오류 ----------------
BASE = '[inputs]\nsuites = ["unit"]\n'


@pytest.mark.parametrize(
    "toml, msg",
    [
        ("[thresholds]\nlizard_cnn = 10\n", "알 수 없는 키: lizard_cnn"),
        ("[inputz]\n", "알 수 없는 키: inputz"),
        (BASE + '[thresholds.suites.unit]\ncoverage_metric = "mcd"\ncoverage_min = 100\n', "coverage_metric 은"),
        (BASE + '[thresholds.suites.unit]\ncoverage_metric = "mcdc"\n', "함께 지정"),
        (BASE + '[thresholds.suites.unit]\ncoverage_metric = "mcdc"\ncoverage_min = 120\n', "0 이상 100 이하"),
        (BASE + "[thresholds.suites.unit]\npass_rate = true\n", "pass_rate"),
        (BASE + "[thresholds.suites.unti]\npass_rate = 100\n", "unti"),
        (BASE + "[thresholds]\nlizard_ccn = 0\n", "lizard_ccn"),
        (BASE + "[thresholds]\nlizard_ccn = 10.5\n", "정수"),
        ('[inputs]\ngtest = "results.xml"\n', "{suite}"),
        ("[inputs]\nsuites = []\n", "비어"),
        ('[project]\npath_anchors = "src"\n', "문자열 목록"),
    ],
)
def test_config_errors(tmp_path, toml, msg):
    p = tmp_path / "c.toml"
    p.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError, match=msg.replace("{", r"\{").replace("}", r"\}")):
        load_config(p)


def test_config_errors_cli(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[thresholds\n", encoding="utf-8")
    assert main(["build", "-c", str(bad), "-o", str(tmp_path / "o")]) == 2
    assert "TOML 문법 오류" in capsys.readouterr().err

    typo = tmp_path / "typo.toml"
    typo.write_text("[thresholds]\nlizard_lenght = 80\n", encoding="utf-8")
    assert main(["build", "-c", str(typo), "-o", str(tmp_path / "o")]) == 2
    assert "lizard_lenght" in capsys.readouterr().err

    assert main(["build", "-c", str(tmp_path / "none.toml"), "-o", str(tmp_path / "o")]) == 2
    assert "설정 파일이 없습니다" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()  # 설정 오류면 아무것도 쓰지 않는다
