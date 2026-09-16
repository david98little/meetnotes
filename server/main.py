"""MeetNotes — 轻量会议纪要服务"""
import logging
import os
import re
import shutil
import uuid
from datetime import datetime

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import AUDIO_DIR, BASE_DIR, WEB_DIR, get_config, load_all, save_config
from .pipeline import submit_new, submit_retry
from .providers import WhisperLocal

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="MeetNotes")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_static(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith(("/static/", "/audio/")) or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.on_event("startup")
def startup():
    load_all()
    db.init(os.path.join(os.path.dirname(AUDIO_DIR), "meet.db"))


AUDIO_SAFE_RE = re.compile(r"^[\w\u4e00-\u9fa5\-]+(\.[\w]{1,6})?$", re.S)


# ---------------- 页面 & 静态 ----------------

@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web")), name="static")


# ---------------- meetings ----------------

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
               ".webm", ".wma", ".amr", ".mp4"}


def _save_upload(file: UploadFile) -> tuple[str, str]:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的音频格式: {ext}（支持 {', '.join(sorted(ALLOWED_EXT))}）")
    mid = uuid.uuid4().hex[:12]
    dst = os.path.join(AUDIO_DIR, f"{mid}_orig{ext}")
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return mid, dst


@app.post("/api/meetings")
async def upload_meeting(file: UploadFile = File(...), title: str = Form("")):
    if get_config()["transcriber"] == "ark" and not get_config()["ark_api_key"]:
        raise HTTPException(400, "尚未配置方舟 API Key，请先到设置页填写")
    mid, path = _save_upload(file)
    title = (title or "").strip() or os.path.splitext(file.filename)[0][:60]
    db.create_meeting(mid, title, datetime.now().strftime("%Y-%m-%d %H:%M"))
    submit_new(mid)
    return {"id": mid}


@app.get("/api/meetings")
def list_meetings():
    return db.list_meetings()


@app.get("/api/meetings/{mid}")
def meeting_detail(mid: str):
    m = db.get_meeting(mid)
    if not m:
        raise HTTPException(404, "会议不存在")
    return {
        **m,
        "segments": db.list_segments(mid),
        "polished": db.get_artifact(mid, "polished"),
        "summary": db.get_artifact(mid, "summary"),
        "engines": {"whisper_local_available": WhisperLocal.available()},
    }


@app.patch("/api/meetings/{mid}")
def rename_meeting(mid: str, body: dict = Body(...)):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    if not db.get_meeting(mid):
        raise HTTPException(404, "会议不存在")
    db.update_meeting(mid, title=title[:80])
    return {"ok": True, "title": title[:80]}


@app.delete("/api/meetings/{mid}")
def delete_meeting(mid: str):
    m = db.get_meeting(mid)
    if not m:
        raise HTTPException(404, "会议不存在")
    db.delete_meeting(mid)
    for f in os.listdir(AUDIO_DIR):
        if f.startswith(f"{mid}_orig") or f.startswith(f"{mid}_part") or f == f"{mid}.mp3":
            try:
                os.remove(os.path.join(AUDIO_DIR, f))
            except OSError:
                pass
    return {"ok": True}


@app.post("/api/meetings/{mid}/retry")
def retry_step(mid: str, body: dict = Body(...)):
    step = body.get("step")
    if step not in ("transcribing", "polishing", "summarizing"):
        raise HTTPException(400, "step 必须是 transcribing | polishing | summarizing")
    m = db.get_meeting(mid)
    if not m:
        raise HTTPException(404, "会议不存在")
    if step != "transcribing" and not db.list_segments(mid):
        raise HTTPException(400, "尚无转写结果，请先重跑转写步骤")
    if step == "summarizing" and not (db.get_artifact(mid, "polished") or db.list_segments(mid)):
        pass
    # 用户编辑过的整理稿重跑摘要时直接以库内最新文稿为准
    submit_retry(mid, step)
    return {"ok": True, "step": step}


@app.patch("/api/meetings/{mid}/artifact/{kind}")
def save_artifact(mid: str, kind: str, body: dict = Body(...)):
    if kind not in ("polished", "summary"):
        raise HTTPException(400, "kind 仅支持 polished | summary")
    if not db.get_meeting(mid):
        raise HTTPException(404, "会议不存在")
    content = body.get("content")
    if content is None:
        raise HTTPException(400, "缺少 content 字段")
    db.upsert_artifact(mid, kind, content)
    return {"ok": True}


@app.get("/audio/{filename}")
def audio_file(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "非法路径")
    path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404)
    media = "audio/mpeg" if filename.endswith(".mp3") else "application/octet-stream"
    return FileResponse(path, media_type=media)


# ---------------- settings ----------------

SECRET_KEYS = {"ark_api_key"}


def _mask(cfg: dict) -> dict:
    out = dict(cfg)
    k = out.get("ark_api_key") or ""
    out["ark_api_key_set"] = bool(k)
    out["ark_api_key_hint"] = (k[:6] + "****" + k[-4:]) if len(k) > 12 else ("已设置" if k else "")
    out.pop("ark_api_key", None)
    return out


@app.get("/api/settings")
def get_settings():
    return _mask(get_config())


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    cfg = get_config()
    for k, v in body.items():
        if k in cfg and v is not None:
            if k == "chunk_seconds":
                v = max(120, min(int(v), 1800))
            cfg[k] = str(v).strip() if isinstance(v, str) else v
    save_config(cfg)
    return {"ok": True, **_mask(get_config())}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
