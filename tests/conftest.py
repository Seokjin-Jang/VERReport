from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples" / "reports"


@pytest.fixture
def samples() -> Path:
    return SAMPLES


@pytest.fixture
def write(tmp_path):
    """tmp_path 아래에 파일을 쓰고 경로를 돌려준다."""

    def _write(name: str, text: str) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    return _write
