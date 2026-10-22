# 보드게임 규칙 도우미

우노 · 루미큐브 중 고른 게임의 **규칙 정리만 근거로** 답하고, 답변마다 **근거 절과 공식 원문 쪽수**를 보여 주는 Streamlit 챗봇입니다.

> `data/rules/`의 규칙 정리는 공식 규칙서(영어)를 수업용으로 한국어 요약한 것이며 공식 번역이 아닙니다.
> 판본과 공식 출처는 `data/문서목록.csv`에 있습니다.

## 주요 기능

- **게임 선택**: 사이드바 선택 상자나 첫 화면의 그림 카드를 눌러 게임을 고릅니다. 문서ID · 판본 · 언어 · 공식 출처가 함께 보입니다.
- **근거 있는 답변**: 고른 게임의 규칙 정리만 OpenAI 모델에 보내 답을 받고, 인용한 절이 실제 문서에 있는지 코드로 확인합니다. 없는 절을 인용하면 "근거 오류"로 표시합니다.
- **근거 내용 보기**: 답변 아래에서 규칙 정리의 해당 절을 원문 그대로 펼쳐 볼 수 있습니다.
- **대화 이어받기**: 같은 게임의 최근 대화 6번까지 함께 보내 "그때 …?", "그럼 …는?" 같은 후속 질문을 이어받습니다.
- **답변 종류 구분**
  - 확인 질문: 상황이나 대상("그 카드")이 여러 가지면 하나를 골라 답하지 않고 되묻습니다.
  - 규칙서에 없음: 정리에 없는 규칙은 지어내지 않고 없다고 알립니다.
  - 원문 안의 불일치: 원문 설명이 서로 다른 상황은 두 설명과 쪽수를 함께 알리고, 적용할 규칙을 정하라고 안내합니다.
  - 다른 게임 질문: 지금 고른 게임이 아닌 게임의 규칙을 물으면 게임 선택을 바꾸라고 안내합니다.
- **게임 전환 · 오류 복구**: 게임을 바꾸면 대화와 근거를 비웁니다. 키가 없으면 질문을 보내기 전에 막고, 시간 초과 · 인증 오류 등은 원인을 알린 뒤 "다시 시도"로 복구합니다.

게임별 분기 코드는 없습니다. 게임 정보는 모두 `문서목록.csv`와 규칙 정리 파일에서 읽으므로, 같은 형식의 문서를 추가하면 같은 기능이 그대로 동작합니다.

## 파일 구성

```
.
├── app.py              # Streamlit 화면(게임 선택, 대화, 근거 표시, 설정, 오류 복구)
├── llm.py              # OpenAI 호출, 프롬프트, 답변 종류 판정, 근거 절 검증
├── rules.py            # 문서목록.csv 읽기, 규칙 정리를 §절로 나누기, 게임 이미지 찾기
├── game_picker.py      # 첫 화면의 그림 카드 선택 컴포넌트(Streamlit Custom Components v2)
├── requirements.txt    # 의존성 목록
├── .gitignore          # .env · .venv 등 올리지 않을 파일
├── assets/
│   └── images/
│       ├── UNO.svg         # 게임 일러스트(직접 그린 그림, 공식 로고 · 박스 이미지 아님)
│       └── RUMMIKUB.svg
└── data/               # 수업 제공 자료(수정하지 않음)
    ├── 문서목록.csv     # 문서ID · 게임명 · 판본 · 언어 · 파일 · 공식출처 · 조회일 · 설명
    └── rules/
        ├── UNO.txt
        └── RUMMIKUB.txt
```

- 규칙 정리 파일은 `§번호 제목 (원문 N쪽 · …)` 줄을 기준으로 절을 나눕니다.
- 게임 이미지는 `assets/images/{문서ID}`에서 `.svg` → `.png` → `.jpg` → `.jpeg` → `.webp` 순서로 찾고, 없으면 이미지 없이 보여 줍니다.

## 로컬에서 실행하기

필요한 것: Python 3.10 이상(개발 · 확인은 3.12), OpenAI API 키

1. 가상환경을 만들고 패키지를 설치합니다.

   ```bash
   python -m venv .venv
   ```
   ```bash
   .venv\Scripts\activate
   ```
   ```bash
   pip install -r requirements.txt
   ```

   macOS · Linux에서는 `source .venv/bin/activate`로 활성화합니다.

2. 프로젝트 폴더에 `.env` 파일을 만들고 키를 넣습니다. 이 파일은 GitHub에 올리지 않습니다.

   ```
   OPENAI_API_KEY=sk-...
   # 선택: 모델 바꾸기(기본값 gpt-4.1-mini)
   # OPENAI_MODEL=gpt-6-sol
   ```

3. 앱을 실행합니다.

   ```bash
   streamlit run app.py
   ```

   브라우저에서 http://localhost:8501 이 열립니다. `.env`를 바꾼 뒤에는 앱을 껐다 켜야 반영됩니다.

### 설정

| 항목 | 위치 | 기본값 | 설명 |
|---|---|---|---|
| `OPENAI_API_KEY` | `.env` 또는 Secrets | (필수) | OpenAI API 키 |
| `OPENAI_MODEL` | `.env` 또는 Secrets | `gpt-4.1-mini` | 사용할 모델. `temperature=0`을 지원하지 않는 모델(예: `gpt-6-sol`)은 자동으로 기본값으로 다시 호출합니다. |
| 응답 제한 시간 | 앱 사이드바 | 30초 | 아주 짧게(예: 0.01초) 바꾸면 시간 초과와 "다시 시도"를 시험할 수 있습니다. |

## 배포하기 (GitHub + Streamlit Community Cloud)

> 배포한 앱은 누구나 접속할 수 있고 질문할 때마다 **내 OpenAI 키로 비용이 나갑니다.**
> 먼저 OpenAI 콘솔의 **Settings → Limits**에서 월 사용 한도를 걸어 두세요.

### 1. GitHub에 올리기

1. GitHub에서 **New repository**로 저장소를 만듭니다(예: `boardgame-rules-helper`, Public).
2. **Add file → Upload files**(빈 저장소면 *uploading an existing file*)로 아래만 올립니다.
   - 올릴 것: `app.py`, `llm.py`, `rules.py`, `game_picker.py`, `requirements.txt`, `.gitignore`, `README.md`, `data/` 폴더, `assets/` 폴더
   - **올리지 말 것: `.env`**, `.venv/`, `__pycache__/`, `.claude/`, 수업 자료(`.docx`)
   - 웹 업로드에는 `.gitignore`가 적용되지 않으니 직접 골라서 올려야 합니다.
3. 저장소에 `data/rules/UNO.txt`, `data/문서목록.csv`, `assets/images/UNO.svg` 경로가 그대로 있는지 확인하고 **Commit changes**를 누릅니다.

### 2. Streamlit Community Cloud 연결

1. https://share.streamlit.io 에서 GitHub 계정으로 로그인합니다.
2. **Create app → Deploy a public app from GitHub**를 고르고 아래처럼 입력합니다.
   - Repository: `내아이디/boardgame-rules-helper`
   - Branch: `main`
   - Main file path: `app.py`
3. **Advanced settings**
   - Python version: `3.12`
   - Secrets:

     ```toml
     OPENAI_API_KEY = "sk-..."
     # OPENAI_MODEL = "gpt-6-sol"
     ```

4. **Deploy**를 누르면 1~3분 뒤 앱 주소가 열립니다.

앱은 키를 로컬에서는 `.env`, 배포 환경에서는 Secrets에서 읽습니다.

### 3. 배포 후 확인 · 수정

- 우노를 고르고 "낼 카드가 없으면 어떻게 해?"를 물어 **UNO §3 차례 진행 (원문 2~3쪽)** 근거가 붙는지 확인합니다.
- 오류가 나면 앱 오른쪽 아래 **Manage app**에서 로그를 봅니다.
  - "API 키가 없습니다" → Secrets 이름 · 따옴표 확인
  - "문서목록.csv 파일이 없습니다" → `data` 폴더가 경로 그대로 올라갔는지 확인
- GitHub에서 파일을 고쳐 Commit하면 자동으로 다시 배포됩니다. 키는 **Manage app → Settings → Secrets**에서 바꿉니다.
