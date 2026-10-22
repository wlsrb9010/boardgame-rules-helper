"""첫 화면에서 그림 카드를 눌러 게임을 고르는 컴포넌트(Streamlit Custom Components v2)."""

import base64
from collections.abc import Callable

import streamlit as st

from rules import Game

_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}

_HTML = """<div class="grid" role="list"></div>"""

_CSS = """
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0;
  overflow: hidden;
  text-align: left;
  font: inherit;
  color: var(--st-text-color);
  background: var(--st-background-color);
  border: 1px solid var(--st-border-color, rgba(49, 51, 63, 0.2));
  border-radius: var(--st-base-radius, 0.5rem);
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.card:hover {
  transform: translateY(-3px);
  border-color: var(--st-primary-color);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
}
.card:focus-visible {
  outline: 2px solid var(--st-primary-color);
  outline-offset: 2px;
}
.card img {
  display: block;
  width: 100%;
  aspect-ratio: 8 / 5;
  object-fit: cover;
}
.text {
  padding: 0 0.85rem 0.85rem;
}
.name {
  font-weight: 700;
  font-size: 1.05rem;
}
.desc {
  margin-top: 0.15rem;
  font-size: 0.85rem;
  opacity: 0.7;
}
.hint {
  margin-top: 0.45rem;
  font-size: 0.8rem;
  color: var(--st-primary-color);
}
"""

_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const grid = parentElement.querySelector(".grid")
  if (!grid) return

  grid.replaceChildren()
  for (const game of data?.games ?? []) {
    const card = document.createElement("button")
    card.type = "button"
    card.className = "card"
    card.setAttribute("role", "listitem")
    card.setAttribute("aria-label", `${game.name} 선택`)

    const img = document.createElement("img")
    img.src = game.image
    img.alt = ""

    const text = document.createElement("div")
    text.className = "text"
    const name = document.createElement("div")
    name.className = "name"
    name.textContent = game.name
    const desc = document.createElement("div")
    desc.className = "desc"
    desc.textContent = game.description
    const hint = document.createElement("div")
    hint.className = "hint"
    hint.textContent = "눌러서 규칙 보기 →"
    text.append(name, desc, hint)

    card.append(img, text)
    card.onclick = () => setTriggerValue("picked", game.id)
    grid.append(card)
  }
}
"""

_PICKER = st.components.v2.component("game_picker", html=_HTML, css=_CSS, js=_JS)


def _data_url(game: Game) -> str:
    encoded = base64.b64encode(game.image.read_bytes()).decode("ascii")
    return f"data:{_MIME.get(game.image.suffix.lower(), 'image/png')};base64,{encoded}"


def game_picker(games: list[Game], on_pick: Callable[[str], None], *, key: str = "game_picker"):
    """그림이 있는 게임들을 카드로 보여 주고, 누른 카드의 문서ID로 on_pick을 부른다."""
    cards = [{"id": g.doc_id, "name": g.name, "description": g.description, "image": _data_url(g)}
             for g in games if g.image is not None]
    if not cards:
        return None

    def handle_pick():
        picked = st.session_state[key].picked
        if picked:
            on_pick(picked)

    return _PICKER(data={"games": cards}, key=key, on_picked_change=handle_pick)
