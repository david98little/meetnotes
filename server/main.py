"""MeetNotes — 轻量会议纪要服务"""
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
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
async def upload_meeting(file: UploadFile = File(...), title: str = Form(""), project: str = Form("")):
    if get_config()["transcriber"] == "ark" and not get_config().get("asr", {}).get("api_key"):
        raise HTTPException(400, "尚未配置方舟 API Key，请先到设置填写")
    mid, path = _save_upload(file)
    user_title = (title or "").strip()
    if user_title:
        title, source = user_title[:60], "user"
    else:
        title, source = os.path.splitext(file.filename)[0][:60], "filename"
    db.create_meeting(mid, title, datetime.now().strftime("%Y-%m-%d %H:%M"), project,
                      meta={"title_source": source})
    submit_new(mid)
    return {"id": mid}


@app.get("/api/meetings")
def list_meetings():
    return db.list_meetings()


@app.get("/api/stats")
def get_stats(rng: str = Query("all", alias="range")):
    """会议看板聚合数据。range: all|year|month|week|day"""
    now = datetime.now()
    starts = {
        "day": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "week": (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0),
        "month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        "year": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    }
    start = starts.get(rng)

    def _dt(m):
        try:
            return datetime.strptime(m["created_at"], "%Y-%m-%d %H:%M")
        except Exception:
            return None

    ms = [m for m in db.list_meetings() if (not start) or ((_dt(m) or now) >= start)]

    # 汇总
    total_dur = sum(m.get("duration") or 0 for m in ms)
    done = sum(1 for m in ms if m["status"] == "done")
    chars, todos = 0, 0
    con = db.connect()
    for m in ms:
        r = con.execute("SELECT COALESCE(SUM(LENGTH(text)),0) AS n FROM segments WHERE meeting_id=?", (m["id"],)).fetchone()
        chars += r["n"]
        art = con.execute("SELECT content FROM artifacts WHERE meeting_id=? AND kind='summary'", (m["id"],)).fetchone()
        if art:
            todos += len(re.findall(r"-\s*\[\s\]\s*\*\*", art["content"]))
    con.close()

    # 趋势分桶
    def bucket(dt):
        if rng in ("all", "year"):
            return dt.strftime("%Y-%m")
        if rng == "month":
            return dt.strftime("%m-%d")
        if rng == "week":
            return ["周一","周二","周三","周四","周五","周六","周日"][dt.weekday()]
        return f"{dt.hour}时"

    trend, hours = {}, {}
    for m in ms:
        dt = _dt(m)
        if not dt:
            continue
        k = bucket(dt)
        t = trend.setdefault(k, {"count": 0, "items": []})
        t["count"] += 1
        t["items"].append({"id": m["id"], "title": m["title"], "date": m["created_at"]})
        hours[dt.hour] = hours.get(dt.hour, 0) + 1
    order = None
    if rng in ("all", "year"):
        order = sorted(trend)
    elif rng == "month":
        order = [(now - timedelta(days=i)).strftime("%m-%d") for i in range(min(31, now.day))] [::-1]
    elif rng == "week":
        order = ["周一","周二","周三","周四","周五","周六","周日"]
    else:
        order = [f"{h}时" for h in range(24)]
    trend_list = [{"label": k, "count": trend.get(k, {}).get("count", 0),
                   "items": trend.get(k, {}).get("items", [])}
                  for k in order if k in trend or rng in ("all", "year", "week", "month")]

    # 项目分布
    proj = {}
    for m in ms:
        p = m.get("project") or ""
        d = proj.setdefault(p, {"name": p or "未分组", "count": 0, "duration": 0, "items": []})
        d["count"] += 1
        d["duration"] += m.get("duration") or 0
        d["items"].append({"id": m["id"], "title": m["title"], "date": m["created_at"]})
    projects = sorted(proj.values(), key=lambda x: -x["count"])[:8]

    # 日历热力图（固定近 365 天，不受 range 影响）
    cal_start = (now - timedelta(days=364))
    cal_start -= timedelta(days=cal_start.weekday())
    daily = {}
    all_ms = db.list_meetings()
    for m in all_ms:
        dt = _dt(m)
        if dt and dt >= cal_start:
            key = dt.strftime("%Y-%m-%d")
            daily.setdefault(key, [])
            daily[key].append({"id": m["id"], "title": m["title"], "date": m["created_at"]})
    calendar = []
    d = cal_start
    while d <= now:
        key = d.strftime("%Y-%m-%d")
        cal_items = daily.get(key, [])
        calendar.append({"date": key, "count": len(cal_items), "items": cal_items})
        d += timedelta(days=1)

    peak = max(hours.items(), key=lambda x: x[1])[0] if hours else None
    return {
        "range": rng,
        "totals": {
            "count": len(ms),
            "duration_sec": round(total_dur),
            "chars": chars,
            "todos": todos,
            "done": done,
            "done_rate": round(done * 100 / len(ms)) if ms else 0,
        },
        "trend": trend_list,
        "projects": projects,
        "calendar": calendar,
        "peak_hour": peak,
    }


@app.get("/api/projects")
def get_projects():
    return db.list_projects()


@app.patch("/api/projects/{name}")
def rename_project(name: str, body: dict = Body(...)):
    if "name" not in body or not str(body["name"]).strip():
        raise HTTPException(400, "新项目名不能为空")
    new = db.rename_project(name, str(body["name"]))
    return {"ok": True, "name": new}


@app.delete("/api/projects/{name}")
def dissolve_project(name: str):
    db.dissolve_project(name)
    return {"ok": True}


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
    if not db.get_meeting(mid):
        raise HTTPException(404, "会议不存在")
    updates = {}
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "标题不能为空")
        updates["title"] = title[:80]
    if "project" in body:
        updates["project"] = (str(body.get("project") or "")).strip()[:40]
    if not updates:
        raise HTTPException(400, "无可更新字段")
    if "title" in updates:  # 手动改名后，AI 不再自动覆盖标题
        m = db.get_meeting(mid)
        try:
            meta = json.loads(m.get("meta") or "{}")
        except Exception:
            meta = {}
        meta["title_source"] = "user"
        db.update_meeting(mid, meta=json.dumps(meta, ensure_ascii=False))
    db.update_meeting(mid, **updates)
    return {"ok": True, **updates}


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

SECRET_FIELDS = [("asr", "api_key"), ("llm", "api_key")]


def _mask(cfg: dict) -> dict:
    """返回脱敏副本：api_key 替换为 *_set / *_hint 两个字段"""
    out = json.loads(json.dumps(cfg, ensure_ascii=False))  # deep copy
    for blk, key in SECRET_FIELDS:
        v = (out.get(blk) or {}).get(key) or ""
        out[blk][key + "_set"] = bool(v)
        out[blk][key + "_hint"] = (v[:5] + "****" + v[-4:]) if len(v) > 12 else ("已设置" if v else "")
        out[blk].pop(key, None)
    return out


def _apply_secret(cfg: dict, blk: str, incoming: dict):
    """api_key 留空/缺失 = 保持原值；非空则更新"""
    if blk not in cfg:
        return
    new_key = incoming.get("api_key")
    if new_key:  # 非空才覆盖
        cfg[blk]["api_key"] = str(new_key).strip()
    incoming.pop("api_key", None)
    cfg[blk].update(incoming)


@app.get("/api/settings")
def get_settings():
    return _mask(get_config())


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    cfg = get_config()
    for k, v in body.items():
        if v is None:
            continue
        if k in ("asr", "llm") and isinstance(v, dict):
            _apply_secret(cfg, k, {kk: str(vv).strip() if isinstance(vv, str) else vv
                                   for kk, vv in v.items()})
        elif k in cfg:
            if k == "chunk_seconds":
                v = max(120, min(int(v), 1800))
            cfg[k] = str(v).strip() if isinstance(v, str) else v
    save_config(cfg)
    return {"ok": True, **_mask(get_config())}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
