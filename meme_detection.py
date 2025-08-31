"""Meme (image) hate / anti-India detection helper.

Pipeline steps (configurable):
 1. OCR text extraction (pytesseract) -> run text detector callback.
 2. Optional CLIP similarity scoring against small hate/harassment prompts.

Env Vars:
  ENABLE_MEME_DETECT=1      Enable this module (default 1)
  ENABLE_CLIP_MEME=0        Enable CLIP scoring (default 0 for CPU speed)
  MEME_THRESHOLD=0.60       CLIP max-sim threshold to flag
  OCR_LANG=eng              Tesseract language code
  TESSERACT_EXE             Path to tesseract.exe if not in PATH (Windows)
  CLIP_MODEL=openai/clip-vit-base-patch32 Override CLIP model id

Returned tuple from detect_hate_meme(image_path, text_cb): (flag, reason, score)
  score = 1.0 for OCR text flags (heuristic) or CLIP similarity value.

Dependencies (optional):
  pip install pillow pytesseract transformers torch torchvision
  Install Tesseract separately: https://github.com/tesseract-ocr/tesseract
"""
from __future__ import annotations
import os
from typing import Tuple, Optional

_ENABLE = os.getenv("ENABLE_MEME_DETECT", "1") in {"1","true","yes"}
_ENABLE_CLIP = os.getenv("ENABLE_CLIP_MEME", "0") in {"1","true","yes"}
_MEME_THRESH = float(os.getenv("MEME_THRESHOLD", "0.60"))
_OCR_LANG = os.getenv("OCR_LANG", "eng")
_DEBUG = os.getenv("DEBUG_DETECT", "0").lower() in {"1","true","yes"}

# Lazy singletons
_tess_ready = False
_clip_ready = False
_clip_model = None
_clip_processor = None
_clip_text_emb = None
_HATE_PROMPTS = [
    "hateful meme", "hate speech meme", "anti india meme", "harassing meme"
]

def _init_tesseract():
    global _tess_ready
    if _tess_ready:
        return
    try:
        path = os.getenv("TESSERACT_EXE")
        if path and os.path.exists(path):
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = path
    except Exception:
        pass
    _tess_ready = True


def _ocr(image_path: str) -> str:
    _init_tesseract()
    try:
        from PIL import Image
        import pytesseract
        with Image.open(image_path) as img:
            txt = pytesseract.image_to_string(img, lang=_OCR_LANG)
            return txt.strip()
    except Exception:
        return ""


def _init_clip():
    global _clip_ready, _clip_model, _clip_processor, _clip_text_emb
    if _clip_ready:
        return
    _clip_ready = True
    if not _ENABLE_CLIP:
        return
    try:
        from transformers import CLIPModel, CLIPProcessor
        import torch
        model_id = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")
        _clip_model = CLIPModel.from_pretrained(model_id)
        _clip_processor = CLIPProcessor.from_pretrained(model_id)
        with torch.no_grad():
            proc = _clip_processor(text=_HATE_PROMPTS, images=None, return_tensors="pt", padding=True)
            text_emb = _clip_model.get_text_features(input_ids=proc["input_ids"], attention_mask=proc["attention_mask"])  # type: ignore
            text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
            _clip_text_emb = text_emb
    except Exception:
        _clip_model = None
        _clip_text_emb = None


def _clip_score(image_path: str) -> Optional[float]:
    if not _ENABLE_CLIP:
        return None
    _init_clip()
    if _clip_model is None or _clip_text_emb is None:
        return None
    try:
        from PIL import Image
        import torch
        img = Image.open(image_path).convert("RGB")
        proc = _clip_processor(images=img, return_tensors="pt")
        with torch.no_grad():
            img_emb = _clip_model.get_image_features(**proc)  # type: ignore
            img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
            sim = (img_emb @ _clip_text_emb.T).max().item()
            return float(sim)
    except Exception:
        return None


def detect_hate_meme(image_path: str, text_detector_cb) -> Tuple[bool, str, float]:
    if not _ENABLE:
        return False, "meme-disabled", 0.0
    if not image_path or not os.path.exists(image_path):
        return False, "no-image", 0.0

    # 1. OCR path
    ocr_text = _ocr(image_path)
    if ocr_text:
        if _DEBUG:
            print(f"[MEME][OCR_TEXT] {ocr_text[:80]!r}")
        f, reason = text_detector_cb(ocr_text)
        if f:
            return True, f"meme-ocr:{reason}", 1.0

    # 2. CLIP path
    sim = _clip_score(image_path)
    if sim is not None and sim >= _MEME_THRESH:
        if _DEBUG:
            print(f"[MEME][CLIP_SIM] {sim:.3f} >= {_MEME_THRESH}")
        return True, f"meme-clip:{sim:.2f}", sim

    return False, "meme-clean", sim or 0.0

if __name__ == "__main__":
    # Light self-test placeholder (will not run heavy model unless enabled)
    test_img = os.getenv("TEST_MEME_IMG")
    if test_img and os.path.exists(test_img):
        def dummy_detector(t):
            return ("hate india" in t.lower(), "dummy")
        print(detect_hate_meme(test_img, dummy_detector))
