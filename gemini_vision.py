"""Gemini Vision classification for Instagram reels (deepfake / anti-India / dangerous / kid safety).

Environment:
  GEMINI_API_KEY        - REQUIRED for calls
  USE_GEMINI_VISION=1   - Enable this module usage
  GEMINI_VISION_MODEL   - Model id (default gemini-1.5-flash-latest)
  GEMINI_TIMEOUT=12     - Seconds HTTP timeout
  GEMINI_CACHE_DIR=.gemini_cache  - Cache directory
  DEBUG_DETECT=1        - Verbose logging

Function:
  classify_image(image_path, context_text="") -> dict | None

Returns dict keys:
  deepfake, anti_india, dangerous, not_kid_safe (bools), reason (str)

Caching: keyed by SHA1(image_bytes + context_text[:300]) to avoid repeat calls.
"""
from __future__ import annotations
import os, json, base64, hashlib, time
from typing import Optional, Dict, Any

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

_API_KEY = os.getenv("GEMINI_API_KEY", "")
_MODEL = os.getenv("GEMINI_VISION_MODEL", os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest"))
_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "12"))
_CACHE_DIR = os.getenv("GEMINI_CACHE_DIR", ".gemini_cache")
_DEBUG = os.getenv("DEBUG_DETECT", "0").lower() in {"1","true","yes"}

if not os.path.exists(_CACHE_DIR):
    try: os.makedirs(_CACHE_DIR, exist_ok=True)
    except Exception: pass

PROMPT = (
    "You are a strict safety and moderation classifier. Given an image (a frame from an Instagram reel) and optional text context, "
    "decide if it shows or implies: (a) a deepfake or AI-generated deceptive human likeness; (b) hostile, hateful or disparaging content targeting India or Indians; "
    "(c) dangerous acts (violence, weapons, self-harm, explicit illegal drugs); (d) content not suitable for young children (sexual, graphic, strong hate, gore).\n"
    "Return ONLY compact JSON with keys: deepfake (true/false), anti_india (true/false), dangerous (true/false), not_kid_safe (true/false), reason (short concise phrase).\n"
    "If unsure, use false for all and reason 'uncertain'."
)

JSON_KEYS = {"deepfake","anti_india","dangerous","not_kid_safe","reason"}

def _cache_path(image_bytes: bytes, context: str) -> str:
    h = hashlib.sha1(image_bytes + context[:300].encode('utf-8', 'ignore')).hexdigest()
    return os.path.join(_CACHE_DIR, f"vision_{h}.json")


def classify_image(image_path: str, context_text: str = "") -> Optional[Dict[str, Any]]:
    if not _API_KEY or not requests:
        return None
    try:
        with open(image_path, 'rb') as f:
            img_bytes = f.read()
    except Exception:
        return None
    cpath = _cache_path(img_bytes, context_text)
    if os.path.exists(cpath):
        try:
            with open(cpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    b64 = base64.b64encode(img_bytes).decode('ascii')
    content_parts = [
        {"text": PROMPT},
        {"text": f"Context: {context_text[:400]}" if context_text else "Context: (none)"}
    ]
    # Gemini API expects separate parts; image inline_data
    payload = {
        "contents": [
            {"parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": b64}},
                {"text": (context_text[:800] or "(no additional text context)")}
            ]}
        ],
        "generationConfig": {"candidateCount": 1, "temperature": 0}
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent?key={_API_KEY}"
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        out_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        start = out_text.find('{'); end = out_text.rfind('}')
        result = None
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(out_text[start:end+1])
                # normalize fields
                norm = {
                    'deepfake': bool(parsed.get('deepfake', False)),
                    'anti_india': bool(parsed.get('anti_india', False)),
                    'dangerous': bool(parsed.get('dangerous', False)),
                    'not_kid_safe': bool(parsed.get('not_kid_safe', False)),
                    'reason': str(parsed.get('reason', ''))[:160]
                }
                result = norm
            except Exception:
                result = None
        if result:
            try:
                with open(cpath, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                if _DEBUG:
                    print(f"[GEMINI_VISION][CACHE_WRITE] {cpath}")
            except Exception:
                pass
            return result
        else:
            if _DEBUG:
                print(f"[GEMINI_VISION][PARSE_FAIL] Raw snippet: {out_text[:120]}")
            return None
    except Exception as e:
        if _DEBUG:
            print(f"[GEMINI_VISION][ERROR] {e}")
        return None

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--context', default='')
    args = ap.parse_args()
    print(classify_image(args.image, args.context))
