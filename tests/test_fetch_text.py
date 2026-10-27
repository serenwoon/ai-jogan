from jogan.fetch_text import fetch_texts


def cand(i):
    return {"id": f"c{i:03d}", "kind": "article", "title": f"t{i}", "url": f"https://example.com/{i}",
            "source": "S", "published": None, "stars": None, "stars_delta": None, "text_file": None}


def test_fetch_texts_writes_limit_files_and_truncates(tmp_path):
    cands = [cand(i) for i in range(1, 6)]
    seen = []

    def extract(url):
        seen.append(url)
        return "가" * 7000

    out = fetch_texts(cands, tmp_path, 3, extract)
    assert len(out) == 5
    assert seen == [c["url"] for c in cands[:3]]  # 상위 3건만 받는다
    for c in out[:3]:
        assert c["text_file"] == f"texts/{c['id']}.txt"
        text = (tmp_path / c["text_file"]).read_text(encoding="utf-8")
        assert len(text) == 6000
    assert all(c["text_file"] is None for c in out[3:])
    assert sorted(p.name for p in (tmp_path / "texts").iterdir()) == ["c001.txt", "c002.txt", "c003.txt"]
    assert cands[0]["text_file"] is None  # 입력은 건드리지 않는다


def test_fetch_texts_skips_failed_extract(tmp_path):
    def extract(url):
        if url.endswith("/2"):
            return None
        if url.endswith("/3"):
            raise RuntimeError("boom")
        if url.endswith("/4"):
            return ""
        return "본문"

    out = fetch_texts([cand(i) for i in range(1, 5)], tmp_path, 10, extract)
    assert [c["text_file"] for c in out] == ["texts/c001.txt", None, None, None]
    assert not (tmp_path / "texts" / "c002.txt").exists()


def test_fetch_texts_file_is_utf8_lf(tmp_path):
    out = fetch_texts([cand(1)], tmp_path, 1, lambda url: "첫 줄\n둘째 줄")
    raw = (tmp_path / out[0]["text_file"]).read_bytes()
    assert raw == "첫 줄\n둘째 줄".encode("utf-8")
