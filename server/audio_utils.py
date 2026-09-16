"""ffmpeg 工具：探测时长 / 归一化转码 / 智能静音切片"""
import math
import re
import subprocess


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 执行失败: {p.stderr[-500:]}")
    return p.stdout


def probe_duration(path) -> float:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path,
    ])
    return float(out.strip())


def normalize_to_mp3(src, dst):
    """统一转成 16kHz 单声道 32kbps MP3：体积小、兼容浏览器播放、适合送云端"""
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
          "-b:a", "32k", "-ar", "16000", "-ac", "1", dst])


def detect_silences(path) -> list[tuple[float, float]]:
    """返回 [(silence_start, silence_end)]，用于寻找安全的切分点"""
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.7", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    pairs = []
    for s in starts:
        e = next((x for x in ends if x > s), None)
        pairs.append((s, e if e is not None else s + 0.7))
    return pairs


def smart_chunks(duration: float, silences: list, target: int, max_len: int) -> list[list[float]]:
    """
    按 target 秒切分；切点尽量落在静音区间中部（不切断句子）。
    返回 [[start,end],...]，个别超长静音段导致无切点时按 max_len 强切。
    """
    chunks, cur = [], 0.0
    while cur < duration - 1:
        ideal = cur + target
        hard = cur + max_len
        cut = None
        if ideal >= duration:
            chunks.append([cur, duration])
            break
        candidates = []
        for s, e in silences:
            mid = (s + e) / 2
            if cur + 20 < mid <= ideal:
                candidates.append(mid)
        if candidates:
            # 取不超过 ideal 的最靠后静音点，天然贴合 target
            cut = candidates[-1]
        elif ideal < hard:
            cut = ideal
        else:
            cut = hard
        chunks.append([cur, min(cut, duration)])
        cur = cut
    return chunks or [[0.0, duration]]


def fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
