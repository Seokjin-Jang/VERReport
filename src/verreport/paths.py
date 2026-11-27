"""도구마다 다른 경로 표기(절대/상대, docker /workspace, Jenkins 워크스페이스, 역슬래시)를
저장소 기준 상대 경로(posix)로 통일한다."""
from __future__ import annotations

from pathlib import Path, PurePosixPath

DEFAULT_ANCHORS = ("src", "tests")


class PathNormalizer:
    def __init__(self, source_root: Path | None = None, anchors: tuple[str, ...] = DEFAULT_ANCHORS):
        self.source_root = Path(source_root).resolve().as_posix() if source_root else None
        self.anchors = tuple(anchors)

    def __call__(self, raw: str) -> str:
        if not raw:
            return ""
        p = raw.replace("\\", "/")
        # 1) 소스 루트 아래면 상대 경로로
        if self.source_root:
            root = self.source_root.rstrip("/") + "/"
            if p.lower().startswith(root.lower()):
                p = p[len(root):]
        parts = [x for x in PurePosixPath(p).parts if x not in ("/", ".")]
        # 2) 여전히 절대 경로(다른 머신/컨테이너)면 첫 앵커 디렉터리부터 자른다
        if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
            for i, part in enumerate(parts):
                if part in self.anchors:
                    return "/".join(parts[i:])
        return "/".join(parts)
