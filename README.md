# AI 조간

매일 아침 6시, 5분이면 다 읽는 AI 소식 메일 한 통을 나에게 보내는 저장소다. 사무·문서 업무를 하면서 AI 업무 자동화 사례와 화제가 된 GitHub 저장소, 에이전트 스킬, MCP 서버를 따라가고 싶었는데, 피드를 직접 돌며 고르는 데만 아침 30분이 들어서 그 일을 GitHub Actions에 넘겼다.

메일에는 다섯 코너가 있다. 오늘의 한 줄, 업무 자동화 사례, 깃허브·스킬 픽, 따라 해보기, 1분 용어. 항목마다 「자세히 →」 링크가 GitHub Pages의 상세 페이지로 이어지고, 거기서 무엇인지와 왜 지금 화제인지, 내 일에 쓸 자리, 배울 점, 주의할 점을 원문 링크와 함께 읽는다.

## 하루가 도는 순서

예약 실행은 UTC 21:00, 한국 시간으로 다음 날 06:00이다. 날짜는 모든 단계에서 KST로 센다. UTC 날짜를 쓰면 경로와 제목과 중복 검사가 하루씩 밀리기 때문이다.

워크플로 하나가 세 작업으로 나뉘어 차례로 돈다.

| 작업 | 저장소 권한 | 하는 일 |
|---|---|---|
| `edit` | 읽기 | 후보를 수집하고 편집 프롬프트를 만든 뒤 Claude가 `issues/<날짜>/digest.json`을 쓴다. 수집 결과와 digest를 아티팩트로 올린다 |
| `publish` | 쓰기 | 새로 받은 저장소에 아티팩트의 정해진 파일만 꺼내 검사하고, 메일과 상세 페이지를 렌더하고, 커밋·푸시한 뒤 메일을 보낸다 |
| `notify` | 읽기 | 앞 두 작업 중 하나라도 실패하거나 취소되거나 시간을 넘기면 실패 메일을 보낸다 |

수집은 RSS 여섯 곳과 GitHub 주제 검색, Hacker News에서 후보를 모으고 본문을 실행기에 받아 둔다. 검사는 스키마와 코너별 항목 수, 글자 수, 원문 링크, 최근 7일 중복을 본다. 렌더와 발송은 템플릿과 네이버 SMTP로 하고 AI를 쓰지 않는다.

Claude가 쓸 수 있는 도구는 Read, Write, WebFetch, WebSearch 넷뿐이다. 셸 실행과 커밋과 발송은 Claude 밖의 파이썬이 맡는다. 웹에서 읽은 글에 숨은 지시가 섞여 있어도 Claude가 메일을 보내거나 명령을 돌릴 수는 없게 하고 싶었다.

Claude는 `edit` 작업에서만 돈다. 이 작업의 토큰은 읽기 권한뿐이고, 저장소를 받을 때 푸시용 인증 정보도 남기지 않는다. Claude 단계 뒤에 이어지는 단계는 결과 파일을 아티팩트로 올리는 것뿐이고, 저장소의 파이썬은 그 작업에서 다시 돌지 않는다.

`publish`는 저장소를 새로 받아서 시작한다. 아티팩트에서 `candidates.json`, `stars.json`, `digest.json`, 월요일이면 주간 노트까지, 이름이 정해진 일반 파일만 제자리로 옮긴다. 일간 아티팩트에 다른 것이 섞여 있으면 거기서 멈추고, 주간 아티팩트라면 주간만 실패로 친다.

수집 결과는 검사 없이 커밋되는 파일이라, `edit`이 Claude를 돌리기 전에 sha256을 재어 넘기고 `publish`는 받은 파일이 그 값과 다르면 멈춘다. 아티팩트도 업로드 단계가 돌려준 ID로만 받아서, 같은 이름으로 다시 올린 것은 받지 않는다.

주간 노트는 받은 자리에서 먼저 검사하고, 통과한 것만 `weekly/`로 옮긴다. Claude가 편집 중에 코드나 다른 파일을 고쳤더라도 그 변경은 `edit` 실행기와 함께 사라지고, 메일 비밀번호를 받는 코드는 커밋된 그대로라고 판단했다.

Claude가 `digest.json`을 안 썼거나 깨진 JSON을 쓴 날은 아티팩트 업로드나 검사에서 멈춘다. 그날은 커밋도 메일도 없고 `docs/`도 그대로이며, `notify`가 멈춘 단계 이름과 실행 기록 링크를 담은 실패 메일을 보낸다. `notify`는 의존성을 설치하지 않고 표준 라이브러리만으로 돌아서, 패키지 설치가 실패한 날에도 실패 메일은 나간다.

커밋한 뒤에는 그날 상세 페이지 하나가 Pages에서 열릴 때까지 3분까지 기다린다. 그래도 안 열리면 메일은 그대로 보낸다. 메일의 「자세히 →」가 잠깐 404를 낼 수는 있어도, 메일이 아예 안 오는 쪽보다 낫다고 봤다.

월요일 실행은 일이 하나 더 있다. 지난주 digest 일곱 개를 모아 `weekly/<YYYY-Www>.md` 주간 노트를 쓰는데, 지난주 소식을 비용·능력·표준·규제 네 신호와 소음으로 다시 나눈다. 주간 프롬프트는 첫 Claude 단계 전에 만들어 두고, 그날 digest는 주간 단계가 돌기 전에 올려서 주간 단계가 손댈 수 없게 했다.

주간 단계가 실패하거나 노트가 없거나 검사에서 떨어지면 주간 노트만 커밋하지 않는다. 그날 메일은 그대로 나가고, 주간 실패 알림이 따로 한 통 더 간다.

커밋하는 것은 제목·링크·출처·날짜·별 수 같은 메타데이터뿐이다. 기사 본문은 실행기의 `.work/`에만 두고 올리지 않는다. 원문을 저장소에 쌓으면 그건 보관이 되어 버린다. 상세 페이지의 원문 인용도 항목마다 15단어 미만 한 번으로 묶었다.

## 구독 토큰을 쓰는 이유

편집 단계는 [claude-code-action](https://github.com/anthropics/claude-code-action)을 Claude 구독의 OAuth 토큰으로 돌린다. 내 구독 한도 안에서 나 한 사람이 받아 볼 메일을 만드는 개인 용도로만 쓴다. 남에게 보내거나 서비스로 돌리려면 구독 토큰이 아니라 API 키와 그에 맞는 약관을 따라야 한다.

API 키는 저장소에도 워크플로에도 두지 않았다. 둘이 같이 있으면 구독 대신 API 요금이 조용히 나가기 때문이다. 토큰이 만료되거나 한도가 차서 편집이 실패한 날은 API로 넘어가지 않고 그날을 건너뛴다. 실패 메일에 토큰을 다시 만드는 명령(`claude setup-token`)을 적어 두었다.

모델은 매일 편집에 `claude-sonnet-5-5`(최대 40턴), 월요일 주간 노트에 `claude-opus-5-5`(최대 30턴)를 쓴다. 턴 상한은 첫 주 사용량을 보고 고칠 생각이다.

## 비밀값

저장소의 Settings → Secrets and variables → Actions에 넷을 넣는다.

| 이름 | 쓰는 곳 | 내용 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `edit`의 Claude 단계 | 노트북에서 `claude setup-token`으로 만든 구독 토큰 |
| `NAVER_USER` | 발송·실패 메일 단계 | 보내는 네이버 계정 주소 |
| `NAVER_APP_PASSWORD` | 발송·실패 메일 단계 | 네이버 2단계 인증의 애플리케이션 비밀번호 |
| `MAIL_TO` | 발송·실패 메일 단계 | 받는 주소. 여럿이면 쉼표로 가른다 |

`GITHUB_TOKEN`은 Actions가 알아서 준다. `edit`에서는 읽기 권한으로 GitHub 검색과 claude-code-action에 쓰고, `publish`에서만 쓰기 권한으로 커밋을 푸시한다. claude-code-action에는 이 토큰을 `github_token`으로 넘겨서 Claude GitHub 앱 없이 돌게 했는데, 앱 없이 정말 도는지는 첫 실행에서 확인할 일이다.

## 주간 노트를 노트북으로 옮기기

`tools/import_weekly.py`는 저장소의 `weekly/` 목록을 GitHub API로 읽고, 내 노트 폴더에 아직 없는 주간 노트만 받아 `AI 조간 주간 <YYYY-Www>.md`로 저장한다. 표준 라이브러리만 쓴다. 이미 있는 파일은 새로 만들기 모드로만 열어서 절대 덮어쓰지 않는데, 내가 고친 노트를 지키려는 것이다.

스크립트에는 저장 위치를 적어 두지 않았다. 처음 한 번, 받을 폴더를 직접 정해 설정 파일을 만든다.

```powershell
python "<저장소 경로>\tools\import_weekly.py" --init "<노트를 받을 폴더>"
```

설정은 `%LOCALAPPDATA%\ai-jogan\config.json`의 `dest`에 들어가고, 폴더는 첫 노트를 받을 때 만든다.

한 번만 다른 곳에 받고 싶으면 `--dest`를 주거나 환경 변수 `AI_JOGAN_DEST`를 쓰는데, 앞의 것이 이긴다. 셋 다 없으면 아무것도 받지 않고 로그에 그 사실만 남긴다.

네트워크가 끊겨도 종료 코드는 늘 0이고, 무슨 일이 있었는지는 `%LOCALAPPDATA%\ai-jogan\import.log`에 한 줄씩 남긴다.

윈도우 작업 스케줄러에는 `tools/import_weekly_task.xml`로 등록한다. 로그온할 때와 매주 월요일 09:00에 돌고, 그 시각을 놓치면 다음 기회에 바로 돈다. PowerShell 7에서 저장소 경로를 넣어 한 번 실행한다.

```powershell
schtasks /Create /TN "AI 조간 주간 가져오기" /XML "<저장소 경로>\tools\import_weekly_task.xml"
```

XML 안의 파이썬 경로와 스크립트 경로는 지금 노트북 기준이라, 다른 기기에서는 두 경로를 먼저 고친다.

## 직접 돌리기

파이썬 3.12에서 만들었다. 윈도우 11에서 테스트를 돌렸고, 워크플로는 우분투 실행기에서 돈다. 패키지 버전은 `requirements.txt`에 고정했다.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # 맥·리눅스는 .venv/bin/python
.venv/Scripts/python -m pytest
```

단계는 `python -m jogan.cli <명령> [--date YYYY-MM-DD]`로 하나씩 부른다. 날짜를 안 주면 KST 오늘이다.

| 명령 | 만드는 것 |
|---|---|
| `collect` | `data/<날짜>/candidates.json`, `data/stars.json`, `.work/texts/` |
| `prompt --kind daily` | `.work/prompt.md`. 주간은 `--kind weekly --out .work/prompt-weekly.md` |
| `check` | 위반이 있으면 한국어로 찍고 종료 코드 1 |
| `render` | `docs/`, `.work/email.html`, `.work/email_subject.txt`, `.work/email.txt` |
| `send` | `.work/`의 메일을 보낸다. 비밀값 셋이 환경 변수에 있어야 하고, 메일 서버 오류는 한 줄로 알리고 1로 끝난다 |
| `fail-mail --stage <이름> --run-url <주소>` | 실패 알림 메일 |
| `check-weekly --week 2026-W43` | 주간 노트 검사 |

편집 단계만은 로컬 명령이 없다. `.work/prompt.md`를 만든 뒤 Claude Code에서 그 파일을 읽혀 `issues/<날짜>/digest.json`을 쓰게 하면 같은 흐름을 손으로 따라갈 수 있다. 수집 출처와 키워드는 `config/sources.json`, Pages 주소와 메일 제목 형식은 `config/site.json`에서 고친다.

## 지금 상태

워크플로는 아직 한 번도 GitHub에서 돌려 보지 않았다. 테스트는 각 단계를 가짜 네트워크와 가짜 SMTP로 확인한 것이고, 세 작업의 연결과 claude-code-action 단계, 봇 푸시 뒤의 Pages 배포, 네이버 메일에서의 표시는 첫 수동 실행에서 확인해야 한다.

라이선스 파일은 아직 두지 않았다.
