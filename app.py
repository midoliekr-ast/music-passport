"""Interactive chat screen for the Music Passport journey."""

from html import escape

import streamlit as st


MOOD_CHOICES = ("😊 설레는", "🌿 차분한", "⚡ 신나는", "🌧️ 우울한")
SITUATION_CHOICES = ("☕ 카페", "🚇 출퇴근", "💻 집중", "🌙 밤 산책")
CITY_CHOICES = ("🇬🇧 런던", "🇫🇷 파리", "🇯🇵 도쿄", "🇰🇷 서울", "🇲🇦 마라케시")
STEPS = ("mood", "situation", "city", "complete")


def select_choice(state_key: str, value: str, next_step: str) -> None:
    """Persist a choice and advance the conversation on the next rerun."""
    st.session_state[state_key] = value
    st.session_state["conversation_step"] = next_step


def reset_conversation() -> None:
    """Clear the journey without disturbing unrelated Streamlit state."""
    for key in ("conversation_step", "mood", "situation", "city"):
        st.session_state.pop(key, None)


def render_ai_avatar() -> str:
    """Return the replaceable placeholder for the concierge profile image."""
    return '<div class="avatar" role="img" aria-label="AI 컨시어지 프로필 이미지 임시 표시"></div>'


def render_ai_message(message: str) -> None:
    st.markdown(
        f"""
        <div class="message-row chat-message">
            {render_ai_avatar()}
            <div>
                <p class="speaker">AI TRAVEL CONCIERGE</p>
                <div class="bubble">{message}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_user_message(message: str) -> None:
    st.markdown(
        f"""
        <div class="user-row chat-message">
            <div class="user-message">
                <p class="speaker">YOU</p>
                <div class="user-bubble">{escape(message)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_choices(state_key: str, choices: tuple[str, ...], next_step: str) -> None:
    st.markdown('<p class="choice-label">하나를 선택해주세요.</p>', unsafe_allow_html=True)
    columns = st.columns(2)
    for index, choice in enumerate(choices):
        with columns[index % 2]:
            st.button(
                choice,
                key=f"{state_key}-{index}",
                use_container_width=True,
                on_click=select_choice,
                args=(state_key, choice, next_step),
            )


st.set_page_config(
    page_title="Music Passport · Step 1",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

if st.session_state.get("conversation_step") not in STEPS:
    st.session_state["conversation_step"] = "mood"

st.markdown(
    """
    <style>
    :root { color-scheme: dark; }

    .stApp, [data-testid="stAppViewContainer"] > .main {
        background:
            radial-gradient(circle at 80% 8%, rgba(67, 94, 151, .22), transparent 30rem),
            linear-gradient(155deg, #101d3a 0%, #071126 52%, #040a18 100%);
        color: #f7f8ff;
    }

    [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], #MainMenu, footer { display: none; }

    .block-container {
        max-width: 780px;
        min-height: 100svh;
        padding: 0 2rem 3rem;
    }

    .passport-header {
        min-height: 84px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid rgba(206, 220, 255, .14);
    }

    .wordmark {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        color: #f7f8ff;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
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
        background: linear-gradient(145deg, #ffb45e, #ff6f61);
        color: #101a34;
        font-family: system-ui, sans-serif;
        font-size: 0.9rem;
    }

    .step {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        color: #aebbd8;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    .step::before {
        content: "";
        width: 28px;
        height: 1px;
        background: linear-gradient(90deg, #ffb45e, #ff7468);
    }

    .journey-intro { padding: 2.4rem 0 2.2rem; }
    .eyebrow {
        margin: 0 0 0.6rem;
        color: #ffb66b;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.15em;
        text-transform: uppercase;
    }
    .journey-intro h1 {
        margin: 0;
        color: #ffffff;
        font-family: Georgia, "Times New Roman", serif;
        font-size: clamp(1.85rem, 5vw, 2.65rem);
        font-weight: 500;
        letter-spacing: -0.04em;
        line-height: 1.2;
    }

    .cabin-window {
        position: relative;
        height: clamp(170px, 32vw, 230px);
        margin-top: 1.7rem;
        overflow: hidden;
        border: 10px solid rgba(217, 227, 248, .22);
        border-radius: 46% 46% 42% 42% / 25% 25% 35% 35%;
        background:
            radial-gradient(circle at 72% 58%, rgba(255, 178, 94, .8) 0 2px, transparent 3px),
            radial-gradient(circle at 62% 67%, rgba(255, 123, 99, .75) 0 2px, transparent 4px),
            radial-gradient(circle at 28% 72%, rgba(111, 187, 255, .75) 0 2px, transparent 4px),
            linear-gradient(180deg, #243968 0%, #131d3f 58%, #080e20 100%);
        box-shadow: inset 0 0 0 3px rgba(7, 13, 29, .72), 0 22px 55px rgba(0, 0, 0, .32);
    }
    .cabin-window::before {
        content: "";
        position: absolute;
        inset: 45% -3% -5%;
        opacity: .78;
        background:
            linear-gradient(90deg, transparent 0 6%, #0a1024 6% 13%, transparent 13% 18%, #0c142a 18% 28%, transparent 28% 33%, #080f22 33% 42%, transparent 42% 47%, #0d1730 47% 61%, transparent 61% 65%, #080e20 65% 76%, transparent 76% 81%, #0b1329 81% 94%, transparent 94%),
            linear-gradient(180deg, transparent 0 28%, #070d1d 29% 100%);
        clip-path: polygon(0 35%, 7% 35%, 7% 8%, 13% 8%, 13% 47%, 20% 47%, 20% 18%, 27% 18%, 27% 40%, 35% 40%, 35% 0, 42% 0, 42% 50%, 52% 50%, 52% 20%, 62% 20%, 62% 44%, 69% 44%, 69% 10%, 76% 10%, 76% 38%, 84% 38%, 84% 15%, 94% 15%, 94% 45%, 100% 45%, 100% 100%, 0 100%);
    }
    .cabin-window::after {
        content: "NIGHT FLIGHT  ·  MP 001";
        position: absolute;
        left: 1.3rem;
        top: 1rem;
        color: rgba(237, 244, 255, .72);
        font-size: .65rem;
        font-weight: 700;
        letter-spacing: .16em;
    }

    .message-row { display: flex; align-items: flex-start; gap: 0.85rem; }
    .chat-message { margin-top: 2.2rem; }
    .avatar {
        width: 38px;
        height: 38px;
        flex: 0 0 38px;
        display: grid;
        place-items: center;
        border: 1px solid rgba(255, 255, 255, .28);
        border-radius: 50%;
        background: linear-gradient(145deg, rgba(142, 171, 219, .34), rgba(45, 65, 108, .42));
        box-shadow: inset 0 1px 0 rgba(255,255,255,.18), 0 8px 20px rgba(0,0,0,.2);
    }
    .avatar::after {
        content: "";
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #b7c7e8;
        box-shadow: 0 9px 0 4px #b7c7e8;
        transform: translateY(-3px) scale(.65);
    }
    .speaker {
        margin: 0 0 0.45rem;
        color: #9dadd0;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
    }
    .bubble {
        max-width: 520px;
        padding: 1.35rem 1.45rem;
        border-radius: 6px 22px 22px 22px;
        background: linear-gradient(145deg, rgba(112, 139, 190, .28), rgba(42, 62, 105, .32));
        border: 1px solid rgba(199, 217, 255, .22);
        color: #f7f9ff;
        font-size: 1.06rem;
        line-height: 1.75;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.1), 0 14px 38px rgba(0,0,0,.22);
        backdrop-filter: blur(18px);
    }
    .choice-label {
        margin: 1.35rem 0 0.65rem 3.2rem;
        color: #92a3c8;
        font-size: 0.78rem;
    }

    [data-testid="stHorizontalBlock"] {
        gap: 0.65rem;
        padding-left: 3.2rem;
    }
    .stButton > button {
        min-height: 72px;
        border: 1px solid rgba(175, 198, 239, .24);
        border-radius: 22px;
        background: linear-gradient(145deg, rgba(41, 63, 109, .72), rgba(21, 36, 72, .86));
        color: #f3f6ff;
        font-size: 1rem;
        font-weight: 600;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 10px 24px rgba(0,0,0,.14);
        transition: border-color 180ms ease, background 180ms ease, transform 180ms ease, box-shadow 180ms ease;
    }
    .stButton > button:hover {
        border-color: #ffad68;
        background: linear-gradient(145deg, rgba(75, 91, 137, .9), rgba(34, 52, 94, .94));
        color: #fff;
        transform: translateY(-4px);
        box-shadow: 0 16px 30px rgba(0,0,0,.26), 0 0 0 1px rgba(255,173,104,.18);
    }
    .stButton > button:focus-visible {
        outline: 3px solid rgba(255, 173, 104, .3);
        outline-offset: 2px;
        box-shadow: none;
    }
    .stButton > button:active { transform: translateY(0); }

    .st-key-restart { margin: 2.4rem 0 0 3.2rem; }
    .st-key-restart .stButton > button {
        width: auto;
        min-height: 0;
        padding: .6rem 1rem;
        border-radius: 999px;
        background: transparent;
        color: #aab8d6;
        font-size: .8rem;
        box-shadow: none;
    }
    .st-key-restart .stButton > button:hover {
        border-color: rgba(255, 173, 104, .65);
        color: #ffd0a4;
        transform: translateY(-2px);
        box-shadow: none;
    }

    .user-row { display: flex; justify-content: flex-end; }
    .user-message { text-align: right; }
    .user-message .speaker { margin-right: 0.25rem; }
    .user-bubble {
        padding: 0.95rem 1.2rem;
        border-radius: 18px 4px 18px 18px;
        background: linear-gradient(135deg, #ffb05f, #ff7468);
        color: #151b34;
        font-size: 1rem;
        font-weight: 700;
        box-shadow: 0 12px 30px rgba(255, 112, 96, .18);
    }

    .travel-note {
        margin: 3.5rem 0 0 3.2rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(206, 220, 255, .13);
        color: #7788ad;
        font-size: 0.75rem;
        line-height: 1.6;
    }

    @media (max-width: 640px) {
        .block-container { padding: 0 1.15rem 2rem; }
        .passport-header { min-height: 72px; }
        .wordmark { font-size: 1.12rem; }
        .logo-mark { width: 31px; height: 31px; }
        .journey-intro { padding: 2rem 0 1.8rem; }
        .cabin-window { height: 165px; border-width: 8px; border-radius: 42% 42% 38% 38% / 22% 22% 30% 30%; }
        .message-row { gap: 0.65rem; }
        .avatar { width: 34px; height: 34px; flex-basis: 34px; }
        .bubble { padding: 1.05rem 1.1rem; font-size: 0.98rem; }
        .choice-label, .travel-note { margin-left: 2.75rem; }
        .st-key-restart { margin-left: 2.75rem; }
        [data-testid="stHorizontalBlock"] {
            padding-left: 2.75rem;
            gap: 0.5rem;
        }
        [data-testid="column"] { min-width: calc(50% - 0.25rem); }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .stButton > button { min-height: 66px; padding: .65rem .45rem; }
    }

    @media (prefers-reduced-motion: reduce) {
        .stButton > button { transition: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

step_number = min(STEPS.index(st.session_state["conversation_step"]) + 1, 3)

st.markdown(
    f"""
    <header class="passport-header">
        <div class="wordmark"><span class="logo-mark">♪</span>Music Passport</div>
        <div class="step">Step {step_number} / 3</div>
    </header>
    <section class="journey-intro" aria-labelledby="journey-title">
        <p class="eyebrow">Your music journey</p>
        <h1 id="journey-title">기분에서 시작하는 음악 여행</h1>
        <div class="cabin-window" role="img" aria-label="비행기 창문 너머로 보이는 밤하늘과 도시의 불빛"></div>
    </section>
    <section aria-label="AI 여행 컨시어지와의 대화"></section>
    """,
    unsafe_allow_html=True,
)

render_ai_message("안녕하세요.<br>오늘은 어떤 음악 여행을 떠나볼까요?<br><br>지금의 기분과 가장 가까운 것은 무엇인가요?")

if st.session_state.get("mood"):
    render_user_message(st.session_state["mood"])
    render_ai_message("이 음악을 어떤 상황에서 듣고 싶으신가요?")

if st.session_state.get("situation"):
    render_user_message(st.session_state["situation"])
    render_ai_message("이번 음악 여행은 어느 도시로 떠나볼까요?")

if st.session_state.get("city"):
    render_user_message(st.session_state["city"])
    render_ai_message("좋습니다.<br>선택한 도시로 음악 여행을 준비하고 있습니다.")

current_step = st.session_state["conversation_step"]
if current_step == "mood":
    render_choices("mood", MOOD_CHOICES, "situation")
elif current_step == "situation":
    render_choices("situation", SITUATION_CHOICES, "city")
elif current_step == "city":
    render_choices("city", CITY_CHOICES, "complete")

st.button("다시 시작하기", key="restart", on_click=reset_conversation)

st.markdown(
    """
    <p class="travel-note">
        하나의 선택에서 새로운 도시와 음악이 시작됩니다.<br>
        Music Passport · Journey 01
    </p>
    """,
    unsafe_allow_html=True,
)
