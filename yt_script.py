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
    api = YouTubeTranscriptApi()
    tracks = list(api.list(video_id))
    langs = [t.language_code for t in tracks]
    print(f"사용 가능 자막: {langs}")
    order = [lang] if lang != "auto" else []
    order += ["ko", "en"]
    for lg in order:
        try:
            data = api.fetch(video_id, languages=[lg])
            print(f"선택 자막: {lg} ({len(data.snippets)} segments)")
            return data, lg
        except Exception:
            continue
    # 최후: 첫 번째 트랙
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
