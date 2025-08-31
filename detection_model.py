"""Detection module for hate speech / anti-India content.

CPU-friendly default using a lightweight Hugging Face model. You can override
model selection and thresholds via environment variables:

Env Vars:
  HATE_MODEL          - (optional) HF model id for hate speech classification
                         default: cardiffnlp/twitter-roberta-base-hate
  HATE_THRESHOLD      - Float probability threshold (default 0.60)
  HATE_ONLY           - If '1' store only flagged items (scrapers honor this)
  DISABLE_HATE_DETECT - If '1' disable model inference (always returns not flagged)

To switch to a larger instruction model (e.g., Gemma) you could implement
`_gemma_score(text)` and call it inside `detect_hate_or_anti_india`.

Returned tuple: (flag: bool, reason: str)

Reason examples:
  'hate:0.82 label=hate'
  'anti-india-keyword:"india sucks"'
  'india+hate-keyword:"destroy"'

If the transformers library or model isn't available, falls back to
keyword heuristics.
"""
from __future__ import annotations
import os
from functools import lru_cache
from typing import Tuple

# Basic keyword heuristics used always (lowercased)
_INDIA_TERMS = {"india", "indian", "indians", "bharat"}
_HATE_COMBOS = {
    "india sucks", "hate india", "destroy india", "down with india",
    "anti india", "anti-india", "kill indians", "eliminate india",
}
# Single-word negative verbs/adjectives that if paired with an India term => flag
_INDIA_NEG = {"destroy", "eliminate", "hate", "boycott", "attack", "ruin", "kill"}

_DEFAULT_MODEL = "cardiffnlp/twitter-roberta-base-hate"


@lru_cache(maxsize=1)
def _load_pipeline():  # lazy import & model load once
    if os.environ.get("DISABLE_HATE_DETECT", "0").lower() in {"1", "true", "yes"}:
        return None
    try:
        from transformers import pipeline  # type: ignore
    except Exception:
        return None
    model_name = os.environ.get("HATE_MODEL", _DEFAULT_MODEL)
    try:
        return pipeline("text-classification", model=model_name, truncation=True)
    except Exception:
        return None


def _model_score(text: str):
    pl = _load_pipeline()
    if not pl:
        return None
    try:
        out = pl(text[:512])  # limit length for speed
        if isinstance(out, list) and out:
            item = out[0]
            label = str(item.get("label", "")).lower()
            score = float(item.get("score", 0.0))
            return {"label": label, "score": score}
    except Exception:
        return None
    return None


def detect_hate_or_anti_india(text: str) -> Tuple[bool, str]:
    text = (text or "").strip()
    if not text:
        return False, "empty"
    low = text.lower()

    # Direct phrase matches first
    for phrase in _HATE_COMBOS:
        if phrase in low:
            return True, f"anti-india-keyword:\"{phrase}\""

    # India term + negative token heuristic
    if any(t in low for t in _INDIA_TERMS):
        for neg in _INDIA_NEG:
            if neg in low:
                return True, f"india+hate-keyword:\"{neg}\""

    # Model inference
    model_res = _model_score(low)
    if model_res:
        thresh = float(os.environ.get("HATE_THRESHOLD", "0.60"))
        label = model_res["label"]
        score = model_res["score"]
        # Accept labels containing 'hate' or 'abuse'
        if ("hate" in label or "abuse" in label) and score >= thresh:
            return True, f"hate:{score:.2f} label={label}"
        # If India mentioned & moderate score -> still flag if score >= thresh*0.85
        if any(t in low for t in _INDIA_TERMS) and score >= (thresh * 0.85) and ("hate" in label or "abuse" in label or "toxic" in label):
            return True, f"india+{label}:{score:.2f}"

    return False, "none"


if __name__ == "__main__":  # quick manual test
    samples = [
        "I absolutely hate India and want to destroy everything.",
        "Indian food is amazing!", 
        "We should boycott Indian products.",
        "Hello world" 
    ]
    for s in samples:
        f, r = detect_hate_or_anti_india(s)
        print(f, r, "->", s)
