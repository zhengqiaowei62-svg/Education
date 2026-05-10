"""双 Agent LLM 客户端封装。

两个角色：
    role="extractor"  → Agent A · 苦力（ModelScope / Qwen，便宜量大、强 JSON）
    role="judge"      → Agent B · 智囊（OpenAI / Codex，对齐裁决 & RAG 回答）

环境变量（.env 自动加载，位于项目根目录）：
    EXTRACTOR_API_KEY    Qwen / ModelScope token
    EXTRACTOR_BASE_URL   默认 https://ms-ens-f456e73b-c835.api-inference.modelscope.cn/v1
    EXTRACTOR_MODEL      默认 TeichAI/Qwen3-14B-Claude-4.5-Opus-High-Reasoning-Distill-GGUF

    JUDGE_API_KEY        OpenAI / Codex sk-…
    JUDGE_BASE_URL       默认 https://api.openai.com/v1（可改 Azure / 代理）
    JUDGE_MODEL          默认 gpt-4o-mini

    OPENAI_API_KEY       兼容旧配置（找不到 JUDGE_API_KEY 时自动使用）
    OPENAI_BASE_URL / LLM_MODEL 同上
"""
from __future__ import annotations
import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


# ---------- .env 简易加载（不依赖 python-dotenv） ----------
def _load_dotenv() -> None:
    root = Path(__file__).resolve().parents[2]  # 项目根
    for candidate in (root / ".env", root / ".env.local"):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception as e:
            print(f"[llm] .env 加载失败 {candidate}: {e}")


_load_dotenv()


# ---------- 角色配置 ----------
DEFAULTS: Dict[str, Dict[str, str]] = {
    "extractor": {
        "key_env":  "EXTRACTOR_API_KEY",
        "base_env": "EXTRACTOR_BASE_URL",
        "model_env": "EXTRACTOR_MODEL",
        "base_default": "https://ms-ens-f456e73b-c835.api-inference.modelscope.cn/v1",
        "model_default": "TeichAI/Qwen3-14B-Claude-4.5-Opus-High-Reasoning-Distill-GGUF",
        "fallback_keys": ("MIMO_API_KEY", "QWEN_API_KEY", "MODELSCOPE_API_KEY"),
    },
    "judge": {
        "key_env":  "JUDGE_API_KEY",
        "base_env": "JUDGE_BASE_URL",
        "model_env": "JUDGE_MODEL",
        "base_default": "https://api.openai.com/v1",
        "model_default": "gpt-4o-mini",
        "fallback_keys": ("OPENAI_API_KEY",),
    },
}


def _role_config(role: str) -> Dict[str, str | None]:
    cfg = DEFAULTS.get(role) or DEFAULTS["judge"]
    api_key = os.getenv(cfg["key_env"]) or ""
    if not api_key:
        for fk in cfg["fallback_keys"]:
            api_key = os.getenv(fk) or ""
            if api_key:
                break
    base_url = os.getenv(cfg["base_env"]) or cfg["base_default"]
    # judge 角色若用 fallback OPENAI_BASE_URL 也兼容
    if role == "judge" and not os.getenv(cfg["base_env"]) and os.getenv("OPENAI_BASE_URL"):
        base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv(cfg["model_env"]) or os.getenv("LLM_MODEL") or cfg["model_default"]
    return {"api_key": api_key, "base_url": base_url, "model": model}


_client_cache: Dict[str, Any] = {}


def _client(role: str):
    if role in _client_cache:
        return _client_cache[role]
    if OpenAI is None:
        raise RuntimeError("openai package not installed")
    cfg = _role_config(role)
    if not cfg["api_key"]:
        raise RuntimeError(f"[{role}] api_key 未配置 (检查 .env / 环境变量)")
    _client_cache[role] = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    return _client_cache[role]


def llm_available(role: str = "judge") -> bool:
    return bool(_role_config(role)["api_key"])


def model_for(role: str) -> str:
    return _role_config(role)["model"] or ""


# ---------- 对话 ----------
def chat(prompt: str, system: str = "", role: str = "judge",
         model: str | None = None, temperature: float = 0.2,
         max_tokens: int = 2000, json_mode: bool = False) -> str:
    cfg = _role_config(role)
    use_model = model or cfg["model"]
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})

    kwargs: Dict[str, Any] = dict(
        model=use_model, messages=msgs,
        temperature=temperature, max_tokens=max_tokens,
    )
    if json_mode:
        # OpenAI / Qwen 都支持 response_format={"type":"json_object"}
        kwargs["response_format"] = {"type": "json_object"}

    import time
    last_err: Exception | None = None
    max_attempts = 10  # ModelScope GGUF 冷启动可能 1–3 分钟
    for attempt in range(max_attempts):
        try:
            resp = _client(role).chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            msg = str(e)
            last_err = e
            # gguf 部署不接受 response_format，降级重试
            if json_mode and "response_format" in msg and "response_format" in kwargs:
                kwargs.pop("response_format", None)
                continue
            # ModelScope 冷启动 (425) / 网关错误：等待后重试
            if any(k in msg for k in ("425", "waking up", "502", "503", "504", "timeout")):
                wait = min(15, 3 * (attempt + 1))
                print(f"[llm:{role}] transient (attempt {attempt+1}/{max_attempts}): {msg[:100]} → retry in {wait}s")
                time.sleep(wait)
                continue
            raise
    raise last_err  # type: ignore[misc]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def chat_json(prompt: str, system: str = "", role: str = "judge",
              default: Any = None, **kw) -> Any:
    """要求 LLM 输出 JSON。失败/无 key 时返回 default。"""
    sys_prompt = system or "你必须只输出合法 JSON，不要包含任何解释文字或 markdown 代码块。"
    try:
        raw = chat(prompt, system=sys_prompt, role=role, json_mode=True, **kw)
    except Exception as e:
        print(f"[llm:{role}] chat_json error: {e}")
        return default
    raw = _FENCE.sub("", raw).strip()
    s, e = raw.find("{"), raw.rfind("}")
    a, b = raw.find("["), raw.rfind("]")
    if s >= 0 and e > s and (a < 0 or s < a):
        raw = raw[s:e + 1]
    elif a >= 0 and b > a:
        raw = raw[a:b + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[llm:{role}] JSON parse fail: {exc} | raw head: {raw[:200]}")
        return default


# ---------- 简易相似度（无需向量模型） ----------
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")


def tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def text_similarity(a: str, b: str) -> float:
    """字符/词级 Jaccard，对中文友好。"""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
