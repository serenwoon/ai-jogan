"""후보 본문을 .work/texts/<id>.txt 로 저장한다. 본문은 커밋하지 않는다(.work/ 는 gitignore)."""
from collections.abc import Callable
from pathlib import Path

from jogan.collect import Candidate, RequestsHttp

MAX_CHARS = 6000


def fetch_texts(candidates: list[Candidate], work_dir: Path, limit: int,
                extract: Callable[[str], str | None]) -> list[Candidate]:
    """상위 limit건의 본문을 work_dir/texts/<id>.txt 에 쓰고 text_file(work_dir 기준 경로)을 채운다.

    extract 는 후보 URL을 받아 본문을 돌려준다. None·빈 문자열이거나 예외가 나면 text_file 은 None.
    입력 목록은 바꾸지 않고 새 목록을 돌려준다.
    """
    texts_dir = Path(work_dir) / "texts"
    out: list[Candidate] = []
    for index, cand in enumerate(candidates):
        new: Candidate = dict(cand)  # type: ignore[assignment]
        if index < limit:
            try:
                text = extract(cand["url"])
            except Exception:
                text = None
            if text:
                texts_dir.mkdir(parents=True, exist_ok=True)
                with open(texts_dir / f"{cand['id']}.txt", "w", encoding="utf-8", newline="\n") as f:
                    f.write(text[:MAX_CHARS])
                new["text_file"] = f"texts/{cand['id']}.txt"
        out.append(new)
    return out


def extract_url_text(url: str) -> str | None:
    """실제 추출기: URL 의 HTML 을 받아 trafilatura 로 본문만 뽑는다. 테스트에서는 쓰지 않는다."""
    import trafilatura  # 무거워서 필요할 때만 불러온다

    html = RequestsHttp().get_bytes(url)
    return trafilatura.extract(html)
