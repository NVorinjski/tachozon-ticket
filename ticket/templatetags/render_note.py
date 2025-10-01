# ticket/templatetags/render_note.py
from django import template
from django.utils.safestring import mark_safe
import bleach
import re

register = template.Library()

ALLOWED_TAGS = [
    "b", "strong", "i", "em", "u",
    "br", "p", "ul", "ol", "li",
    "blockquote", "code", "pre", "a"
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"]
}

def _is_probably_html(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # sehr simple Heuristik: hat Tags wie <p>…</p> o.ä.
    return bool(re.search(r"<[a-zA-Z][^>]*>", s))

def _nl2br(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")

def _sanitize_html(s: str) -> str:
    return bleach.clean(s, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

def _strip_all_html(s: str) -> str:
    # alles entfernen, nur Text behalten
    return bleach.clean(s or "", tags=[], attributes={}, strip=True)

@register.filter(name="render_note")
def render_note_filter(value: str) -> str:
    """
    - E-Mail-Notizen: HTML beibehalten (aber whitelisten/säubern)
    - In-App-Notizen (Plaintext): escapen + Zeilenumbrüche -> <br>
    """
    if not value:
        return ""

    if _is_probably_html(value):
        safe_html = _sanitize_html(value)
        return mark_safe(safe_html)
    else:
        # Plaintext: alles escapen und \n -> <br>
        escaped = _strip_all_html(value)
        return mark_safe(_nl2br(escaped))

@register.filter(name="render_note_preview")
def render_note_preview_filter(value: str, limit: int = 120) -> str:
    """
    Vorschau: immer reiner Text (Tags entfernen), dann kürzen und <br> für Zeilenumbrüche.
    """
    text = _strip_all_html(value)
    if len(text) > int(limit):
        text = text[: int(limit)].rstrip() + "…"
    return mark_safe(_nl2br(text))

# ---- Aliasse, damit du sie im Shell direkt importieren kannst ----
render_note = render_note_filter
render_note_preview = render_note_preview_filter

__all__ = ["render_note", "render_note_preview"]
