"""yt 클라우드 백엔드 (FastAPI).
로컬 실행: uvicorn server:app --port 8789
외출용: Render/Railway에 이 폴더 배포.
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, r"D:\MyProject\yt-script")
import yt_script as core  # 기존 추출 로직 재사용

app = FastAPI(title="yt-script API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN/외출용. 상용 시 앱 도메인으로 제한
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class Req(BaseModel):
    url: str
    lang: str = "ko"


@app.get("/")
def root():
    return {"ok": True, "usage": "POST /api/extract {url, lang}"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/extract")
def extract(req: Req):
    url = (req.url or "").strip()
    if not url:
        return {"ok": False, "error": "URL을 입력하세요."}
    try:
        vid = core.parse_video_id(url)
        meta = core.get_meta(vid)
        data, used = core.fetch_transcript(vid, req.lang or "ko")
        doc = core.build_doc(meta, vid, used, data)
        return {"ok": True, "video_id": vid, "title": meta["title"],
                "channel": meta["author"], "lang": used,
                "chars": len(doc), "full": doc}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
