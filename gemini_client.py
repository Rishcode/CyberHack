"""Gemini (Google AI) secondary classifier integration.

Usage:
  Set environment variables:
    GEMINI_API_KEY=your_key
    USE_GEMINI=1
    GEMINI_MODEL=gemini-1.5-flash-latest (default) or another supported model.
    GEMINI_TIMEOUT=12  (seconds)
    GEMINI_CACHE_DIR=.gemini_cache  (optional)

  Then detection_model.detect_hate_or_anti_india will invoke Gemini only if
  local detection did not already flag text.

Security: DO NOT hardcode keys in source. Provide via environment / secrets manager.
"""
from __future__ import annotations
import os, json, hashlib, time
from typing import Optional, Dict, Any

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")
_API_KEY = os.getenv("GEMINI_API_KEY", "")
_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "12"))
_CACHE_DIR = os.getenv("GEMINI_CACHE_DIR", ".gemini_cache")
_DEBUG = os.getenv("DEBUG_DETECT", "0").lower() in {"1","true","yes"}

PROMPT_TEMPLATE = (
    "You are a strict moderation classifier. Assess the following content for: "
    "(a) general hate or abusive / harassing language; (b) hostile / disparaging content targeting India or Indians. "
    "Return ONLY compact JSON object with keys: hate (true/false), anti_india (true/false), reason (short phrase).\n\nContent:\n<<<\n{content}\n>>>"
)

if not os.path.exists(_CACHE_DIR):  # light weight lazy creation
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
    except Exception:
        pass

def _cache_path(text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return os.path.join(_CACHE_DIR, f"{h}.json")


def gemini_classify(text: str) -> Optional[Dict[str, Any]]:
    """Call Gemini API for classification. Returns dict or None on failure.
    Caches responses keyed by SHA1 of text.
    """
    if not _API_KEY or not requests:
        return None
    text = (text or "").strip()
    if not text:
        return None
    cpath = _cache_path(text)
    if os.path.exists(cpath):
        try:
            with open(cpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_DEFAULT_MODEL}:generateContent?key={_API_KEY}"
    payload = {
        "contents": [
            {"parts": [{"text": PROMPT_TEMPLATE.format(content=text)}]}
        ],
        "generationConfig": {"candidateCount": 1, "temperature": 0}
    }
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        out_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        # Extract JSON substring
        start = out_text.find('{')
        end = out_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            js = out_text[start:end+1]
            try:
                parsed = json.loads(js)
                with open(cpath, 'w', encoding='utf-8') as f:
                    json.dump(parsed, f, ensure_ascii=False, indent=2)
                if _DEBUG:
                    print(f"[GEMINI][CACHE_WRITE] {cpath}")
                return parsed
            except Exception:
                if _DEBUG:
                    print("[GEMINI][PARSE_FAIL] Raw:", out_text[:120])
                return None
    except Exception as e:
        if _DEBUG:
            print(f"[GEMINI][ERROR] {e}")
        return None
    return None

if __name__ == "__main__":  # manual test
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    args = ap.parse_args()
    print(gemini_classify(args.text))
