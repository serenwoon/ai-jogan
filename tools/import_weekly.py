"""주간 노트를 내 노트 폴더로 가져온다.

저장소 `weekly/<YYYY-Www>.md` 중 도착 폴더에 없는 것만 내려받는다.
이미 있는 파일은 절대 덮어쓰지 않는다. 표준 라이브러리만 쓴다.

도착 폴더는 `--dest`, 환경 변수 `AI_JOGAN_DEST`,
`%LOCALAPPDATA%/ai-jogan/config.json`의 `"dest"` 순서로 찾는다.
셋 다 없으면 아무것도 하지 않는다. 설정 파일은 `--init <폴더>`로 한 번 만든다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable

LIST_URL = "https://api.github.com/repos/serenwoon/ai-jogan/contents/weekly"
RAW_URL = "https://raw.githubusercontent.com/serenwoon/ai-jogan/main/weekly/{week}.md"
DEST_ENV = "AI_JOGAN_DEST"
TIMEOUT = 30
_WEEK_FILE = re.compile(r"^\d{4}-W\d{2}\.md$")
_WEEK = re.compile(r"^\d{4}-W\d{2}$")


def _app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ai-jogan"


def log_path() -> Path:
    return _app_dir() / "import.log"


def config_path() -> Path:
    return _app_dir() / "config.json"


def log(message: str) -> None:
    """도착 폴더 밖 로그 파일에 한 줄 남긴다. 로그 실패는 삼킨다."""
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{stamp} {message}\n")
    except OSError:
        pass


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "ai-jogan-import"})


def list_weeks(urlopen=urllib.request.urlopen) -> list[str]:
    """저장소 weekly/ 에 있는 주 이름(`2026-W43`)을 정렬해 돌려준다. 실패하면 빈 목록."""
    try:
        with urlopen(_request(LIST_URL), timeout=TIMEOUT) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
        names = [e.get("name", "") for e in entries if isinstance(e, dict)]
    except Exception as exc:  # 네트워크·HTTP·JSON 어느 쪽이든 조용히 끝낸다
        log(f"목록 실패: {exc!r}")
        return []
    return sorted(n[: -len(".md")] for n in names if _WEEK_FILE.match(n))


def fetch_week(week: str, urlopen=urllib.request.urlopen) -> str:
    with urlopen(_request(RAW_URL.format(week=week)), timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def import_missing(
    list_weeks: Callable[[], list[str]],
    fetch: Callable[[str], str],
    dest_dir: Path,
) -> list[Path]:
    """도착 폴더에 없는 주만 가져와 새로 쓴 파일 경로를 돌려준다."""
    dest_dir = Path(dest_dir)
    try:
        weeks = list(list_weeks())
    except Exception as exc:
        log(f"목록 실패: {exc!r}")
        return []
    weeks = [w for w in weeks if _WEEK.match(w)]
    if not weeks:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for week in weeks:
        target = dest_dir / f"AI 조간 주간 {week}.md"
        if target.exists():
            continue
        try:
            text = fetch(week)
        except Exception as exc:
            log(f"{week} 가져오기 실패: {exc!r}")
            continue
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        try:
            with open(target, "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except FileExistsError:
            continue
        except OSError as exc:
            log(f"{week} 쓰기 실패: {exc!r}")
            continue
        written.append(target)
    return written


def _config_dest() -> Path | None:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log(f"설정 파일을 읽지 못함: {exc!r}")
        return None
    dest = data.get("dest") if isinstance(data, dict) else None
    if not isinstance(dest, str) or not dest.strip():
        log(f"설정 파일에 dest 가 없음: {config_path()}")
        return None
    return _absolute_or_none(dest.strip(), "설정 파일")


def _absolute_or_none(value: str | Path, source: str) -> Path | None:
    """상대 경로는 작업 스케줄러의 작업 폴더에 따라 엉뚱한 곳을 가리킨다. 받지 않는다."""
    path = Path(value)
    if not str(value).strip() or not path.is_absolute():
        log(f"도착 폴더가 절대 경로가 아님({source}): {str(value)!r} — 가져오지 않는다")
        return None
    return path


def resolve_dest(arg: str | Path | None) -> Path | None:
    """`--dest` → 환경 변수 → 설정 파일 순서. 어디에도 없으면 None. 기본 경로는 두지 않는다.

    앞 순서에 값이 있는데 절대 경로가 아니면 뒤로 넘어가지 않고 None 이다.
    """
    if arg is not None:
        return _absolute_or_none(arg, "--dest")
    env = os.environ.get(DEST_ENV, "").strip()
    if env:
        return _absolute_or_none(env, DEST_ENV)
    return _config_dest()


def write_config(folder: Path) -> Path:
    """설정 파일에 도착 폴더를 적는다. 도착 폴더 자체는 만들지 않는다."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    dest = str(Path(folder).expanduser().absolute())
    text = json.dumps({"dest": dest}, ensure_ascii=False, indent=2) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def _say(message: str) -> None:
    """콘솔에 한 줄. cp949 창에서 못 찍는 글자는 \\u 꼴로 바꿔 찍는다. 출력 실패는 삼킨다."""
    out = sys.stdout
    if out is None:  # pythonw 로 돌면 콘솔이 없다
        return
    try:
        out.write(message + "\n")
    except UnicodeEncodeError:
        enc = getattr(out, "encoding", None) or "ascii"
        try:
            out.write(message.encode(enc, "backslashreplace").decode(enc) + "\n")
        except (OSError, ValueError, LookupError):
            return
    except (OSError, ValueError):
        return
    try:
        out.flush()
    except (OSError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="주간 AI 조간 노트를 내 노트 폴더로 가져온다")
    parser.add_argument("--dest", default=None, help="이번 실행의 도착 폴더(절대 경로)")
    parser.add_argument("--init", type=Path, default=None, metavar="FOLDER",
                        help="도착 폴더를 설정 파일에 적고 끝낸다")
    args = parser.parse_args(argv)
    if args.init is not None:
        try:
            path = write_config(args.init)
        except OSError as exc:
            _say(f"설정 파일을 쓰지 못했다: {exc}")
            return 1
        _say(f"설정 파일을 썼다: {path}")
        return 0
    try:
        dest = resolve_dest(args.dest)
        if dest is None:
            log("도착 폴더 설정 없음 — --init <폴더> 로 한 번 정한다")
            _say(f"도착 폴더 설정 없음. --init <폴더> 로 한 번 정한다 (로그 {log_path()})")
            return 0
        written = import_missing(list_weeks, fetch_week, dest)
        log(f"새 파일 {len(written)}개: {[p.name for p in written]}")
    except Exception as exc:  # 어떤 경우에도 종료 코드는 0
        log(f"예기치 못한 오류: {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
