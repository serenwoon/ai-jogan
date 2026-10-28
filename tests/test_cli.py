import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import jogan.cli as cli
from jogan.digest import load_digest

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures"
DAY = "2026-10-28"  # 수요일
MONDAY = "2026-10-26"
PLACEHOLDERS = ["{date}", "{candidates_path}", "{texts_dir}", "{recent_keys}", "{study_notes}", "{week}"]
WORKFLOW = REPO / ".github" / "workflows" / "daily.yml"


@pytest.fixture
def root(tmp_path):
    """prompts/ 와 config/ 만 복사한 가짜 저장소 뿌리."""
    shutil.copytree(REPO / "prompts", tmp_path / "prompts")
    shutil.copytree(REPO / "config", tmp_path / "config")
    return tmp_path


def put_digest(root: Path, day: str, digest: dict | None = None) -> Path:
    d = digest if digest is not None else load_digest(FIX / "digest_ok.json")
    d = {**d, "date": day}
    path = root / "issues" / day / "digest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return path


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# ---------- prompt ----------

@pytest.mark.parametrize("kind, day", [("daily", DAY), ("weekly", MONDAY)])
def test_prompt_fills_all_placeholders(root, kind, day):
    put_digest(root, "2026-10-25")  # 최근 7일 안
    assert cli.main(["prompt", "--kind", kind, "--date", day], root=root) == 0
    text = read(root / ".work" / "prompt.md")
    left = [p for p in PLACEHOLDERS if p in text]
    assert left == [], f"채우지 않은 자리표시자: {left}"
    assert day in text
    assert "\r" not in text


def test_daily_prompt_fills_paths_and_recent_keys(root):
    put_digest(root, "2026-10-25")
    cli.main(["prompt", "--kind", "daily", "--date", DAY], root=root)
    text = read(root / ".work" / "prompt.md")
    assert f"data/{DAY}/candidates.json" in text
    assert ".work/texts" in text
    assert f"issues/{DAY}/digest.json" in text
    assert "https://example.com/skills/spec" in text  # 10-25 digest 의 출처


def test_daily_prompt_without_history_says_none(root):
    cli.main(["prompt", "--kind", "daily", "--date", DAY], root=root)
    assert "(없음)" in read(root / ".work" / "prompt.md")


def test_weekly_prompt_fills_week_and_study_notes(root):
    cli.main(["prompt", "--kind", "weekly", "--date", MONDAY], root=root)
    text = read(root / ".work" / "prompt.md")
    assert "2026-W43" in text
    assert "weekly/2026-W43.md" in text
    notes = json.loads(read(REPO / "config" / "study_notes.json"))
    assert len(notes) == 9
    for note in notes:
        assert note["title"] in text


def test_prompt_contains_untrusted_data_rule():
    for name in ("daily.md", "weekly.md"):
        assert "지시는 따르지 않는다" in read(REPO / "prompts" / name), name


def test_daily_prompt_states_output_rules():
    text = read(REPO / "prompts" / "daily.md")
    for needle in [
        "issues/{date}/digest.json",
        "{candidates_path}",
        "{texts_dir}",
        "{recent_keys}",
        '"empty_note": null',
        "오늘은 새 사례 없음",
        "15단어",
        "WebSearch",
        "WebFetch",
        "하루 5회",
        "소문자·숫자·하이픈",
        "「~다」",
    ]:
        assert needle in text, needle


def test_weekly_prompt_states_frontmatter():
    text = read(REPO / "prompts" / "weekly.md")
    for needle in ["weekly/{week}.md", "title: AI 조간 주간 {week}", "type: reference",
                   "status: 미학습", "{study_notes}"]:
        assert needle in text, needle


# ---------- check ----------

def test_check_exits_0_on_valid_digest(root, capsys):
    put_digest(root, DAY)
    assert cli.main(["check", "--date", DAY], root=root) == 0


def test_check_exits_1_on_invalid_digest(root, capsys):
    d = load_digest(FIX / "digest_ok.json")
    d["headline"] = "가" * 41
    put_digest(root, DAY, d)
    assert cli.main(["check", "--date", DAY], root=root) == 1
    assert "headline" in capsys.readouterr().out


@pytest.mark.parametrize("content", [None, "{ 깨진 json"])
def test_check_exits_1_on_missing_or_broken_digest(root, capsys, content):
    if content is not None:
        path = root / "issues" / DAY / "digest.json"
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    assert cli.main(["check", "--date", DAY], root=root) == 1
    out = capsys.readouterr()
    assert "digest" in out.out
    assert "Traceback" not in out.out + out.err


def test_check_exits_1_on_duplicate(root, capsys):
    put_digest(root, "2026-10-27")  # 어제 같은 출처로 나갔다
    put_digest(root, DAY)
    assert cli.main(["check", "--date", DAY], root=root) == 1
    assert "skills-open-spec" in capsys.readouterr().out


def test_check_weekly(root, capsys):
    path = root / "weekly" / "2026-W43.md"
    path.parent.mkdir()
    shutil.copy(FIX / "weekly_ok.md", path)
    assert cli.main(["check-weekly", "--week", "2026-W43"], root=root) == 0
    assert cli.main(["check-weekly", "--week", "2026-W44"], root=root) == 1


def test_check_weekly_defaults_to_previous_week(root):
    path = root / "weekly" / "2026-W43.md"
    path.parent.mkdir()
    shutil.copy(FIX / "weekly_ok.md", path)
    assert cli.main(["check-weekly", "--date", MONDAY], root=root) == 0


# ---------- render · send · fail-mail ----------

def test_render_writes_docs_and_mail_files(root):
    put_digest(root, DAY)
    assert cli.main(["render", "--date", DAY], root=root) == 0
    work = root / ".work"
    assert (root / "docs" / DAY / "index.html").is_file()
    assert (root / "docs" / DAY / "skills-open-spec.html").is_file()
    assert read(work / "email_subject.txt").startswith("AI 조간 10/28(수)")
    assert "<" in read(work / "email.html")
    text = read(work / "email.txt")
    assert "<" not in text and "오늘의 한 줄" in text


def test_send_reads_work_files(root, monkeypatch):
    work = root / ".work"
    work.mkdir()
    (work / "email_subject.txt").write_text("제목\n", encoding="utf-8")
    (work / "email.html").write_text("<p>본문</p>", encoding="utf-8")
    (work / "email.txt").write_text("본문", encoding="utf-8")
    sent = []
    monkeypatch.setattr(cli, "send_mail", lambda s, h, t, env: sent.append((s, h, t)))
    assert cli.main(["send"], root=root) == 0
    assert sent == [("제목", "<p>본문</p>", "본문")]


def test_send_without_env_exits_1(root, monkeypatch, capsys):
    put_digest(root, DAY)
    cli.main(["render", "--date", DAY], root=root)
    for name in ("NAVER_USER", "NAVER_APP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["send"], root=root) == 1
    assert "NAVER_USER" in capsys.readouterr().err


@pytest.mark.parametrize("exc", [
    __import__("smtplib").SMTPAuthenticationError(535, b"auth failed"),
    TimeoutError("timed out"),
    ConnectionRefusedError("refused"),
])
def test_send_smtp_error_exits_1_with_one_line(root, monkeypatch, capsys, exc):
    put_digest(root, DAY)
    cli.main(["render", "--date", DAY], root=root)
    capsys.readouterr()

    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(cli, "send_mail", boom)
    assert cli.main(["send"], root=root) == 1
    out = capsys.readouterr()
    assert out.err.count("\n") == 1 and out.err.startswith("발송 실패")
    assert "Traceback" not in out.out + out.err


def test_prompt_out_option(root):
    assert cli.main(["prompt", "--kind", "weekly", "--date", MONDAY,
                     "--out", ".work/prompt-weekly.md"], root=root) == 0
    assert "weekly/2026-W43.md" in read(root / ".work" / "prompt-weekly.md")
    assert not (root / ".work" / "prompt.md").exists()


def test_fail_mail_sends_stage_and_url(root, monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "send_mail", lambda s, h, t, env: sent.append((s, h, t)))
    url = "https://github.com/o/r/actions/runs/1"
    assert cli.main(["fail-mail", "--date", DAY, "--stage", "check", "--run-url", url], root=root) == 0
    subject, html, text = sent[0]
    assert subject == "AI 조간 10/28(수) — 실패"
    assert "check" in text and url in text


def test_empty_date_means_today(root, monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "send_mail", lambda s, h, t, env: sent.append(s))
    monkeypatch.setattr(cli, "kst_today", lambda: __import__("datetime").date(2026, 10, 28))
    assert cli.main(["fail-mail", "--date", "", "--stage", "date", "--run-url", "u"], root=root) == 0
    assert sent == ["AI 조간 10/28(수) — 실패"]


# ---------- collect ----------

def test_collect_writes_metadata_and_texts(root, monkeypatch):
    result = {
        "date": DAY,
        "candidates": [
            {"id": "c001", "kind": "article", "title": "글", "url": "https://example.com/a",
             "source": "OpenAI", "published": None, "stars": None, "stars_delta": None, "text_file": None},
            {"id": "c002", "kind": "repo", "title": "저장소", "url": "https://github.com/o/r",
             "source": "GitHub", "published": None, "stars": 5, "stars_delta": None, "text_file": None},
        ],
        "failed_sources": [{"source": "Hacker News", "error": "Timeout"}],
    }
    seen = {}

    def fake_collect(cfg, today, stars_path, http):
        seen.update(cfg=cfg, today=today, stars_path=stars_path)
        return json.loads(json.dumps(result))

    monkeypatch.setattr("jogan.collect.collect_all", fake_collect)
    monkeypatch.setattr("jogan.collect.RequestsHttp", lambda: object())
    monkeypatch.setattr("jogan.fetch_text.extract_url_text",
                        lambda url: "본문 전체" if url.endswith("/a") else None)
    assert cli.main(["collect", "--date", DAY], root=root) == 0

    assert seen["stars_path"] == root / "data" / "stars.json"
    assert seen["cfg"]["fetch_text_limit"] == 25
    saved = json.loads(read(root / "data" / DAY / "candidates.json"))
    assert saved["failed_sources"] == result["failed_sources"]
    assert saved["candidates"][0]["text_file"] == ".work/texts/c001.txt"
    assert saved["candidates"][1]["text_file"] is None
    assert "본문 전체" not in read(root / "data" / DAY / "candidates.json")
    assert read(root / ".work" / "texts" / "c001.txt") == "본문 전체"


def test_fail_mail_needs_no_third_party_modules():
    """의존성 설치가 실패한 날에도 실패 메일은 나가야 한다."""
    code = """
import sys
import jogan.cli as cli
sent = []
cli.send_mail = lambda s, h, t, env: sent.append(s)
assert cli.main(["fail-mail", "--date", "2026-10-28", "--stage", "install", "--run-url", "u"]) == 0
assert sent, sent
heavy = sorted(m for m in ("feedparser", "requests", "trafilatura", "jinja2") if m in sys.modules)
print("HEAVY=" + ",".join(heavy))
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                         encoding="utf-8", env={"PYTHONPATH": str(REPO), "PYTHONUTF8": "1",
                                                "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert out.returncode == 0, out.stderr
    assert "HEAVY=\n" in out.stdout, out.stdout


# ---------- 공개 파일 ----------

_BANNED_MARK = "# 금지어 목록"
BANNED = ["IFIS", "저축은행", "자동차손해배상", "PMO", "PMS", "WATCH2", "30_projects",  # 금지어 목록
          "Obsidian Vault", "adverwjddns"]  # 금지어 목록


def _public_files() -> list[Path]:
    """저장소에 올라가는 파일 전부(git ls-files). 아직 커밋 안 한 새 파일도 포함한다."""
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=REPO, capture_output=True, check=True)
    names = [n for n in out.stdout.decode("utf-8").split("\0") if n]
    return [REPO / n for n in names if (REPO / n).is_file()]


def _text_or_none(raw: bytes) -> str | None:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None  # 바이너리 파일만 건너뛴다


def test_public_files_do_not_leak_private_names():
    this = Path(__file__).resolve()
    seen, marked = set(), 0
    for path in _public_files():
        rel = path.relative_to(REPO).as_posix()
        seen.add(rel)
        text = _text_or_none(path.read_bytes())
        if text is None:
            continue
        if path.resolve() == this:  # 금지어 목록 자체는 뺀다 — 표시한 줄 수까지 고정
            lines = text.split("\n")
            kept = [l for l in lines if not l.rstrip().endswith(_BANNED_MARK)]
            marked += len(lines) - len(kept)
            text = "\n".join(kept)
        for word in BANNED:
            assert word not in text, f"{rel}: {word}"
    assert marked == 2, f"금지어 목록 표시 줄이 {marked}개다 — 2개여야 한다"
    assert {"README.md", ".github/workflows/daily.yml", "tools/import_weekly.py",
            "tools/import_weekly_task.xml", "tests/test_cli.py", "requirements.txt"} <= seen


def test_workflow_has_no_api_key():
    assert "ANTHROPIC_API_KEY" not in WORKFLOW.read_text(encoding="utf-8")


def _jobs(text: str) -> dict[str, str]:
    """jobs: 아래 작업을 이름 → 본문으로 떼어 낸다(들여쓰기 2칸의 `이름:`)."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  (\w+):\n", "\n" + body)
    return dict(zip(parts[1::2], parts[2::2]))


def _steps(job: str) -> list[str]:
    """steps: 아래 항목. 들여쓰기 6칸의 `- `로 시작하고, 안쪽 줄은 2칸으로 맞춘다."""
    body = job.split("\n    steps:\n", 1)[1]
    parts = re.split(r"\n      - ", "\n" + body)
    return ["- " + part.replace("\n        ", "\n  ") for part in parts if part.strip()]


def _step(steps: list[str], step_id: str) -> str:
    found = [s for s in steps if re.search(rf"^- id: {step_id}$", s, re.M)]
    assert len(found) == 1, step_id
    return found[0]


def _ids(steps: list[str]) -> list[str]:
    return [m.group(1) for s in steps for m in [re.search(r"^- id: (\w+)$", s, re.M)] if m]


def _minutes(block: str) -> int:
    m = re.search(r"^  timeout-minutes: (\d+)$", block, re.M)
    assert m, block[:200]
    return int(m.group(1))


def test_workflow_contract():
    text = read(WORKFLOW)
    for needle in [
        'cron: "0 21 * * *"',
        "workflow_dispatch",
        "TZ: Asia/Seoul",
        "concurrency: {group: ai-jogan, cancel-in-progress: false}",
        "anthropics/claude-code-action@v1",
        "claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        'prompt: "Read .work/prompt.md and follow it exactly."',
        'prompt: "Read .work/prompt-weekly.md and follow it exactly."',
        '--model claude-sonnet-5-5 --max-turns 40 --allowedTools "Read,Write,WebFetch,WebSearch"'
        ' --disallowedTools "Bash,Edit,MultiEdit,NotebookEdit"',
        '--model claude-opus-5-5 --max-turns 30 --allowedTools "Read,Write,WebFetch,WebSearch"'
        ' --disallowedTools "Bash,Edit,MultiEdit,NotebookEdit"',
        "github-actions[bot]",
        "41898282+github-actions[bot]@users.noreply.github.com",
        "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}",
        'python-version: "3.12"',
    ]:
        assert needle in text, needle
    assert "--bare" not in text
    assert "ANTHROPIC_API_KEY" not in text
    assert text.count("--disallowedTools") == 2


def test_workflow_has_three_jobs():
    jobs = _jobs(read(WORKFLOW))
    assert list(jobs) == ["edit", "publish", "notify"]


def test_edit_job_is_read_only_and_runs_nothing_after_claude():
    edit = _jobs(read(WORKFLOW))["edit"]
    assert "permissions: {contents: read}" in edit
    steps = _steps(edit)
    checkout = [s for s in steps if "actions/checkout@" in s]
    assert len(checkout) == 1 and "persist-credentials: false" in checkout[0]

    ids = _ids(steps)
    first_claude = next(i for i, s in enumerate(steps) if "anthropics/claude-code-action@v1" in s)
    # Claude 전에: 수집, 두 프롬프트, 수집 결과 업로드
    before = "\n".join(steps[:first_claude])
    assert "python -m jogan.cli collect" in before
    assert "--kind daily" in before and "--kind weekly" in before and "prompt-weekly.md" in before
    assert ids.index("upload_collect") < ids.index("edit")
    # Claude 뒤에는 run 단계가 하나도 없다 — 저장소 파이썬도 git도 돌지 않는다
    for s in steps[first_claude:]:
        assert "\n  run:" not in s and not s.startswith("- run:"), s[:120]
        assert "python -m jogan" not in s and "git " not in s
        assert re.search(r"uses: (anthropics/claude-code-action|actions/upload-artifact)@", s), s[:120]
    # 그날 digest 는 주간 단계 전에 올린다
    assert ids.index("edit") < ids.index("upload_digest") < ids.index("weekly_edit") < ids.index("upload_weekly")
    assert "continue-on-error: true" in _step(steps, "weekly_edit")
    assert "if-no-files-found: ignore" in _step(steps, "upload_weekly")
    for key in ("date:", "week:", "is_monday:", "failed_stage:", "weekly_outcome:"):
        assert f"\n      {key}" in edit.split("\n    steps:\n")[0], key


def test_publish_job_order_and_weekly_handling():
    publish = _jobs(read(WORKFLOW))["publish"]
    assert "needs: edit" in publish and "permissions: {contents: write}" in publish
    steps = _steps(publish)
    ids = _ids(steps)
    assert ids.index("download") < ids.index("place") < ids.index("check") < ids.index("render")
    assert ids.index("render") < ids.index("commit") < ids.index("pages") < ids.index("send")
    assert ids.index("send") < ids.index("weekly_notice")
    weekly = _step(steps, "weekly_check")
    assert "continue-on-error: true" in weekly and "check-weekly" in weekly
    assert "continue-on-error: true" in _step(steps, "pages")
    assert 'git add -- "weekly/$WEEK.md"' in _step(steps, "commit")
    assert "--stage weekly" in _step(steps, "weekly_notice")
    assert "failed_stage:" in publish.split("\n    steps:\n")[0]


def test_notify_job_runs_always_without_pip():
    notify = _jobs(read(WORKFLOW))["notify"]
    assert "needs: [edit, publish]" in notify
    assert "if: always() && (needs.edit.result != 'success' || needs.publish.result != 'success')" in notify
    assert "pip install" not in notify
    assert "python -m jogan.cli fail-mail" in notify
    assert "needs.edit.outputs.failed_stage" in notify and "needs.publish.outputs.failed_stage" in notify


def test_naver_secrets_only_where_mail_is_sent():
    jobs = _jobs(read(WORKFLOW))
    for name, job in jobs.items():
        for s in _steps(job):
            if "secrets.NAVER" in s or "secrets.MAIL_TO" in s:
                assert "python -m jogan.cli send" in s or "python -m jogan.cli fail-mail" in s, (name, s[:120])
        assert "secrets.NAVER" not in job.split("\n    steps:\n")[0], name
    assert "secrets.NAVER" not in jobs["edit"]
    assert "secrets.CLAUDE_CODE_OAUTH_TOKEN" not in jobs["publish"] + jobs["notify"]


def test_step_timeouts_fit_inside_job_timeout():
    for name, job in _jobs(read(WORKFLOW)).items():
        head = job.split("\n    steps:\n")[0]
        job_minutes = int(re.search(r"^    timeout-minutes: (\d+)$", "\n" + head, re.M).group(1))
        total = sum(_minutes(s) for s in _steps(job))
        assert total < job_minutes, (name, total, job_minutes)


def test_requirements_are_pinned_with_tzdata():
    lines = [l for l in read(REPO / "requirements.txt").split("\n") if l.strip()]
    names = {l.split("==")[0].lower() for l in lines}
    assert all("==" in l for l in lines), lines
    assert {"feedparser", "requests", "trafilatura", "jinja2", "pytest", "tzdata"} <= names


# ---------- 공개 전 보강: 수집물 해시 고정 · 작은 수정 ----------

def _head(job: str) -> str:
    return job.split("\n    steps:\n")[0]


def _run_script(step: str) -> str:
    """단계의 `run: |` 본문을 꺼낸다. GitHub처럼 블록의 공통 들여쓰기(4칸)를 걷어 낸다."""
    lines = step.split("\n")
    start = lines.index("  run: |") + 1
    body = []
    for line in lines[start:]:
        if line and not line.startswith("    "):
            break
        body.append(line[4:])
    return "\n".join(body).rstrip("\n") + "\n"


def _bash():
    if os.name == "nt":
        p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(p) if p.exists() else None
    return shutil.which("bash")


BASH = _bash()


def _sh(tmp_path: Path, script: str, cwd: Path, **env: str):
    """GitHub의 기본 셸(`bash -e {0}`)처럼 단계 본문을 돌린다."""
    path = tmp_path / f"step-{len(list(tmp_path.glob('step-*')))}.sh"
    path.write_bytes(script.encode("utf-8"))
    full = {**os.environ, "PYTHONUTF8": "1", **env}
    out = subprocess.run([BASH, "-e", str(path)], cwd=cwd, capture_output=True, env=full)
    return out.returncode, out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")


def test_edit_job_hardening():
    jobs = _jobs(read(WORKFLOW))
    head = _head(jobs["edit"])
    assert "\n    env:\n" in head
    for line in ('GIT_CONFIG_COUNT: "1"', "GIT_CONFIG_KEY_0: core.fsmonitor", 'GIT_CONFIG_VALUE_0: "false"'):
        assert f"\n      {line}" in head, line
    assert "cache: pip" not in jobs["edit"]


def test_no_job_uses_any_cache():
    """Claude 단계는 실행기 토큰으로 캐시를 쓸 수 있다. 비밀값을 가진 작업이 그걸 복원하면 안 된다."""
    text = read(WORKFLOW)
    assert re.search(r"^\s*cache(-[\w-]+)?:", text, re.M) is None
    assert "actions/cache" not in text
    # A3 환경 변수는 한 겹 덧댄 것일 뿐이다. 주석이 그 한계를 밝히고, README는 그걸 내세우지 않는다
    head = _head(_jobs(text)["edit"])
    comment = re.search(r"((?:\n    #[^\n]*)+)\n    env:\n      GIT_CONFIG_COUNT", "\n" + head).group(1)
    assert "GITHUB_ENV" in comment and "막지 못한다" in comment, comment
    readme = read(REPO / "README.md")
    assert "fsmonitor" not in readme and "GIT_CONFIG" not in readme


def test_download_steps_note_v4_layout():
    publish = _jobs(read(WORKFLOW))["publish"]
    assert re.search(r"\n      # [^\n]*actions/download-artifact@v4[^\n]*\n(      #[^\n]*\n)*"
                     r"      - id: download\n", "\n" + publish), "다운로드 단계 앞에 v4 배치 주석이 없다"
    note = re.search(r"((?:\n      #[^\n]*)+)\n      - id: download\n", "\n" + publish).group(1)
    assert "v5" in note
    steps = _steps(publish)
    for step_id in ("download", "download_weekly"):
        assert "uses: actions/download-artifact@v4\n" in _step(steps, step_id), step_id


def test_collect_artifact_is_pinned_by_hash():
    jobs = _jobs(read(WORKFLOW))
    edit_steps = _steps(jobs["edit"])
    ids = _ids(edit_steps)
    first_claude = next(i for i, s in enumerate(edit_steps) if "anthropics/claude-code-action@v1" in s)
    assert ids.index("prompt") < ids.index("hash") < ids.index("upload_collect") < first_claude
    hash_step = _step(edit_steps, "hash")
    assert "sha256sum" in hash_step and "base64 -w0" in hash_step and '"$GITHUB_OUTPUT"' in hash_step
    edit_head = _head(jobs["edit"])
    assert "collect_sha: ${{ steps.hash.outputs.collect_sha }}" in edit_head
    assert "steps.hash.outcome == 'failure' && 'hash'" in edit_head

    publish_steps = _steps(jobs["publish"])
    place = _step(publish_steps, "place")
    assert "COLLECT_SHA: ${{ needs.edit.outputs.collect_sha }}" in place
    assert "base64 -d" in place and "::error::" in place
    # 두 작업이 같은 함수로 잰다
    sums = re.search(r"^    sums\(\) \{.*?^    \}$", hash_step, re.M | re.S).group(0)
    assert sums in place
    # 해시를 맞춘 뒤에야 data/ 로 옮긴다
    assert place.index('[ "$actual" != "$expected" ]') < place.index('cp "$IN/collect/candidates.json"')
    # place 가 떨어지면 publish 실패 → notify 가 실패 메일을 보낸다
    assert "steps.place.outcome == 'failure' && 'place'" in _head(jobs["publish"])


def test_downloads_are_pinned_to_uploaded_artifact_ids():
    jobs = _jobs(read(WORKFLOW))
    edit_head = _head(jobs["edit"])
    for key, step_id in (("collect_id", "upload_collect"), ("digest_id", "upload_digest"),
                         ("weekly_id", "upload_weekly")):
        assert f"{key}: ${{{{ steps.{step_id}.outputs.artifact-id }}}}" in edit_head, key
    steps = _steps(jobs["publish"])
    ids = _ids(steps)
    assert ids.index("download") < ids.index("download_weekly") < ids.index("place")
    download = _step(steps, "download")
    assert ("artifact-ids: ${{ needs.edit.outputs.collect_id }},${{ needs.edit.outputs.digest_id }}"
            in download)
    assert "merge-multiple" not in download  # 아티팩트마다 이름 폴더로 풀린다
    weekly = _step(steps, "download_weekly")
    assert "artifact-ids: ${{ needs.edit.outputs.weekly_id }}" in weekly
    assert "continue-on-error: true" in weekly
    assert "needs.edit.outputs.weekly_id != ''" in weekly


def test_weekly_note_is_checked_where_it_was_downloaded():
    weekly = _step(_steps(_jobs(read(WORKFLOW))["publish"]), "weekly_check")
    assert "root=Path(sys.argv[1])" in weekly and '"$RUNNER_TEMP/in"' in weekly
    assert weekly.index("check-weekly") < weekly.index("mkdir -p weekly")
    assert weekly.index("check-weekly") < weekly.index('cp "$IN/$WEEK.md" "weekly/$WEEK.md"')


def test_small_workflow_fixes():
    jobs = _jobs(read(WORKFLOW))
    pages = _step(_steps(jobs["publish"]), "pages")
    assert "curl -s --max-time 20 " in pages
    assert "seq 1 18" not in pages  # 횟수가 아니라 시간으로 끊어야 단계 시간 안에 끝난다
    assert _minutes(_step(_steps(jobs["edit"]), "weekly_edit")) == 15


@pytest.mark.skipif(BASH is None, reason="bash 없음")
@pytest.mark.parametrize("tamper", [None, "change", "add_stars", "drop_stars", "empty_sha", "bad_sha"])
def test_hash_step_and_place_step_run(tmp_path, tamper):
    jobs = _jobs(read(WORKFLOW))
    hash_script = _run_script(_step(_steps(jobs["edit"]), "hash"))
    place_script = _run_script(_step(_steps(jobs["publish"]), "place"))

    edit_temp = tmp_path / "edit-temp"
    (edit_temp / "collect").mkdir(parents=True)
    (edit_temp / "collect" / "candidates.json").write_text('{"candidates": []}\n', encoding="utf-8")
    if tamper != "add_stars":
        (edit_temp / "collect" / "stars.json").write_text('{"a/b": 1}\n', encoding="utf-8")
    out = tmp_path / "github_output"
    out.write_text("", encoding="utf-8")
    code, log = _sh(tmp_path, hash_script, tmp_path, RUNNER_TEMP=edit_temp.as_posix(),
                    GITHUB_OUTPUT=out.as_posix())
    assert code == 0, log
    lines = [l for l in out.read_text(encoding="utf-8").split("\n") if l]
    assert len(lines) == 1 and lines[0].startswith("collect_sha="), lines
    sha = lines[0].split("=", 1)[1]
    decoded = base64.b64decode(sha).decode("utf-8")
    assert re.fullmatch(r"[0-9a-f]{64}  candidates\.json(\n[0-9a-f]{64}  stars\.json)?", decoded), decoded

    pub_temp = tmp_path / "pub-temp"
    shutil.copytree(edit_temp / "collect", pub_temp / "in" / "collect")
    (pub_temp / "in" / "digest").mkdir(parents=True)
    (pub_temp / "in" / "digest" / "digest.json").write_text("{}\n", encoding="utf-8")
    got = pub_temp / "in" / "collect"
    if tamper == "change":
        (got / "candidates.json").write_text('{"candidates": [1]}\n', encoding="utf-8")
    elif tamper == "add_stars":
        (got / "stars.json").write_text('{"x/y": 9}\n', encoding="utf-8")
    elif tamper == "drop_stars":
        (got / "stars.json").unlink()
    elif tamper == "empty_sha":
        sha = ""
    elif tamper == "bad_sha":
        sha = "!!!"

    work = tmp_path / "work"
    work.mkdir()
    code, log = _sh(tmp_path, place_script, work, RUNNER_TEMP=pub_temp.as_posix(), DATE=DAY,
                    COLLECT_SHA=sha)
    if tamper is None:
        assert code == 0, log
        assert ((work / "data" / DAY / "candidates.json").read_bytes()
                == (edit_temp / "collect" / "candidates.json").read_bytes())
        assert (work / "data" / "stars.json").exists()
        assert (work / "issues" / DAY / "digest.json").exists()
    else:
        assert code != 0, log
        assert "::error::" in log and "해시" in log, log
        assert not (work / "data").exists()


@pytest.mark.skipif(BASH is None, reason="bash 없음")
@pytest.mark.parametrize("missing", ["collect/candidates.json", "digest/digest.json", "collect", "digest"])
def test_place_fails_loudly_when_an_artifact_file_is_missing(tmp_path, missing):
    jobs = _jobs(read(WORKFLOW))
    hash_script = _run_script(_step(_steps(jobs["edit"]), "hash"))
    place_script = _run_script(_step(_steps(jobs["publish"]), "place"))
    edit_temp = tmp_path / "edit-temp"
    (edit_temp / "collect").mkdir(parents=True)
    (edit_temp / "collect" / "candidates.json").write_bytes(b'{"candidates": []}\n')
    out = tmp_path / "github_output"
    out.write_bytes(b"")
    code, log = _sh(tmp_path, hash_script, tmp_path, RUNNER_TEMP=edit_temp.as_posix(),
                    GITHUB_OUTPUT=out.as_posix())
    assert code == 0, log
    sha = out.read_text(encoding="utf-8").strip().split("=", 1)[1]

    pub_in = tmp_path / "pub-temp" / "in"
    shutil.copytree(edit_temp / "collect", pub_in / "collect")
    (pub_in / "digest").mkdir()
    (pub_in / "digest" / "digest.json").write_bytes(b"{}\n")
    target = pub_in / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    work = tmp_path / "work"
    work.mkdir()
    code, log = _sh(tmp_path, place_script, work, RUNNER_TEMP=(tmp_path / "pub-temp").as_posix(),
                    DATE=DAY, COLLECT_SHA=sha)
    assert code != 0, log
    name = missing if "/" in missing else {"collect": "collect/candidates.json",
                                            "digest": "digest/digest.json"}[missing]
    assert f"::error::아티팩트에 {name} 가 없다" in log, log
    assert not (work / "data").exists() and not (work / "issues").exists()


@pytest.mark.skipif(BASH is None, reason="bash 없음")
@pytest.mark.parametrize("good", [True, False])
def test_weekly_check_copies_only_after_passing(tmp_path, good):
    script = _run_script(_step(_steps(_jobs(read(WORKFLOW))["publish"]), "weekly_check"))
    temp = tmp_path / "temp"
    note = temp / "in" / "weekly" / "2026-W43.md"
    note.parent.mkdir(parents=True)
    text = read(FIX / "weekly_ok.md")
    note.write_bytes((text if good else text.replace("status:", "stat:")).encode("utf-8"))
    work = tmp_path / "work"
    work.mkdir()
    py_dir = str(Path(sys.executable).parent)
    code, log = _sh(tmp_path, script, work, RUNNER_TEMP=temp.as_posix(), WEEK="2026-W43",
                    PYTHONPATH=str(REPO), PATH=py_dir + os.pathsep + os.environ.get("PATH", ""))
    if good:
        assert code == 0, log
        assert (work / "weekly" / "2026-W43.md").read_bytes() == note.read_bytes()
    else:
        assert code != 0, log
        assert not (work / "weekly").exists(), "떨어진 노트가 작업 폴더를 더럽혔다"


# ---------- images ----------

def test_images_writes_found_pictures_and_render_uses_them(root, monkeypatch):
    from jogan import images

    put_digest(root, DAY)
    page = '<meta property="og:image" content="https://cdn.example.com/lead.jpg">'
    monkeypatch.setattr(images, "fetch_page", lambda url: page)
    monkeypatch.setattr(images, "image_ok", lambda url: True)
    assert cli.main(["images", "--date", DAY], root=root) == 0
    saved = json.loads(read(root / "issues" / DAY / "images.json"))
    assert saved and set(saved.values()) == {"https://cdn.example.com/lead.jpg"}
    assert cli.main(["render", "--date", DAY], root=root) == 0
    assert 'src="https://cdn.example.com/lead.jpg"' in read(root / ".work" / "email.html")


def test_images_finding_nothing_is_not_a_failure(root, monkeypatch):
    from jogan import images

    put_digest(root, DAY)
    monkeypatch.setattr(images, "fetch_page", lambda url: None)
    monkeypatch.setattr(images, "image_ok", lambda url: True)
    assert cli.main(["images", "--date", DAY], root=root) == 0
    assert json.loads(read(root / "issues" / DAY / "images.json")) == {}


def test_render_ignores_broken_images_json(root):
    put_digest(root, DAY)
    (root / "issues" / DAY / "images.json").write_text("{깨짐", encoding="utf-8")
    assert cli.main(["render", "--date", DAY], root=root) == 0
    assert "<img" not in read(root / ".work" / "email.html")


def test_publish_finds_images_after_check_before_render_and_never_blocks():
    steps = _steps(_jobs(read(WORKFLOW))["publish"])
    ids = _ids(steps)
    assert ids.index("check") < ids.index("images") < ids.index("render")
    step = _step(steps, "images")
    assert "continue-on-error: true" in step and "jogan.cli images" in step
