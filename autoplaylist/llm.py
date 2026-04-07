from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from autoplaylist import config as cfg

_SYSTEM_PROMPT = """\
You are a music recommendation expert. Given a song name, artist, or mood description, \
recommend a playlist of SIMILAR songs. Return ONLY valid JSON with no extra text.

Rules:
- If input is a specific song (e.g. "后来", "Someone Like You"): recommend 20 DIFFERENT songs \
  with similar style/mood. STRICT: do NOT include the input song, its covers, its remixes, \
  its live versions, or any song with the same title in ANY language. Every recommended song \
  must be a COMPLETELY DIFFERENT song by a DIFFERENT artist.
- If input is a mood/genre description: recommend 20 matching songs.
- Recommend songs in the SAME LANGUAGE as the input when possible.
- Each entry in "songs" must be a specific "Artist - Title" pair suitable for YouTube search.

Return exactly this JSON schema:
{
  "songs": ["Artist - Title", "Artist - Title", ...],
  "mood": "single mood descriptor"
}

Examples:
- "后来" → {"songs": ["刘若英 - 很爱很爱你", "孙燕姿 - 遇见", "梁静茹 - 勇气", "陈奕迅 - 十年", \
  "周杰伦 - 青花瓷", "王菲 - 红豆", "张惠妹 - 我可以抱你吗", "林忆莲 - 至少还有你", \
  "许茹芸 - 如果云知道", "莫文蔚 - 他不爱我"], "mood": "melancholic"}
- "rainy lo-fi jazz" → {"songs": ["Norah Jones - Don't Know Why", "Billie Holiday - The Very Thought of You", \
  "Bill Evans - Waltz for Debby", "Miles Davis - Blue in Green", "Chet Baker - Almost Blue"], "mood": "relaxing"}
- "something like Radiohead" → {"songs": ["Portishead - Glory Box", "Massive Attack - Teardrop", \
  "Thom Yorke - Analyse", "Sigur Ros - Hoppipolla", "Bjork - Joga"], "mood": "melancholic"}
"""

_TIMEOUT = 30
_GEMINI_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# OpenAI-compatible backend presets
# (base_url, default_model, config_key_for_api_key)
# None api key config → no key required (Ollama)
# ---------------------------------------------------------------------------
_PRESETS: dict[str, tuple[str, str, str | None]] = {
    "groq":          ("https://api.groq.com/openai/v1",                    "llama-3.1-70b-versatile", "llm_api_key"),
    "deepseek":      ("https://api.deepseek.com/v1",                        "deepseek-chat",           "llm_api_key"),
    "qwen":          ("https://dashscope.aliyuncs.com/compatible-mode/v1",  "qwen-turbo",              "llm_api_key"),
    "kimi":          ("https://api.moonshot.cn/v1",                         "moonshot-v1-8k",          "llm_api_key"),
    "ollama":        ("http://localhost:11434/v1",                           "qwen2.5:7b",              None),
    "openai-compat": ("",                                                    "",                        "llm_api_key"),
}


# ---------------------------------------------------------------------------
# Claude backend
# ---------------------------------------------------------------------------

def _find_claude() -> str | None:
    if shutil.which("claude"):
        return "claude"
    return None


def _call_claude(prompt: str) -> str:
    claude = _find_claude()
    if not claude:
        return ""

    full_prompt = f"{_SYSTEM_PROMPT}\n\nMusic description: {prompt}"
    try:
        result = subprocess.run(
            [claude, "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            stdin=subprocess.DEVNULL,  # don't inherit raw-mode TTY stdin
        )
    except subprocess.TimeoutExpired:
        print("LLM timed out.")
        return ""
    except Exception:
        print("LLM subprocess error.")
        return ""

    if result.returncode != 0:
        print("LLM returned non-zero exit.")
        return ""

    return result.stdout


# ---------------------------------------------------------------------------
# Gemini backend
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str) -> str:
    import json as _json
    import urllib.request
    import urllib.error

    api_key = cfg.get("gemini_api_key")
    if not api_key:
        print("Gemini API key not configured. Run `myplaylist setup` to set it up.")
        return ""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={api_key}"
    )
    body = _json.dumps({
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": f"Music description: {prompt}"}]}],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = _json.loads(resp.read())
        candidates = data.get("candidates", [])
        if not candidates:
            print(f"Gemini returned no candidates: {data}")
            return ""
        return candidates[0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="replace")
        print(f"Gemini API error {e.code}: {body_err[:200]}")
        return ""
    except Exception as e:
        print(f"Gemini error: {e}")
        return ""


# ---------------------------------------------------------------------------
# OpenAI-compatible backend (Groq, DeepSeek, Qwen, Kimi, Ollama, custom)
# ---------------------------------------------------------------------------

def _call_openai_compat(endpoint: str, api_key: str | None, model: str,
                        system_prompt: str, user_msg: str) -> str:
    import json as _json
    import urllib.request
    import urllib.error

    body = _json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
    }).encode()

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=body,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = _json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="replace")
        print(f"LLM API error {e.code}: {body_err[:200]}")
        return ""
    except Exception as e:
        print(f"LLM error ({endpoint}): {e}")
        return ""


def _call_via_preset(backend: str, system_prompt: str, user_msg: str) -> str:
    """Resolve preset config and call OpenAI-compat endpoint."""
    preset = _PRESETS.get(backend)
    if not preset:
        return ""
    base_url, default_model, key_cfg = preset

    # openai-compat: endpoint and model come from user config
    if backend == "openai-compat":
        base_url = cfg.get("openai_compat_endpoint") or ""
        default_model = cfg.get("llm_model") or ""
        if not base_url or not default_model:
            print("openai-compat backend requires 'openai_compat_endpoint' and 'llm_model' in config.")
            return ""

    # ollama: model override via ollama_model config key
    if backend == "ollama":
        default_model = cfg.get("ollama_model", default_model)

    # allow per-backend model override via llm_model
    model = cfg.get("llm_model") or default_model

    api_key: str | None = None
    if key_cfg:
        api_key = cfg.get(key_cfg)
        if not api_key:
            print(f"{backend} backend requires '{key_cfg}' in config. Run `myplaylist setup` to set it.")
            return ""

    return _call_openai_compat(base_url, api_key, model, system_prompt, user_msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_prompt(text: str) -> dict[str, Any]:
    """
    Call the configured LLM backend to get song recommendations.
    Returns dict with keys: songs (list of 'Artist - Title'), mood (str).
    Falls back to empty result on any failure.
    """
    backend = cfg.get("llm_backend", "claude")

    if backend == "gemini":
        raw = _call_gemini(text)
    elif backend in _PRESETS:
        raw = _call_via_preset(backend, _SYSTEM_PROMPT, f"Music description: {text}")
    else:
        raw = _call_claude(text)

    if not raw:
        return _fallback(text)

    return _parse_json_response(raw, text)


def _parse_json_response(output: str, original: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?\s*", "", output).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return _fallback(original, reason="LLM returned no JSON object")

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return _fallback(original, reason="LLM returned malformed JSON")

    return {
        "songs": data.get("songs", []),
        "mood": data.get("mood", ""),
    }


def _fallback(text: str, reason: str = "") -> dict[str, Any]:
    if reason:
        print(f"LLM parsing failed ({reason}). Using raw prompt as search query.")
    return {"songs": [], "mood": ""}


def get_song_recommendations(parsed: dict[str, Any]) -> list[str]:
    """Return list of 'Artist - Title' search queries from parsed output."""
    return parsed.get("songs", [])


_MOOD_LABELS = {"calm", "melancholic", "energetic", "romantic", "nostalgic"}
_MOOD_PROMPT = (
    "Reply with exactly ONE word from this list: calm, melancholic, energetic, romantic, nostalgic.\n"
    "Choose the word that best describes the mood of the song: {artist} - {title}\n"
    "Reply with only the single word, nothing else."
)


def classify_mood(artist: str, title: str) -> str:
    """Return a mood label for the given track. Falls back to 'calm' on any error."""
    prompt = _MOOD_PROMPT.format(artist=artist, title=title)
    backend = cfg.get("llm_backend", "claude")
    try:
        if backend == "gemini":
            raw = _call_gemini_simple(prompt)
        elif backend in _PRESETS:
            raw = _call_via_preset(backend, "You are a music mood classifier.", prompt)
        else:
            raw = _call_claude_simple(prompt)
        word = raw.strip().lower().split()[0] if raw.strip() else ""
        return word if word in _MOOD_LABELS else "calm"
    except Exception:
        return "calm"


def _call_claude_simple(prompt: str) -> str:
    """Call Claude with a plain prompt (no music system prompt)."""
    claude = _find_claude()
    if not claude:
        return ""
    try:
        result = subprocess.run(
            [claude, "-p", prompt],
            capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _call_gemini_simple(prompt: str) -> str:
    """Call Gemini with a plain prompt (no music system prompt)."""
    import urllib.request, urllib.error
    api_key = cfg.get("gemini_api_key")
    if not api_key:
        return ""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_GEMINI_MODEL}:generateContent?key={api_key}")
    import json as _json
    body = _json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return ""
