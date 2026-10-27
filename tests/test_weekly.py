from pathlib import Path

import pytest

from jogan.weekly import validate_weekly

FIX = Path(__file__).resolve().parent / "fixtures"
WEEK = "2026-W43"


def ok_text() -> str:
    # read_text 는 줄바꿈을 바꾸므로 바이트로 읽는다
    return (FIX / "weekly_ok.md").read_bytes().decode("utf-8")


def test_validate_weekly_ok_fixture():
    assert validate_weekly(ok_text(), WEEK) == []


def test_validate_weekly_rejects_crlf_and_missing_status():
    crlf = validate_weekly(ok_text().replace("\n", "\r\n"), WEEK)
    assert any("CR" in v for v in crlf)

    no_status = "\n".join(line for line in ok_text().split("\n") if not line.startswith("status:"))
    assert any("status" in v for v in validate_weekly(no_status, WEEK))


@pytest.mark.parametrize(
    "old, new, word",
    [
        ("type: reference", "type: 학습노트", "type"),
        ("status: 미학습", "status: 학습", "status"),
        ("title: AI 조간 주간 2026-W43", "title: AI 조간 주간 2026-W42", "title"),
        ("tags: [AI, 동향, 주간]", "tags: []", "tags"),
        ("created: 2026-10-26", "created: 어제", "created"),
        ("updated: 2026-10-26\n", "", "updated"),
    ],
)
def test_validate_weekly_rejects_bad_frontmatter(old, new, word):
    text = ok_text()
    assert old in text
    violations = validate_weekly(text.replace(old, new, 1), WEEK)
    assert any(word in v for v in violations), violations


def test_validate_weekly_needs_frontmatter():
    body = ok_text().split("---\n", 2)[2]
    assert any("프론트매터" in v for v in validate_weekly(body, WEEK))


def test_validate_weekly_needs_a_link():
    text = ok_text().replace("](https://", "](")
    assert any("링크" in v for v in validate_weekly(text, WEEK))
