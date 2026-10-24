from app.highlight import wrap, splice, clean_full_output, normalize_selection, HighlightError
import pytest

DOC = "Line one.\nThe main reason is long.\nLine three.\n"
S, E = DOC.index("The main"), DOC.index("Line three") - 1  # selection = second line, no newline

def test_wrap_inserts_tags_in_place():
    assert wrap(DOC, S, E) == "Line one.\n<highlighted-text>The main reason is long.</highlighted-text>\nLine three.\n"

def test_splice_replaces_only_selection():
    out = "Line one.\n<highlighted-text>Short reason.</highlighted-text>\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

def test_splice_ignores_changes_outside_tags():
    out = "LINE ONE CHANGED\n<highlighted-text>Short reason.</highlighted-text>\nextra\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

def test_splice_drops_newlines_model_added_inside_tags():
    out = "Line one.\n<highlighted-text>\nShort reason.\n</highlighted-text>\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

@pytest.mark.parametrize("out", ["no tags here", "<highlighted-text>a</highlighted-text><highlighted-text>b</highlighted-text>", "<highlighted-text>never closed"])
def test_splice_rejects_missing_or_duplicate_tags(out):
    with pytest.raises(HighlightError):
        splice(DOC, S, E, out)

def test_wrap_rejects_document_containing_tag():
    with pytest.raises(HighlightError):
        wrap("has <highlighted-text> inside", 0, 3)

def test_clean_full_output_strips_one_code_fence():
    assert clean_full_output("```markdown\nNew doc\n```") == "New doc\n"
    assert clean_full_output("New doc\n") == "New doc\n"

def test_normalize_selection():
    assert normalize_selection(DOC, None) is None
    assert normalize_selection(DOC, (5, 5)) is None
    assert normalize_selection(DOC, (S, E)) == (S, E)
    with pytest.raises(HighlightError):
        normalize_selection(DOC, (0, len(DOC) + 1))


def test_clean_full_output_drops_stray_highlight_tags():
    out = "Intro.\n\n<highlighted-text>\n## New\n\nBody.\n</highlighted-text>\n\n## Next\n"
    assert clean_full_output(out) == "Intro.\n\n## New\n\nBody.\n\n## Next\n"
    assert clean_full_output("A <highlighted-text>b</highlighted-text> c\n") == "A b c\n"


def test_splice_accepts_tag_variants():
    out = "Line one.\n< Highlighted-Text >Short reason.</ highlighted-text>\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"


def test_splice_falls_back_to_unchanged_context_without_tags():
    out = "Line one.\nShort reason.\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"
    fenced = "```markdown\nLine one.\nShort reason.\nLine three.\n```"
    assert splice(DOC, S, E, fenced) == "Line one.\nShort reason.\nLine three.\n"


def test_splice_error_carries_model_output():
    with pytest.raises(HighlightError) as e:
        splice(DOC, S, E, "something else entirely")
    assert e.value.model_output == "something else entirely"
