"""配置中心：data/config.json 是唯一真源，.env 仅作首次引导默认值

双通道结构：asr（语音识别）与 llm（文本生成）各自独立配置
base_url / api_key / model，可分别接入不同厂商（方舟、DeepSeek 官方、
任意 OpenAI 兼容端点）。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
WEB_DIR = os.path.join(BASE_DIR, "web")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"

DEFAULTS = {
    "transcriber": "ark",            # ark | whisper-local
    "asr": {
        "base_url": ARK_BASE,
        "api_key": "",
        "model": "doubao-seed-2-0-mini-260428",
    },
    "llm": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-flash",
        "thinking": "disabled",      # disabled | enabled（deepseek 系思考模型开关）
    },
    "whisper_model_size": "small",
    "hotwords": "",
    "attendees": "",
    "chunk_seconds": 600,            # ASR 切片目标时长
}


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)


def _read_env_key() -> str:
    env_key = os.getenv("ARK_API_KEY", "")
    if env_key:
        return env_key
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("ARK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 里的子字段覆盖 base，缺失子字段用 base 默认值补齐"""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _migrate(saved: dict) -> dict:
    """旧扁平配置（ark_api_key/asr_model/llm_model ...）→ 新双通道结构"""
    if "asr" in saved or "llm" in saved:
        return saved
    asr = dict(DEFAULTS["asr"])
    if saved.get("ark_api_key"):
        asr["api_key"] = saved["ark_api_key"]
    if saved.get("ark_base_url"):
        asr["base_url"] = saved["ark_base_url"]
    if saved.get("asr_model"):
        asr["model"] = saved["asr_model"]

    # 旧 llm_model 保持迁移后行为不变：默认仍指向方舟端
    llm = dict(DEFAULTS["llm"])
    llm["base_url"] = saved.get("ark_base_url") or ARK_BASE
    llm["api_key"] = asr["api_key"]
    llm["model"] = saved.get("llm_model") or DEFAULTS["llm"]["model"]
    llm["thinking"] = "enabled" if "deepseek" in llm["model"] else "disabled"

    out = {k: v for k, v in saved.items() if k not in
           ("ark_api_key", "ark_base_url", "asr_model", "llm_model")}
    out["asr"] = asr
    out["llm"] = llm
    return out


def _bootstrap():
    """首次初始化：config.json 不存在时由 .env / 环境变量填充 ASR 默认值"""
    global CONFIG
    if not os.path.exists(CONFIG_PATH):
        cfg = dict(DEFAULTS)
        env_key = _read_env_key()
        if env_key:
            cfg["asr"]["api_key"] = env_key
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
    CONFIG = _deep_merge(DEFAULTS, _migrate(saved))
    return CONFIG


def save_config(cfg: dict):
    merged = _deep_merge(DEFAULTS, _migrate(cfg))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    global CONFIG
    CONFIG = merged


CONFIG = {}
load_all()
