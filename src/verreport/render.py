"""Jinja2 로 정적 HTML 리포트를 만든다.

Jenkins HTML Publisher 의 기본 CSP(default-src 'none'; style-src 'self'; img-src 'self')에서도 깨지지 않도록
- 스크립트를 쓰지 않는다(툴팁은 SVG <title>, 펼치기는 <details>),
- 인라인 style 을 쓰지 않는다(모든 스타일은 assets/style.css 의 클래스),
- 외부 리소스를 불러오지 않는다.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from . import __version__, detail
from .aggregate import Report
from .view import PAGES, dashboard


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("verreport", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["num"] = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
    return env


def _copy_assets(out: Path) -> None:
    dst = out / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    src = resources.files("verreport") / "static"
    for item in src.iterdir():
        if item.is_file():
            with resources.as_file(item) as p:
                shutil.copyfile(p, dst / item.name)


def render(report: Report, out: Path) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _copy_assets(out)
    env = _env()
    b = report.data.build
    common = {
        "build": b,
        "generated": datetime.now(),
        "version": __version__,
        "pages": PAGES,
    }
    written = []

    page = out / "index.html"
    page.write_text(env.get_template("index.html").render(**common, active="index", **dashboard(report)), encoding="utf-8")
    written.append(page)

    builders = {
        "gtest": detail.gtest_page,
        "coverage": detail.coverage_page,
        "cppcheck": detail.cppcheck_page,
        "lizard": detail.lizard_page,
    }
    for key, name in PAGES.items():
        page = out / name
        page.write_text(env.get_template(name).render(**common, active=key, **builders[key](report)), encoding="utf-8")
        written.append(page)
    return written
