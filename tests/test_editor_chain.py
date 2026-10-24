from app.editor_chain import SYSTEM_PROMPT, build_messages, run_edit


def test_build_messages_wraps_selection():
    msgs = build_messages("A.\nB.\n", "shorter", (3, 5))
    assert "<highlighted-text>B.</highlighted-text>" in msgs[0].content
    assert msgs[1].content == "shorter"


def test_build_messages_whole_document_has_no_tags():
    msgs = build_messages("A.\nB.\n", "formal", None)
    assert "<highlighted-text>" not in msgs[0].content.split(SYSTEM_PROMPT)[1]


def test_run_edit_splices_with_fake_model():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    llm = FakeListChatModel(responses=["A.\n<highlighted-text>b</highlighted-text>\n"])
    result = run_edit(llm, "A.\nB.\n", "lowercase", (3, 5))
    assert result.proposed_text == "A.\nb\n" and result.seconds >= 0
    assert result.output_tokens == 0


def test_run_edit_whole_document_cleans_fence():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    llm = FakeListChatModel(responses=["```\nA.\nb\n```"])
    result = run_edit(llm, "A.\nB.\n", "lowercase", (2, 2))
    assert result.proposed_text == "A.\nb\n"
