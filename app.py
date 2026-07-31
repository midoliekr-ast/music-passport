"""Music Passport home screen.

This module intentionally contains presentation only. The start button does not
navigate or trigger any recommendation logic yet.
"""

import streamlit as st


st.set_page_config(
    page_title="Music Passport",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root {
        color-scheme: light;
    }

    .stApp {
        background: #ffffff;
        color: #171717;
    }

    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    #MainMenu,
    footer {
        display: none;
    }

    [data-testid="stAppViewContainer"] > .main {
        background: #ffffff;
    }

    .block-container {
        max-width: 920px;
        min-height: 100svh;
        padding: clamp(5rem, 15vh, 10rem) 2rem 4rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .home-copy {
        margin: 0 auto;
        text-align: center;
    }

    .home-copy h1 {
        margin: 0;
        color: #111111;
        font-family: Georgia, "Times New Roman", serif;
        font-size: clamp(3rem, 8vw, 6rem);
        font-weight: 500;
        letter-spacing: -0.045em;
        line-height: 1.05;
    }

    .home-copy h2 {
        margin: 1.5rem 0 0;
        color: #292929;
        font-size: clamp(1.2rem, 2.4vw, 1.55rem);
        font-weight: 500;
        letter-spacing: -0.025em;
        line-height: 1.45;
    }

    .home-copy p {
        margin: 2rem auto 0;
        color: #5c5c5c;
        font-size: clamp(1rem, 1.8vw, 1.125rem);
        font-weight: 400;
        line-height: 1.8;
        word-break: keep-all;
    }

    .stButton {
        display: flex;
        justify-content: center;
        margin-top: clamp(3rem, 7vh, 4.5rem);
    }

    .stButton > button {
        min-width: min(100%, 280px);
        min-height: 58px;
        padding: 0.9rem 2.25rem;
        border: 1px solid #171717;
        border-radius: 2px;
        background: #171717;
        color: #ffffff;
        font-size: 1rem;
        font-weight: 600;
        letter-spacing: -0.01em;
        box-shadow: none;
        transition: background 160ms ease, color 160ms ease;
    }

    .stButton > button:hover {
        border-color: #171717;
        background: #ffffff;
        color: #171717;
    }

    .stButton > button:focus-visible {
        outline: 3px solid #737373;
        outline-offset: 3px;
        box-shadow: none;
    }

    .stButton > button:active {
        background: #303030;
        color: #ffffff;
    }

    @media (max-width: 640px) {
        .block-container {
            min-height: 100svh;
            padding: 4rem 1.5rem 3rem;
        }

        .home-copy p br {
            display: none;
        }

        .stButton > button {
            width: 100%;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .stButton > button {
            transition: none;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <section class="home-copy" aria-labelledby="home-title">
        <h1 id="home-title">Music Passport</h1>
        <h2>음악으로 떠나는 새로운 여행</h2>
        <p>
            기분과 상황을 선택하면<br>
            당신만의 플레이리스트와 음악 여권을 만들어드립니다.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

# The CTA is visual-only for this iteration; no navigation or API call is bound.
st.button("여행 시작하기", use_container_width=False)
