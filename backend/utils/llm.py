"""双 Agent LLM 客户端封装。

两个角色：
    role="extractor"  → Agent A · 苦力（ModelScope / Qwen，便宜量大、强 JSON）
    role="judge"      → Agent B · 智囊（ModelScope / Qwen，对齐裁决 & RAG 回答）

环境变量（.env 自动加载，位于项目根目录）：
    EXTRACTOR_API_KEY    Qwen / ModelScope token
    EXTRACTOR_BASE_URL   默认 https://ms-ens-f456e73b-c835.api-inference.modelscope.cn/v1
    EXTRACTOR_MODEL      默认 TeichAI/Qwen3-14B-Claude-4.5-Opus-High-Reasoning-Distill-GGUF

    JUDGE_API_KEY        ModelScope / OpenAI token
    JUDGE_BASE_URL       默认 ModelScope 端点（可改为其他兼容端点）
    JUDGE_MODEL          默认 TeichAI/Qwen3-14B-Claude-4.5-Opus-High-Reasoning-Distill-GGUF
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
        "base_default": "https://ms-ens-f456e73b-c835.api-inference.modelscope.cn/v1",
        "model_default": "TeichAI/Qwen3-14B-Claude-4.5-Opus-High-Reasoning-Distill-GGUF",
        "fallback_keys": ("MODELSCOPE_API_KEY", "EXTRACTOR_API_KEY"),
    },
    "vision": {
        "key_env":  "VISION_API_KEY",
        "base_env": "VISION_BASE_URL",
        "model_env": "VISION_MODEL",
        "base_default": "https://ms-ens-1b7b4b03-431b.api-inference.modelscope.cn/v1",
        "model_default": "OpenDataLab/MinerU2.5-Pro-2604-1.2B",
        "fallback_keys": ("MODELSCOPE_API_KEY", "EXTRACTOR_API_KEY"),
    },
}


# ---------- Ollama 本地部署支持（OpenAI 兼容） ----------
# 用户在 .env 中设置 LLM_PROVIDER=ollama 即可把 extractor/judge 全部切换到本地 Ollama。
#   OLLAMA_BASE_URL  默认 http://localhost:11434/v1
#   OLLAMA_MODEL     默认 qwen2.5:7b
# 也可单独覆盖 EXTRACTOR_BASE_URL / JUDGE_BASE_URL 走 Ollama，其它继续走云端。
def _maybe_use_ollama(role: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider != "ollama":
        return cfg
    cfg = dict(cfg)
    cfg["api_key"] = cfg.get("api_key") or os.getenv("OLLAMA_API_KEY") or "ollama"  # 任意非空字符串
    cfg["base_url"] = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    cfg["model"] = (
        os.getenv(f"{role.upper()}_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or "qwen2.5:7b"
    )
    return cfg


def _role_config(role: str) -> Dict[str, str | None]:
    cfg = DEFAULTS.get(role) or DEFAULTS["judge"]
    api_key = os.getenv(cfg["key_env"]) or ""
    if not api_key:
        for fk in cfg["fallback_keys"]:
            api_key = os.getenv(fk) or ""
            if api_key:
                break
    base_url = os.getenv(cfg["base_env"]) or cfg["base_default"]
    model = os.getenv(cfg["model_env"]) or os.getenv("LLM_MODEL") or cfg["model_default"]
    return _maybe_use_ollama(role, {"api_key": api_key, "base_url": base_url, "model": model})


_client_cache: Dict[str, Any] = {}


# ---------- Token 用量统计（全进程，可被 /api/stats/tokens 读取） ----------
TOKEN_USAGE: Dict[str, Dict[str, int]] = {
    "extractor": {"prompt": 0, "completion": 0, "calls": 0},
    "judge":     {"prompt": 0, "completion": 0, "calls": 0},
    "vision":    {"prompt": 0, "completion": 0, "calls": 0},
}


def _approx_tokens(text: str) -> int:
    """无 tokenizer 时的近似估算：中文按字符、英文按词 0.75 比例。"""
    if not text:
        return 0
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    en = max(0, len(text) - cn)
    return cn + max(1, int(en / 4))


def _record_usage(role: str, prompt_text: str, completion_text: str, usage_obj=None) -> None:
    """优先使用 SDK 返回的 usage，缺失时按字符近似。"""
    bucket = TOKEN_USAGE.setdefault(role, {"prompt": 0, "completion": 0, "calls": 0})
    bucket["calls"] += 1
    p = c = 0
    try:
        if usage_obj is not None:
            p = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
            c = int(getattr(usage_obj, "completion_tokens", 0) or 0)
    except Exception:
        pass
    if not p:
        p = _approx_tokens(prompt_text)
    if not c:
        c = _approx_tokens(completion_text)
    bucket["prompt"] += p
    bucket["completion"] += c


def get_token_usage() -> Dict[str, Any]:
    total_prompt = sum(b["prompt"] for b in TOKEN_USAGE.values())
    total_completion = sum(b["completion"] for b in TOKEN_USAGE.values())
    total_calls = sum(b["calls"] for b in TOKEN_USAGE.values())
    return {
        "by_role": TOKEN_USAGE,
        "total": {
            "prompt": total_prompt,
            "completion": total_completion,
            "tokens": total_prompt + total_completion,
            "calls": total_calls,
        },
    }


def reset_token_usage() -> None:
    for bucket in TOKEN_USAGE.values():
        bucket["prompt"] = bucket["completion"] = bucket["calls"] = 0


def _client(role: str):
    if role in _client_cache:
        return _client_cache[role]
    if OpenAI is None:
        raise RuntimeError("openai package not installed")
    cfg = _role_config(role)
    if not cfg["api_key"]:
        raise RuntimeError(f"[{role}] api_key 未配置 (检查 .env / 环境变量)")
    # ModelScope 部分端点对非流式请求会无响应直到超时，
    # 这里给客户端默认 180s 超时，避免应用层阻塞。
    _client_cache[role] = OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=180.0,
        max_retries=0,  # 我们自己重试，避免 SDK 静默 sleep
    )
    return _client_cache[role]


def llm_available(role: str = "judge") -> bool:
    return bool(_role_config(role)["api_key"])


def model_for(role: str) -> str:
    return _role_config(role)["model"] or ""


def _is_quota_error(message: str) -> bool:
    lower = message.lower()
    return any(k in lower for k in ("429", "insufficient_quota", "exceeded your current quota", "billing"))


def _msgs_to_text(msgs: list) -> str:
    return "\n".join(str(m.get("content", "")) for m in (msgs or []))


# ---------- 文本后处理 ----------
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
# Qwen3 思考链：<think>…</think>，需要剥离才能拿到正式回答 / JSON
_THINK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)


def _strip_think(text: str) -> str:
    """剥离 <think>…</think> 推理段；若标签未闭合，截到最后一个 </think>。"""
    if not text or "<think>" not in text:
        return text or ""
    cleaned = _THINK.sub("", text)
    if "<think>" in cleaned:
        idx = cleaned.rfind("</think>")
        if idx >= 0:
            cleaned = cleaned[idx + len("</think>"):]
        else:
            # 标签从未闭合 → 整段都是 thought，丢掉
            cleaned = ""
    return cleaned.strip()


# ---------- 对话 ----------
def chat(prompt: str, system: str = "", role: str = "judge",
         model: str | None = None, temperature: float = 0.2,
         max_tokens: int = 2000, json_mode: bool = False,
         messages: list | None = None) -> str:
    cfg = _role_config(role)
    use_model = model or cfg["model"]
    msgs: List[Dict[str, str]]
    if messages is not None:
        msgs = messages
    else:
        msgs = []
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

    # Qwen3 推理模型默认开启 <think> 思考链（在流式下会拖慢大量时间）
    # 通过 extra_body 传 enable_thinking=False 关闭。
    # OpenAI 端忽略未知字段，所以这里对 judge 也安全。
    base = (cfg.get("base_url") or "").lower()
    if "modelscope" in base or "qwen" in (use_model or "").lower():
        kwargs["extra_body"] = {"enable_thinking": False}

    import time
    last_err: Exception | None = None
    max_attempts = 10  # ModelScope GGUF 冷启动可能 1–3 分钟
    # 默认走流式：ModelScope GGUF 端点对非流式请求经常挂起。
    use_stream = True
    t_start = time.time()
    print(f"[llm:{role}] → POST {cfg.get('base_url')} model={use_model} max_tokens={max_tokens}", flush=True)
    for attempt in range(max_attempts):
        try:
            if use_stream:
                t_req = time.time()
                stream = _client(role).chat.completions.create(stream=True, **kwargs)
                print(f"[llm:{role}]   stream opened in {time.time()-t_req:.1f}s, reading…", flush=True)
                parts: list[str] = []
                last_log = time.time()
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if piece:
                        parts.append(piece)
                        if time.time() - last_log > 5:
                            print(f"[llm:{role}]   recv {sum(len(p) for p in parts)} chars @ {time.time()-t_start:.1f}s", flush=True)
                            last_log = time.time()
                txt = _strip_think("".join(parts))
                print(f"[llm:{role}] ← stream done in {time.time()-t_start:.1f}s, {len(txt)} chars", flush=True)
                # 流式接口通常不返回 usage，按近似计入
                _record_usage(role, _msgs_to_text(msgs), txt, None)
                return txt
            else:
                resp = _client(role).chat.completions.create(**kwargs)
                content = _strip_think(resp.choices[0].message.content or "")
                _record_usage(role, _msgs_to_text(msgs), content, getattr(resp, "usage", None))
                return content
        except Exception as e:
            msg = str(e)
            last_err = e
            print(f"[llm:{role}] !! {type(e).__name__}: {msg[:200]}", flush=True)
            # gguf 部署不接受 response_format，降级重试
            if json_mode and "response_format" in msg and "response_format" in kwargs:
                kwargs.pop("response_format", None)
                continue
            # ModelScope 冷启动 (425) / 网关错误：等待后重试
            if any(k in msg for k in ("425", "waking up", "502", "503", "504", "timeout", "Timeout")):
                wait = min(15, 3 * (attempt + 1))
                print(f"[llm:{role}] transient (attempt {attempt+1}/{max_attempts}): {msg[:100]} → retry in {wait}s")
                time.sleep(wait)
                continue
            if role == "judge" and _is_quota_error(msg) and llm_available("extractor"):
                print("[llm:judge] quota exhausted, fallback to extractor role")
                return chat(
                    prompt,
                    system=system,
                    role="extractor",
                    model=None,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            raise
    raise last_err  # type: ignore[misc]


def chat_json(prompt: str, system: str = "", role: str = "judge",
              default: Any = None, messages: list | None = None, **kw) -> Any:
    """要求 LLM 输出 JSON。失败/无 key 时返回 default。"""
    sys_prompt = system or "你必须只输出合法 JSON，不要包含任何解释文字或 markdown 代码块。"
    try:
        raw = chat(prompt, system=sys_prompt, role=role, json_mode=True, messages=messages, **kw)
    except Exception as e:
        print(f"[llm:{role}] chat_json error: {e}")
        return default
    raw = _strip_think(raw)
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


def chat_json_validated(role: str, messages: list, model_class, max_reflexion: int = 3, **kwargs):
    """
    带 Reflexion 校验的 JSON 调用：
    1. 调用 chat_json 获取原始 JSON dict
    2. 用 model_class.model_validate(data) 校验
    3. 若 ValidationError，将错误信息追加到 messages 让 LLM 修正
    4. 最多 max_reflexion 轮
    5. 全部失败则返回 None
    """
    import copy
    from pydantic import ValidationError

    conv = copy.deepcopy(messages)
    for attempt in range(max_reflexion):
        raw = chat_json("", "", role=role, messages=conv, **kwargs)
        if raw is None:
            return None
        try:
            result = model_class.model_validate(raw)
            if attempt > 0:
                print(f"[Reflexion] 第{attempt+1}轮修正成功")
            return result
        except ValidationError as e:
            error_msg = str(e)[:800]
            print(f"[Reflexion] 第{attempt+1}轮校验失败: {error_msg[:200]}")
            conv.append({"role": "assistant", "content": str(raw)})
            conv.append({"role": "user", "content": f"你刚才生成的JSON存在格式/字段错误：\n{error_msg}\n请严格按照Schema修正后重新输出完整JSON，不要输出任何解释。"})

    print("[Reflexion] 已达最大重试次数，返回None")
    return None


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
