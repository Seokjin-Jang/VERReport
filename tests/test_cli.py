from pathlib import Path

from verreport.cli import input_status, main
from verreport.config import load_config

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "verreport.toml"


def test_load_config():
    cfg = load_config(CONFIG)
    assert cfg.suites == ("unit", "integration", "tdd")
    assert cfg.thresholds.lizard_ccn == 10
    assert cfg.thresholds.lizard_length == 80
    assert cfg.thresholds.suites["unit"].coverage_metric == "mcdc"
    assert cfg.thresholds.suites["tdd"].coverage_min is None


def test_sample_inputs_exist():
    assert all(ok for _, _, ok in input_status(load_config(CONFIG)))


def test_reports_override(tmp_path):
    cfg = load_config(CONFIG, tmp_path)
    assert cfg.input("cppcheck") == tmp_path.resolve() / "cppcheck.xml"


def test_build_runs(tmp_path, capsys):
    rc = main(["build", "-c", str(CONFIG), "-o", str(tmp_path / "out")])
    assert rc == 0
    assert (tmp_path / "out").is_dir()
    assert "OK" in capsys.readouterr().out
