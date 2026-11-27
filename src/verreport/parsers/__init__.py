"""도구별 파서. 입력 파일을 공통 모델(models.py)로 변환한다."""
from __future__ import annotations

from pathlib import Path


class ParseError(Exception):
    """입력 파일이 해당 도구의 형식이 아니거나 손상된 경우."""

    def __init__(self, path: Path, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
