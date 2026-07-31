"""Presentation-only chat screen for the Music Passport journey."""

import streamlit as st


st.set_page_config(
    page_title="Music Passport · Step 1",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root { color-scheme: light; }

    .stApp, [data-testid="stAppViewContainer"] > .main {
        background: #f7f6f2;
        color: #20211f;
    }

    [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], #MainMenu, footer { display: none; }

    .block-container {
        max-width: 760px;
        min-height: 100svh;
        padding: 0 2rem 3rem;
    }

    .passport-header {
        min-height: 84px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #deddd7;
    }

    .wordmark {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        color: #20211f;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 1.3rem;
        font-weight: 600;
        letter-spacing: -0.025em;
    }

    .logo-mark {
        width: 34px;
        height: 34px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: #243f36;
        color: #fffdf7;
        font-family: system-ui, sans-serif;
        font-size: 0.9rem;
    }

    .step {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        color: #62645e;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    .step::before {
        content: "";
        width: 28px;
        height: 1px;
        background: #9fa198;
    }

    .journey-intro { padding: 3rem 0 2.5rem; }
    .eyebrow {
        margin: 0 0 0.6rem;
        color: #758179;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.15em;
        text-transform: uppercase;
    }
    .journey-intro h1 {
        margin: 0;
        color: #20211f;
        font-family: Georgia, "Times New Roman", serif;
        font-size: clamp(1.85rem, 5vw, 2.65rem);
        font-weight: 500;
        letter-spacing: -0.04em;
        line-height: 1.2;
    }

    .message-row { display: flex; align-items: flex-start; gap: 0.85rem; }
    .avatar {
        width: 38px;
        height: 38px;
        flex: 0 0 38px;
        display: grid;
        place-items: center;
        border: 1px solid #ccd1cb;
        border-radius: 50%;
        background: #e8ece7;
    }
    .avatar::after {
        content: "";
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #76847b;
        box-shadow: 0 9px 0 4px #76847b;
        transform: translateY(-3px) scale(.65);
    }
    .speaker {
        margin: 0 0 0.45rem;
        color: #777a73;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
    }
    .bubble {
        max-width: 520px;
        padding: 1.25rem 1.35rem;
        border-radius: 4px 20px 20px 20px;
        background: #ffffff;
        border: 1px solid #e5e3dc;
        color: #252623;
        font-size: 1.04rem;
        line-height: 1.75;
        box-shadow: 0 8px 28px rgba(39, 45, 40, 0.045);
    }
    .choice-label {
        margin: 1.35rem 0 0.65rem 3.2rem;
        color: #777a73;
        font-size: 0.78rem;
    }

    [data-testid="stHorizontalBlock"] {
        gap: 0.65rem;
        padding-left: 3.2rem;
    }
    .stButton > button {
        min-height: 48px;
        border: 1px solid #d5d7d0;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.76);
        color: #343632;
        font-size: 0.93rem;
        font-weight: 600;
        box-shadow: none;
        transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
    }
    .stButton > button:hover {
        border-color: #365c4e;
        background: #eef3ef;
        color: #243f36;
        transform: translateY(-1px);
    }
    .stButton > button:focus-visible {
        outline: 3px solid rgba(54, 92, 78, 0.25);
        outline-offset: 2px;
        box-shadow: none;
    }
    .stButton > button:active { transform: translateY(0); }

    .user-row { display: flex; justify-content: flex-end; margin-top: 2rem; }
    .user-message { text-align: right; }
    .user-message .speaker { margin-right: 0.25rem; }
    .user-bubble {
        padding: 0.95rem 1.2rem;
        border-radius: 18px 4px 18px 18px;
        background: #243f36;
        color: #fff;
        font-size: 1rem;
        box-shadow: 0 8px 24px rgba(36, 63, 54, 0.12);
    }

    .travel-note {
        margin: 3.5rem 0 0 3.2rem;
        padding-top: 1rem;
        border-top: 1px solid #deddd7;
        color: #898b84;
        font-size: 0.75rem;
        line-height: 1.6;
    }

    @media (max-width: 640px) {
        .block-container { padding: 0 1.15rem 2rem; }
        .passport-header { min-height: 72px; }
        .wordmark { font-size: 1.12rem; }
        .logo-mark { width: 31px; height: 31px; }
        .journey-intro { padding: 2.25rem 0 2rem; }
        .message-row { gap: 0.65rem; }
        .avatar { width: 34px; height: 34px; flex-basis: 34px; }
        .bubble { padding: 1.05rem 1.1rem; font-size: 0.98rem; }
        .choice-label, .travel-note { margin-left: 2.75rem; }
        [data-testid="stHorizontalBlock"] {
            padding-left: 2.75rem;
            gap: 0.5rem;
        }
        [data-testid="column"] { min-width: calc(50% - 0.25rem); }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .stButton > button { min-height: 46px; }
    }

    @media (prefers-reduced-motion: reduce) {
        .stButton > button { transition: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <header class="passport-header">
        <div class="wordmark"><span class="logo-mark">♪</span>Music Passport</div>
        <div class="step">Step 1</div>
    </header>
    <section class="journey-intro" aria-labelledby="journey-title">
        <p class="eyebrow">Your music journey</p>
        <h1 id="journey-title">기분에서 시작하는 음악 여행</h1>
    </section>
    <section aria-label="AI 여행 컨시어지와의 대화">
        <div class="message-row">
            <div class="avatar" role="img" aria-label="AI 컨시어지 프로필 이미지 임시 표시"></div>
            <div>
                <p class="speaker">AI TRAVEL CONCIERGE</p>
                <div class="bubble">안녕하세요.<br>오늘은 어떤 음악 여행을 떠나볼까요?</div>
            </div>
        </div>
        <p class="choice-label">지금의 기분과 가장 가까운 것을 골라주세요.</p>
    </section>
    """,
    unsafe_allow_html=True,
)

choices = ("😊 설레는", "🌿 차분한", "⚡ 신나는", "🌧️ 우울한")
columns = st.columns(2)
selected = None
for index, choice in enumerate(choices):
    with columns[index % 2]:
        if st.button(choice, key=f"mood-{index}", use_container_width=True):
            selected = choice

# This local state only demonstrates how a choice will appear in the chat UI.
if selected:
    st.session_state["mood_preview"] = selected

if st.session_state.get("mood_preview"):
    st.markdown(
        f"""
        <div class="user-row" aria-live="polite">
            <div class="user-message">
                <p class="speaker">YOU</p>
                <div class="user-bubble">{st.session_state['mood_preview']}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <p class="travel-note">
        하나의 선택에서 새로운 도시와 음악이 시작됩니다.<br>
        Music Passport · Journey 01
    </p>
    """,
    unsafe_allow_html=True,
)
