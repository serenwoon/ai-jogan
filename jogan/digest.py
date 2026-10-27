"""digest.json 읽기 · 검사 · 읽기 시간.

Claude가 쓴 digest.json이 메일로 나가도 되는지 여기서 가린다.
스키마를 별도 라이브러리 없이 직접 검사하고, 위반 사항은 한국어 문장 목록으로 돌려준다.
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

CORNERS: tuple[str, ...] = ("one_line", "automation", "github", "try_this", "term")

EMPTY_NOTE = "오늘은 새 사례 없음"
DETAIL_KEYS = ("what", "why_now", "use_at_work", "lesson", "caution")

HEADLINE_MAX = 40
TITLE_MAX = 60
SUMMARY_MAX = 120
DETAIL_MAX = 400
TAGS_MAX = 3
READING_MINUTES_MAX = 5
CHARS_PER_MINUTE = 500

# 코너별 항목 수 (최소, 최대). 최소가 0인 코너만 비울 수 있다.
ITEM_COUNTS: dict[str, tuple[int, int]] = {
    "one_line": (1, 1),
    "automation": (0, 1),
    "github": (0, 2),
    "try_this": (1, 1),
    "term": (1, 1),
}

_ID_RE = re.compile(r"[a-z0-9-]+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")  # 줄바꿈·탭 포함. 제목줄·한 줄 글에 들어가면 메일 헤더와 화면이 깨진다
RESERVED_IDS = {"index"}  # docs/<날짜>/index.html 은 그날 목차 페이지다


class DigestError(Exception):
    """digest.json을 읽을 수 없을 때(파일 없음, JSON 오류, 객체가 아님)."""


def load_digest(path: Path) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise DigestError(f"digest 파일을 읽을 수 없습니다: {path} ({e})") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise DigestError(f"digest 파일이 올바른 JSON이 아닙니다: {path} ({e})") from e
    if not isinstance(data, dict):
        raise DigestError(f"digest 파일의 최상위가 JSON 객체가 아닙니다: {path}")
    return data


def _visible_strings(d) -> list[str]:
    """메일에 보이는 글(headline, 항목 title·summary, empty_note)을 모은다. 깨진 구조는 건너뛴다."""
    out: list[str] = []
    if not isinstance(d, dict):
        return out
    if isinstance(d.get("headline"), str):
        out.append(d["headline"])
    corners = d.get("corners")
    if not isinstance(corners, dict):
        return out
    for corner in CORNERS:
        c = corners.get(corner)
        if not isinstance(c, dict):
            continue
        items = c.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for key in ("title", "summary"):
                        if isinstance(item.get(key), str):
                            out.append(item[key])
        if isinstance(c.get("empty_note"), str):
            out.append(c["empty_note"])
    return out


def reading_minutes(d: dict) -> int:
    """메일에 보이는 글자 수 ÷ 500, 올림."""
    chars = sum(len(s) for s in _visible_strings(d))
    return -(-chars // CHARS_PER_MINUTE)


def _check_text(value, label: str, max_len: int, out: list[str], required: bool = True,
                single_line: bool = False) -> None:
    if not isinstance(value, str):
        out.append(f"{label}이(가) 글이 아닙니다.")
        return
    if required and not value.strip():
        out.append(f"{label}이(가) 비어 있습니다.")
    if single_line and _CONTROL_RE.search(value):
        out.append(f"{label}에 줄바꿈이나 제어 문자가 들어 있습니다.")
    if len(value) > max_len:
        out.append(f"{label}이(가) {max_len}자를 넘습니다 ({len(value)}자).")


def _is_http_url(url) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _check_item(item, where: str, seen_ids: set[str], out: list[str]) -> None:
    if not isinstance(item, dict):
        out.append(f"{where}: 항목이 객체가 아닙니다.")
        return
    item_id = item.get("id")
    if not isinstance(item_id, str) or not _ID_RE.fullmatch(item_id):
        out.append(f"{where}: id는 소문자·숫자·하이픈만 쓸 수 있습니다 ({item_id!r}).")
    elif item_id in RESERVED_IDS:
        out.append(f"{where}: id '{item_id}'는 예약된 이름이라 쓸 수 없습니다.")
    elif item_id in seen_ids:
        out.append(f"{where}: id '{item_id}'가 같은 날 안에서 겹칩니다.")
    else:
        seen_ids.add(item_id)

    _check_text(item.get("title"), f"{where}: 제목", TITLE_MAX, out, single_line=True)
    _check_text(item.get("summary"), f"{where}: 요약", SUMMARY_MAX, out, single_line=True)

    tags = item.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        out.append(f"{where}: tags는 글 목록이어야 합니다.")
    elif len(tags) > TAGS_MAX:
        out.append(f"{where}: tags는 {TAGS_MAX}개까지입니다 ({len(tags)}개).")

    detail = item.get("detail")
    if not isinstance(detail, dict):
        out.append(f"{where}: detail이 객체가 아닙니다.")
    else:
        for key in DETAIL_KEYS:
            if key not in detail:
                out.append(f"{where}: detail.{key}이(가) 없습니다.")
            else:
                _check_text(detail[key], f"{where}: detail.{key}", DETAIL_MAX, out, required=False)

    sources = item.get("sources")
    if not isinstance(sources, list) or not sources:
        out.append(f"{where}: 출처가 하나 이상 있어야 합니다.")
    else:
        for n, src in enumerate(sources, 1):
            if not isinstance(src, dict) or not isinstance(src.get("title"), str):
                out.append(f"{where}: 출처 {n}번이 title·url을 가진 객체가 아닙니다.")
            elif not _is_http_url(src.get("url")):
                out.append(f"{where}: 출처 {n}번 URL은 http 또는 https여야 합니다.")


def validate_digest(d: dict, expected_date: date) -> list[str]:
    """위반 사항을 한국어 문장 목록으로 돌려준다. 빈 목록이면 통과."""
    if not isinstance(d, dict):
        return ["digest가 JSON 객체가 아닙니다."]
    out: list[str] = []

    if d.get("date") != expected_date.isoformat():
        out.append(f"날짜가 {expected_date.isoformat()}이(가) 아닙니다 ({d.get('date')!r}).")
    _check_text(d.get("headline"), "headline", HEADLINE_MAX, out, single_line=True)

    corners = d.get("corners")
    if not isinstance(corners, dict):
        out.append("corners가 객체가 아닙니다.")
        return out

    seen_ids: set[str] = set()
    for corner in CORNERS:
        c = corners.get(corner)
        if not isinstance(c, dict):
            out.append(f"{corner} 코너가 없습니다.")
            continue
        items = c.get("items")
        if not isinstance(items, list):
            out.append(f"{corner} 코너의 items가 목록이 아닙니다.")
            continue
        low, high = ITEM_COUNTS[corner]
        note = c.get("empty_note")
        if len(items) == 0:
            if low > 0:
                out.append(f"{corner} 코너는 비울 수 없습니다 (항목 {low}개 필요).")
            elif note != EMPTY_NOTE:
                out.append(f"{corner} 코너가 비면 empty_note는 '{EMPTY_NOTE}'이어야 합니다.")
        else:
            if len(items) > high:
                out.append(f"{corner} 코너는 항목이 {high}개까지입니다 ({len(items)}개).")
            if note is not None:
                out.append(f"{corner} 코너에 항목이 있으면 empty_note는 null이어야 합니다.")
        for n, item in enumerate(items, 1):
            _check_item(item, f"{corner} {n}번째 항목", seen_ids, out)

    minutes = reading_minutes(d)
    if minutes > READING_MINUTES_MAX:
        out.append(f"읽는 시간이 {minutes}분으로 {READING_MINUTES_MAX}분을 넘습니다.")
    return out


def normalize_url(url: str) -> str:
    """utm_* 쿼리·끝 '/'·'#' 조각을 없애고 스킴·호스트를 소문자로 맞춘다."""
    url = url.strip()
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    query = "&".join(
        q for q in parts.query.split("&") if q and not q.lower().startswith("utm_")
    )
    result = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"
    if query:
        result += "?" + query
    return result
