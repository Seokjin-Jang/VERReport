from datetime import datetime

from verreport.config import load_config
from verreport.loader import load

from conftest import ROOT


def test_load_samples():
    data = load(load_config(ROOT / "verreport.toml"), build_id="42", demangle=False)
    assert data.build.build_id == "42"
    # 가장 이른 GTest 시각. 시간대가 없고 test_timezone 도 없으므로 현지 시각으로 본다
    assert data.build.timestamp == datetime(2026, 11, 27, 10, 0, 0).astimezone()
    assert data.build.timestamp.tzinfo is not None
    assert list(data.suites) == ["unit", "integration", "system", "tdd"]
    assert all(s.tests_available and s.coverage_available for s in data.suites.values())
    assert data.suites["integration"].coverage_totals["functions"].percent == 100.0
    assert data.cppcheck_available and len(data.violations) == 4
    assert data.lizard_available and len(data.complexity) == 2


def test_load_missing_inputs(tmp_path):
    cfg = load_config(ROOT / "verreport.toml", reports_dir=tmp_path)
    data = load(cfg, build_time=datetime(2026, 1, 1))
    assert data.build.timestamp == datetime(2026, 1, 1).astimezone()
    assert not any(s.tests_available or s.coverage_available for s in data.suites.values())
    assert not data.cppcheck_available and not data.lizard_available
