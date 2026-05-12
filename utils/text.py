"""Metin normalizasyon yardımcıları."""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Türkçe karakterler dahil metni URL-dostu slug'a dönüştürür."""
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
