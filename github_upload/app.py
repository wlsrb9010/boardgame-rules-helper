import json

import openai
import streamlit as st

import llm
from game_picker import game_picker
from rules import CatalogError, Game, load_catalog

st.set_page_config(page_title="보드게임 규칙 도우미", page_icon=":material/casino:")

GAME_CHANGED = "게임을 변경하여 대화를 새로 시작합니다."


@st.cache_data(ttl=60)
def get_games():
    return load_catalog()


def get_api_key() -> str | None:
    """로컬은 .env, 배포(Streamlit Cloud)는 st.secrets에서 키를 읽는다."""
    key = llm.get_api_key()
    if key:
        return key
    try:
        return st.secrets.get("OPENAI_API_KEY") or None
    except Exception:  # secrets.toml이 없으면 예외가 난다
        return None


def image_source(game: Game) -> str | None:
    """st.image에 넘길 값. SVG는 글자로 읽어 넘기고, 나머지는 파일 경로를 넘긴다."""
    if game.image is None:
        return None
    if game.image.suffix == ".svg":
        return game.image.read_text(encoding="utf-8")
    return str(game.image)


def reset_chat():
    """대화 · 근거 · 실패한 질문을 모두 비운다."""
    st.session_state.messages = []
    st.session_state.pending = None
    st.session_state.notice = None


def on_game_change():
    had_game = st.session_state.current_game is not None
    reset_chat()
    if had_game:
        st.session_state.notice = GAME_CHANGED


def pick_game(doc_id: str):
    """첫 화면 그림 카드를 눌렀을 때: 사이드바 선택 상자와 같은 값으로 게임을 고른다."""
    st.session_state.game_id = doc_id
    on_game_change()


def render_message(msg: dict, game: Game | None):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("status") == "error":
            st.error(msg["content"], title=msg.get("title", "답변을 만들지 못했습니다"))
            return
        kind = msg.get("kind")
        if kind == llm.CLARIFY:
            st.info(msg["content"], icon=":material/help:", title="어떤 상황인지 알려 주세요")
        elif kind == llm.NOT_IN_RULES:
            st.warning(msg["content"], icon=":material/search_off:", title="규칙서에 없음")
        elif kind == llm.CONFLICT:
            st.warning(msg["content"], icon=":material/compare_arrows:", title="원문 안의 불일치")
        elif kind == llm.OTHER_GAME:
            st.warning(msg["content"], icon=":material/swap_horiz:", title="다른 게임에 대한 질문")
        else:
            st.markdown(msg["content"])
        if msg.get("sections") and game is not None and game.doc_id == msg.get("doc_id"):
            render_evidence(game, msg["sections"])


def render_evidence(game: Game, numbers: list[int]):
    """답변 아래 근거 표시. 절 내용은 모델 문장이 아니라 규칙 정리에서 그대로 읽는다."""
    sections = [game.section(n) for n in numbers]
    labels = " · ".join(f"{game.doc_id} {s.label} (원문 {s.pages})" for s in sections)
    st.caption(f":material/menu_book: 근거: {labels}")
    with st.expander("근거 내용 보기"):
        for s in sections:
            st.markdown(f"**{game.doc_id} {s.label}** · 원문 {s.pages}")
            st.text(s.body)


def chat_history(game: Game) -> list[dict]:
    """같은 게임의 성공한 대화만 모은다. 실패한 질문 · 답은 맥락에 넣지 않는다."""
    return [m for m in st.session_state.messages
            if m.get("doc_id") == game.doc_id and m.get("status") == "ok"]


def answer_question(game: Game, question: str, api_key: str, others: list[str], timeout: float) -> dict:
    """LLM을 불러 답을 받고, 화면에 남길 메시지로 바꾼다. 실패는 error 상태로 돌려준다."""
    def failed(title, content):
        return {"role": "assistant", "status": "error", "title": title, "content": content}

    try:
        answer = llm.ask(game, question, api_key, history=chat_history(game),
                         other_games=others, timeout=timeout)
    except llm.CitationError as e:
        return failed("근거 오류", str(e))
    except openai.APITimeoutError:
        return failed("응답 시간 초과", f"{timeout:g}초 안에 응답을 받지 못했습니다. 제한 시간을 확인하고 다시 시도하세요.")
    except openai.AuthenticationError:
        return failed("API 키 인증 실패", "API 키가 올바르지 않거나 만료되었습니다. .env의 키를 확인하세요.")
    except openai.RateLimitError:
        return failed("사용 한도 초과", "요청이 너무 많거나 크레딧이 부족합니다. 잠시 뒤 다시 시도하세요.")
    except openai.APIConnectionError:
        return failed("연결 실패", "OpenAI 서버에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.")
    except (openai.OpenAIError, json.JSONDecodeError, KeyError) as e:
        return failed("모델 호출 오류", f"모델 호출 중 오류가 났습니다 ({type(e).__name__}). 다시 시도하세요.")
    return {
        "role": "assistant",
        "status": "ok",
        "kind": answer.kind,
        "content": answer.text,
        "doc_id": game.doc_id,
        "sections": [c.section for c in answer.citations],
    }


def run_question(game: Game, question: str, api_key: str, others: list[str], timeout: float):
    """질문 하나를 처리한다. 성공하면 대화에 남기고, 실패하면 다시 시도할 수 있게 보류해 둔다."""
    with st.chat_message("assistant"):
        with st.spinner(f"{game.name} 규칙서를 확인하는 중..."):
            reply = answer_question(game, question, api_key, others, timeout)
    if reply["status"] == "ok":
        user_msg = {"role": "user", "content": question, "doc_id": game.doc_id, "status": "ok"}
        st.session_state.messages += [user_msg, reply]
        st.session_state.pending = None
    else:
        # 실패한 질문은 대화(맥락)에 넣지 않고, 같은 질문을 다시 시도할 수 있게만 둔다
        st.session_state.pending = {"question": question, "doc_id": game.doc_id, "error": reply}
    st.rerun()


# ---- 상태 초기화 ----
for name, default in {"messages": [], "pending": None, "notice": None, "current_game": None}.items():
    st.session_state.setdefault(name, default)

# ---- 문서 불러오기 ----
try:
    games = get_games()
except CatalogError as e:
    st.error(str(e), title="문서목록을 읽을 수 없습니다")
    st.stop()

available = {g.doc_id: g for g in games if g.available}
unavailable = [g for g in games if not g.available]
api_key = get_api_key()

# ---- 사이드바: 게임 선택 · 설정 ----
with st.sidebar:
    st.header("게임 선택")
    selected_id = st.selectbox(
        "규칙을 물어볼 게임",
        options=list(available),
        format_func=lambda doc_id: f"{available[doc_id].name} ({doc_id})",
        index=None,
        placeholder="게임을 선택하세요",
        key="game_id",
        on_change=on_game_change,
    )
    if st.button("새 대화", icon=":material/add_comment:", width="stretch"):
        reset_chat()  # 고른 게임은 그대로 두고 대화만 비운다
    for g in unavailable:
        st.warning(f"{g.error}", title=f"{g.name}({g.doc_id})은(는) 지금 쓸 수 없습니다")
    if api_key is None:
        st.warning(".env에 OPENAI_API_KEY를 설정하고 앱을 다시 시작하세요.", title="API 키가 없습니다")

    st.divider()
    st.subheader("설정")
    timeout = st.number_input(
        "응답 제한 시간(초)",
        min_value=0.01,
        max_value=120.0,
        value=llm.DEFAULT_TIMEOUT,
        step=5.0,
        format="%.2f",
        key="timeout",
        help="시간 초과 처리를 시험할 때 아주 짧게(예: 0.01초) 바꿔 보세요.",
    )
    st.caption(f"모델: {llm.get_model()}")

game = available.get(selected_id) if selected_id else None
st.session_state.current_game = selected_id
others = [g.name for g in games if game is None or g.doc_id != game.doc_id]

# ---- 본문 ----
st.title("보드게임 규칙 도우미")

if game is None:
    st.info("왼쪽에서 게임을 선택하거나 아래 그림을 눌러 고르세요. 선택한 게임의 규칙서만 근거로 답합니다.")
    game_picker(list(available.values()), on_pick=pick_game)
else:
    with st.container(border=True):
        picture = image_source(game)
        if picture:
            image_col, info_col = st.columns([2, 3], vertical_alignment="center")
            image_col.image(picture, width="stretch", alt=f"{game.name} 일러스트")
        else:
            info_col = st.container()
        with info_col:
            st.subheader(game.name)
            st.caption(game.description)
            st.markdown(
                f"**문서ID** {game.doc_id}  \n"
                f"**판본** {game.edition}  \n"
                f"**언어** {game.language}  \n"
                f"**공식 출처** [{game.source_url}]({game.source_url}) (조회일 {game.accessed})"
            )
        st.caption(
            "규칙 정리는 공식 규칙서(영어)를 수업용으로 요약한 것이며 공식 번역이 아닙니다. "
            "정확한 문구는 공식 출처에서 확인하세요."
        )
        with st.expander(f"규칙 정리 보기 ({game.doc_id} · {len(game.sections)}개 절)"):
            for s in game.sections:
                st.markdown(f"**{s.label}** · 원문 {s.pages}")
                st.text(s.body)

if st.session_state.notice:
    st.info(st.session_state.notice, icon=":material/restart_alt:")

# ---- 대화 ----
for msg in st.session_state.messages:
    render_message(msg, game)

pending = st.session_state.pending
if pending and game is not None and pending["doc_id"] == game.doc_id:
    render_message({"role": "user", "content": pending["question"]}, game)
    render_message(pending["error"], game)
    if st.button("다시 시도", icon=":material/refresh:") and api_key:
        run_question(game, pending["question"], api_key, others, timeout)

if question := st.chat_input("규칙에 대해 물어보세요"):
    st.session_state.notice = None
    st.session_state.pending = None  # 새 질문을 하면 실패한 질문은 버린다
    user_msg = {"role": "user", "content": question, "doc_id": game.doc_id if game else None}
    render_message(user_msg, game)
    if game is None:
        # 게임을 고르기 전에는 LLM을 부르지 않는다
        reply = {"role": "assistant", "content": "먼저 왼쪽에서 게임을 선택해 주세요. 선택한 게임의 규칙서만 근거로 답합니다."}
    elif api_key is None:
        # 키가 없으면 질문을 보내기 전에 막는다(키 값은 화면에 보이지 않는다)
        reply = {"role": "assistant", "status": "error", "title": "API 키가 없습니다",
                 "content": ".env 파일에 OPENAI_API_KEY를 설정한 뒤 앱을 다시 시작하세요."}
    else:
        run_question(game, question, api_key, others, timeout)  # 끝나면 다시 그린다
    user_msg["status"] = "info"
    st.session_state.messages += [user_msg, reply]
    st.rerun()
