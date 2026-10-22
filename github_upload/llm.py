"""OpenAI 호출과 근거 검증 모듈.

고른 게임의 규칙 정리 하나만 모델에 보내고, 모델이 붙인 근거(문서ID · 절)가
실제로 그 문서에 있는 절인지 코드로 확인한다. 게임별 분기는 두지 않는다.
"""

import json
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import BadRequestError, OpenAI

from rules import Game

load_dotenv()

DEFAULT_MODEL = "gpt-4.1-mini"  # .env의 OPENAI_MODEL로 바꿀 수 있다(예: gpt-6-sol)
DEFAULT_TIMEOUT = 30.0
HISTORY_TURNS = 6  # 함께 보낼 최근 대화 수(질문 + 답변 한 쌍이 1번)

# 답변 종류
ANSWER = "answer"  # 규칙 정리에 근거한 답
CLARIFY = "clarify"  # 상황 · 대상이 여러 가지라 되묻는 확인 질문
NOT_IN_RULES = "not_in_rules"  # 규칙 정리에 없는 내용
CONFLICT = "conflict"  # 정리에 '원문 안의 불일치'로 적힌 상황
OTHER_GAME = "other_game"  # 지금 고른 게임이 아닌 다른 게임에 대한 질문
KINDS = [ANSWER, CLARIFY, NOT_IN_RULES, CONFLICT, OTHER_GAME]

# "그 카드", "그거"처럼 앞에 나온 대상을 가리키는 말("그때"는 상황을 이어받는 말이라 넣지 않는다)
REFERRING_WORDS = re.compile(r"그\s*(카드|타일|패|말|거|것|걸|규칙)|그거|그것")

RESPONSE_SCHEMA = {
    "name": "rule_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": KINDS},
            "answer": {"type": "string", "description": "사용자에게 보여 줄 짧은 한국어 답변"},
            "citations": {
                "type": "array",
                "description": "답의 근거가 된 절. 근거가 없으면 빈 배열",
                "items": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "section": {"type": "integer", "description": "§ 뒤의 절 번호"},
                    },
                    "required": ["doc_id", "section"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["kind", "answer", "citations"],
        "additionalProperties": False,
    },
}

REFERENT_SCHEMA = {
    "name": "referents",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"candidates": {"type": "array", "items": {"type": "string"}}},
        "required": ["candidates"],
        "additionalProperties": False,
    },
}

REFERENT_PROMPT = """아래 [앞선 대화] 뒤에 [마지막 질문]이 왔다.
[마지막 질문]의 가리키는 말("그 카드", "그거", "그것" 등)이 가리킬 수 있는 대상을, [앞선 대화]의 질문과 답변에서
주제로 다룬 같은 종류의 대상 가운데 모두 찾아 candidates에 적어라.
가장 최근 것 하나만 고르지 마라. 예를 들어 앞에서 A에 대해 묻고 이어서 "그럼 B는?"이라고 물었다면 candidates는 ["A", "B"]다.
가리킬 수 있는 대상이 하나뿐이면 그 하나만 적는다."""


@dataclass
class Citation:
    doc_id: str
    section: int


@dataclass
class Answer:
    kind: str
    text: str
    citations: list[Citation]


class CitationError(Exception):
    """모델이 문서에 없는 문서ID나 절을 근거로 댔을 때."""


def get_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or None


def get_model() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def build_system_prompt(game: Game, other_games: list[str] | None = None) -> str:
    sections = "\n\n".join(f"{s.label} (원문 {s.pages})\n{s.body}" for s in game.sections)
    others = ", ".join(other_games) if other_games else "없음"
    return f"""너는 보드게임 규칙 도우미다. 아래 [규칙 정리]만 근거로 한국어로 짧게 답한다.

기본 규칙:
- [규칙 정리]에 적힌 내용만 쓴다. 웹 검색 결과나 네가 알고 있는 다른 판본 · 가족 규칙으로 빈칸을 채우지 않는다.
- 답에 쓴 내용이 나온 절을 citations에 넣는다. doc_id는 "{game.doc_id}", section은 § 뒤의 숫자다.
- 목록에 있는 절 번호(§{game.sections[0].number}~§{game.sections[-1].number})만 인용한다.
- 답변 문장 안에 절 번호나 쪽수를 쓰지 않는다. 근거 표시는 앱이 따로 한다.

대화 이어받기:
- 앞선 대화가 함께 오면 "그때 …?", "그럼 …는?", "그 카드" 같은 짧은 후속 질문을 앞 질문의 뜻으로 이어받아 해석한다.
- 앞선 답변이 [규칙 정리]와 다르면 [규칙 정리]를 따른다.

kind 고르기(하나만):
- "answer": [규칙 정리]에서 답을 찾았다. citations에 근거 절을 하나 이상 넣는다.
- "clarify": 질문이 가리킬 수 있는 상황이 여러 가지라 답(장수 · 점수 등)이 달라지거나, "그 카드"처럼 가리키는 대상이
  앞선 대화에 둘 이상 있으면 하나를 골라 답하지 않는다. 가능한 상황 · 대상을 짧게 나열해 어느 것을 묻는지 되묻는다.
  citations는 비운다.
- "not_in_rules": [규칙 정리] 어디에도 근거가 없는 규칙 · 상황이다(가족 규칙, 온라인 대전, 정리에 없는 구성 등).
  규칙을 지어내지 말고 "현재 규칙서에는 …에 대한 규칙이 없습니다"처럼 알린다. citations는 비운다.
- "conflict": 질문한 상황이 [규칙 정리]에 '원문 안의 불일치'로 적힌 바로 그 상황이다. 한쪽을 골라 단정하지 말고
  두 설명을 모두 알리되 각 설명 앞에 "원문 N쪽"을 붙인다(예외로 이때는 쪽수를 답변에 쓴다). 그런 뒤 원문만으로는
  확정할 수 없으니 함께 하는 사람들이 적용할 규칙을 먼저 정해야 한다고 안내한다.
  관련된 절을 모두 citations에 넣는다. 불일치가 없다고 적힌 비슷한 다른 경우에는 불일치를 넓혀 적용하지 말고 "answer"로 답한다.
- "other_game": 질문이 지금 고른 게임({game.name})이 아니라 다른 게임(예: {others})의 규칙을 묻는다. 그 게임의 규칙을
  답하지 말고, 그 게임을 물으려면 왼쪽에서 게임 선택을 바꾸라고 안내한다. citations는 비운다.

[문서 정보]
게임: {game.name} / 문서ID: {game.doc_id} / 판본: {game.edition}

[규칙 정리]
{sections}"""


def validate_citations(game: Game, citations: list[Citation]) -> list[Citation]:
    """근거가 고른 문서의 실제 절인지 확인하고, 중복을 뺀 목록을 돌려준다."""
    bad = [c for c in citations if c.doc_id != game.doc_id or game.section(c.section) is None]
    if bad:
        cited = ", ".join(f"{c.doc_id} §{c.section}" for c in bad)
        raise CitationError(f"규칙 정리에 없는 근거를 인용했습니다: {cited}")
    seen, unique = set(), []
    for c in citations:
        if c.section not in seen:
            seen.add(c.section)
            unique.append(c)
    return unique


# temperature=0을 거부한 모델(예: gpt-6-sol). 한 번 거부되면 그 뒤로는 기본값으로 부른다.
_NO_TEMPERATURE_MODELS: set[str] = set()


def call_model(messages: list[dict], api_key: str, model: str, timeout: float,
               schema: dict = RESPONSE_SCHEMA) -> str:
    """실제 OpenAI 호출. 모델이 돌려준 JSON 문자열을 그대로 돌려준다."""
    client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
    request = {
        "model": model,
        "response_format": {"type": "json_schema", "json_schema": schema},
        "messages": messages,
    }
    if model not in _NO_TEMPERATURE_MODELS:
        try:
            response = client.chat.completions.create(temperature=0, **request)
            return response.choices[0].message.content
        except BadRequestError as e:
            if "temperature" not in str(e):
                raise
            _NO_TEMPERATURE_MODELS.add(model)
    response = client.chat.completions.create(**request)
    return response.choices[0].message.content


def recent(history: list[dict]) -> list[dict]:
    return history[-HISTORY_TURNS * 2:]


def build_messages(game: Game, question: str, history: list[dict],
                   other_games: list[str] | None = None) -> list[dict]:
    """시스템 프롬프트 + 최근 대화 + 이번 질문. history는 {"role", "content", "sections"?} 목록."""
    messages = [{"role": "system", "content": build_system_prompt(game, other_games)}]
    for h in recent(history):
        content = h["content"]
        if h["role"] == "assistant" and h.get("sections"):
            content += "\n(근거: " + ", ".join(f"{game.doc_id} §{n}" for n in h["sections"]) + ")"
        messages.append({"role": h["role"], "content": content})
    messages.append({"role": "user", "content": question})
    return messages


def find_referents(question: str, history: list[dict], api_key: str, model: str, timeout: float) -> list[str]:
    """가리키는 말이 앞선 대화의 어떤 대상들을 가리킬 수 있는지 따로 묻는다(작은 모델도 안정적으로 하도록 한 가지 일만 시킴)."""
    talk = "\n".join(f"{'사용자' if h['role'] == 'user' else '도우미'}: {h['content']}" for h in recent(history))
    messages = [
        {"role": "system", "content": REFERENT_PROMPT},
        {"role": "user", "content": f"[앞선 대화]\n{talk}\n\n[마지막 질문]\n{question}"},
    ]
    data = json.loads(call_model(messages, api_key, model, timeout, schema=REFERENT_SCHEMA))
    return list(dict.fromkeys(c.strip() for c in data["candidates"] if c.strip()))


def ask(game: Game, question: str, api_key: str, history: list[dict] | None = None,
        other_games: list[str] | None = None, model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT) -> Answer:
    history = history or []
    model = model or get_model()
    if history and REFERRING_WORDS.search(question):
        candidates = find_referents(question, history, api_key, model, timeout)
        if len(candidates) >= 2:
            # 가리키는 대상이 둘 이상이면 하나를 골라 답하지 않고 되묻는다
            return Answer(kind=CLARIFY, text=f"어느 것을 말하는지 알려 주세요: {', '.join(candidates)}", citations=[])

    raw = call_model(build_messages(game, question, history, other_games), api_key, model, timeout)
    data = json.loads(raw)
    kind = data["kind"] if data["kind"] in KINDS else ANSWER
    citations = [Citation(doc_id=c["doc_id"], section=int(c["section"])) for c in data["citations"]]
    citations = validate_citations(game, citations)
    if kind in (CLARIFY, NOT_IN_RULES, OTHER_GAME):
        citations = []  # 확인 질문 · 규칙서에 없음 · 다른 게임 안내에는 근거 절을 붙이지 않는다
    return Answer(kind=kind, text=data["answer"].strip(), citations=citations)
