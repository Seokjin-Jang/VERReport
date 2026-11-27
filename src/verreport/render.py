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
        "root": "",
    }
    written: list[Path] = []

    def write(rel: str, template: str, **ctx) -> None:
        page = out / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        # 페이지 단위로 스트리밍해서 큰 페이지도 메모리에 한 번에 올리지 않는다
        with page.open("w", encoding="utf-8", newline="\n") as f:
            for chunk in env.get_template(template).generate(**{**common, **ctx}):
                f.write(chunk)
        written.append(page)

    write("index.html", "index.html", active="index", **dashboard(report))

    cov = detail.coverage_page(report)
    contexts = {
        "gtest": detail.gtest_page(report),
        "coverage": cov,
        "cppcheck": detail.cppcheck_page(report),
        "lizard": detail.lizard_page(report),
    }
    for key, name in PAGES.items():
        write(name, name, active=key, **contexts[key])

    # 모듈별 함수 커버리지 페이지. 이전 빌드에서 남은 모듈 페이지는 지운다 (없어진 모듈로 가는 링크 방지).
    cov_dir = out / detail.COV_DIR
    if cov_dir.is_dir():
        for old in cov_dir.glob("*.html"):
            old.unlink()
    for rel, ctx in detail.coverage_module_pages(cov):
        write(rel, "coverage_module.html", active="coverage", root="../", **ctx)
    return written
