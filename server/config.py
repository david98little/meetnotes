"""配置中心：data/config.json 是唯一真源，.env 仅作首次引导默认值"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
WEB_DIR = os.path.join(BASE_DIR, "web")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    "ark_api_key": "",
    "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "asr_model": "doubao-seed-2-0-mini-260428",
    "llm_model": "doubao-seed-2-0-mini-260428",
    "transcriber": "ark",            # ark | whisper-local
    "whisper_model_size": "small",
    "hotwords": "",
    "attendees": "",
    "chunk_seconds": 600,            # ASR 切片目标时长
}


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)


def _bootstrap():
    """首次初始化：config.json 不存在时由 .env / 环境变量填充默认值"""
    global CONFIG
    if not os.path.exists(CONFIG_PATH):
        cfg = dict(DEFAULTS)
        env_key = ""
        env_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line.startswith("ARK_API_KEY="):
                    env_key = line.split("=", 1)[1].strip()
        cfg["ark_api_key"] = os.getenv("ARK_API_KEY", "") or env_key or cfg["ark_api_key"]
        save_config(cfg)


def get_config() -> dict:
    global CONFIG
    return CONFIG


def load_all():
    global CONFIG
    ensure_dirs()
    _bootstrap()
    with open(CONFIG_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    CONFIG = {**DEFAULTS, **saved}
    return CONFIG


def save_config(cfg: dict):
    merged = {**DEFAULTS, **cfg}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    global CONFIG
    CONFIG = merged


CONFIG = {}
load_all()
