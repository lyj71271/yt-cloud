"""YouTube URL -> 스크립트 문서(.txt) 생성기.
사용법:
    python yt_script.py <YouTube URL> [--lang ko] [--out DIR]

예:
    python yt_script.py https://www.youtube.com/watch?v=xexkvM2qRhg
    python yt_script.py https://youtu.be/xexkvM2qRhg --lang en --out .
필요 패키지: youtube-transcript-api, requests
    pip install youtube-transcript-api requests
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
import requests


def parse_video_id(url: str) -> str:
    url = url.strip()
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    raise ValueError(f"video ID를 찾을 수 없습니다: {url}")


def safe_name(s: str, limit: int = 80) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if len(s) > limit else s


def get_meta(video_id: str) -> dict:
    meta = {"title": video_id, "author": ""}
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=30,
        )
        if r.status_code == 200:
            j = r.json()
            meta["title"] = j.get("title", video_id)
            meta["author"] = j.get("author_name", "")
    except Exception as e:
        print(f"[경고] 영상 정보 조회 실패: {e}", file=sys.stderr)
    return meta


def fetch_transcript(video_id: str, lang: str):
    return fetch_transcript_smart(video_id, lang)


# 클라우드 IP 차단 시 우회용 미러 목록 (Invidious 공개 인스턴스)
INVIDIOUS = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://iv.duti.dev",
    "https://vid.puffyan.us",
]


def _parse_caption_text(raw: str):
    """VTT/TTML 자막 원문을 [(start초, 텍스트)] 로 변환."""
    import html as _html
    import re as _re
    out = []

    def ts2s(t: str) -> float:
        t = t.replace(",", ".")
        parts = t.split(":")
        s = float(parts[-1])
        m = int(parts[-2]) if len(parts) > 1 else 0
        h = int(parts[-3]) if len(parts) > 2 else 0
        return h * 3600 + m * 60 + s

    # TTML/XML: <p begin="00:00:01.200" ...>텍스트</p>
    for m in _re.finditer(r'<p[^>]*begin="([\d:.,]+)"[^>]*>(.*?)</p>', raw, _re.S):
        txt = _re.sub(r"<[^>]+>", "", m.group(2))
        txt = _html.unescape(txt).strip()
        if txt:
            out.append((ts2s(m.group(1)), txt))
    if out:
        return out
    # WebVTT: 00:00:01.200 --> 00:00:03.400
    blocks = _re.split(r"\n\s*\n", raw)
    for b in blocks:
        m = _re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)\s*\n(.*)", b, _re.S)
        if m:
            txt = _re.sub(r"<[^>]+>", "", m.group(3))
            txt = _html.unescape(txt).replace("\n", " ").strip()
            if txt and "WEBVTT" not in txt:
                out.append((ts2s(m.group(1)), txt))
    return out


class _Snip:
    def __init__(self, start, text):
        self.start = start
        self.text = text


class _Data:
    def __init__(self, snippets):
        self.snippets = snippets


def fetch_via_invidious(video_id: str, lang: str):
    """차단 우회: Invidious 미러에서 자막 가져오기."""
    order = ([lang] if lang != "auto" else []) + ["ko", "en"]
    last = None
    for base in INVIDIOUS:
        try:
            r = requests.get(f"{base}/api/v1/captions/{video_id}", timeout=20)
            if r.status_code != 200:
                continue
            tracks = r.json()
            if not isinstance(tracks, list) or not tracks:
                continue
            pick = None
            for lg in order:
                for t in tracks:
                    code = (t.get("languageCode") or t.get("language_code") or "")
                    if code.split("-")[0].lower() == lg.lower():
                        pick = t
                        break
                if pick:
                    break
            if pick is None:
                pick = tracks[0]
            url = pick.get("url", "")
            if url.startswith("/"):
                url = base + url
            t = requests.get(url, timeout=20)
            if t.status_code != 200 or not t.text.strip():
                continue
            segs = _parse_caption_text(t.text)
            if not segs:
                continue
            code = (pick.get("languageCode") or pick.get("language_code") or "?")
            print(f"우회 성공: {base} ({code}, {len(segs)} segments)")
            return _Data([_Snip(s, x) for s, x in segs]), code
        except Exception as e:
            last = e
            continue
    raise RuntimeError(f"Invidious 우회 실패: {last}")


def fetch_via_supadata(video_id: str, lang: str):
    """유료 우회(무료 100건/월): Supadata API. 환경변수 SUPADATA_KEY 필요."""
    import os as _os
    key = _os.environ.get("SUPADATA_KEY", "").strip()
    if not key:
        raise RuntimeError("SUPADATA_KEY 없음")
    langs = ([lang] if lang != "auto" else []) + ["ko", "en"]
    last = None
    for lg in langs:
        try:
            r = requests.get(
                "https://api.supadata.ai/v1/youtube/transcript",
                params={"videoId": video_id, "lang": lg},
                headers={"x-api-key": key},
                timeout=40,
            )
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                continue
            j = r.json()
            items = j.get("content") or j.get("transcript") or []
            segs = [(float(x.get("offset", 0)) / 1000.0
                     if float(x.get("offset", 0)) > 1000 else float(x.get("offset", 0)),
                     str(x.get("text", "")).strip())
                    for x in items if str(x.get("text", "")).strip()]
            if not segs:
                last = "empty"
                continue
            print(f"우회 성공: supadata ({lg}, {len(segs)} segments)")
            return _Data([_Snip(s, x) for s, x in segs]), lg
        except Exception as e:
            last = e
            continue
    raise RuntimeError(f"supadata 실패: {last}")


def fetch_transcript_smart(video_id: str, lang: str):
    """직접 시도 → 차단 시 우회(supadata→invidious). 기존 반환 형식과 동일."""
    api = YouTubeTranscriptApi()
    try:
        tracks = list(api.list(video_id))
    except Exception as e:
        name = type(e).__name__
        if "Blocked" in name:
            print(f"직접 차단({name}). 우회 시도...")
            try:
                return fetch_via_supadata(video_id, lang)
            except Exception as e2:
                print(f"supadata 스킵: {e2}")
            return fetch_via_invidious(video_id, lang)
        raise
    langs = [t.language_code for t in tracks]
    print(f"사용 가능 자막: {langs}")
    order = [lang] if lang != "auto" else []
    order += ["ko", "en"]
    blocked = False
    failed = None
    for lg in order:
        try:
            data = api.fetch(video_id, languages=[lg])
            print(f"선택 자막: {lg} ({len(data.snippets)} segments)")
            return data, lg
        except Exception as e:
            if "Blocked" in type(e).__name__:
                blocked = True
                break
            failed = e
            continue
    if blocked or failed is not None:
        print(f"직접 실패({type(failed).__name__ if failed else 'Blocked'}). 우회 시도...")
        try:
            return fetch_via_supadata(video_id, lang)
        except Exception as e:
            print(f"supadata 스킵: {e}")
        try:
            return fetch_via_invidious(video_id, lang)
        except Exception:
            pass
        if failed is not None:
            raise failed
    t0 = tracks[0]
    data = api.fetch(video_id, languages=[t0.language_code])
    print(f"선택 자막: {t0.language_code} ({len(data.snippets)} segments)")
    return data, t0.language_code


def build_doc(meta: dict, video_id: str, lang: str, data) -> str:
    def ts(s: float) -> str:
        s = float(s)
        h, rem = divmod(int(s), 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    plain = re.sub(r"\s+", " ", " ".join(s.text for s in data.snippets)).strip()
    lines = [
        meta["title"],
        f"채널: {meta['author']}" if meta["author"] else "채널: (조회 실패)",
        f"URL: https://www.youtube.com/watch?v={video_id}",
        f"자막: {lang} ({len(data.snippets)} segments)",
        "",
        "===== 읽기용 전문 =====",
        plain,
        "",
        "===== 시간대별 스크립트 =====",
    ]
    lines += [f"[{ts(s.start)}] {s.text}" for s in data.snippets]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="YouTube 스크립트 문서 생성기")
    ap.add_argument("url", help="YouTube 영상 URL 또는 video ID")
    ap.add_argument("--lang", default="ko", help="우선 자막 언어 (기본 ko, 자동선택은 auto)")
    ap.add_argument("--out", default=r"C:\Users\lyj\Downloads\스크립트",
                    help="저장 폴더 (기본: 다운로드\\스크립트)")
    args = ap.parse_args()

    try:
        video_id = parse_video_id(args.url)
    except ValueError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    print(f"video ID: {video_id}")

    try:
        meta = get_meta(video_id)
        print(f"제목: {meta['title']}")
        data, used = fetch_transcript(video_id, args.lang)
        doc = build_doc(meta, video_id, used, data)
    except Exception as e:
        print(f"[오류] 자막 추출 실패 ({type(e).__name__}): {e}", file=sys.stderr)
        print("자막이 없는 영상이거나 연령제한/비공개 영상일 수 있습니다.", file=sys.stderr)
        return 1

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    fname = f"유튜브 {video_id} {safe_name(meta['title'], 50)} 스크립트 ({used}).txt"
    outpath = outdir / fname
    i = 1
    while outpath.exists():
        outpath = outdir / f"유튜브 {video_id} {safe_name(meta['title'], 50)} 스크립트 ({used}) ({i}).txt"
        i += 1
    outpath.write_text(doc, encoding="utf-8")
    print(f"저장: {outpath} ({len(doc)}자)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
