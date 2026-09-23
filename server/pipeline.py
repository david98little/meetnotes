"""任务编排状态机：normalizing → transcribing → polishing → summarizing → done"""
import json
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import audio_utils, db
from .config import get_config
from .prompts import PROMPT_POLISH, PROMPT_SUMMARY, SUMMARY_FALLBACK_MD, summary_json_to_md
from .providers import ArkClient, WhisperLocal, build_context_hint, get_transcriber

log = logging.getLogger("meetnotes.pipeline")
_pool = ThreadPoolExecutor(max_workers=2)      # 会议级并发
_asr_pool = ThreadPoolExecutor(max_workers=3)  # 单会议内切片级并发
_inflight: set[str] = set()


def _audio_dir() -> str:
    from .config import AUDIO_DIR
    return AUDIO_DIR


def _part_path(mid, idx) -> str:
    return os.path.join(_audio_dir(), f"{mid}_part{idx}.mp3")


def _load_meta(mid) -> dict:
    raw = db.get_meeting(mid).get("meta")
    return json.loads(raw) if raw else {}


# ---------------- 提交入口 ----------------

def submit_new(mid: str):
    """新会议：完整流水线"""
    if mid not in _inflight:
        _inflight.add(mid)
        _pool.submit(_guard, mid, [_normalize, _transcribe, _polish, _summarize])


def submit_retry(mid: str, start_step: str):
    """从指定步骤重跑，包含后续所有步骤"""
    chain_map = {"transcribing": [_transcribe, _polish, _summarize],
                 "polishing": [_polish, _summarize],
                 "summarizing": [_summarize]}
    chain = chain_map[start_step]
    if mid not in _inflight:
        _inflight.add(mid)
        _pool.submit(_guard, mid, chain)


def _guard(mid, chain):
    try:
        for fn in chain:
            fn(mid)
    except Exception as e:
        log.exception("pipeline failed %s", mid)
        db.update_meeting(mid, status="failed", error=str(e)[:800])
    finally:
        _inflight.discard(mid)


# ---------------- 各步骤 ----------------

def _normalize(mid):
    db.update_meeting(mid, status="processing", step="normalizing", error=None)
    adir = _audio_dir()
    # 找原始文件
    origs = [f for f in os.listdir(adir) if f.startswith(f"{mid}_orig.")]
    if not origs:
        raise RuntimeError("找不到原始音频文件")
    src = os.path.join(adir, origs[0])
    dst = os.path.join(adir, f"{mid}.mp3")
    audio_utils.normalize_to_mp3(src, dst)
    duration = audio_utils.probe_duration(dst)

    chunks = [[0.0, duration]]
    if get_transcriber() == "ark" and duration > get_config()["chunk_seconds"]:
        target = int(get_config()["chunk_seconds"])
        max_len = target * 2
        silences = audio_utils.detect_silences(dst)
        chunks = audio_utils.smart_chunks(duration, silences, target, max_len)
        # 物理切片
        for idx, (cs, ce) in enumerate(chunks):
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-ss", str(cs), "-t", str(round(ce - cs, 2)), "-i", dst,
                 "-c:a", "copy", _part_path(mid, idx)],
                check=True, capture_output=True,
            )
    merged = _load_meta(mid)
    merged["chunks"] = chunks
    db.update_meeting(
        mid, duration=round(duration, 2), audio_file=f"{mid}.mp3",
        meta=json.dumps(merged, ensure_ascii=False),
    )


def _transcribe(mid):
    db.update_meeting(mid, status="processing", step="transcribing", error=None)
    engine = get_transcriber()
    mp3 = os.path.join(_audio_dir(), f"{mid}.mp3")

    if engine == "whisper-local":
        rows = [(i, round(s, 2), round(e, 2), t)
                for i, (s, e, t) in enumerate(WhisperLocal.transcribe_segments(mp3))]
    else:
        chunks = _load_meta(mid).get("chunks") or [[0.0, db.get_meeting(mid)["duration"]]]
        ark = ArkClient()
        futs = []
        single = len(chunks) == 1
        for idx, (cs, ce) in enumerate(chunks):
            src = mp3 if single else _part_path(mid, idx)
            futs.append((idx, cs, ce, _asr_pool.submit(ark.transcribe_file, src)))
        rows = []
        for idx, cs, ce, fut in sorted(futs):
            text = fut.result().strip()
            if text:
                rows.append((idx, round(cs, 2), round(ce, 2), text))

    if not rows or not any(r[3] for r in rows):
        raise RuntimeError("未识别到任何语音内容（可能是纯静音或损坏的音频）")
    db.replace_segments(mid, rows)
    db.update_meeting(mid, step="transcribed")
    cleanup_parts(mid)


def _fmt_transcript(segs) -> str:
    return "\n".join(f"[{audio_utils.fmt_ts(s['t_start'])}] {s['text']}" for s in segs)


def _base_doc(mid) -> str:
    art = db.get_artifact(mid, "polished")
    return art["content"] if art else _fmt_transcript(db.list_segments(mid))


def _polish(mid):
    db.update_meeting(mid, status="processing", step="polishing", error=None)
    doc = ArkClient().chat_text(
        "你是一名专业的会议记录员，输出整洁、忠实、不编造。",
        PROMPT_POLISH.format(hint=build_context_hint(),
                             transcript=_fmt_transcript(db.list_segments(mid))),
    )
    db.upsert_artifact(mid, "polished", doc)
    db.update_meeting(mid, step="polished_done")


def _summarize(mid):
    db.update_meeting(mid, status="processing", step="summarizing", error=None)
    raw = ArkClient().chat_text(
        "你是一名会议纪要助手，严格按要求输出 JSON。",
        PROMPT_SUMMARY.format(hint=build_context_hint(), doc=_base_doc(mid)))
    md = None
    data = None
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        try:
            data = json.loads(match.group())
            md = summary_json_to_md(data)
        except Exception:
            md = None
    if md is None:
        md = SUMMARY_FALLBACK_MD.format(raw=raw.strip()[:3000])
    db.upsert_artifact(mid, "summary", md)
    _auto_title(mid, data)
    db.update_meeting(mid, status="done", step="summary_done", error=None)


def _auto_title(mid, data):
    """AI 根据内容归纳会议名（≤20字）。用户手动命名过的（meta.title_source=user）不覆盖。"""
    if not data or not (data.get("meeting_title") or "").strip():
        return
    m = db.get_meeting(mid)
    try:
        meta = json.loads(m.get("meta") or "{}")
    except Exception:
        meta = {}
    if meta.get("title_source") == "user":
        return
    title = str(data["meeting_title"]).strip()[:20]
    if title and title != m["title"]:
        db.update_meeting(mid, title=title)


def cleanup_parts(mid):
    for f in os.listdir(_audio_dir()):
        if f.startswith(f"{mid}_part"):
            try:
                os.remove(os.path.join(_audio_dir(), f))
            except OSError:
                pass
