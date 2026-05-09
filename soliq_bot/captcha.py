"""CAPTCHA solver via Google Gemini vision API (google-genai SDK)."""
from __future__ import annotations

import io
import re
from typing import Optional

from PIL import Image

try:
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except Exception:  # noqa: BLE001
    genai = None  # type: ignore
    genai_types = None  # type: ignore

from .config import GEMINI_MAX_TOKENS, GEMINI_MODEL


_PROMPT = (
    "Расмдаги CAPTCHA текстини ўқинг ва фақат шу текстни қайтаринг. "
    "Изоҳ ёзманг, фақат CAPTCHA даги символларни ёзинг."
)


def _normalize_image(image_bytes: bytes) -> bytes:
    """Convert image bytes to PNG."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def solve_captcha(image_bytes: bytes, api_key: str) -> Optional[str]:
    """Send a CAPTCHA image to Gemini and return the recognized text."""
    if not api_key:
        raise RuntimeError("Gemini API ключи берилмаган")
    if genai is None or genai_types is None:
        raise RuntimeError(
            "google-genai пакет ўрнатилмаган. "
            "`pip install google-genai` буйруғини бажаринг."
        )

    png_bytes = _normalize_image(image_bytes)

    client = genai.Client(api_key=api_key)
    image_part = genai_types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    config = genai_types.GenerateContentConfig(
        max_output_tokens=GEMINI_MAX_TOKENS,
        temperature=0.0,
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[_PROMPT, image_part],
        config=config,
    )
    text = (getattr(response, "text", "") or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9А-Яа-я]", "", text)
    return cleaned or None
