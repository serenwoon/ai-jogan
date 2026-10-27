"""주간 노트 검사. 볼트로 들어갈 파일이라 볼트의 프론트매터 규칙을 그대로 잰다."""
import re

REQUIRED_KEYS = ("title", "tags", "type", "status", "created", "updated")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LINK = re.compile(r"\]\(https?://[^)\s]+\)")


def _frontmatter(text: str) -> dict[str, str] | None:
    """맨 앞 `---` 두 줄 사이의 `키: 값`. 없으면 None."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    last: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if line.lstrip().startswith("- ") and last is not None:  # 블록 형식 목록(tags:\n  - a)
            fields[last] = (fields[last] + " " + line.strip()).strip()
            continue
        key, sep, value = line.partition(":")
        if sep and key and not key.startswith((" ", "\t", "-")):
            last = key.strip()
            fields[last] = value.strip()
    return None  # 닫는 줄이 없다


def validate_weekly(text: str, week: str) -> list[str]:
    """위반 사항을 한국어 문장 목록으로 돌려준다. 빈 목록이면 통과."""
    out: list[str] = []
    if "\r" in text:
        out.append("줄바꿈에 CR(\\r)이 들어 있습니다. LF만 써야 합니다.")
    text = text.replace("\r\n", "\n")

    fm = _frontmatter(text)
    if fm is None:
        out.append("맨 앞에 `---`로 감싼 프론트매터가 없습니다.")
        fm = {}
    else:
        for key in REQUIRED_KEYS:
            if key not in fm:
                out.append(f"프론트매터에 {key}이(가) 없습니다.")
        expected_title = f"AI 조간 주간 {week}"
        if "title" in fm and fm["title"].strip("\"'") != expected_title:
            out.append(f"title은 '{expected_title}'이어야 합니다 ({fm['title']!r}).")
        if "tags" in fm and fm["tags"] in ("", "[]"):
            out.append("tags가 비어 있습니다.")
        if "type" in fm and fm["type"] != "reference":
            out.append(f"type은 reference여야 합니다 ({fm['type']!r}).")
        if "status" in fm and fm["status"] != "미학습":
            out.append(f"status는 미학습이어야 합니다 ({fm['status']!r}).")
        for key in ("created", "updated"):
            if key in fm and not _ISO_DATE.fullmatch(fm[key]):
                out.append(f"{key}는 YYYY-MM-DD 형식이어야 합니다 ({fm[key]!r}).")

    if not _LINK.search(text):
        out.append("본문에 http(s) 링크가 하나도 없습니다.")
    return out
