"""Wrap a selected span in <highlighted-text> tags and splice the model's rewrite back."""
import re

OPEN_TAG = "<highlighted-text>"
CLOSE_TAG = "</highlighted-text>"

_FENCE_RE = re.compile(r"\A\s*```[^\n]*\n(.*?)\n?```\s*\Z", re.DOTALL)
_TAG_LINE_RE = re.compile(r"^[ \t]*</?highlighted-text>[ \t]*\n", re.MULTILINE)
_TAG_RE = re.compile(r"</?highlighted-text>")
_OPEN_RE = re.compile(r"<\s*highlighted-text\s*>", re.IGNORECASE)
_CLOSE_RE = re.compile(r"<\s*/\s*highlighted-text\s*>", re.IGNORECASE)


class HighlightError(ValueError):
    def __init__(self, message, model_output=None):
        super().__init__(message)
        self.model_output = model_output


def normalize_selection(text, selection):
    """Return (start, end) or None for no/empty selection; raise if out of range."""
    if selection is None:
        return None
    start, end = selection
    if not (0 <= start <= end <= len(text)):
        raise HighlightError(f"selection {selection} out of range for text of length {len(text)}")
    if start == end:
        return None
    return start, end


def wrap(text, start, end):
    if OPEN_TAG in text or CLOSE_TAG in text:
        raise HighlightError("document already contains highlight tags")
    return text[:start] + OPEN_TAG + text[start:end] + CLOSE_TAG + text[end:]


def _between_tags(model_output):
    opens = list(_OPEN_RE.finditer(model_output))
    closes = list(_CLOSE_RE.finditer(model_output))
    if len(opens) == 1 and len(closes) == 1 and opens[0].end() <= closes[0].start():
        return model_output[opens[0].end():closes[0].start()]
    return None


def _between_context(original, start, end, model_output):
    """Without tags: the rewrite is what sits between the unchanged text before and after the selection."""
    if _OPEN_RE.search(model_output) or _CLOSE_RE.search(model_output):
        return None
    out = clean_full_output(model_output).rstrip()
    before, after = original[:start], original[end:].rstrip()
    if out.startswith(before) and out.endswith(after) and len(before) + len(after) <= len(out):
        return out[len(before):len(out) - len(after)]
    return None


def splice(original, start, end, model_output):
    replacement = _between_tags(model_output)
    if replacement is None:
        replacement = _between_context(original, start, end, model_output)
    if replacement is None:
        raise HighlightError(
            "The model did not mark the rewritten text, so nothing was changed. Try Run again.",
            model_output,
        )
    selected = original[start:end]
    if replacement.startswith("\n") and not selected.startswith("\n"):
        replacement = replacement[1:]
    if replacement.endswith("\n") and not selected.endswith("\n"):
        replacement = replacement[:-1]
    return original[:start] + replacement + original[end:]


def clean_full_output(model_output):
    """Strip one outer code fence if present, and any highlight tags the model added."""
    m = _FENCE_RE.match(model_output)
    if m:
        body = m.group(1)
        model_output = body if body.endswith("\n") else body + "\n"
    return _TAG_RE.sub("", _TAG_LINE_RE.sub("", model_output))
