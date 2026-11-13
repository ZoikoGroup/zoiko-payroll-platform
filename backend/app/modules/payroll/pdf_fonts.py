"""Unicode TrueType font for generated PDFs (ZP-PL-ENG-001 PL-023).

ReportLab's built-in Helvetica only covers WinAnsi (cp1252): Polish letters
such as ł, ś, ż, ć, ń are not in it and would print wrongly. unicode_font()
registers the first Unicode TTF found on the host (DejaVu / Liberation / Noto
on Linux — the backend image installs fonts-dejavu-core — Arial / Tahoma on
Windows, Arial on macOS) once per process and returns (regular, bold) font
names, or None when the host has none. needs_unicode() tells a caller when
Helvetica is not enough, so it can refuse instead of printing wrong text.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional, Tuple

REGULAR, BOLD = "ZpUnicode", "ZpUnicode-Bold"
_registered: Optional[Tuple[str, str]] = None
_searched = False


def _candidates():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        (os.path.join(windir, "Fonts", "arial.ttf"), os.path.join(windir, "Fonts", "arialbd.ttf")),
        (os.path.join(windir, "Fonts", "tahoma.ttf"), os.path.join(windir, "Fonts", "tahomabd.ttf")),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ]


def unicode_font() -> Optional[Tuple[str, str]]:
    global _registered, _searched
    if _searched:
        return _registered
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont, TTFError

    for regular_path, bold_path in _candidates():
        if not os.path.isfile(regular_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(REGULAR, regular_path))
            pdfmetrics.registerFont(TTFont(BOLD, bold_path if os.path.isfile(bold_path) else regular_path))
        except (TTFError, OSError):
            continue
        _registered = (REGULAR, BOLD)
        break
    _searched = True
    return _registered


def needs_unicode(texts: Iterable) -> bool:
    """True when any text cannot be printed with the built-in (cp1252) fonts."""
    for text in texts:
        try:
            str(text if text is not None else "").encode("cp1252")
        except UnicodeEncodeError:
            return True
    return False
