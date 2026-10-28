"""digest.json → 아침 메일 HTML · GitHub Pages 상세 페이지 · 목차.

AI 없이 템플릿만 쓴다. 같은 입력이면 같은 출력이 나오도록 시각 같은 값은 넣지 않는다.
"""
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from jogan.dates import korean_date_label
from jogan.digest import CORNERS, DETAIL_KEYS, EMPTY_NOTE, DigestError, load_digest, reading_minutes

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
INDEX_DAYS = 30

CORNER_LABELS: dict[str, str] = {
    "one_line": "① 오늘의 한 줄",
    "automation": "② 업무 자동화 사례",
    "github": "③ 깃허브·스킬 픽",
    "try_this": "④ 따라 해보기",
    "term": "⑤ 1분 용어",
}

DETAIL_HEADINGS: dict[str, str] = {
    "what": "무엇인가",
    "why_now": "왜 지금 화제인가",
    "use_at_work": "내 업무에 쓸 자리",
    "lesson": "배울 점",
    "caution": "주의",
}

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# autoescape=True: 제목·요약·출처 제목·URL은 모두 속성/본문 이스케이프를 거친다.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def item_url(base_url: str, d: date, item_id: str) -> str:
    return f"{base_url.rstrip('/')}/{d.isoformat()}/{item_id}.html"


def _safe_href(url) -> str:
    """앞뒤 공백을 떼고 http/https만 돌려준다. 그 밖은 빈 문자열(링크 없이 글로만 보인다)."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and parts.netloc:
        return url
    return ""


def _mail_view(digest: dict, site: dict, link_for) -> dict:
    d = date.fromisoformat(digest["date"])
    label = korean_date_label(d)
    corners = []
    for key in CORNERS:
        corner = digest["corners"][key]
        items = [{**it, "url": link_for(it["id"])} for it in corner["items"]]
        corners.append(
            {
                "key": key,
                "label": CORNER_LABELS[key],
                "entries": items,
                "empty_note": corner.get("empty_note") or EMPTY_NOTE,
            }
        )
    return {
        "subject": site["subject_format"].format(label=label, headline=digest["headline"]),
        "mail_title": site["mail_title"],
        "label": label,
        "minutes": reading_minutes(digest),
        "corners": corners,
    }


def render_email(digest: dict, site: dict) -> tuple[str, str]:
    """(제목줄, 메일 HTML). 링크는 절대 주소, 스타일은 모두 인라인."""
    d = date.fromisoformat(digest["date"])
    view = _mail_view(digest, site, lambda item_id: item_url(site["base_url"], d, item_id))
    view["index_url"] = site["base_url"].rstrip("/") + "/"
    html = _env.get_template("email.html.j2").render(v=view)
    return view["subject"], html


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def _detail_view(digest: dict, site: dict, corner_key: str, item: dict) -> dict:
    label = korean_date_label(date.fromisoformat(digest["date"]))
    sections = []
    for key in DETAIL_KEYS:
        text = (item["detail"].get(key) or "").strip()
        if text:
            sections.append({"heading": DETAIL_HEADINGS[key], "text": text, "warn": key == "caution"})
    sources = [
        {"title": s.get("title", ""), "url": _safe_href(s.get("url"))} for s in item["sources"]
    ]
    return {
        "page_title": f"{item['title']} — {site['mail_title']} {label}",
        "mail_title": site["mail_title"],
        "label": label,
        "corner_label": CORNER_LABELS[corner_key],
        "item": {**item, "sources": sources},
        "sections": sections,
    }


def _index_entries(digest: dict, issues_dir: Path) -> list[dict]:
    """issues/*/digest.json 과 지금 digest 를 합쳐 최근 30개를 새것부터 돌려준다."""
    by_date: dict[str, str] = {}
    issues_dir = Path(issues_dir)
    if issues_dir.is_dir():
        for folder in issues_dir.iterdir():
            if not (folder.is_dir() and _ISO_DATE.fullmatch(folder.name)):
                continue
            try:
                past = load_digest(folder / "digest.json")
            except DigestError:
                continue
            headline = past.get("headline")
            if isinstance(headline, str) and headline.strip():
                by_date[folder.name] = headline
    by_date[digest["date"]] = digest["headline"]  # 지금 digest 가 이긴다
    entries = []
    for iso in sorted(by_date, reverse=True)[:INDEX_DAYS]:
        entries.append(
            {"date": iso, "label": korean_date_label(date.fromisoformat(iso)), "headline": by_date[iso]}
        )
    return entries


def render_site(digest: dict, site: dict, docs_dir: Path, issues_dir: Path) -> list[Path]:
    """docs/<날짜>/index.html · docs/<날짜>/<id>.html · docs/index.html · docs/.nojekyll 을 쓴다.

    쓴 파일 목록을 돌려준다. 그날 폴더에 남은 옛 항목 페이지(id 가 바뀐 경우)는 지운다.
    """
    docs_dir = Path(docs_dir)
    iso = digest["date"]
    day_dir = docs_dir / iso
    written: list[Path] = []

    day_view = _mail_view(digest, site, lambda item_id: f"{item_id}.html")
    day_view["index_url"] = "../index.html"
    written.append(_write(day_dir / "index.html", _env.get_template("day.html.j2").render(v=day_view)))

    detail_tpl = _env.get_template("detail.html.j2")
    for key in CORNERS:
        for item in digest["corners"][key]["items"]:
            view = _detail_view(digest, site, key, item)
            written.append(_write(day_dir / f"{item['id']}.html", detail_tpl.render(v=view)))

    keep = {p.name for p in written}
    for old in sorted(day_dir.glob("*.html")):
        if old.name not in keep:
            old.unlink()

    index_html = _env.get_template("index.html.j2").render(
        mail_title=site["mail_title"], entries=_index_entries(digest, issues_dir)
    )
    written.append(_write(docs_dir / "index.html", index_html))
    written.append(_write(docs_dir / ".nojekyll", ""))
    return written


# ---------- 평문 본문 ----------

_BLOCK_GAP = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table"}
_BLOCK_LINE = {"div", "li", "tr", "section", "article", "header", "footer", "blockquote", "hr"}
_SKIP = {"head", "title", "style", "script"}


class _TextExtractor(HTMLParser):
    # 자체 상태는 _jg_ 접두사로 둔다. HTMLParser가 판마다 내부 속성(예: 3.12.15의 _pending)을 늘려서, 같은 이름을 쓰면 close()가 깨진다.
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._jg_skip = 0
        self._jg_pending = 0  # 다음 글 앞에 넣을 줄바꿈 수(1 = 줄바꿈, 2 = 빈 줄)
        self._jg_href: str | None = None
        self._jg_link_text: list[str] = []

    def _jg_break(self, n: int) -> None:
        self._jg_pending = max(self._jg_pending, n)

    def _jg_put(self, s: str) -> None:
        if self._jg_pending and self.parts:
            self.parts.append("\n" * self._jg_pending)
        self._jg_pending = 0
        self.parts.append(s)

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._jg_skip += 1
        elif tag == "br":
            self._jg_pending = min(2, self._jg_pending + 1)
        elif tag in _BLOCK_GAP:
            self._jg_break(2)
        elif tag in _BLOCK_LINE:
            self._jg_break(1)
        elif tag == "a":
            self._jg_href = dict(attrs).get("href") or ""
            self._jg_link_text = []

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._jg_skip = max(0, self._jg_skip - 1)
        elif tag in _BLOCK_GAP:
            self._jg_break(2)
        elif tag in _BLOCK_LINE:
            self._jg_break(1)
        elif tag == "a" and self._jg_href is not None:
            href, self._jg_href = self._jg_href, None
            text = re.sub(r"\s+", " ", "".join(self._jg_link_text)).strip()
            if href and text != href:
                self._jg_put(f" ({href})" if text else href)

    def handle_data(self, data):
        if self._jg_skip:
            return
        data = re.sub(r"\s+", " ", data)  # 소스의 줄바꿈은 공백일 뿐, 줄은 블록 태그가 만든다
        if self._jg_pending and not data.strip():
            return
        if self._jg_href is not None:
            self._jg_link_text.append(data)
        self._jg_put(data)


def html_to_text(html: str) -> str:
    """메일 평문 본문. 링크는 「글 (주소)」, 블록은 줄바꿈, 공백은 한 칸으로 모은다."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    raw = "".join(parser.parts)
    lines = [re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in raw.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip("\n")
