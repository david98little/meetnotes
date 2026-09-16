"""可插拔能力层：方舟 ASR/LLM 客户端 + 本地 Whisper（可选）"""
import base64
import json
import os

import httpx

from .config import get_config


class ArkClient:
    """火山方舟 chat/completions：文本对话 + input_audio 转写"""

    def __init__(self):
        cfg = get_config()
        self.api_key = cfg["ark_api_key"]
        self.base = cfg["ark_base_url"].rstrip("/")

    def _post(self, payload: dict) -> dict:
        r = httpx.post(
            f"{self.base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=300,
        )
        if r.status_code != 200:
            raise RuntimeError(f"方舟 API {r.status_code}: {r.text[:400]}")
        return r.json()

    def chat_text(self, system: str, user: str) -> str:
        cfg = get_config()
        resp = self._post({
            "model": cfg["llm_model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        })
        return resp["choices"][0]["message"]["content"]

    def transcribe_file(self, mp3_path: str) -> str:
        """一段音频 → 纯文本转写"""
        cfg = get_config()
        with open(mp3_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = self._post({
            "model": cfg["asr_model"],
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
                    {"type": "text", "text": "请完整逐句转写这段录音的内容，只输出转写文本，不要任何说明。"},
                ],
            }],
        })
        return resp["choices"][0]["message"]["content"]


class WhisperLocal:
    """本地离线转写（需 pip install faster-whisper，首次运行自动下载模型）"""

    _model = None
    _size = None

    @classmethod
    def available(cls) -> bool:
        try:
            import faster_whisper  # noqa
            return True
        except ImportError:
            return False

    @classmethod
    def transcribe_segments(cls, mp3_path: str) -> list[tuple[float, float, str]]:
        from faster_whisper import WhisperModel
        size = get_config()["whisper_model_size"]
        if cls._model is None or cls._size != size:
            cls._model = WhisperModel(size, device="auto", compute_type="auto")
            cls._size = size
        segments, _info = cls._model.transcribe(mp3_path, vad_filter=True)
        return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


def build_context_hint() -> str:
    """热词 + 参会人提示，注入所有 LLM 调用"""
    cfg = get_config()
    parts = []
    if cfg.get("attendees"):
        parts.append(f"本次参会人：{cfg['attendees']}")
    if cfg.get("hotwords"):
        parts.append(f"术语/专名表（转写中出现的近似词请修正为这些写法）：{cfg['hotwords']}")
    return "\n".join(parts)


def get_transcriber():
    cfg = get_config()
    if cfg["transcriber"] == "whisper-local":
        if not WhisperLocal.available():
            raise RuntimeError(
                "whisper-local 引擎未安装。请执行: pip install faster-whisper"
            )
        return "whisper-local"
    return "ark"
