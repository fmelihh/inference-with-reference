import time
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.highlight import clean_full_output, normalize_selection, splice, wrap

SYSTEM_PROMPT = (
    "You are a document editor. Follow the user's instruction.\n"
    "Rules:\n"
    "- Rewrite only the text inside <highlighted-text> tags, following the instruction.\n"
    "- If the document has no <highlighted-text> tags, apply the instruction to the whole document.\n"
    "- Return the complete document, keeping the <highlighted-text> tags around the rewritten text.\n"
    "- Change nothing else.\n"
    "- Output only the document: no explanations and no code fences.\n"
    "\n"
    "The document follows."
)


@dataclass
class EditResult:
    proposed_text: str
    raw_output: str
    seconds: float
    output_tokens: int


def _system_message(document: str, selection: tuple[int, int] | None) -> SystemMessage:
    body = wrap(document, *selection) if selection else document
    return SystemMessage(SYSTEM_PROMPT + "\n\n" + body)


def build_messages(
    document: str, instruction: str, selection: tuple[int, int] | None
) -> list[BaseMessage]:
    return [_system_message(document, selection), HumanMessage(instruction)]


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.vllm_base_url,
        model=settings.vllm_model,
        api_key="none",
        temperature=0,
        max_tokens=8192,
    )


def run_edit(
    llm, document: str, instruction: str, selection: tuple[int, int] | None
) -> EditResult:
    selection = normalize_selection(document, selection)
    messages = build_messages(document, instruction, selection)
    start = time.perf_counter()
    response = llm.invoke(messages)
    seconds = time.perf_counter() - start
    raw = response.content
    if selection:
        proposed = splice(document, selection[0], selection[1], raw)
    else:
        proposed = clean_full_output(raw)
    tokens = (response.usage_metadata or {}).get("output_tokens", 0)
    return EditResult(proposed, raw, seconds, tokens)


def prime(llm, document: str) -> None:
    llm.bind(max_tokens=1).invoke(
        [_system_message(document, None), HumanMessage("Ready.")]
    )
