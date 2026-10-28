"""하위 명령: collect prompt check images render send fail-mail check-weekly.

`python -m jogan.cli <명령> [--date YYYY-MM-DD]` — 날짜를 안 주거나 빈 값이면 KST 오늘.
워크플로가 단계마다 하나씩 부른다. 실패는 종료 코드 1과 한국어 메시지로 알리고 추적 정보는 찍지 않는다.

수집·렌더 모듈(feedparser·requests·trafilatura·jinja2)은 그 명령 안에서만 불러온다.
의존성 설치가 실패한 날에도 `fail-mail`은 표준 라이브러리만으로 돌아야 하기 때문이다.
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from jogan.dates import kst_today, load_site_config, previous_iso_week
from jogan.digest import DigestError, load_digest, validate_digest
from jogan.history import find_duplicates, recent_keys
from jogan.mail import MailConfigError, failure_mail, send_mail
from jogan.weekly import validate_weekly

REPO_ROOT = Path(__file__).resolve().parents[1]
WORK = ".work"
TEXTS_DIR = f"{WORK}/texts"
MAIL_FILES = ("email_subject.txt", "email.html", "email.txt")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _write_json(path: Path, data) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest_path(root: Path, day: date) -> Path:
    return root / "issues" / day.isoformat() / "digest.json"


# ---------- 명령 ----------

def cmd_collect(root: Path, day: date) -> int:
    from jogan import collect, fetch_text

    cfg = _read_json(root / "config" / "sources.json")
    result = collect.collect_all(cfg, day, root / "data" / "stars.json", collect.RequestsHttp())

    work = root / WORK
    texts = work / "texts"
    for old in texts.glob("*.txt"):  # 같은 날 다시 돌 때 지난 실행의 본문이 섞이지 않게
        old.unlink()
    candidates = fetch_text.fetch_texts(result["candidates"], work, cfg["fetch_text_limit"],
                                        fetch_text.extract_url_text)
    for cand in candidates:
        if cand["text_file"]:  # fetch_texts 는 .work 기준 경로를 준다 → 저장소 뿌리 기준으로
            cand["text_file"] = f"{WORK}/{cand['text_file']}"
    result["candidates"] = candidates

    _write_json(root / "data" / day.isoformat() / "candidates.json", result)
    with_text = sum(1 for c in candidates if c["text_file"])
    print(f"후보 {len(candidates)}건, 본문 {with_text}건, 실패한 출처 {len(result['failed_sources'])}곳")
    for failed in result["failed_sources"]:
        print(f"  실패: {failed['source']} — {failed['error']}")
    return 0


def _study_notes_text(root: Path) -> str:
    notes = _read_json(root / "config" / "study_notes.json")
    return "\n".join(f"- {n['title']} — {n['topic']}" for n in notes)


def cmd_prompt(root: Path, day: date, kind: str, out: str = f"{WORK}/prompt.md") -> int:
    template = (root / "prompts" / f"{kind}.md").read_text(encoding="utf-8")
    keys = sorted(recent_keys(root / "issues", day))
    values = {
        "{date}": day.isoformat(),
        "{candidates_path}": f"data/{day.isoformat()}/candidates.json",
        "{texts_dir}": TEXTS_DIR,
        "{recent_keys}": "\n".join(keys) if keys else "(없음)",
        "{study_notes}": _study_notes_text(root),
        "{week}": previous_iso_week(day),
    }
    text = template
    for token, value in values.items():  # str.format 은 스키마의 JSON 중괄호를 깨뜨린다
        text = text.replace(token, value)
    _write(root / out, text)
    print(f"{out} 를 썼다 ({kind}, {day.isoformat()})")
    return 0


def cmd_check(root: Path, day: date) -> int:
    try:
        digest = load_digest(_digest_path(root, day))
    except DigestError as e:
        print(f"검사 실패: {e}")
        return 1
    problems = validate_digest(digest, day)
    duplicates = find_duplicates(digest, recent_keys(root / "issues", day))
    problems += [f"항목 '{item_id}'의 출처가 최근 7일 안에 이미 나갔습니다." for item_id in duplicates]
    if problems:
        print(f"검사 실패: {len(problems)}건")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"검사 통과: {day.isoformat()}")
    return 0


def cmd_check_weekly(root: Path, week: str) -> int:
    path = root / "weekly" / f"{week}.md"
    try:
        text = path.read_bytes().decode("utf-8")  # CR 을 잡으려고 줄바꿈 변환 없이 읽는다
    except (OSError, UnicodeDecodeError) as e:
        print(f"주간 노트를 읽을 수 없습니다: {path.relative_to(root)} ({e})")
        return 1
    problems = validate_weekly(text, week)
    if problems:
        print(f"주간 노트 검사 실패: {len(problems)}건")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"주간 노트 검사 통과: {week}")
    return 0


def _images_path(root: Path, day: date) -> Path:
    return root / "issues" / day.isoformat() / "images.json"


def cmd_images(root: Path, day: date) -> int:
    """항목마다 원문의 대표 사진 주소를 찾아 issues/<날짜>/images.json 에 쓴다. 못 찾아도 실패가 아니다."""
    from jogan import images

    try:
        digest = load_digest(_digest_path(root, day))
    except DigestError as e:
        print(f"사진 찾기 실패: {e}")
        return 1
    found = images.find_images(digest, images.fetch_page, images.image_ok)
    _write_json(_images_path(root, day), dict(sorted(found.items())))
    total = sum(len(digest["corners"][k]["items"]) for k in digest["corners"])
    print(f"사진 {len(found)}/{total}건")
    return 0


def _load_images(root: Path, day: date) -> dict:
    try:
        return _read_json(_images_path(root, day))
    except (OSError, ValueError):
        return {}


def cmd_render(root: Path, day: date) -> int:
    from jogan.render import html_to_text, render_email, render_site

    try:
        digest = load_digest(_digest_path(root, day))
    except DigestError as e:
        print(f"렌더 실패: {e}")
        return 1
    site = load_site_config(root)
    pictures = _load_images(root, day)
    render_site(digest, site, root / "docs", root / "issues", pictures)
    subject, html = render_email(digest, site, pictures)
    work = root / WORK
    _write(work / "email_subject.txt", subject + "\n")
    _write(work / "email.html", html)
    _write(work / "email.txt", html_to_text(html) + "\n")
    print(f"렌더 끝: docs/{day.isoformat()}/ · {WORK}/email.html")
    return 0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _send(subject: str, html: str, text: str) -> int:
    try:
        send_mail(subject, html, text, os.environ)
    except MailConfigError as e:
        return _fail(f"발송 실패: {e}")
    except OSError as e:  # smtplib.SMTPException 도 OSError 다. 추적 정보 없이 한 줄만
        return _fail(f"발송 실패: 메일 서버와 주고받지 못했습니다 ({type(e).__name__}: {e})")
    print(f"발송 끝: {subject}")
    return 0


def cmd_send(root: Path) -> int:
    work = root / WORK
    try:
        subject, html, text = (
            (work / name).read_bytes().decode("utf-8") for name in MAIL_FILES
        )
    except OSError as e:
        return _fail(f"발송 실패: 렌더 결과가 없습니다 ({e})")
    return _send(subject.strip(), html, text)


def cmd_fail_mail(day: date, stage: str, run_url: str) -> int:
    return _send(*failure_mail(day, stage, run_url))


# ---------- 인자 ----------

def _date_arg(value: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD 형식이어야 합니다: {value!r}")


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", type=_date_arg, default=None,
                        help="YYYY-MM-DD. 없거나 빈 값이면 KST 오늘")
    parser = argparse.ArgumentParser(prog="python -m jogan.cli", description="AI 조간 단계 실행기")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", parents=[common], help="후보 수집과 본문 받기")
    p = sub.add_parser("prompt", parents=[common], help=".work/prompt.md 만들기")
    p.add_argument("--kind", choices=("daily", "weekly"), required=True)
    p.add_argument("--out", default=f"{WORK}/prompt.md", help="저장소 뿌리 기준 출력 경로")
    sub.add_parser("check", parents=[common], help="digest 검사와 7일 중복 검사")
    sub.add_parser("images", parents=[common], help="원문 대표 사진 주소 찾기")
    sub.add_parser("render", parents=[common], help="docs/ 와 메일 파일 만들기")
    sub.add_parser("send", parents=[common], help=".work/ 의 메일 보내기")
    p = sub.add_parser("fail-mail", parents=[common], help="실패 알림 메일 보내기")
    p.add_argument("--stage", required=True)
    p.add_argument("--run-url", required=True)
    p = sub.add_parser("check-weekly", parents=[common], help="주간 노트 검사")
    p.add_argument("--week", default=None, help="2026-W43 꼴. 없으면 날짜의 지난 ISO 주")
    return parser


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(root) if root is not None else REPO_ROOT
    day = args.date or kst_today()
    if args.command == "collect":
        return cmd_collect(root, day)
    if args.command == "prompt":
        return cmd_prompt(root, day, args.kind, args.out)
    if args.command == "check":
        return cmd_check(root, day)
    if args.command == "images":
        return cmd_images(root, day)
    if args.command == "render":
        return cmd_render(root, day)
    if args.command == "send":
        return cmd_send(root)
    if args.command == "fail-mail":
        return cmd_fail_mail(day, args.stage, args.run_url)
    if args.command == "check-weekly":
        return cmd_check_weekly(root, args.week or previous_iso_week(day))
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
