"""문서목록.csv와 규칙 정리 파일을 읽고 §절로 나누는 모듈.

게임 이름에 따른 분기 없이, 어떤 규칙 정리 파일이든 같은 방식으로 처리한다.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
CATALOG_FILE = DATA_DIR / "문서목록.csv"
# 게임 이미지: assets/images/{문서ID}.svg(또는 png · jpg · webp). 없으면 이미지 없이 보여 준다.
IMAGE_DIR = Path(__file__).parent / "assets" / "images"
IMAGE_TYPES = (".svg", ".png", ".jpg", ".jpeg", ".webp")
REQUIRED_COLUMNS =["문서ID", "게임명", "판본", "언어", "파일", "공식출처", "조회일", "설명"]

# 예: "§3 차례 진행 (원문 2~3쪽 · LET'S PLAY!)"
SECTION_HEADER = re.compile(r"^§(\d+)\s+(.+?)\s*\(원문\s*([^)·]+?)\s*(?:·\s*([^)]*))?\)\s*$")


@dataclass
class Section:
    number: int
    title: str
    pages: str  # 예: "2~3쪽"
    original_heading: str  # 원문 영어 소제목(없으면 빈 문자열)
    body: str

    @property
    def label(self) -> str:
        return f"§{self.number} {self.title}"


@dataclass
class Game:
    doc_id: str
    name: str
    edition: str
    language: str
    file: str
    source_url: str
    accessed: str
    description: str
    header: str = ""  # 첫 절 앞의 머리말(문서ID · 제목 · 안내 등)
    sections: list[Section] = field(default_factory=list)
    error: str | None = None  # 쓸 수 없는 이유. None이면 사용 가능

    @property
    def available(self) -> bool:
        return self.error is None

    @property
    def image(self) -> Path | None:
        candidates = (IMAGE_DIR / f"{self.doc_id}{ext}" for ext in IMAGE_TYPES)
        return next((p for p in candidates if p.is_file()), None)

    def section(self, number: int) -> Section | None:
        return next((s for s in self.sections if s.number == number), None)


class CatalogError(Exception):
    """문서목록.csv 자체를 쓸 수 없을 때."""


def parse_sections(text: str) -> tuple[str, list[Section]]:
    """규칙 정리 본문을 머리말과 §절 목록으로 나눈다."""
    header_lines: list[str] = []
    sections: list[Section] = []
    current: dict | None = None
    body_lines: list[str] = []

    def close_current():
        if current is not None:
            sections.append(Section(body="\n".join(body_lines).strip(), **current))

    for line in text.splitlines():
        match = SECTION_HEADER.match(line.strip())
        if match:
            close_current()
            number, title, pages, original = match.groups()
            current = {
                "number": int(number),
                "title": title.strip(),
                "pages": pages.strip(),
                "original_heading": (original or "").strip(),
            }
            body_lines = []
        elif current is None:
            header_lines.append(line)
        else:
            body_lines.append(line)
    close_current()
    return "\n".join(header_lines).strip(), sections


def load_game(row: dict) -> Game:
    """목록 한 줄과 그 규칙 정리 파일을 읽는다. 문제가 있으면 error에 이유를 담는다."""
    game = Game(
        doc_id=row["문서ID"],
        name=row["게임명"],
        edition=row["판본"],
        language=row["언어"],
        file=row["파일"],
        source_url=row["공식출처"],
        accessed=row["조회일"],
        description=row["설명"],
    )
    path = DATA_DIR / game.file
    if not path.is_file():
        game.error = f"규칙 파일이 없습니다 (data/{game.file})"
        return game
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        game.error = f"규칙 파일이 비어 있습니다 (data/{game.file})"
        return game
    game.header, game.sections = parse_sections(text)
    if not game.sections:
        game.error = f"규칙 파일에서 §절을 찾지 못했습니다 (data/{game.file})"
    return game


def load_catalog() -> list[Game]:
    """문서목록.csv의 모든 게임을 읽는다. 쓸 수 없는 게임도 error와 함께 돌려준다."""
    if not CATALOG_FILE.is_file():
        raise CatalogError("data/문서목록.csv 파일이 없습니다.")
    df = pd.read_csv(CATALOG_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CatalogError(f"문서목록.csv에 필수 열이 없습니다: {', '.join(missing)}")
    rows = df[df["문서ID"].str.strip() != ""].to_dict("records")
    return [load_game(row) for row in rows]
