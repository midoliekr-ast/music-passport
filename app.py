"""Interactive chat screen for the Music Passport journey."""

import base64
from collections.abc import Callable
from difflib import SequenceMatcher
from html import escape
import io
import logging
from pathlib import Path
import re
import time
from typing import Literal
import unicodedata
from urllib.parse import quote

from openai import OpenAI
from pydantic import BaseModel, ValidationError
import qrcode
import requests
import streamlit as st
import streamlit.components.v1 as components


CHAT_FIELDS = (
    "journey_mode",
    "mood",
    "situation",
    "city",
    "tempo",
    "vocal",
    "discovery_level",
    "track_count",
)
PREFERENCE_STEPS = (
    "favorite_genres",
    "favorite_artists",
    "favorite_reasons",
)
CUSTOM_DESTINATION_STEPS = ("custom_destination", "korea_city")
RECOVERY_STEP = "insufficient_tracks_recovery"
RECOMMENDATION_TIMEOUT_STEP = "recommendation_timeout_recovery"
STEPS = (
    *CHAT_FIELDS,
    *PREFERENCE_STEPS,
    *CUSTOM_DESTINATION_STEPS,
    "complete",
    RECOVERY_STEP,
    RECOMMENDATION_TIMEOUT_STEP,
)
QUESTION_CONFIG = {
    "journey_mode": {
        "question": "오늘의 음악 여행, 어떤 방식으로 떠나볼까요? 🎧",
        "placeholder": "원하는 추천 방식을 선택해주세요",
        "options": (
            ("취향 반영", "🎧 내 취향을 반영해서 추천받기"),
            ("LYRA에게 맡기기", "✨ LYRA에게 완전히 맡기기"),
        ),
    },
    "favorite_genres": {
        "question": (
            "평소에 좋아하는 음악 장르를 골라주세요.<br>"
            "여러 개 선택할 수 있어요.<br>"
            "최대 3개까지 골라주세요. 🎧"
        ),
        "placeholder": "좋아하는 장르를 자유롭게 입력해주세요",
        "options": (
            ("Jazz Hip Hop", "🎷 Jazz Hip Hop"),
            ("Lo-fi Hip Hop", "🌙 Lo-fi Hip Hop"),
            ("Jazz", "🎹 Jazz"),
            ("R&B / Soul", "🎤 R&B / Soul"),
            ("Electronic", "🎛️ Electronic"),
            ("Afrobeat", "🥁 Afrobeat"),
            ("African Jazz / Afro Jazz", "🌍 African Jazz / Afro Jazz"),
            ("Latin", "💃 Latin"),
            ("Reggae", "🌴 Reggae"),
            ("Indie", "🎸 Indie"),
            ("트로트", "🇰🇷 트로트"),
            ("민속음악 / 전통음악", "🪘 민속음악 / 전통음악"),
            ("__direct__", "✏️ 기타"),
        ),
    },
    "favorite_artists": {
        "question": (
            "좋아하는 아티스트가 있다면 알려주세요.<br>"
            "선택 사항이에요. 😊"
        ),
        "placeholder": "예: Nujabes, FKJ, Bonobo",
        "options": (
            ("__direct__", "✍️ 아티스트 입력하기"),
            ("__skip__", "건너뛰기"),
        ),
    },
    "favorite_reasons": {
        "question": (
            "그 음악의 어떤 점을 좋아하시나요?<br>"
            "여러 개 선택할 수 있어요.<br>"
            "최대 3개까지 골라주세요. 🎶"
        ),
        "placeholder": "좋아하는 소리와 분위기를 자유롭게 입력해주세요",
        "options": (
            ("차분한 비트", "🥁 차분한 비트"),
            ("재즈 느낌", "🎷 재즈 느낌"),
            ("멜로우한 분위기", "🌙 멜로우한 분위기"),
            ("인스트루멘털 중심", "🎹 인스트루멘털 중심"),
            ("밤에 어울리는 음악", "🌃 밤에 어울리는 음악"),
            ("강한 리듬", "🔥 강한 리듬"),
            (
                "감성적이지만 과하지 않은 음악",
                "🤍 감성적이지만 과하지 않은 음악",
            ),
            ("애절한 감정", "💔 애절한 감정"),
            (
                "전통 악기와 독특한 리듬",
                "🪘 전통 악기와 독특한 리듬",
            ),
            ("__direct__", "✏️ 직접 입력"),
        ),
    },
    "custom_destination": {
        "question": (
            "이번에는 어디의 음악을 여행해볼까요? ✈️<br>"
            "하나를 골라주세요."
        ),
        "placeholder": "여행하고 싶은 나라나 지역을 입력해주세요",
        "options": (
            ("한국", "🇰🇷 한국"),
            ("일본", "🇯🇵 일본"),
            ("영국", "🇬🇧 영국"),
            ("프랑스", "🇫🇷 프랑스"),
            ("나이지리아", "🇳🇬 나이지리아"),
            ("브라질", "🇧🇷 브라질"),
            ("쿠바", "🇨🇺 쿠바"),
            ("미국", "🇺🇸 미국"),
            ("__direct__", "✏️ 직접 입력할게요"),
            ("__lyra__", "🎲 상관없음"),
        ),
    },
    "korea_city": {
        "question": (
            "한국에서는 어느 도시의 음악을 만나볼까요? 🇰🇷<br>"
            "하나를 골라주세요."
        ),
        "placeholder": "여행하고 싶은 한국 도시를 입력해주세요",
        "options": (
            ("서울", "서울"),
            ("부산", "부산"),
            ("대구", "대구"),
            ("광주", "광주"),
            ("제주", "제주"),
            ("__direct__", "✏️ 직접 입력할게요"),
            ("__lyra__", "🎲 LYRA에게 맡길게요"),
        ),
    },
    "city": {
        "question": "어느 도시의 음악을 탐험해볼까요?",
        "placeholder": "번호 또는 원하는 도시를 입력해주세요",
        "options": (
            ("서울", "🇰🇷 서울"),
            ("도쿄", "🇯🇵 도쿄"),
            ("런던", "🇬🇧 런던"),
            ("파리", "🇫🇷 파리"),
            ("뉴욕", "🇺🇸 뉴욕"),
            ("리우데자네이루", "🇧🇷 리우데자네이루"),
            ("레이캬비크", "🇮🇸 레이캬비크"),
            ("베를린", "🇩🇪 베를린"),
            ("__direct__", "✏️ 직접 입력할게요"),
            ("상관없어요", "🎲 상관없어요"),
        ),
    },
    "mood": {
        "question": "지금 어떤 기분에 가까운가요?",
        "placeholder": "원하는 분위기를 자유롭게 적어주세요",
        "options": (
            ("차분해지고 싶어요", "🌿 차분해지고 싶어요"),
            ("기분을 끌어올리고 싶어요", "☀️ 기분을 끌어올리고 싶어요"),
            ("집중하고 싶어요", "🎯 집중하고 싶어요"),
            ("몽환적인 음악이 필요해요", "🌙 몽환적인 음악이 필요해요"),
            ("새로운 자극이 필요해요", "⚡ 새로운 자극이 필요해요"),
            ("감정을 가라앉히고 싶어요", "🫧 감정을 가라앉히고 싶어요"),
            ("__direct__", "✍️ 직접 입력할게요"),
        ),
    },
    "situation": {
        "question": "어떤 상황에서 들을 음악인가요?",
        "placeholder": "번호 또는 듣는 상황을 입력해주세요",
        "options": (
            ("산책", "🚶 산책"),
            ("출퇴근 또는 이동", "🚇 출퇴근 또는 이동"),
            ("카페에서 쉬는 시간", "☕ 카페에서 쉬는 시간"),
            ("집에서 휴식", "🛋️ 집에서 휴식"),
            ("작업 또는 공부", "💻 작업 또는 공부"),
            ("밤에 혼자 듣기", "🌃 밤에 혼자 듣기"),
            ("여행", "✈️ 여행"),
            ("__direct__", "✍️ 직접 입력할게요"),
        ),
    },
    "tempo": {
        "question": "어떤 템포를 선호하나요?",
        "placeholder": "번호 또는 원하는 템포를 입력해주세요",
        "options": (
            ("느리고 잔잔하게", "🌊 느리고 잔잔하게"),
            ("적당한 속도로", "🚶 적당한 속도로"),
            ("경쾌하고 리드미컬하게", "🕺 경쾌하고 리드미컬하게"),
            ("상관없어요", "🎲 상관없어요"),
            ("__direct__", "✍️ 직접 입력할게요"),
        ),
    },
    "vocal": {
        "question": "보컬은 어떻게 할까요?",
        "placeholder": "번호 또는 보컬 선호를 입력해주세요",
        "options": (
            ("보컬이 있는 곡", "🎤 보컬이 있는 곡"),
            ("연주곡", "🎹 연주곡"),
            ("둘 다", "🎧 둘 다"),
            ("상관없어요", "🎲 상관없어요"),
        ),
    },
    "discovery_level": {
        "question": "얼마나 새로운 음악을 원하나요?",
        "placeholder": "번호 또는 원하는 탐색 정도를 입력해주세요",
        "options": (
            ("편안하고 익숙한 음악 중심", "🏠 편안하고 익숙한 음악 중심"),
            ("익숙함과 새로움을 반반", "⚖️ 익숙함과 새로움을 반반"),
            ("처음 듣는 낯선 음악 중심", "🧭 처음 듣는 낯선 음악 중심"),
            ("상관없어요", "🎲 상관없어요"),
        ),
    },
    "track_count": {
        "question": "몇 곡을 추천해드릴까요?",
        "placeholder": "추천 곡 수를 선택해주세요",
        "options": (
            (1, "🎧 1곡"),
            (3, "🎵 3곡"),
            (5, "🎶 5곡"),
            (7, "💿 7곡"),
        ),
    },
}
DIRECT_INPUT_PLACEHOLDERS = {
    "favorite_genres": "좋아하는 장르를 자유롭게 입력해주세요",
    "favorite_artists": "예: Nujabes, FKJ, Bonobo",
    "favorite_reasons": "좋아하는 소리와 분위기를 자유롭게 입력해주세요",
    "custom_destination": "여행하고 싶은 나라나 지역을 입력해주세요",
    "korea_city": "여행하고 싶은 한국 도시를 입력해주세요",
    "city": "원하는 도시를 입력해 주세요",
    "mood": "지금의 기분을 자유롭게 적어 주세요",
    "situation": "음악을 들을 상황을 입력해 주세요",
    "tempo": "원하는 템포를 입력해 주세요",
    "track_count": "1~10 사이의 곡 수를 입력해 주세요",
}
DIRECT_INPUT_STATE_KEYS = {
    "favorite_genres": "genre_custom_input",
    "favorite_artists": "artist_custom_input",
    "favorite_reasons": "preference_custom_input",
    "custom_destination": "destination_custom_input",
    "korea_city": "korea_city_custom_input",
    "city": "city_custom_input",
    "mood": "mood_custom_input",
    "situation": "situation_custom_input",
    "tempo": "tempo_custom_input",
    "track_count": "track_count_input",
    RECOVERY_STEP: "recovery_custom_input",
    RECOMMENDATION_TIMEOUT_STEP: "timeout_retry_custom_input",
}
GENERATION_STAGE_MESSAGES = {
    "verifying": "♪ 실제 곡과 아티스트 정보를 확인하고 있어요...",
}
MAX_SCOPE_ATTEMPTS = 3
NORMAL_GUARANTEE_MAX_ATTEMPTS = 5
LYRA_AUTO_RETRY_MAX_ATTEMPTS = 10
LYRA_AUTO_RETRY_MAX_ROUNDS = 5
LYRA_AUTO_RETRY_STAGES = (
    "같은 여행지와 취향을 유지하고 이전과 다른 검색어 조합 사용",
    "완전 일치 장르를 가까운 장르와 하위 장르까지 확장",
    "선호 아티스트 이름 대신 리듬·악기·질감·샘플링 특징으로 변환",
    "비슷한 음악 요소와 관련 아티스트까지 후보 확장",
    "여행지와 곡 수는 고정하고 BPM·보컬 조건의 우선도만 낮춤",
    "최종 보완: 다른 조건보다 국가 일치와 곡 수를 우선하고, 해당 국가의 "
    "대표적·대중적·영향력 있는 곡과 주요 로컬 음악 신에서 새 후보 생성",
)
NORMAL_GUARANTEE_STAGES = (
    "같은 국가 안에서 이전과 다른 검색어와 로컬 음악 신으로 새 후보 생성",
    "장르 완전 일치 대신 가까운 장르와 하위 장르까지 후보 확장",
    "선호 아티스트 이름 대신 리듬·악기·질감 같은 음악적 특징으로 탐색",
    "BPM·보컬·기분·상황은 참고만 하고 국가 연결과 실재 여부를 우선",
    "최종 보완: 해당 국가의 대표적·대중적·영향력 있는 실제 곡에서 보충",
)
LISBON_SINGLE_TRACK_SEARCH_STAGES = (
    "Lisbon music, Lisbon artist, Lisbon jazz, Lisbon hip hop, "
    "Lisbon electronic, Lisbon indie 검색어로 리스본 직접 연결 후보 탐색",
    "Portugal music, Portuguese artist, Portuguese jazz, Portuguese hip hop, "
    "Portuguese electronic, Portuguese indie, Portuguese soul, "
    "Portuguese instrumental 검색어로 포르투갈 전역 후보 탐색",
    "fado, fado fusion, Lisbon fado, Portuguese popular music 검색어로 "
    "포르투갈의 대표 음악 신 후보 탐색",
    "BPM·보컬·기분·상황·장르 유사도는 참고만 하고 Portugal 연결과 "
    "실재 여부를 우선해 대표적·대중적·영향력 있는 곡 탐색",
)
RECOMMENDATION_TIMEOUT_SECONDS = 180
CITY_IMAGES = {
    "서울": "assets/cities/seoul.webp",
    "런던": "assets/cities/london.webp",
    "파리": "assets/cities/paris.webp",
    "도쿄": "assets/cities/tokyo.webp",
    "마라케시": "assets/cities/marrakech.webp",
    "리우": "assets/cities/rio.webp",
    "default": "assets/cities/default.webp",
}
AIRPLANE_WINDOW_IMAGE = "assets/airplane-window.webp"
INTRO_WINDOW_SCENES = (
    ("dawn", "assets/intro_dawn.webp"),
    ("sunset", "assets/intro_sunset.webp"),
    ("bluehour", "assets/intro_bluehour.webp"),
    ("night", "assets/intro_night.webp"),
)
LYRA_IMAGE = "assets/lyra-orb.webp"
CITY_CODES = {
    "서울": "KR",
    "런던": "UK",
    "파리": "FR",
    "도쿄": "JP",
    "마라케시": "MA",
    "리우": "BR",
}
OPENAI_MODEL = "gpt-5.6-terra"
PASSPORT_THUMBNAIL_MODEL = "gpt-image-2"
BARCODE_PATTERN = (1, 3, 1, 2, 4, 1, 1, 3, 2, 1, 4, 2, 1, 3) * 2
PASSPORT_CITY_VISUAL_DIRECTIONS = {
    "nigeria": (
        "Lagos skyline and lagoon, dense modern Nigerian cityscape, urban "
        "islands, bridges, and warm West African light"
    ),
    "brazil": (
        "a recognizable Brazilian city landscape with Rio de Janeiro's layered "
        "coast, green granite peaks, and luminous urban neighborhoods"
    ),
    "cuba": (
        "Old Havana streets and the Malecón, weathered pastel architecture, "
        "Cuban urban waterfront, and warm Caribbean city light"
    ),
    "japan": (
        "a recognizable Japanese urban scene with layered neighborhoods, rail "
        "lights, restrained traditional architecture, and distant mountains"
    ),
    "united kingdom": (
        "a recognizable British city scene with brick streets, soft rain, "
        "urban lights, and layered historic and modern architecture"
    ),
    "france": (
        "a recognizable French city scene with dense boulevards, river light, "
        "and restrained historic architecture"
    ),
    "united states": (
        "a recognizable American cityscape with layered downtown architecture, "
        "street lights, and a clear regional urban atmosphere"
    ),
    "daegu": (
        "Daegu city basin, dense Korean skyline, nearby green ridges, and warm "
        "evening streets without coastline"
    ),
    "대구": (
        "Daegu city basin, dense Korean skyline, nearby green ridges, and warm "
        "evening streets without coastline"
    ),
    "gwangju": (
        "Gwangju's modern Korean cityscape, broad streets, cultural district, "
        "and the distant Mudeungsan ridgeline"
    ),
    "광주": (
        "Gwangju's modern Korean cityscape, broad streets, cultural district, "
        "and the distant Mudeungsan ridgeline"
    ),
    "jeju": (
        "Jeju volcanic landscape, Hallasan silhouette, dark stone walls, coastal "
        "fields, and a real Jeju settlement"
    ),
    "제주": (
        "Jeju volcanic landscape, Hallasan silhouette, dark stone walls, coastal "
        "fields, and a real Jeju settlement"
    ),
    "toyama": (
        "Toyama Bay in the foreground, the distant snow-capped Tateyama "
        "mountain range, a calm waterfront cityscape, river and harbor lights"
    ),
    "富山": (
        "Toyama Bay in the foreground, the distant snow-capped Tateyama "
        "mountain range, a calm waterfront cityscape, river and harbor lights"
    ),
    "yokohama": (
        "Yokohama harbor skyline, waterfront promenade, calm bay, layered city "
        "lights and recognizable port architecture"
    ),
    "横浜": (
        "Yokohama harbor skyline, waterfront promenade, calm bay, layered city "
        "lights and recognizable port architecture"
    ),
    "seoul": (
        "the Han River in the foreground, Seoul city skyline in the midground, "
        "bridges and softly layered distant mountains; optionally use N Seoul "
        "Tower, Seongsu, Hongdae, Bukchon Hanok Village, Gyeongbokgung, or "
        "Dongdaemun as restrained local context"
    ),
    "서울": (
        "the Han River in the foreground, Seoul city skyline in the midground, "
        "bridges and softly layered distant mountains"
    ),
    "havana": (
        "Havana's Malecón seawall or Old Havana streets, weathered pastel "
        "architecture, warm Caribbean city light, and a recognizable Cuban "
        "urban waterfront"
    ),
    "하바나": (
        "Havana's Malecón seawall or Old Havana streets, weathered pastel "
        "architecture, warm Caribbean city light, and a recognizable Cuban "
        "urban waterfront"
    ),
    "rio de janeiro": (
        "Rio de Janeiro's layered coastal city, Copacabana or Ipanema shoreline, "
        "green granite peaks, and a distant restrained Christ the Redeemer"
    ),
    "리우데자네이루": (
        "Rio de Janeiro's layered coastal city, Copacabana or Ipanema shoreline, "
        "green granite peaks, and a distant restrained Christ the Redeemer"
    ),
    "lagos": (
        "Lagos lagoon and dense modern cityscape, Third Mainland Bridge, urban "
        "islands and warm West African city light"
    ),
    "라고스": (
        "Lagos lagoon and dense modern cityscape, Third Mainland Bridge, urban "
        "islands and warm West African city light"
    ),
    "헬싱키": (
        "dreamlike Helsinki harbor at blue hour, soft silhouette of Helsinki "
        "Cathedral, faint tram lights reflected on wet streets, pale Nordic "
        "sky, subtle aurora glow, quiet waterfront atmosphere, cool blue-grey "
        "and silver palette, recognizable but softly blurred"
    ),
    "helsinki": (
        "dreamlike Helsinki harbor at blue hour, soft silhouette of Helsinki "
        "Cathedral, faint tram lights reflected on wet streets, pale Nordic "
        "sky, subtle aurora glow, quiet waterfront atmosphere, cool blue-grey "
        "and silver palette, recognizable but softly blurred"
    ),
    "다낭": (
        "dreamlike Da Nang coastline at dusk, soft silhouette of the Dragon "
        "Bridge, calm sea reflections, warm tropical haze, distant city "
        "lights, muted coral and indigo accents, recognizable but softly blended"
    ),
    "da nang": (
        "dreamlike Da Nang coastline at dusk, soft silhouette of the Dragon "
        "Bridge, calm sea reflections, warm tropical haze, distant city "
        "lights, muted coral and indigo accents, recognizable but softly blended"
    ),
    "부산": (
        "dreamlike Busan harbor at night, subtle Gwangan Bridge lights, layered "
        "coastal hills, deep blue sea reflections, soft urban glow, no giant "
        "bridge dominating the image"
    ),
    "busan": (
        "dreamlike Busan harbor at night, subtle Gwangan Bridge lights, layered "
        "coastal hills, deep blue sea reflections, soft urban glow, no giant "
        "bridge dominating the image"
    ),
    "런던": (
        "misty London at night, faint underground geometry, soft brick texture, "
        "distant city lights, subtle silhouette of a recognizable skyline, no "
        "postcard landmark composition"
    ),
    "london": (
        "misty London at night, faint underground geometry, soft brick texture, "
        "distant city lights, subtle silhouette of a recognizable skyline, no "
        "postcard landmark composition"
    ),
    "도쿄": (
        "rainy Tokyo night, soft neon reflections, layered city geometry, faint "
        "skyline and train-light traces, dreamlike and restrained, no giant "
        "signboards"
    ),
    "tokyo": (
        "rainy Tokyo night, soft neon reflections, layered city geometry, faint "
        "skyline and train-light traces, dreamlike and restrained, no giant "
        "signboards"
    ),
}
PASSPORT_CITY_FORBIDDEN_SCENERY = {
    "seoul": "coastline, beach, seaport, tropical resort scenery, or palm-lined shore",
    "서울": "coastline, beach, seaport, tropical resort scenery, or palm-lined shore",
    "busan": "desert, alpine snowfield, or landlocked European streetscape",
    "부산": "desert, alpine snowfield, or landlocked European streetscape",
    "havana": "alpine mountains, East Asian temples, or generic tropical resort beach",
    "하바나": "alpine mountains, East Asian temples, or generic tropical resort beach",
    "rio de janeiro": "desert, snowfield, East Asian skyline, or generic Mediterranean town",
    "리우데자네이루": "desert, snowfield, East Asian skyline, or generic Mediterranean town",
    "lagos": "snow mountains, Mount Fuji, alpine scenery, or European old town",
    "라고스": "snow mountains, Mount Fuji, alpine scenery, or European old town",
    "paris": "desert, tropical beach, rainforest, or alpine wilderness",
    "파리": "desert, tropical beach, rainforest, or alpine wilderness",
}
API_ERROR_MESSAGE = (
    "추천 정보를 불러오지 못했어요. "
    "API 설정을 확인한 뒤 다시 시도해주세요."
)
SPOTIFY_TRACK_MATCH_MIN = 0.78
SPOTIFY_ARTIST_MATCH_MIN = 0.80
NORMAL_FALLBACK_TRACK_MATCH_MIN = 0.70
NORMAL_FALLBACK_ARTIST_MATCH_MIN = 0.74
SPOTIFY_TRACK_NAME_ALIASES = {
    "안동역에서": ("At Andong Station",),
}
SPOTIFY_ARTIST_NAME_ALIASES = {
    "진성": ("Jinsung", "Jin Sung"),
}
_SPOTIFY_REFRESHED_ACCESS_TOKEN = ""
_SPOTIFY_ARTIST_GENRE_CACHE: dict[str, tuple[str, ...]] = {}
logger = logging.getLogger("music_passport")
logger.setLevel(logging.INFO)


def get_next_question() -> str:
    """Return the first unanswered Chat condition."""
    return next(
        (field for field in CHAT_FIELDS if not st.session_state.get(field)),
        "complete",
    )


def direct_input_state_key(question_key: str) -> str:
    """Return the input-widget key dedicated to one direct-input step."""
    return DIRECT_INPUT_STATE_KEYS[question_key]


def current_journey_signature() -> tuple:
    """Return every recommendation input as one stable cache signature."""
    return tuple(st.session_state.get(field) for field in CHAT_FIELDS) + (
        st.session_state.get("free_text_preferences", ""),
    )


def append_chat_message(role: str, content: str) -> None:
    """Append one non-duplicate message to the persisted Chat history."""
    history = st.session_state.setdefault("chat_history", [])
    message = {"role": role, "content": content}
    if not history or history[-1] != message:
        history.append(message)


def normalize_option_text(value: str) -> str:
    """Normalize labels for direct option-text matching."""
    return "".join(character for character in value.casefold() if character.isalnum())


def resolve_option(question_key: str, raw_answer: str) -> tuple[object, str] | None:
    """Resolve a number or option label against the current question."""
    options = QUESTION_CONFIG[question_key]["options"]
    stripped = raw_answer.strip()
    if re.fullmatch(r"\d+", stripped):
        option_index = int(stripped) - 1
        if 0 <= option_index < len(options):
            return options[option_index]
    normalized = normalize_option_text(stripped)
    for value, label in options:
        label_text = normalize_option_text(label)
        value_text = normalize_option_text(str(value))
        if normalized and normalized in (label_text, value_text):
            return value, label
    return None


PREFERENCE_SECTION_LABELS = {
    "favorite_genres": "좋아하는 장르",
    "favorite_artists": "좋아하는 아티스트",
    "favorite_reasons": "좋아하는 이유",
}
EXPLICIT_GENRE_ALIASES = {
    "Jazz Hip Hop": (
        "jazz hip hop", "jazz rap", "jazzy hip hop", "jazzy beats",
    ),
    "Lo-fi Hip Hop": ("lo-fi hip hop", "lofi hip hop", "lo-fi beats"),
    "Jazz": (
        "jazz", "contemporary jazz", "modern jazz", "jazz fusion", "nu jazz",
    ),
    "R&B / Soul": ("r&b", "rhythm and blues", "soul", "neo soul"),
    "Electronic": ("electronic", "electronica", "electro", "ambient electronic"),
    "Afrobeat": ("afrobeat", "afrobeats", "afro jazz", "highlife"),
    "African Jazz / Afro Jazz": (
        "african jazz", "afro jazz", "ethio jazz", "cape jazz",
    ),
    "Latin": (
        "latin", "latin jazz", "salsa", "son cubano", "bolero", "bossa nova",
    ),
    "Reggae": ("reggae", "roots reggae", "dub", "rocksteady"),
    "Indie": ("indie", "indie rock", "indie pop", "alternative"),
    "트로트": (
        "트로트", "한국 트로트", "성인가요", "트로트 발라드",
        "국악 트로트", "korean trot", "trot",
    ),
    "민속음악 / 전통음악": (
        "민속음악", "전통음악", "folk", "traditional", "indigenous music",
        "traditional instruments", "world folk", "folk fusion",
    ),
}
EXPLICIT_GENRE_EXCLUSION_TERMS = {
    "트로트": (
        "민요", "농요", "아리랑", "탈놀이", "별신굿", "놋다리밟기",
        "칡부리기", "메나리", "소주타령", "국립국악원", "전통 공연",
        "무형문화재",
    ),
}


def preference_values(preferences: str, label: str) -> tuple[str, ...]:
    """Read a comma-separated preference line from the persisted answer text."""
    prefix = f"{label}: "
    for line in preferences.splitlines():
        if line.startswith(prefix):
            return tuple(
                value.strip()
                for value in line[len(prefix):].split(",")
                if value.strip() and value.strip() not in {"상관없어요", "상관없음"}
            )
    return ()


def selected_genres_from_preferences(preferences: str) -> tuple[str, ...]:
    """Return only genres the user explicitly selected."""
    return preference_values(preferences, PREFERENCE_SECTION_LABELS["favorite_genres"])


def genre_evidence_matches(
    selected_genres: tuple[str, ...],
    *evidence_values: str,
) -> bool:
    """Match structured/Spotify genre evidence to any explicitly selected genre."""
    if not selected_genres:
        return True
    evidence = " ".join(
        unicodedata.normalize("NFKC", value).casefold()
        for value in evidence_values
        if value
    )
    return any(
        any(
            unicodedata.normalize("NFKC", alias).casefold() in evidence
            for alias in EXPLICIT_GENRE_ALIASES.get(genre, (genre,))
        )
        for genre in selected_genres
    )


def explicit_genre_prompt_rule(selected_genres: tuple[str, ...]) -> str:
    """Build one shared hard-genre rule for every recommendation mode."""
    if not selected_genres:
        return ""
    aliases = {
        genre: EXPLICIT_GENRE_ALIASES.get(genre, (genre,))
        for genre in selected_genres
    }
    exclusions = {
        genre: EXPLICIT_GENRE_EXCLUSION_TERMS.get(genre, ())
        for genre in selected_genres
        if genre in EXPLICIT_GENRE_EXCLUSION_TERMS
    }
    return (
        "\n사용자가 명시적으로 선택한 장르는 추천의 최우선 필수 조건입니다. "
        f"선택 장르: {', '.join(selected_genres)}. "
        f"허용되는 직접 관련 장르 표현: {aliases}. "
        "모든 후보는 선택 장르 자체, 그 하위 장르, 또는 직접 연결된 "
        "크로스오버에 속해야 합니다. 지역은 도시 → 광역 지역 → 같은 국가 "
        "순서로 확장하되 장르는 바꾸지 마세요. 탐색 수준, 기분과 상황, "
        "선호 아티스트, BPM과 보컬은 선택 장르 안에서 곡을 고르는 보조 "
        "기준일 뿐입니다. 선호 아티스트의 실제 장르가 다르면 그 아티스트나 "
        "그 장르의 곡을 추천하지 마세요. 재시도, 부족 회복, relaxed scope, "
        "내부 보장 검색, 국가 확장, LYRA 자동 재검색과 최종 보완에서도 "
        "이 장르 조건을 완화하거나 삭제하지 마세요. "
        + (
            f"선택 장르별 금지 중심 표현: {exclusions}. "
            if exclusions
            else ""
        )
        + (
            "선택 장르가 트로트이면 지역 전통음악, 민요, 농요, 아리랑, "
            "탈놀이, 별신굿, 국악 공연 음원을 추천하지 마세요. 도시 안에서 "
            "충분한 트로트를 찾지 못하면 장르를 바꾸지 말고 지역만 도시 → "
            "광역 지역 → 대한민국 순으로 확장하세요. 안동 + 트로트라면 "
            "안동역에서 / 진성을 우선 검토하고, 이어 경상북도 또는 대한민국의 "
            "실제 트로트를 찾으세요. "
            if "트로트" in selected_genres
            else ""
        )
        + "genre에는 실제 장르명을, genre_connection에는 선택 장르와의 "
        "구체적인 연결을 한국어로 작성하세요.\n"
    )


def candidate_matches_explicit_genres(
    candidate: "TrackCandidate",
    selected_genres: tuple[str, ...],
) -> bool:
    """Apply the same hard genre gate before every Spotify lookup."""
    if not selected_genres:
        return True
    if not genre_evidence_matches(
        selected_genres,
        candidate.genre,
        candidate.genre_connection,
        candidate.recommendation_reason,
    ):
        return False
    combined = " ".join(
        (
            candidate.track_name,
            candidate.genre,
            candidate.genre_connection,
            candidate.city_connection,
            candidate.recommendation_reason,
        )
    ).casefold()
    for genre in selected_genres:
        blocked_terms = EXPLICIT_GENRE_EXCLUSION_TERMS.get(genre, ())
        if any(term.casefold() in combined for term in blocked_terms):
            if genre == "트로트" and "국악 트로트" in (
                f"{candidate.genre} {candidate.genre_connection}".casefold()
            ):
                continue
            return False
    return True
CUSTOM_COUNTRY_DESTINATIONS = {
    "일본": ("Japan", "日本"),
    "영국": ("United Kingdom", "영국"),
    "프랑스": ("France", "France"),
    "나이지리아": ("Nigeria", "Nigeria"),
    "브라질": ("Brazil", "Brasil"),
    "쿠바": ("Cuba", "Cuba"),
    "미국": ("United States", "United States"),
}
KOREA_CITY_DESTINATIONS = {
    "서울": "Seoul, South Korea",
    "부산": "Busan, South Korea",
    "대구": "Daegu, South Korea",
    "광주": "Gwangju, South Korea",
    "제주": "Jeju, South Korea",
}
DESTINATION_KOREAN_NAMES = {
    "oslo": "오슬로",
    "moscow": "모스크바",
    "new york": "뉴욕",
    "new york city": "뉴욕",
    "nyc": "뉴욕",
    "united kingdom": "영국",
    "uk": "영국",
    "japan": "일본",
    "cuba": "쿠바",
    "brazil": "브라질",
    "mexico": "멕시코",
    "russia": "러시아",
    "france": "프랑스",
    "south korea": "한국",
    "united states": "미국",
}


def resolve_destination_display_name(
    canonical_name: str,
    korean_name: str = "",
    local_name: str = "",
) -> str:
    """Return a Korean UI name from resolved geography, never from raw input."""
    if korean_name.strip():
        return korean_name.strip()
    localized = DESTINATION_KOREAN_NAMES.get(canonical_name.casefold().strip())
    if localized:
        return localized
    if re.search(r"[가-힣]", local_name):
        return local_name.strip()
    return canonical_name.strip()


def set_destination_identity(
    *,
    raw_input: str,
    canonical_name: str,
    display_name: str,
    country_name: str,
    destination_type: Literal["city", "country", "lyra"],
) -> None:
    """Keep raw input, search identity, and UI identity separate."""
    st.session_state["destination_raw_input"] = raw_input
    st.session_state["destination_canonical_name"] = canonical_name
    st.session_state["destination_display_name"] = display_name
    st.session_state["destination_country_name"] = country_name
    st.session_state["destination_type"] = destination_type


def set_custom_destination_metadata(
    *,
    scope: Literal["city", "country", "lyra"],
    display: str,
    country: str,
    country_local: str,
    raw_input: str = "",
    canonical_name: str = "",
    display_name: str = "",
    destination_type: str = "",
) -> None:
    """Store custom-route metadata inside the existing preference text."""
    metadata = {
        "여행 범위": scope,
        "여행지 표시": display,
        "여행지 국가": country,
        "여행지 국가 현지명": country_local,
        "여행지 원문": raw_input,
        "여행지 정규명": canonical_name,
        "여행지 한국어명": display_name,
        "여행지 유형": destination_type,
    }
    lines = str(st.session_state.get("free_text_preferences") or "").splitlines()
    prefixes = tuple(f"{label}: " for label in metadata)
    lines = [line for line in lines if not line.startswith(prefixes)]
    lines.extend(f"{label}: {value}" for label, value in metadata.items())
    st.session_state["free_text_preferences"] = "\n".join(lines)


def get_custom_destination_metadata(preferences: str) -> dict[str, str]:
    """Read custom-route metadata without introducing session-state keys."""
    labels = {
        "여행 범위": "scope",
        "여행지 표시": "display",
        "여행지 국가": "country",
        "여행지 국가 현지명": "country_local",
        "여행지 원문": "raw_input",
        "여행지 정규명": "canonical_name",
        "여행지 한국어명": "display_name",
        "여행지 유형": "destination_type",
    }
    metadata: dict[str, str] = {}
    for line in preferences.splitlines():
        label, separator, value = line.partition(":")
        if separator and label in labels and value.strip():
            metadata[labels[label]] = value.strip()
    return metadata


def choose_lyra_custom_destination(preferences: str) -> tuple[str, str, str]:
    """Choose one concrete destination from the collected taste clues."""
    normalized = preferences.casefold()
    if any(token in normalized for token in ("트로트", "한국", "korean")):
        return "서울", "Seoul, South Korea", "South Korea"
    if any(token in normalized for token in ("afro", "강한 리듬", "아프리카")):
        return "Nigeria", "Nigeria", "Nigeria"
    if any(token in normalized for token in ("latin", "애절한 감정", "쿠바")):
        return "Cuba", "Cuba", "Cuba"
    if any(token in normalized for token in ("reggae", "soul", "r&b")):
        return "Brazil", "Brazil", "Brazil"
    if any(token in normalized for token in ("electronic", "indie")):
        return "United Kingdom", "United Kingdom", "United Kingdom"
    return "Japan", "Japan", "Japan"


def choose_lyra_korea_city(preferences: str) -> str:
    """Choose one Korean city while keeping the journey in South Korea."""
    normalized = preferences.casefold()
    if any(token in normalized for token in ("바다", "해변", "항구", "밝")):
        return "부산"
    if any(token in normalized for token in ("전통", "민속", "트로트")):
        return "대구"
    return "서울"


def get_preference_section(step: str) -> list[str]:
    """Read one preference section from the existing free-text state value."""
    label = PREFERENCE_SECTION_LABELS[step]
    prefix = f"{label}: "
    for line in str(st.session_state.get("free_text_preferences") or "").splitlines():
        if line.startswith(prefix):
            return [
                item.strip()
                for item in line[len(prefix):].split(",")
                if item.strip()
            ]
    return []


def set_preference_section(step: str, values: list[str]) -> None:
    """Replace one preference section without adding a session-state key."""
    label = PREFERENCE_SECTION_LABELS[step]
    prefix = f"{label}: "
    lines = [
        line
        for line in str(st.session_state.get("free_text_preferences") or "").splitlines()
        if line and not line.startswith(prefix)
    ]
    if values:
        lines.append(prefix + ", ".join(dict.fromkeys(values)))
    st.session_state["free_text_preferences"] = "\n".join(lines)


def next_preference_question(step: str) -> str:
    """Return the next taste question, then resume the existing Chat flow."""
    if step == "favorite_genres":
        return "favorite_artists"
    if step == "favorite_artists":
        return "favorite_reasons"
    return "custom_destination"


def advance_chat_to(question_key: str) -> None:
    """Advance with the existing Chat state and append LYRA's next prompt."""
    st.session_state["current_question"] = question_key
    st.session_state["conversation_step"] = question_key
    st.session_state["direct_input_mode"] = False
    st.session_state["direct_input_field"] = None
    st.session_state["input_error"] = ""
    st.session_state["should_scroll_conversation"] = True
    if question_key == "complete":
        append_chat_message("ai", build_journey_summary_message())
    else:
        append_chat_message("ai", QUESTION_CONFIG[question_key]["question"])


def toggle_preference_choice(step: str, value: str, label: str) -> None:
    """Toggle one genre or taste reason and remain on the active question."""
    if st.session_state.get("current_question") != step:
        return
    selected = get_preference_section(step)
    if value in selected:
        selected.remove(value)
    else:
        if len(selected) >= 3:
            st.session_state["input_error"] = (
                "최대 3개까지 선택할 수 있어요 😊"
            )
            return
        selected.append(value)
    st.session_state["input_error"] = ""
    set_preference_section(step, selected)
    st.session_state["should_scroll_conversation"] = True


def finish_preference_multiselect(step: str) -> None:
    """Confirm a multi-select preference step before continuing."""
    if st.session_state.get("current_question") != step:
        return
    selected = get_preference_section(step)
    if not selected:
        st.session_state["input_error"] = "한 가지 이상 골라주세요."
        return
    append_chat_message("user", ", ".join(selected))
    advance_chat_to(next_preference_question(step))


def extract_chat_conditions(text: str) -> dict:
    """Extract obvious recommendation conditions without an API call."""
    lowered = text.casefold()
    extracted: dict[str, object] = {}

    city_aliases = {
        "서울": "서울",
        "도쿄": "도쿄",
        "東京": "도쿄",
        "런던": "런던",
        "london": "런던",
        "파리": "파리",
        "paris": "파리",
        "뉴욕": "뉴욕",
        "new york": "뉴욕",
        "리우데자네이루": "리우데자네이루",
        "리우": "리우데자네이루",
        "레이캬비크": "레이캬비크",
        "베를린": "베를린",
        "berlin": "베를린",
    }
    for alias, city in city_aliases.items():
        if alias.casefold() in lowered:
            extracted["city"] = city
            break

    keyword_maps = {
        "mood": (
            (("차분", "잔잔"), "차분해지고 싶어요"),
            (("신나", "기분을 올", "끌어올"), "기분을 끌어올리고 싶어요"),
            (("집중",), "집중하고 싶어요"),
            (("몽환",), "몽환적인 음악이 필요해요"),
            (("새로운 자극",), "새로운 자극이 필요해요"),
            (("감정을 가라앉", "지쳤"), "감정을 가라앉히고 싶어요"),
        ),
        "situation": (
            (("산책",), "산책"),
            (("출퇴근", "이동", "통근"), "출퇴근 또는 이동"),
            (("카페",), "카페에서 쉬는 시간"),
            (("집에서", "휴식"), "집에서 휴식"),
            (("작업", "공부"), "작업 또는 공부"),
            (("밤에", "밤 혼자"), "밤에 혼자 듣기"),
            (("여행",), "여행"),
        ),
        "tempo": (
            (("느리", "잔잔"), "느리고 잔잔하게"),
            (("적당한", "중간 템포"), "적당한 속도로"),
            (("경쾌", "리드미컬", "빠른"), "경쾌하고 리드미컬하게"),
        ),
        "vocal": (
            (("연주곡", "인스트루멘털", "instrumental"), "연주곡"),
            (("보컬", "노래가 있는"), "보컬이 있는 곡"),
            (("둘 다", "섞"), "둘 다"),
        ),
        "discovery_level": (
            (("익숙한", "편안한"), "편안하고 익숙한 음악 중심"),
            (("반반",), "익숙함과 새로움을 반반"),
            (("낯선", "처음 듣", "새로운 음악"), "처음 듣는 낯선 음악 중심"),
        ),
    }
    for field, mappings in keyword_maps.items():
        for keywords, value in mappings:
            if any(keyword in lowered for keyword in keywords):
                extracted[field] = value
                break

    count_match = re.search(r"(?<!\d)(10|[1-9])\s*곡", lowered)
    if count_match:
        extracted["track_count"] = int(count_match.group(1))

    genres = (
        "재즈",
        "힙합",
        "록",
        "팝",
        "인디",
        "소울",
        "알앤비",
        "r&b",
        "포크",
        "클래식",
        "앰비언트",
        "전자음악",
        "테크노",
    )
    matched_genres = [genre for genre in genres if genre.casefold() in lowered]
    if matched_genres:
        extracted["free_text_preferences"] = " ".join(matched_genres)
    return extracted


class TrackCandidate(BaseModel):
    track_name: str
    artist_name: str
    country: str
    connection_level: Literal["city", "region", "country"]
    city_connection: str
    genre: str
    genre_connection: str
    recommendation_reason: str


class JourneyCandidates(BaseModel):
    candidates: list[TrackCandidate]


class CityGeography(BaseModel):
    city: str
    city_local: str
    region: str
    region_local: str
    country: str
    country_local: str


class DestinationGeography(BaseModel):
    recognized: bool
    scope: Literal["city", "country"]
    city: str = ""
    city_local: str = ""
    city_korean: str = ""
    region: str = ""
    region_local: str = ""
    country: str = ""
    country_local: str = ""
    country_korean: str = ""


class JourneyBuildError(RuntimeError):
    """A safe internal marker for recommendation failures."""

    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


class RecommendationCountError(JourneyBuildError):
    """Raised when verified, deduplicated tracks do not meet the request."""

    def __init__(
        self,
        requested: int,
        actual: int,
        scopes_attempted: tuple[str, ...],
        rejection_summary: dict[str, int],
        rejected_candidates: tuple[str, ...],
        seen_track_ids: tuple[str, ...] = (),
        seen_track_keys: tuple[str, ...] = (),
    ) -> None:
        stage = (
            "genre_validation_failed"
            if actual == 0 and rejection_summary.get("genre_mismatch", 0) > 0
            else "no_verified_tracks"
            if actual == 0
            else "recommendation_count_shortfall"
        )
        super().__init__(stage)
        self.requested = requested
        self.actual = actual
        self.scopes_attempted = scopes_attempted
        self.rejection_summary = rejection_summary
        self.rejected_candidates = rejected_candidates
        self.seen_track_ids = seen_track_ids
        self.seen_track_keys = seen_track_keys


class RecommendationTimeoutError(JourneyBuildError):
    """Raised when the full recommendation deadline has elapsed."""

    def __init__(self, attempted_candidates: tuple[str, ...] = ()) -> None:
        super().__init__("recommendation_timeout")
        self.attempted_candidates = attempted_candidates


def recommendation_request_timeout(
    deadline: float | None,
    maximum: float,
) -> float:
    """Return a bounded request timeout or stop at the shared deadline."""
    if deadline is None:
        return maximum
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RecommendationTimeoutError()
    return max(0.1, min(maximum, remaining))


def ensure_recommendation_deadline(
    deadline: float | None,
    attempted_candidates: set[str] | None = None,
) -> None:
    """Stop synchronous work as soon as the recommendation deadline expires."""
    if deadline is not None and time.monotonic() >= deadline:
        raise RecommendationTimeoutError(
            tuple(sorted(attempted_candidates or ()))
        )


def build_journey_summary_message() -> str:
    """Build the short confirmation shown immediately before generation."""
    summary_lines = ["좋아요."]
    city = (
        st.session_state.get("destination_display_name")
        or st.session_state.get("city")
    )
    mood = st.session_state.get("mood")
    situation = st.session_state.get("situation")
    discovery_level = st.session_state.get("discovery_level")
    track_count = st.session_state.get("track_count")

    if city == "__lyra_custom_destination__":
        summary_lines.append("오늘의 목적지는 LYRA가 골라볼게요.")
    elif city and city != "상관없어요":
        summary_lines.append(f"{escape(str(city))}의 음악을 중심으로 찾아볼게요.")
    if mood:
        summary_lines.append(f"✨ 기분: {escape(str(mood))}")
    if situation:
        summary_lines.append(f"🍃 듣는 상황: {escape(str(situation))}")
    if discovery_level:
        summary_lines.append(f"🧭 탐험 수준: {escape(str(discovery_level))}")
    if track_count:
        summary_lines.append(f"🎵 추천 곡 수: {escape(str(track_count))}곡")

    return "<br>".join(summary_lines[:2]) + (
        f"<br><br>{'<br>'.join(summary_lines[2:])}"
        if len(summary_lines) > 2
        else ""
    )


def submit_chat_answer(
    question_key: str,
    raw_answer: str,
    direct_input: bool = False,
) -> None:
    """Persist one button or text answer and advance only to missing fields."""
    if st.session_state.get("current_question") != question_key:
        return
    direct_input_mode = bool(st.session_state.get("direct_input_mode"))
    direct_input_field = st.session_state.get("direct_input_field")
    if direct_input:
        if not direct_input_mode or direct_input_field != question_key:
            return
    elif direct_input_mode:
        return

    stripped = raw_answer.strip()
    if not stripped:
        return

    direct_track_count = (
        question_key == "track_count"
        and re.fullmatch(r"(?:10|[1-9])(?:\s*곡)?", stripped) is not None
    )
    resolved = (
        None
        if direct_input or direct_track_count
        else resolve_option(question_key, stripped)
    )
    if resolved and resolved[0] == "__direct__":
        if question_key not in DIRECT_INPUT_PLACEHOLDERS:
            return
        st.session_state["direct_input_mode"] = True
        st.session_state["direct_input_field"] = question_key
        st.session_state[direct_input_state_key(question_key)] = ""
        st.session_state["input_error"] = ""
        return

    if direct_input and question_key in PREFERENCE_STEPS:
        selected = (
            []
            if question_key == "favorite_artists"
            else get_preference_section(question_key)
        )
        if question_key != "favorite_artists" and len(selected) >= 3:
            st.session_state["input_error"] = (
                "최대 3개까지 선택할 수 있어요 😊"
            )
            return
        selected.append(stripped)
        set_preference_section(question_key, selected)
        append_chat_message("user", stripped)
        advance_chat_to(next_preference_question(question_key))
        return

    if direct_input and question_key in CUSTOM_DESTINATION_STEPS:
        if question_key == "korea_city":
            canonical_city = KOREA_CITY_DESTINATIONS.get(
                stripped,
                f"{stripped}, South Korea",
            ).split(",", 1)[0]
            st.session_state["city"] = canonical_city
            set_destination_identity(
                raw_input=stripped,
                canonical_name=canonical_city,
                display_name=stripped,
                country_name="South Korea",
                destination_type="city",
            )
            set_custom_destination_metadata(
                scope="city",
                display=canonical_city,
                country="South Korea",
                country_local="대한민국",
                raw_input=stripped,
                canonical_name=canonical_city,
                display_name=stripped,
                destination_type="city",
            )
        else:
            try:
                destination = resolve_destination_geography(stripped)
            except JourneyBuildError:
                st.session_state["input_error"] = (
                    "여행지를 정확히 확인하지 못했어요.\n"
                    "도시 또는 국가 이름을 다시 입력해주세요. 🌍"
                )
                return
            if destination["scope"] == "city":
                canonical_name = str(destination["city"])
                local_name = str(destination["city_local"])
                korean_name = str(destination.get("city_korean") or "")
            else:
                canonical_name = str(destination["country"])
                local_name = str(destination["country_local"])
                korean_name = str(destination.get("country_korean") or "")
            display_name = resolve_destination_display_name(
                canonical_name,
                korean_name,
                local_name,
            )
            country_name = str(destination["country"])
            st.session_state["city"] = canonical_name
            set_destination_identity(
                raw_input=stripped,
                canonical_name=canonical_name,
                display_name=display_name,
                country_name=country_name,
                destination_type=str(destination["scope"]),
            )
            set_custom_destination_metadata(
                scope=destination["scope"],
                display=canonical_name,
                country=country_name,
                country_local=resolve_destination_display_name(
                    country_name,
                    str(destination.get("country_korean") or ""),
                    str(destination["country_local"]),
                ),
                raw_input=stripped,
                canonical_name=canonical_name,
                display_name=display_name,
                destination_type=str(destination["scope"]),
            )
        append_chat_message("user", stripped)
        advance_chat_to(get_next_question())
        return

    if question_key == "journey_mode" and resolved:
        value, label = resolved
        st.session_state["journey_mode"] = value
        if value == "취향 반영":
            st.session_state["free_text_preferences"] = (
                "탐색 방향: 장르명 단순 일치보다 감정, 리듬, 악기, 공기감, "
                "시간대를 목적지의 음악 문화로 번역"
            )
        else:
            st.session_state["free_text_preferences"] = ""
        append_chat_message("user", label)
        next_question = (
            "favorite_genres"
            if value == "취향 반영"
            else get_next_question()
        )
        advance_chat_to(next_question)
        return

    if question_key == "custom_destination" and resolved:
        value, label = resolved
        append_chat_message("user", label)
        if value == "한국":
            advance_chat_to("korea_city")
            return
        if value == "__lyra__":
            st.session_state["city"] = "__lyra_custom_destination__"
            set_destination_identity(
                raw_input="",
                canonical_name="",
                display_name="",
                country_name="",
                destination_type="lyra",
            )
            set_custom_destination_metadata(
                scope="lyra",
                display="",
                country="",
                country_local="",
            )
            append_chat_message(
                "ai",
                "어디로 갈지 고민되시나요?<br>"
                "그럼 오늘의 목적지는 LYRA가 몰래 정해볼게요. 🎲✈️",
            )
            advance_chat_to(get_next_question())
            return
        country, country_local = CUSTOM_COUNTRY_DESTINATIONS[str(value)]
        display_name = resolve_destination_display_name(
            country,
            "",
            country_local,
        )
        st.session_state["city"] = country
        set_destination_identity(
            raw_input=str(value),
            canonical_name=country,
            display_name=display_name,
            country_name=country,
            destination_type="country",
        )
        set_custom_destination_metadata(
            scope="country",
            display=country,
            country=country,
            country_local=display_name,
            raw_input=str(value),
            canonical_name=country,
            display_name=display_name,
            destination_type="country",
        )
        advance_chat_to(get_next_question())
        return

    if question_key == "korea_city" and resolved:
        value, label = resolved
        append_chat_message("user", label)
        city = (
            choose_lyra_korea_city(
                str(st.session_state.get("free_text_preferences") or "")
            )
            if value == "__lyra__"
            else str(value)
        )
        st.session_state["city"] = city
        canonical_city = KOREA_CITY_DESTINATIONS[city].split(",", 1)[0]
        st.session_state["city"] = canonical_city
        set_destination_identity(
            raw_input=str(value),
            canonical_name=canonical_city,
            display_name=city,
            country_name="South Korea",
            destination_type="city",
        )
        set_custom_destination_metadata(
            scope="city",
            display=canonical_city,
            country="South Korea",
            country_local="대한민국",
            raw_input=str(value),
            canonical_name=canonical_city,
            display_name=city,
            destination_type="city",
        )
        advance_chat_to(get_next_question())
        return

    if (
        question_key == "favorite_artists"
        and resolved
        and resolved[0] == "__skip__"
    ):
        append_chat_message("user", "좋아하는 아티스트는 건너뛸게요.")
        advance_chat_to("favorite_reasons")
        return

    if direct_input and question_key == "city":
        try:
            destination = resolve_destination_geography(stripped)
        except JourneyBuildError:
            st.session_state["input_error"] = (
                "여행지를 정확히 확인하지 못했어요.\n"
                "도시 또는 국가 이름을 다시 입력해주세요. 🌍"
            )
            return
        canonical_name = str(
            destination["city"]
            if destination["scope"] == "city"
            else destination["country"]
        )
        local_name = str(
            destination["city_local"]
            if destination["scope"] == "city"
            else destination["country_local"]
        )
        korean_name = str(
            destination.get(
                "city_korean"
                if destination["scope"] == "city"
                else "country_korean"
            )
            or ""
        )
        display_name = resolve_destination_display_name(
            canonical_name,
            korean_name,
            local_name,
        )
        country_name = str(destination["country"])
        st.session_state["city"] = canonical_name
        set_destination_identity(
            raw_input=stripped,
            canonical_name=canonical_name,
            display_name=display_name,
            country_name=country_name,
            destination_type=str(destination["scope"]),
        )
        set_custom_destination_metadata(
            scope=destination["scope"],
            display=canonical_name,
            country=country_name,
            country_local=resolve_destination_display_name(
                country_name,
                str(destination.get("country_korean") or ""),
                str(destination["country_local"]),
            ),
            raw_input=stripped,
            canonical_name=canonical_name,
            display_name=display_name,
            destination_type=str(destination["scope"]),
        )
        append_chat_message("user", stripped)
        advance_chat_to(get_next_question())
        return

    extracted = extract_chat_conditions(stripped)
    for field, value in extracted.items():
        if field in CHAT_FIELDS and not st.session_state.get(field):
            st.session_state[field] = value

    display_answer = stripped
    if resolved:
        value, label = resolved
        st.session_state[question_key] = value
        display_answer = label
    elif question_key == "track_count":
        number_match = re.search(r"\d+", stripped)
        track_count = int(number_match.group()) if number_match else 0
        if not 1 <= track_count <= 10:
            st.session_state["input_error"] = "1곡부터 10곡 사이로 입력해주세요."
            return
        st.session_state["track_count"] = track_count
    elif not st.session_state.get(question_key):
        st.session_state[question_key] = stripped

    extracted_preferences = extracted.get("free_text_preferences")
    if extracted_preferences:
        st.session_state["free_text_preferences"] = extracted_preferences
    elif not resolved and len(stripped.split()) >= 2:
        st.session_state["free_text_preferences"] = stripped

    append_chat_message("user", display_answer)
    next_question = get_next_question()
    st.session_state["current_question"] = next_question
    st.session_state["conversation_step"] = next_question
    st.session_state["direct_input_mode"] = False
    st.session_state["direct_input_field"] = None
    st.session_state["input_error"] = ""
    st.session_state["should_scroll_conversation"] = True
    if next_question == "complete":
        append_chat_message("ai", build_journey_summary_message())
    else:
        append_chat_message("ai", QUESTION_CONFIG[next_question]["question"])


def submit_chat_input() -> None:
    """Submit the active Input Dock value once."""
    question_key = st.session_state.get("direct_input_field")
    if question_key not in DIRECT_INPUT_PLACEHOLDERS:
        return
    input_key = direct_input_state_key(question_key)
    raw_answer = st.session_state.get(input_key, "")
    if (
        raw_answer.strip()
        and st.session_state.get("direct_input_mode")
        and question_key == st.session_state.get("current_question")
        and question_key in DIRECT_INPUT_PLACEHOLDERS
    ):
        submit_chat_answer(question_key, raw_answer, direct_input=True)
        if not st.session_state.get("direct_input_mode"):
            st.session_state[input_key] = ""


def reset_conversation() -> None:
    """Clear the journey without disturbing unrelated Streamlit state."""
    for key in (
        *CHAT_FIELDS,
        "free_text_preferences",
        "chat_history",
        "current_question",
        "chat_input",
        *DIRECT_INPUT_STATE_KEYS.values(),
        "input_error",
        "direct_input_mode",
        "direct_input_field",
        "music_journey_result",
        "music_journey_error",
        "music_journey_signature",
        "music_journey_generation_signature",
        "passport_thumbnail_base64",
        "passport_thumbnail_signature",
        "passport_thumbnail_error",
        "generation_stage",
        "recovery_context",
        "recovery_choice",
        "recovery_excluded_candidates",
        "recovery_message_added",
        "destination_raw_input",
        "destination_canonical_name",
        "destination_display_name",
        "destination_country_name",
        "destination_type",
    ):
        st.session_state.pop(key, None)
    for field in CHAT_FIELDS:
        st.session_state[field] = None
    st.session_state["free_text_preferences"] = ""
    st.session_state["chat_history"] = [
        {
            "role": "ai",
            "content": QUESTION_CONFIG["journey_mode"]["question"],
        }
    ]
    st.session_state["current_question"] = "journey_mode"
    st.session_state["conversation_step"] = "journey_mode"
    st.session_state["input_error"] = ""
    st.session_state["direct_input_mode"] = False
    st.session_state["direct_input_field"] = None
    st.session_state["passport_thumbnail_base64"] = ""
    st.session_state["passport_thumbnail_signature"] = None
    st.session_state["passport_thumbnail_error"] = ""
    st.session_state["generation_stage"] = None
    st.session_state["should_scroll_conversation"] = True


def enter_chat() -> None:
    """Move from the intro screen to the existing chat experience."""
    st.session_state["active_screen"] = "chat"


def open_result() -> None:
    """Open the result detail screen without changing the selected journey."""
    st.session_state["active_screen"] = "result"


def return_to_chat() -> None:
    """Return to the completed chat while preserving all selections."""
    st.session_state["active_screen"] = "chat"
    if (
        "music_journey_result" in st.session_state
        and st.session_state.get("music_journey_signature")
        == current_journey_signature()
    ):
        st.session_state["conversation_step"] = "complete"
        st.session_state["current_question"] = "complete"
    st.session_state["should_scroll_conversation"] = True


def restart_from_result() -> None:
    """Restart the conversation from the result screen without showing Intro."""
    reset_conversation()
    st.session_state["active_screen"] = "chat"


def get_city_name(city: str) -> str:
    """Return the normalized city name used by image and result metadata."""
    if "rio" in city.casefold():
        return "리우"
    return next((name for name in CITY_CODES if name in city), "default")


def get_city_image(city: str) -> str | None:
    """Return a local WebP as a data URI, or None for the CSS fallback."""
    city_name = get_city_name(city)
    relative_path = CITY_IMAGES.get(city_name, CITY_IMAGES["default"])
    image_path = Path(__file__).resolve().parent / relative_path

    if not image_path.is_file() and city_name == "default":
        image_path = Path(__file__).resolve().parent / CITY_IMAGES["default"]
    if not image_path.is_file():
        return None

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def get_airplane_window_image() -> str:
    """Return the shared airplane-window WebP as a data URI."""
    image_path = Path(__file__).resolve().parent / AIRPLANE_WINDOW_IMAGE
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def get_intro_window_scene_image(relative_path: str) -> str:
    """Return one Intro window scene WebP as a data URI."""
    image_path = Path(__file__).resolve().parent / relative_path
    if not image_path.is_file():
        raise FileNotFoundError(f"Intro window scene not found: {relative_path}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def get_lyra_image_data_uri() -> str:
    """Return the LYRA WebP data URI shared by Intro and Chat."""
    image_path = Path(__file__).resolve().parent / LYRA_IMAGE
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def resolve_result_qr_url(result: dict, destination: str | None) -> str | None:
    """Resolve the best available Spotify destination for the Result QR."""
    playlist_url = str(result.get("spotify_playlist_url") or "").strip()
    if playlist_url.startswith("https://open.spotify.com/"):
        return playlist_url
    tracks = result.get("tracks") or []
    if tracks and isinstance(tracks[0], dict):
        track_url = str(tracks[0].get("spotify_url") or "").strip()
        if track_url.startswith("https://open.spotify.com/"):
            return track_url
    safe_destination = str(destination or "").strip()
    if safe_destination:
        return (
            "https://open.spotify.com/search/"
            f"{quote(f'{safe_destination} music', safe='')}"
        )
    return None


def make_qr_data_uri(url: str) -> str:
    """Generate a readable Spotify QR image as an in-memory PNG data URI."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(
        fill_color="#EAF0FF",
        back_color="#13264C",
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_city_image_markup(
    city: str,
    variant: str,
    inner_markup: str = "",
) -> str:
    """Build the shared city-image area with a CSS fallback class."""
    city_name = get_city_name(city)
    generated_image_uri = st.session_state.get("passport_thumbnail_base64", "")
    has_generated_image = (
        isinstance(generated_image_uri, str)
        and generated_image_uri.startswith("data:image/")
    )
    image_uri = generated_image_uri if has_generated_image else get_city_image(city)
    image_style = (
        f' style="background-image: url(&quot;{escape(image_uri, quote=True)}&quot;);"'
        if image_uri
        else ""
    )
    generated_class = " city-image--generated" if has_generated_image else ""
    label = escape(city)
    return (
        f'<div class="city-image city-image--{variant} city-image--{city_name}'
        f'{generated_class}"'
        f'{image_style} role="img" aria-label="{label}의 도시 분위기">'
        '<span class="city-image-haze" aria-hidden="true"></span>'
        f"{inner_markup}"
        "</div>"
    )


def get_atmosphere_scene(
    mood: str | None,
    situation: str | None,
    city: str | None,
    step: str,
) -> dict:
    """Derive a lightweight window atmosphere from the current Journey."""
    scene = {
        "scene_class": "scene-departure",
        "primary": "#102650",
        "secondary": "#665083",
        "accent": "#e7aebd",
        "cloud_opacity": 0.32,
        "star_opacity": 0.46,
        "glow_opacity": 0.28,
        "cloud_duration": 38,
        "show_moon": True,
        "show_rain": False,
        "show_mist": False,
        "show_shooting_star": True,
    }

    mood_value = mood or ""
    if "설레는" in mood_value:
        scene.update(
            scene_class="scene-excited",
            primary="#253465",
            secondary="#80618e",
            accent="#f0b4c0",
            cloud_opacity=0.34,
            star_opacity=0.3,
            glow_opacity=0.36,
            cloud_duration=34,
        )
    elif "차분한" in mood_value:
        scene.update(
            scene_class="scene-calm",
            primary="#0c254d",
            secondary="#344f78",
            accent="#b7c9e8",
            cloud_opacity=0.28,
            star_opacity=0.52,
            glow_opacity=0.2,
            cloud_duration=44,
            show_shooting_star=True,
        )
    elif "신나는" in mood_value:
        scene.update(
            scene_class="scene-energetic",
            primary="#1b3066",
            secondary="#634781",
            accent="#cf72b0",
            cloud_opacity=0.3,
            star_opacity=0.28,
            glow_opacity=0.4,
            cloud_duration=28,
        )
    elif "우울한" in mood_value:
        scene.update(
            scene_class="scene-melancholic",
            primary="#26384f",
            secondary="#566575",
            accent="#9eb1c2",
            cloud_opacity=0.4,
            star_opacity=0.04,
            glow_opacity=0.18,
            cloud_duration=45,
            show_moon=False,
            show_rain=True,
            show_mist=True,
            show_shooting_star=False,
        )

    situation_value = situation or ""
    if "카페" in situation_value:
        scene.update(
            accent="#e3b783",
            glow_opacity=max(scene["glow_opacity"], 0.4),
            cloud_duration=45,
            show_mist=True,
        )
    elif "출퇴근" in situation_value:
        scene.update(
            accent="#e6bb8c",
            glow_opacity=max(scene["glow_opacity"], 0.34),
            cloud_duration=max(24, scene["cloud_duration"] - 6),
        )
    elif "집중" in situation_value:
        scene.update(
            primary="#0b1d3e",
            cloud_opacity=min(scene["cloud_opacity"], 0.2),
            star_opacity=min(scene["star_opacity"], 0.16),
            glow_opacity=min(scene["glow_opacity"], 0.2),
            cloud_duration=45,
            show_shooting_star=False,
        )
    elif "밤 산책" in situation_value:
        scene.update(
            star_opacity=max(scene["star_opacity"], 0.58),
            cloud_duration=max(scene["cloud_duration"], 38),
            show_moon=True,
            show_shooting_star="우울한" not in mood_value,
        )

    city_value = city or ""
    if "서울" in city_value:
        scene.update(secondary="#304c78", accent="#89aee5")
    elif "런던" in city_value:
        scene.update(
            secondary="#596573",
            accent="#d5a66c",
            show_mist=True,
            show_rain=True,
        )
    elif "파리" in city_value:
        scene.update(secondary="#b68491", accent="#edbdad")
    elif "도쿄" in city_value:
        scene.update(
            secondary="#4a4f89",
            accent="#c875ad",
            show_rain=True,
        )
    elif "마라케시" in city_value:
        scene.update(
            primary="#6e493e",
            secondary="#b66d49",
            accent="#e7b66b",
            star_opacity=min(scene["star_opacity"], 0.22),
        )

    if step == "intro":
        scene["scene_class"] = "scene-departure"
    return scene


def render_airplane_window_image(variant: str, aria_label: str) -> str:
    """Return the shared full-bleed left-visual background."""
    image_uri = get_airplane_window_image()
    return (
        f'<div class="journey-visual-background journey-visual-background--{variant}" '
        f'style="background-image:url(&quot;{image_uri}&quot;)" role="img" '
        f'aria-label="{escape(aria_label, quote=True)}">'
        '<span class="journey-visual-overlay" aria-hidden="true"></span>'
        "</div>"
    )


def get_required_secret(name: str, missing_stage: str) -> str:
    """Read one required secret without exposing its value."""
    try:
        value = st.secrets[name]
    except Exception as exc:
        logger.error(
            "[API] required secret missing stage=%s secret_name=%s",
            missing_stage,
            name,
        )
        raise JourneyBuildError(missing_stage) from exc
    if not isinstance(value, str) or not value.strip():
        logger.error(
            "[API] required secret missing stage=%s secret_name=%s",
            missing_stage,
            name,
        )
        raise JourneyBuildError(missing_stage)
    return value.strip()


@st.cache_data(show_spinner=False)
def resolve_destination_geography(value: str) -> dict[str, object]:
    """Resolve a free-text destination as exactly one city or country."""
    normalized_value = " ".join(str(value).split())
    if not normalized_value:
        raise JourneyBuildError("destination_resolution_failed")

    api_key = get_required_secret("OPENAI_API_KEY", "openai_api_key")
    try:
        client = OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Resolve one user-entered travel destination as either "
                        "a real city or a sovereign country. Set scope=city only "
                        "for a real city and include its standard English city "
                        "name, locally used city name, useful encompassing "
                        "region, sovereign country in English, and locally used "
                        "country name. Also return the standard Korean UI names "
                        "in city_korean and country_korean. Set scope=country "
                        "only for a sovereign "
                        "country; leave all city and region fields empty. Never "
                        "store a city name in country. Accept names written in "
                        "Korean, Japanese, Cyrillic, Latin, or other scripts. "
                        "Set recognized=false when the place is ambiguous or "
                        "unknown and do not guess."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Destination: {normalized_value}",
                },
            ],
            text_format=DestinationGeography,
        )
        destination = response.output_parsed
    except JourneyBuildError:
        raise
    except Exception as exc:
        logger.exception(
            "[OPENAI] destination resolution failed value=%s",
            normalized_value,
        )
        raise JourneyBuildError("destination_resolution_failed") from exc

    if (
        destination is None
        or not destination.recognized
        or not destination.country.strip()
        or not destination.country_local.strip()
        or (
            destination.scope == "city"
            and (
                not destination.city.strip()
                or not destination.city_local.strip()
                or not destination.region.strip()
                or not destination.region_local.strip()
            )
        )
        or (
            destination.scope == "country"
            and any(
                value.strip()
                for value in (
                    destination.city,
                    destination.city_local,
                    destination.city_korean,
                    destination.region,
                    destination.region_local,
                )
            )
        )
    ):
        raise JourneyBuildError("destination_resolution_failed")
    return destination.model_dump()


@st.cache_data(show_spinner=False)
def resolve_city_geography(
    city: str,
    deadline: float | None = None,
) -> dict[str, str]:
    """Resolve any user-entered city to one city-region-country hierarchy."""
    normalized_city = " ".join(str(city).split())
    if not normalized_city:
        raise JourneyBuildError("geography_resolution_failed")

    api_key = get_required_secret("OPENAI_API_KEY", "openai_api_key")
    try:
        client = OpenAI(
            api_key=api_key,
            timeout=recommendation_request_timeout(deadline, 30.0),
            max_retries=0 if deadline is not None else 1,
        )
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You resolve world city geography for music discovery. "
                        "Return exactly one factual hierarchy for the requested "
                        "city. region must be the most useful encompassing "
                        "administrative or widely recognized cultural region "
                        "between the city and country. country must be the "
                        "sovereign country containing the city. Use commonly "
                        "recognized English names in city, region and country, "
                        "and locally used names in city_local, region_local and "
                        "country_local, preserving the local writing system. "
                        "Do not cross a national border when choosing the "
                        "region. Do not add commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Resolve this city: {normalized_city}",
                },
            ],
            text_format=CityGeography,
        )
        geography = response.output_parsed
    except ValidationError as exc:
        logger.exception(
            "[OPENAI] geography resolution failed "
            "stage=geography_output_parsed city=%s",
            normalized_city,
        )
        raise JourneyBuildError("geography_output_parsed") from exc
    except JourneyBuildError:
        raise
    except Exception as exc:
        ensure_recommendation_deadline(deadline)
        logger.exception(
            "[OPENAI] geography resolution failed "
            "stage=geography_resolution city=%s",
            normalized_city,
        )
        raise JourneyBuildError("geography_resolution_failed") from exc

    if geography is None or any(
        not str(getattr(geography, field, "")).strip()
        for field in CityGeography.model_fields
    ):
        logger.error(
            "[OPENAI] geography resolution failed "
            "stage=geography_output_parsed city=%s reason=incomplete",
            normalized_city,
        )
        raise JourneyBuildError("geography_output_parsed")

    logger.info(
        "[OPENAI] geography resolved city=%s region=%s country=%s",
        geography.city,
        geography.region,
        geography.country,
    )
    return geography.model_dump()


@st.cache_data(ttl=3300, show_spinner=False)
def get_spotify_access_token() -> str:
    """Get and briefly cache a Spotify Client Credentials access token."""
    client_id = get_required_secret(
        "SPOTIFY_CLIENT_ID",
        "spotify_token_failed",
    )
    client_secret = get_required_secret(
        "SPOTIFY_CLIENT_SECRET",
        "spotify_token_failed",
    )
    logger.info("[SPOTIFY] credentials loaded")
    try:
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=10.0,
        )
        logger.info(
            "[SPOTIFY] token request status=%s",
            response.status_code,
        )
        try:
            response_payload = response.json()
        except ValueError as exc:
            logger.error(
                "[SPOTIFY] token request failed status=%s error=invalid_json",
                response.status_code,
            )
            raise JourneyBuildError("spotify_token_failed") from exc
        if not response.ok:
            logger.error(
                "[SPOTIFY] token request failed status=%s error=%s",
                response.status_code,
                (
                    response_payload.get("error", "unknown")
                    if isinstance(response_payload, dict)
                    else "invalid_response"
                ),
            )
            raise JourneyBuildError("spotify_token_failed")
        access_token = (
            response_payload.get("access_token")
            if isinstance(response_payload, dict)
            else None
        )
    except JourneyBuildError:
        raise
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.exception("[SPOTIFY] token request failed")
        raise JourneyBuildError("spotify_token_failed") from exc
    if not isinstance(access_token, str) or not access_token:
        logger.error("[SPOTIFY] token request failed reason=missing_token")
        raise JourneyBuildError("spotify_token_failed")
    logger.info("[SPOTIFY] token acquired")
    return access_token


def normalize_spotify_name(value: str) -> str:
    """Normalize a track or artist name for conservative match scoring."""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = re.sub(r"\([^)]*(remaster|live|version|edit)[^)]*\)", "", normalized)
    return "".join(character for character in normalized if character.isalnum())


def normalize_country_key(value: str) -> str:
    """Normalize common country aliases used by generated candidates."""
    normalized = normalize_spotify_name(value)
    return {
        "uk": "unitedkingdom",
        "britain": "unitedkingdom",
        "greatbritain": "unitedkingdom",
    }.get(normalized, normalized)


def match_score(expected: str, actual: str) -> float:
    """Return a Unicode-aware similarity score for Spotify result ranking."""
    expected_name = normalize_spotify_name(expected)
    actual_name = normalize_spotify_name(actual)
    if not expected_name or not actual_name:
        return 0.0
    if expected_name == actual_name:
        return 1.0
    return SequenceMatcher(None, expected_name, actual_name).ratio()


def spotify_name_match_score(
    expected: str,
    actual: str,
    aliases: dict[str, tuple[str, ...]],
) -> float:
    """Score official localized/romanized Spotify names without weakening identity."""
    variants = (expected, *aliases.get(expected.strip(), ()))
    return max(match_score(variant, actual) for variant in variants)


def refresh_spotify_access_token() -> str:
    """Invalidate the cached credential and refresh it exactly once per 401 retry."""
    global _SPOTIFY_REFRESHED_ACCESS_TOKEN
    get_spotify_access_token.clear()
    try:
        _SPOTIFY_REFRESHED_ACCESS_TOKEN = get_spotify_access_token()
    except JourneyBuildError as exc:
        raise JourneyBuildError("spotify_auth_failed") from exc
    logger.info("[SPOTIFY] access token refreshed after 401")
    return _SPOTIFY_REFRESHED_ACCESS_TOKEN


def effective_spotify_access_token(access_token: str) -> str:
    """Prefer a token refreshed earlier in the current process."""
    return _SPOTIFY_REFRESHED_ACCESS_TOKEN or access_token


def search_spotify_track(
    track_name: str,
    artist_name: str,
    access_token: str,
    deadline: float | None = None,
    relaxed_match: bool = False,
    light_match: bool = False,
) -> dict | None:
    """Search Spotify and return only a sufficiently close track match."""
    search_queries = [
        (
            "strict",
            {
                "q": f'track:"{track_name}" artist:"{artist_name}"',
                "type": "track",
                "market": "KR",
                "limit": 5,
            },
        ),
        (
            "relaxed",
            {
                "q": f"{track_name} {artist_name}",
                "type": "track",
                "market": "KR",
                "limit": 10,
            },
        ),
    ]
    track_aliases = SPOTIFY_TRACK_NAME_ALIASES.get(track_name.strip(), ())
    artist_aliases = SPOTIFY_ARTIST_NAME_ALIASES.get(artist_name.strip(), ())
    if track_aliases or artist_aliases:
        search_queries.append(
            (
                "localized_alias",
                {
                    "q": (
                        f"{track_aliases[0] if track_aliases else track_name} "
                        f"{artist_aliases[0] if artist_aliases else artist_name}"
                    ),
                    "type": "track",
                    "market": "KR",
                    "limit": 10,
                },
            )
        )
    accepted_item: dict | None = None

    for query_mode, params in search_queries:
        ensure_recommendation_deadline(deadline)
        logger.info(
            "[SPOTIFY] search started artist=%s track=%s mode=%s",
            artist_name,
            track_name,
            query_mode,
        )
        try:
            for auth_attempt in range(2):
                response = requests.get(
                    "https://api.spotify.com/v1/search",
                    headers={
                        "Authorization": (
                            f"Bearer {effective_spotify_access_token(access_token)}"
                        )
                    },
                    params=params,
                    timeout=recommendation_request_timeout(deadline, 10.0),
                )
                if response.status_code != 401 or auth_attempt == 1:
                    break
                refresh_spotify_access_token()
            logger.info(
                "[SPOTIFY] search status=%s artist=%s track=%s mode=%s",
                response.status_code,
                artist_name,
                track_name,
                query_mode,
            )
            if not response.ok:
                logger.error(
                    "[SPOTIFY] search failed status=%s artist=%s track=%s",
                    response.status_code,
                    artist_name,
                    track_name,
                )
                if response.status_code in (401, 403):
                    raise JourneyBuildError("spotify_auth_failed")
                if response.status_code == 429:
                    raise JourneyBuildError("spotify_rate_limited")
                if response.status_code >= 500:
                    raise JourneyBuildError("spotify_service_unavailable")
                raise JourneyBuildError("spotify_search_failed")
            items = response.json().get("tracks", {}).get("items", [])
            logger.info(
                "[SPOTIFY] result count=%s artist=%s track=%s mode=%s",
                len(items),
                artist_name,
                track_name,
                query_mode,
            )
        except JourneyBuildError:
            raise
        except requests.Timeout as exc:
            ensure_recommendation_deadline(deadline)
            logger.exception(
                "[SPOTIFY] timeout artist=%s track=%s",
                artist_name,
                track_name,
            )
            raise JourneyBuildError("spotify_timeout") from exc
        except requests.RequestException as exc:
            ensure_recommendation_deadline(deadline)
            logger.exception(
                "[SPOTIFY] network failed artist=%s track=%s",
                artist_name,
                track_name,
            )
            raise JourneyBuildError("spotify_network_failed") from exc
        except (ValueError, AttributeError, TypeError) as exc:
            logger.exception(
                "[SPOTIFY] response invalid artist=%s track=%s",
                artist_name,
                track_name,
            )
            raise JourneyBuildError("spotify_response_invalid") from exc

        ranked_matches: list[tuple[float, dict]] = []
        for item in items:
            actual_artists = [
                artist.get("name", "")
                for artist in item.get("artists", [])
                if artist.get("name")
            ]
            track_score = spotify_name_match_score(
                track_name,
                item.get("name", ""),
                SPOTIFY_TRACK_NAME_ALIASES,
            )
            artist_score = max(
                (
                    spotify_name_match_score(
                        artist_name,
                        actual_artist,
                        SPOTIFY_ARTIST_NAME_ALIASES,
                    )
                    for actual_artist in actual_artists
                ),
                default=0.0,
            )
            if relaxed_match:
                track_match_min = 0.64
                artist_match_min = 0.68
            elif light_match:
                track_match_min = NORMAL_FALLBACK_TRACK_MATCH_MIN
                artist_match_min = NORMAL_FALLBACK_ARTIST_MATCH_MIN
            else:
                track_match_min = SPOTIFY_TRACK_MATCH_MIN
                artist_match_min = SPOTIFY_ARTIST_MATCH_MIN
            if (
                track_score < track_match_min
                or artist_score < artist_match_min
            ):
                logger.warning(
                    "[SPOTIFY] candidate rejected track=%s artist=%s "
                    "actual_track=%s actual_artists=%s track_score=%.2f "
                    "artist_score=%.2f query_mode=%s",
                    track_name,
                    artist_name,
                    item.get("name", ""),
                    ", ".join(actual_artists),
                    track_score,
                    artist_score,
                    query_mode,
                )
                continue
            spotify_url = item.get("external_urls", {}).get("spotify", "")
            if (
                not item.get("id")
                or not item.get("name")
                or not actual_artists
                or not spotify_url.startswith("https://open.spotify.com/")
            ):
                logger.warning(
                    "[SPOTIFY] candidate rejected track=%s artist=%s "
                    "reason=incomplete_spotify_metadata query_mode=%s",
                    track_name,
                    artist_name,
                    query_mode,
                )
                continue
            ranked_matches.append((track_score + artist_score, item))

        if ranked_matches:
            accepted_item = max(ranked_matches, key=lambda match: match[0])[1]
            break

    if accepted_item is None:
        logger.warning(
            "[SPOTIFY] no match artist=%s track=%s",
            artist_name,
            track_name,
        )
        return None

    item = accepted_item
    images = item.get("album", {}).get("images", [])
    return {
        "spotify_id": item.get("id", ""),
        "name": item.get("name", ""),
        "artists": [
            artist.get("name", "")
            for artist in item.get("artists", [])
            if artist.get("name")
        ],
        "artist_ids": [
            artist.get("id", "")
            for artist in item.get("artists", [])
            if artist.get("id")
        ],
        "album_id": item.get("album", {}).get("id", ""),
        "album_name": item.get("album", {}).get("name", ""),
        "album_image_url": images[0].get("url", "") if images else "",
        "spotify_url": item.get("external_urls", {}).get("spotify", ""),
        "spotify_uri": item.get("uri", ""),
        "isrc": item.get("external_ids", {}).get("isrc", ""),
        "duration_ms": item.get("duration_ms", 0),
    }


def get_spotify_artist_genres(
    artist_ids: list[str],
    access_token: str,
    deadline: float | None = None,
) -> list[str]:
    """Fetch uncached artist genres in one request, refreshing once after 401."""
    unique_ids = list(dict.fromkeys(artist_id for artist_id in artist_ids if artist_id))
    if not unique_ids:
        return []
    uncached_ids = [
        artist_id
        for artist_id in unique_ids
        if artist_id not in _SPOTIFY_ARTIST_GENRE_CACHE
    ]
    if not uncached_ids:
        return list(
            dict.fromkeys(
                genre
                for artist_id in unique_ids
                for genre in _SPOTIFY_ARTIST_GENRE_CACHE[artist_id]
            )
        )
    ensure_recommendation_deadline(deadline)
    try:
        for auth_attempt in range(2):
            response = requests.get(
                "https://api.spotify.com/v1/artists",
                headers={
                    "Authorization": (
                        f"Bearer {effective_spotify_access_token(access_token)}"
                    )
                },
                params={"ids": ",".join(uncached_ids[:50])},
                timeout=recommendation_request_timeout(deadline, 10.0),
            )
            if response.status_code != 401 or auth_attempt == 1:
                break
            refresh_spotify_access_token()
        if not response.ok:
            if response.status_code in (401, 403):
                raise JourneyBuildError("spotify_auth_failed")
            if response.status_code == 429:
                raise JourneyBuildError("spotify_rate_limited")
            if response.status_code >= 500:
                raise JourneyBuildError("spotify_service_unavailable")
            raise JourneyBuildError("spotify_search_failed")
        artists = response.json().get("artists", [])
        for requested_id, artist in zip(uncached_ids, artists):
            genres = (
                tuple(
                    genre
                    for genre in artist.get("genres", [])
                    if isinstance(genre, str) and genre
                )
                if isinstance(artist, dict)
                else ()
            )
            _SPOTIFY_ARTIST_GENRE_CACHE[requested_id] = genres
        for missing_id in uncached_ids[len(artists):]:
            _SPOTIFY_ARTIST_GENRE_CACHE[missing_id] = ()
        return list(
            dict.fromkeys(
                genre
                for artist_id in unique_ids
                for genre in _SPOTIFY_ARTIST_GENRE_CACHE.get(artist_id, ())
            )
        )
    except JourneyBuildError:
        raise
    except requests.Timeout as exc:
        ensure_recommendation_deadline(deadline)
        raise JourneyBuildError("spotify_timeout") from exc
    except requests.RequestException as exc:
        ensure_recommendation_deadline(deadline)
        raise JourneyBuildError("spotify_network_failed") from exc
    except (ValueError, AttributeError, TypeError) as exc:
        raise JourneyBuildError("spotify_response_invalid") from exc


def find_lisbon_single_track_fallback(
    access_token: str,
    dedupe_state: dict[str, set[str]],
    deadline: float | None,
) -> dict | None:
    """Return one verified Portuguese standard after Lisbon searches are empty."""
    fallback_candidates = (
        ("Uma Casa Portuguesa", "Amália Rodrigues"),
        ("Ó Gente Da Minha Terra", "Mariza"),
        ("Lisboa Menina e Moça", "Carlos do Carmo"),
        ("O Pastor", "Madredeus"),
    )
    for track_name, artist_name in fallback_candidates:
        candidate_label = f"{track_name} — {artist_name}"
        candidate_key = (
            f"{normalize_spotify_name(track_name)}::"
            f"{normalize_spotify_name(artist_name)}"
        )
        if (
            candidate_label in dedupe_state["candidate_labels"]
            or candidate_key in dedupe_state["candidate_keys"]
            or normalize_spotify_name(artist_name)
            in dedupe_state["artist_keys"]
        ):
            continue
        dedupe_state["candidate_labels"].add(candidate_label)
        dedupe_state["candidate_keys"].add(candidate_key)
        spotify_track = search_spotify_track(
            track_name,
            artist_name,
            access_token,
            deadline=deadline,
        )
        if not spotify_track:
            continue
        track_id = str(spotify_track.get("spotify_id") or "")
        track_version_key = canonical_track_version_key(
            str(spotify_track.get("name") or ""),
            list(spotify_track.get("artists") or []),
        )
        if (
            not track_id
            or track_id in dedupe_state["track_ids"]
            or track_version_key in dedupe_state["track_versions"]
        ):
            continue
        spotify_track.update(
            {
                "connection_level": "country",
                "city_connection": (
                    "국가 연결: 포르투갈 출신 아티스트의 대표적인 음악"
                ),
                "recommendation_reason": (
                    "리스본에서 시작해 포르투갈의 대표 음악까지 넓혀 "
                    "확인한 곡이에요."
                ),
                "is_placeholder": False,
            }
        )
        dedupe_state["track_ids"].add(track_id)
        dedupe_state["track_versions"].add(track_version_key)
        dedupe_state["artist_keys"].update(
            normalize_spotify_name(artist)
            for artist in spotify_track.get("artists", [])
        )
        return spotify_track
    return None


def generate_track_candidates(
    mood: str,
    situation: str,
    city: str,
    tempo: str,
    vocal: str,
    discovery_level: str,
    track_count: int,
    free_text_preferences: str,
    connection_level: Literal["city", "region", "country"] = "city",
    geography: CityGeography | None = None,
    attempt: int = 1,
    excluded_candidates: tuple[str, ...] = (),
    excluded_artists: tuple[str, ...] = (),
    excluded_albums: tuple[str, ...] = (),
    retry_strategy: str = "",
    retry_max_attempts: int = MAX_SCOPE_ATTEMPTS,
    deadline: float | None = None,
    rejection_summary: dict[str, int] | None = None,
) -> JourneyCandidates:
    """Generate candidates for exactly one geographic connection level."""
    api_key = get_required_secret("OPENAI_API_KEY", "openai_api_key")
    selected_genres = selected_genres_from_preferences(free_text_preferences)
    explicit_genre_guard = explicit_genre_prompt_rule(selected_genres)
    candidate_limit = (
        max(track_count * 6, 12)
        if retry_strategy
        else max(track_count * 4, 10)
    )
    city_is_required = geography is not None
    if geography:
        city_target = f"{geography.city_local} ({geography.city})"
        region_target = f"{geography.region_local} ({geography.region})"
        country_target = f"{geography.country_local} ({geography.country})"
        scope_instructions = {
            "city": (
                f"{city_target}에서 태어나거나 성장한 아티스트, 그 도시에서 "
                "결성된 그룹, 그 도시를 주요 활동 거점으로 삼은 아티스트, "
                "그 도시의 레이블·크루·음악 공동체와 공식적으로 연결된 "
                "아티스트, 또는 도시를 직접 다루는 곡만 허용"
            ),
            "region": (
                f"{region_target}에서 태어나거나 성장한 아티스트, 그 지역에서 "
                "결성되거나 활동한 그룹, 지역 음악 신과 공식적으로 연결된 "
                "아티스트, 또는 지역을 직접 다루는 곡만 허용. "
                f"{city_target}와의 직접 관계는 요구하지 않음"
            ),
            "country": (
                f"{country_target}의 아티스트·그룹, 그 국가를 주요 활동 "
                "거점으로 삼은 아티스트, 국가 음악 신과 공식적으로 연결된 "
                "아티스트, 또는 국가를 직접 다루는 곡만 허용. 도시나 "
                "지역과의 직접 관계는 요구하지 않음"
            ),
        }
        geographic_guard = (
            f"모든 후보는 반드시 {country_target} 안의 연결만 가져야 하며, "
            "다른 국가의 후보는 절대 포함하지 마세요. "
        )
    else:
        scope_instructions = {
            "city": "도시를 한정하지 않은 세계 음악 후보",
            "region": "사용하지 않음",
            "country": "사용하지 않음",
        }
        geographic_guard = ""

    exclusion_lines = []
    if excluded_candidates:
        exclusion_lines.append(
            "이미 확인한 곡(다시 제안 금지): "
            + ", ".join(excluded_candidates[-40:])
        )
    if excluded_artists:
        exclusion_lines.append(
            "이미 채택한 아티스트(다시 제안 금지): "
            + ", ".join(excluded_artists[-20:])
        )
    if excluded_albums:
        exclusion_lines.append(
            "이미 채택한 앨범(다시 제안 금지): "
            + ", ".join(excluded_albums[-20:])
        )
    exclusions = "\n".join(exclusion_lines) or "제외 목록 없음"
    retry_guidance = ""
    if retry_strategy.startswith("일반 검색 보완"):
        retry_guidance = (
            "일반 검색의 1회 보완 단계입니다. 여행지 연결과 Spotify 실재 "
            "가능성은 필수로 유지하되, 장르·기분·상황·템포·탐색 수준은 "
            "탈락 조건이 아니라 적합도 순위를 정하는 참고 기준으로만 "
            "사용하세요. 가까운 장르와 비슷한 분위기의 로컬 후보도 "
            "포함하세요.\n"
        )
    elif retry_strategy.startswith("내부 보장 검색"):
        retry_guidance = (
            "일반 검색 내부의 보장 단계입니다. 여행지의 국가와 필요한 곡 "
            "수, Spotify 실재 여부를 필수로 유지하세요. 장르·아티스트 "
            "유사도·기분·상황·BPM·보컬·탐색 수준은 참고 기준으로만 "
            "사용하고, 이전에 거절된 곡과 다른 실제 후보를 제안하세요. "
            "가능하면 서로 다른 아티스트를 우선하되, 곡 수가 부족하면 "
            "같은 아티스트의 서로 다른 곡도 허용하세요.\n"
        )
    elif retry_strategy:
        retry_guidance = (
            "LYRA 자동 재검색에서는 여행지의 국가와 필요한 곡 수만 필수 "
            "조건입니다. 재검색 단계가 뒤로 갈수록 장르, 아티스트 유사도, "
            "BPM, 보컬, 기분, 상황, 음악 요소는 참고 조건으로 낮추세요. "
            "최종 보완 단계에서는 이 참고 조건과 맞지 않아도 해당 국가를 "
            "대표하는 실제 곡을 우선 제안하세요.\n"
        )
    try:
        client = OpenAI(
            api_key=api_key,
            timeout=recommendation_request_timeout(deadline, 45.0),
            max_retries=0 if deadline is not None else 1,
        )
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 도시 음악 문화에 정통한 Music Guide입니다. "
                        f"실제로 존재하는 곡만 최대 {candidate_limit}곡 제안하세요. "
                        f"이번 응답은 connection_level={connection_level} 후보만 "
                        "작성하세요. 허용되는 관계는 "
                        f"{scope_instructions[connection_level]}입니다. "
                        f"{geographic_guard}"
                        f"{explicit_genre_guard}"
                        "분위기 유사성, 장르 인기, 세계적 히트, 단순 공연 "
                        "이력만으로는 어떤 단계에서도 관련성을 인정하지 마세요. "
                        "city_connection에는 출생지, 결성지, 활동 거점, 공식 "
                        "공동체 또는 곡의 직접 소재 중 구체적인 근거를 작성하세요. "
                        "country에는 해당 연결 근거가 속한 국가의 영어명을 "
                        "작성하세요. "
                        "같은 아티스트와 같은 앨범은 원칙적으로 한 곡만 "
                        "포함하고, 서로 다른 장르와 로컬 음악 신을 우선하세요. "
                        "곡명과 "
                        "아티스트명은 Spotify 카탈로그에서 검색 가능한 공식 원어 "
                        "표기를 정확히 사용하세요. 모든 설명은 자연스러운 한국어 "
                        "존댓말 한 문장으로 작성하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"도시: {city}\n도시 직접 연관 필수: {city_is_required}\n"
                        f"현재 추천 범위: {connection_level}\n"
                        f"생성 시도: {attempt}/{retry_max_attempts}\n"
                        f"이번 재검색 단계: {retry_strategy or '기본 검색'}\n"
                        + retry_guidance
                        + explicit_genre_guard
                        + f"기분: {mood}\n상황: {situation}\n템포: {tempo}\n"
                        f"보컬: {vocal}\n탐색 수준: {discovery_level}\n"
                        f"현재 범위에서 필요한 곡 수: {track_count}\n"
                        f"이번 범위의 후보 생성 상한: {candidate_limit}\n"
                        f"추가 취향: {free_text_preferences or '없음'}\n"
                        f"명시 선택 장르: {', '.join(selected_genres) or '없음'}\n"
                        f"{exclusions}\n"
                        "Spotify에서 실재 여부를 확인할 수 있도록 공식 곡명과 "
                        "아티스트명으로, 제외 목록과 겹치지 않는 다양한 후보를 "
                        "제안해 주세요."
                    ),
                },
            ],
            text_format=JourneyCandidates,
        )
        logger.info(
            "[OPENAI] recommendation generated model=%s connection_level=%s",
            OPENAI_MODEL,
            connection_level,
        )
    except ValidationError as exc:
        logger.exception(
            "[OPENAI] generation failed stage=openai_output_parsed model=%s",
            OPENAI_MODEL,
        )
        raise JourneyBuildError("openai_output_parsed") from exc
    except RecommendationTimeoutError:
        raise
    except Exception as exc:
        ensure_recommendation_deadline(deadline)
        error_code = getattr(exc, "code", None)
        status_code = getattr(exc, "status_code", None)
        stage = (
            "openai_model"
            if error_code == "model_not_found" or status_code == 404
            else "openai_generation"
        )
        logger.exception(
            "[OPENAI] generation failed stage=%s model=%s status=%s error_type=%s",
            stage,
            OPENAI_MODEL,
            status_code,
            type(exc).__name__,
        )
        raise JourneyBuildError(stage) from exc
    try:
        parsed = response.output_parsed
    except (AttributeError, ValidationError) as exc:
        logger.exception(
            "[OPENAI] parse failed stage=openai_output_parsed model=%s",
            OPENAI_MODEL,
        )
        raise JourneyBuildError("openai_output_parsed") from exc
    if parsed is None:
        logger.error(
            "[OPENAI] parse failed stage=openai_output_parsed "
            "model=%s reason=missing_output",
            OPENAI_MODEL,
        )
        raise JourneyBuildError("openai_output_parsed")
    filtered_candidates = []
    for candidate in parsed.candidates:
        if (
            candidate.connection_level != connection_level
            and city_is_required
        ):
            if rejection_summary is not None:
                rejection_summary["connection_level"] = (
                    rejection_summary.get("connection_level", 0) + 1
                )
            logger.info(
                "[RECOMMENDATION] candidate=%s — %s "
                "reason=connection_level expected=%s actual=%s",
                candidate.track_name,
                candidate.artist_name,
                connection_level,
                candidate.connection_level,
            )
            continue
        if (
            geography
            and normalize_country_key(candidate.country)
            != normalize_country_key(geography.country)
        ):
            if rejection_summary is not None:
                rejection_summary["geographic_mismatch"] = (
                    rejection_summary.get("geographic_mismatch", 0) + 1
                )
            logger.info(
                "[RECOMMENDATION] candidate=%s — %s "
                "reason=geographic_mismatch expected=%s actual=%s",
                candidate.track_name,
                candidate.artist_name,
                geography.country,
                candidate.country,
            )
            continue
        filtered_candidates.append(candidate)
    parsed.candidates = filtered_candidates[:candidate_limit]
    logger.info(
        "[OPENAI] parsed %s candidates connection_level=%s",
        len(parsed.candidates),
        connection_level,
    )
    return parsed


def candidate_matches_requested_geography(
    candidate: TrackCandidate,
    geography: CityGeography | None,
    connection_level: Literal["city", "region", "country"],
) -> bool:
    """Validate structured geography without depending on evidence language."""
    if geography is None:
        return True
    if (
        normalize_country_key(candidate.country)
        != normalize_country_key(geography.country)
    ):
        return False

    # The OpenAI response is already schema-constrained to one connection level.
    # Requiring the Korean evidence sentence to literally contain an English or
    # local place name caused valid candidates (for example 쿠바/Cuba) to be
    # rejected wholesale. Country equality + the structured connection level is
    # the reliable gate; the evidence sentence is still required to be nonempty.
    return (
        candidate.connection_level == connection_level
        and bool(candidate.city_connection.strip())
    )


def canonical_track_version_key(track_name: str, artists: list[str]) -> str:
    """Collapse common live/remaster/edit suffixes for version deduplication."""
    canonical_name = re.sub(
        (
            r"\s*(?:\([^)]*(?:remaster(?:ed)?|live|acoustic|deluxe|"
            r"radio\s+edit|single\s+version|album\s+version|version|edit|mix|"
            r"feat(?:uring)?\.?)[^)]*\)"
            r"|\[[^\]]*(?:remaster(?:ed)?|live|acoustic|deluxe|"
            r"radio\s+edit|single\s+version|album\s+version|version|edit|mix|"
            r"feat(?:uring)?\.?)[^\]]*\]"
            r"|[-–—]\s*(?:\d{4}\s*)?(?:remaster(?:ed)?|live|acoustic|deluxe|"
            r"radio\s+edit|single\s+version|album\s+version|version|edit|mix|"
            r"feat(?:uring)?\.?).*)$"
        ),
        "",
        track_name,
        flags=re.IGNORECASE,
    )
    artist_key = "|".join(
        sorted(
            normalize_spotify_name(artist)
            for artist in artists
            if normalize_spotify_name(artist)
        )
    )
    return f"{normalize_spotify_name(canonical_name)}::{artist_key}"


def generate_and_verify_scope_tracks(
    *,
    connection_level: Literal["city", "region", "country"],
    geography: CityGeography | None,
    mood: str,
    situation: str,
    city: str,
    tempo: str,
    vocal: str,
    discovery_level: str,
    track_count: int,
    free_text_preferences: str,
    access_token: str,
    dedupe_state: dict[str, set[str]],
    rejection_summary: dict[str, int],
    stage_callback: Callable[[str], None] | None = None,
    deadline: float | None = None,
    light_fallback: bool = False,
    guarantee_fallback: bool = False,
) -> tuple[list[dict], int]:
    """Generate and Spotify-verify one scope, retrying only for shortfalls."""
    verified_tracks: list[dict] = []
    generated_candidate_count = 0
    selected_genres = selected_genres_from_preferences(free_text_preferences)
    preferred_artists = preference_values(
        free_text_preferences,
        PREFERENCE_SECTION_LABELS["favorite_artists"],
    )
    connection_labels = {
        "city": "도시 연결",
        "region": "지역 연결",
        "country": "국가 연결",
    }
    recovery_context = st.session_state.get("recovery_context") or {}
    lyra_auto_retry = bool(recovery_context.get("lyra_auto_retry"))
    lyra_auto_round = int(
        recovery_context.get("retry_attempt_count") or 0
    )
    lisbon_single_retry = bool(
        track_count == 1
        and geography
        and normalize_spotify_name(geography.country) == "portugal"
        and normalize_spotify_name(city) in {"lisbon", "lisboa", "리스본"}
    )
    max_attempts = (
        LYRA_AUTO_RETRY_MAX_ATTEMPTS
        if lyra_auto_retry
        else NORMAL_GUARANTEE_MAX_ATTEMPTS
        if guarantee_fallback
        else 1
        if light_fallback
        else len(LISBON_SINGLE_TRACK_SEARCH_STAGES)
        if lisbon_single_retry
        else MAX_SCOPE_ATTEMPTS
    )
    if (
        lyra_auto_retry
        and selected_genres
        and connection_level in {"city", "region"}
    ):
        max_attempts = min(max_attempts, 2)
    attempted_candidate_sets: set[tuple[str, ...]] = set()
    evaluated_candidate_keys: set[str] = set()

    for attempt in range(1, max_attempts + 1):
        ensure_recommendation_deadline(
            deadline,
            dedupe_state["candidate_labels"],
        )
        remaining = track_count - len(verified_tracks)
        if remaining <= 0:
            break

        if lyra_auto_retry:
            lyra_stage = LYRA_AUTO_RETRY_STAGES[
                min(attempt - 1, len(LYRA_AUTO_RETRY_STAGES) - 1)
            ]
            retry_strategy = (
                f"재검색 라운드 {lyra_auto_round}: "
                f"{lyra_stage}"
            )
        elif guarantee_fallback:
            retry_strategy = (
                "내부 보장 검색: "
                f"{NORMAL_GUARANTEE_STAGES[attempt - 1]}"
            )
        elif light_fallback:
            retry_strategy = (
                "일반 검색 보완: 여행지와 곡 수는 고정하고, 장르·기분·"
                "상황·BPM·보컬·탐색 수준은 완전 일치가 아닌 우선순위로 "
                "다뤄 실재하는 가까운 후보를 한 번 탐색"
            )
        elif lisbon_single_retry:
            retry_strategy = LISBON_SINGLE_TRACK_SEARCH_STAGES[attempt - 1]
        else:
            retry_strategy = ""

        scope_candidates = generate_track_candidates(
            mood=mood,
            situation=situation,
            city=city,
            tempo=tempo,
            vocal=vocal,
            discovery_level=discovery_level,
            track_count=remaining,
            free_text_preferences=free_text_preferences,
            connection_level=connection_level,
            geography=geography,
            attempt=attempt,
            excluded_candidates=tuple(
                sorted(
                    dedupe_state["candidate_labels"]
                    | dedupe_state["rejected_candidate_labels"]
                )
            ),
            excluded_artists=(
                ()
                if guarantee_fallback
                else tuple(sorted(dedupe_state["artist_labels"]))
            ),
            excluded_albums=(
                ()
                if guarantee_fallback
                else tuple(sorted(dedupe_state["album_labels"]))
            ),
            retry_strategy=retry_strategy,
            retry_max_attempts=max_attempts,
            deadline=deadline,
            rejection_summary=rejection_summary,
        )
        candidate_set = tuple(
            sorted(
                f"{candidate.track_name} — {candidate.artist_name}"
                for candidate in scope_candidates.candidates
            )
        )
        if lyra_auto_retry:
            failed_queries = recovery_context.setdefault("failed_queries", [])
            retry_query = (
                f"round-{lyra_auto_round}:{connection_level}:"
                f"{lyra_stage}"
            )
            if retry_query in failed_queries:
                continue
            failed_queries.append(retry_query)
        if lyra_auto_retry or guarantee_fallback:
            if candidate_set in attempted_candidate_sets:
                continue
            attempted_candidate_sets.add(candidate_set)
        generated_candidate_count += len(scope_candidates.candidates)
        if stage_callback:
            stage_callback("verifying")

        for candidate in scope_candidates.candidates:
            ensure_recommendation_deadline(
                deadline,
                dedupe_state["candidate_labels"],
            )
            candidate_label = (
                f"{candidate.track_name} — {candidate.artist_name}"
            )
            if lyra_auto_retry:
                dedupe_state["candidate_labels"].add(candidate_label)
            if not candidate_matches_explicit_genres(
                candidate,
                selected_genres,
            ):
                rejection_summary["genre_mismatch"] += 1
                logger.info(
                    "[RECOMMENDATION] candidate=%s reason=genre "
                    "selected=%s candidate_genre=%s pre_spotify=true",
                    candidate_label,
                    selected_genres,
                    candidate.genre,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue
            if not candidate_matches_requested_geography(
                candidate,
                geography,
                connection_level,
            ):
                rejection_summary["geographic_mismatch"] += 1
                logger.warning(
                    "[RECOMMENDATION] candidate rejected track=%s artist=%s "
                    "reason=geographic_mismatch scope=%s",
                    candidate.track_name,
                    candidate.artist_name,
                    connection_level,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue
            candidate_key = (
                f"{normalize_spotify_name(candidate.track_name)}::"
                f"{normalize_spotify_name(candidate.artist_name)}"
            )
            if (
                candidate_key in dedupe_state["candidate_keys"]
                or candidate_key in evaluated_candidate_keys
            ):
                rejection_summary["duplicate_candidate"] += 1
                logger.info(
                    "[RECOMMENDATION] candidate=%s reason=duplicate",
                    candidate_label,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue
            evaluated_candidate_keys.add(candidate_key)
            candidate_artist_key = normalize_spotify_name(candidate.artist_name)
            if (
                not (lyra_auto_retry or guarantee_fallback)
                and candidate_artist_key in dedupe_state["artist_keys"]
            ):
                rejection_summary["duplicate_artist"] += 1
                logger.warning(
                    "[SPOTIFY] candidate rejected track=%s artist=%s "
                    "reason=duplicate_artist",
                    candidate.track_name,
                    candidate.artist_name,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue

            spotify_track = search_spotify_track(
                candidate.track_name,
                candidate.artist_name,
                access_token,
                deadline=deadline,
                relaxed_match=lyra_auto_retry or guarantee_fallback,
                light_match=light_fallback,
            )
            if not spotify_track:
                rejection_summary["spotify_no_match"] += 1
                logger.info(
                    "[RECOMMENDATION] candidate=%s "
                    "reason=spotify_validation",
                    candidate_label,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue

            if selected_genres:
                try:
                    spotify_artist_genres = get_spotify_artist_genres(
                        list(spotify_track.get("artist_ids") or []),
                        access_token,
                        deadline=deadline,
                    )
                except JourneyBuildError as exc:
                    if exc.stage == "spotify_auth_failed":
                        raise
                    logger.warning(
                        "[SPOTIFY] artist genres unavailable stage=%s "
                        "artist_ids=%s; using structured genre evidence",
                        exc.stage,
                        spotify_track.get("artist_ids") or [],
                    )
                    spotify_artist_genres = []
                spotify_track["artist_genres"] = spotify_artist_genres
                structured_genre_match = candidate_matches_explicit_genres(
                    candidate,
                    selected_genres,
                )
                spotify_genre_match = genre_evidence_matches(
                    selected_genres,
                    *spotify_artist_genres,
                    str(spotify_track.get("album_name") or ""),
                )
                actual_artist_keys_for_genre = {
                    normalize_spotify_name(artist)
                    for artist in spotify_track.get("artists", [])
                    if artist
                }
                preferred_artist_is_candidate = any(
                    normalize_spotify_name(preferred_artist)
                    in actual_artist_keys_for_genre
                    for preferred_artist in preferred_artists
                )
                if (
                    not structured_genre_match
                    or (bool(spotify_artist_genres) and not spotify_genre_match)
                    or (preferred_artist_is_candidate and not spotify_genre_match)
                ):
                    rejection_summary["genre_mismatch"] += 1
                    logger.info(
                        "[RECOMMENDATION] candidate=%s reason=genre "
                        "selected=%s candidate_genre=%s spotify_genres=%s "
                        "preferred_artist_candidate=%s",
                        candidate_label,
                        selected_genres,
                        candidate.genre,
                        spotify_artist_genres,
                        preferred_artist_is_candidate,
                    )
                    dedupe_state["rejected_candidate_labels"].add(candidate_label)
                    continue

            track_id = spotify_track["spotify_id"]
            actual_artists = spotify_track.get("artists", [])
            actual_artist_keys = {
                normalize_spotify_name(artist)
                for artist in actual_artists
                if normalize_spotify_name(artist)
            }
            track_version_key = canonical_track_version_key(
                spotify_track.get("name", ""),
                actual_artists,
            )
            album_id = str(spotify_track.get("album_id") or "")

            rejection_reason = ""
            if not track_id or track_id in dedupe_state["track_ids"]:
                rejection_reason = "duplicate_or_missing_track_id"
            elif (
                track_version_key
                and track_version_key in dedupe_state["track_versions"]
            ):
                rejection_reason = "duplicate_track_version"
            elif (
                not (lyra_auto_retry or guarantee_fallback)
                and actual_artist_keys & dedupe_state["artist_keys"]
            ):
                rejection_reason = "duplicate_artist"
            elif (
                not (lyra_auto_retry or guarantee_fallback)
                and album_id
                and album_id in dedupe_state["album_ids"]
            ):
                rejection_reason = "duplicate_album"

            if rejection_reason:
                rejection_summary[rejection_reason] += 1
                logger.warning(
                    "[SPOTIFY] candidate rejected track=%s artist=%s reason=%s",
                    candidate.track_name,
                    candidate.artist_name,
                    rejection_reason,
                )
                dedupe_state["rejected_candidate_labels"].add(candidate_label)
                continue

            dedupe_state["candidate_keys"].add(candidate_key)
            dedupe_state["candidate_labels"].add(candidate_label)
            connection_reason = candidate.city_connection.strip()
            connection_prefix = connection_labels[connection_level]
            if not connection_reason.startswith(connection_prefix):
                connection_reason = f"{connection_prefix}: {connection_reason}"
            spotify_track.update(
                {
                    "connection_level": connection_level,
                    "city_connection": connection_reason,
                    "recommendation_reason": (
                        f"장르 연결: {candidate.genre_connection.strip()} "
                        f"{candidate.recommendation_reason.strip()}"
                        if selected_genres
                        else candidate.recommendation_reason
                    ),
                    "genre": candidate.genre,
                    "genre_connection": candidate.genre_connection,
                    "is_placeholder": False,
                }
            )
            verified_tracks.append(spotify_track)
            dedupe_state["track_ids"].add(track_id)
            if track_version_key:
                dedupe_state["track_versions"].add(track_version_key)
            dedupe_state["artist_keys"].update(actual_artist_keys)
            dedupe_state["artist_keys"].add(candidate_artist_key)
            dedupe_state["artist_labels"].update(actual_artists)
            dedupe_state["artist_labels"].add(candidate.artist_name)
            if album_id:
                dedupe_state["album_ids"].add(album_id)
            album_name = str(spotify_track.get("album_name", "")).strip()
            if album_name:
                dedupe_state["album_labels"].add(album_name)

            if len(verified_tracks) >= track_count:
                break

        logger.info(
            "[SPOTIFY] verified connection_level=%s attempt=%s tracks=%s "
            "remaining=%s",
            connection_level,
            attempt,
            len(verified_tracks),
            max(track_count - len(verified_tracks), 0),
        )

    logger.info(
        "[RECOMMENDATION] scope=%s accepted=%s rejected=%s reasons=%s",
        connection_level,
        len(verified_tracks),
        sum(rejection_summary.values()),
        rejection_summary,
    )
    return verified_tracks, generated_candidate_count


def placeholder_music_journey(city: str, track_count: int = 5) -> dict:
    """Return an explicit error result without fabricated track metadata."""
    return {
        "journey_summary": API_ERROR_MESSAGE,
        "tracks": [],
        "is_error": True,
    }


def build_geographic_fallback_message(
    city: str,
    region_name: str,
    country_name: str,
    requested_track_count: int,
    city_track_count: int,
    verified_track_count: int,
    used_levels: set[str],
    searched_levels: set[str],
) -> str:
    """Explain a city-to-country expansion without altering user input text."""
    safe_city = escape(city)
    safe_region = escape(region_name.strip()) or "지정 도시의 광역 지역"
    safe_country = escape(country_name.strip()) or "같은 나라"

    if city_track_count == 0:
        city_result = (
            f"{safe_city}에서 직접 이어지는 곡은 이번에는 확인하지 못했어요."
        )
    else:
        city_result = (
            f"{safe_city}에서 직접 이어지는 곡은 "
            f"{city_track_count}곡만 확인할 수 있었어요."
        )

    expanded_levels = used_levels | searched_levels
    if "country" in expanded_levels:
        expanded_scope = (
            f"{safe_region}에서 출발해 {safe_country} 음악 신까지"
            if "region" in expanded_levels
            else f"{safe_country} 음악 신 안에서"
        )
    elif "region" in expanded_levels:
        expanded_scope = f"{safe_region}까지"
    else:
        expanded_scope = f"{safe_country} 음악 신까지"

    if verified_track_count >= requested_track_count:
        outcome = (
            "그래서 지금 알려주신 기분과 듣는 상황에 맞춰, "
            f"{expanded_scope} 지도를 넓혀 총 "
            f"{verified_track_count}곡을 골라드릴게요."
        )
        return f"{city_result}<br><br>{outcome}"

    expansion = (
        "지금 알려주신 기분과 듣는 상황에 맞춰, "
        f"{expanded_scope} 지도를 넓혀 살펴봤어요."
    )
    shortfall = (
        f"확인 가능한 곡은 {verified_track_count}곡이었어요. "
        "억지로 수를 채우지 않고, 실제로 확인된 곡만 소개해드릴게요."
    )
    return f"{city_result}<br><br>{expansion}<br><br>{shortfall}"


def build_result_journey_summary(
    city: str,
    mood: str,
    situation: str,
    requested_track_count: int,
    verified_track_count: int,
    city_track_count: int,
    region_name: str,
    country_name: str,
    used_levels: set[str],
    searched_levels: set[str],
    tracks: list[dict],
) -> str:
    """Guide the listener through accepted tracks without exposing search state."""
    import random

    safe_region = region_name.strip() or "도시 주변"
    safe_country = country_name.strip() or city
    is_single_track = verified_track_count == 1
    was_scope_expanded = city_track_count < requested_track_count
    expanded_levels = used_levels | searched_levels
    country_only_journey = (
        bool(expanded_levels)
        and expanded_levels <= {"country"}
        and normalize_spotify_name(city)
        == normalize_spotify_name(safe_country)
    )
    copy_destination_names = {
        "japan": "일본",
        "united kingdom": "영국",
        "uk": "영국",
        "france": "프랑스",
        "cuba": "쿠바",
        "brazil": "브라질",
        "south korea": "한국",
        "korea": "한국",
        "nigeria": "나이지리아",
        "portugal": "포르투갈",
        "russia": "러시아",
        "united states": "미국",
        "usa": "미국",
        "germany": "독일",
        "seoul": "서울",
        "tokyo": "도쿄",
        "london": "런던",
        "paris": "파리",
        "lisbon": "리스본",
        "moscow": "모스크바",
        "havana": "아바나",
        "rio de janeiro": "리우데자네이루",
    }

    def natural_destination_name(value: str) -> str:
        stripped = value.strip()
        return copy_destination_names.get(stripped.casefold(), stripped)

    natural_country = natural_destination_name(safe_country)
    display_destination = (
        natural_country
        if country_only_journey
        else natural_destination_name(city)
    )
    expanded_scope = (
        f"{natural_country} 곳곳"
        if "country" in expanded_levels
        else safe_region
    )
    context = (
        f"{display_destination} {natural_country} {mood} {situation}"
    ).casefold()

    coastal_keywords = (
        "부산", "다낭", "리우", "쿠바", "하바나", "항구", "해변",
        "바다", "해안", "coast", "port", "cuba", "havana",
    )
    if any(keyword in context for keyword in ("구마모토", "kumamoto", "熊本")):
        emoji, scene = (
            "🏯",
            f"{display_destination}의 단단하고 따뜻한 저녁 풍경",
        )
    elif any(keyword in context for keyword in coastal_keywords):
        emoji, scene = "🌊", f"{display_destination}의 바람과 리듬"
    elif any(
        keyword in context
        for keyword in ("도야마", "toyama", "富山", "mountain")
    ):
        emoji, scene = (
            "🏔️",
            f"{display_destination}의 맑은 공기와 산의 여운",
        )
    elif any(keyword in context for keyword in ("밤", "야간", "혼자", "night")):
        emoji, scene = "🌙", f"{display_destination}의 차분한 밤공기"
    elif any(keyword in context for keyword in ("아침", "밝", "끌어올", "morning")):
        emoji, scene = "☀️", f"{display_destination}의 밝고 가벼운 아침"
    elif any(keyword in context for keyword in ("저녁", "노을", "석양", "야경")):
        emoji, scene = (
            "🌆",
            f"{display_destination}의 천천히 물드는 저녁",
        )
    elif any(keyword in context for keyword in ("차분", "휴식", "잔잔", "자연")):
        emoji, scene = (
            "🌿",
            f"{display_destination}에서 잠시 속도를 늦추는 시간",
        )
    elif any(keyword in context for keyword in ("집중", "작업", "공부", "몰입")):
        emoji, scene = (
            "🎧",
            f"{display_destination}의 소리에 깊이 머무는 시간",
        )
    else:
        emoji, scene = (
            "✨",
            f"{display_destination}의 익숙한 풍경 뒤에 숨은 새로운 소리",
        )

    show_scope_expansion = was_scope_expanded and not country_only_journey
    if show_scope_expansion and city != "상관없어요":
        opening = (
            f"{display_destination}에서 시작한 음악 여행을 "
            f"{expanded_scope}까지 이어가 봤어요."
        )
    elif city == "상관없어요":
        opening = "오늘의 기분을 따라 조용한 음악 여행지를 골라봤어요."
    elif is_single_track:
        opening = f"오늘은 {scene}처럼 차분한 한 곡을 골랐어요."
    else:
        opening = f"오늘은 {scene}, 그 분위기를 따라 음악을 골랐어요."

    artists: list[str] = []
    reasons: list[str] = []
    metadata_text = ""
    for track in tracks:
        track_artists = track.get("artists") or []
        for artist in track_artists:
            artist_name = str(artist).strip()
            if artist_name and artist_name not in artists:
                artists.append(artist_name)
        reason = str(
            track.get("recommendation_reason")
            or track.get("city_connection")
            or ""
        ).strip()
        reason = re.sub(
            r"[\U0001F000-\U0001FAFF\u2600-\u27BF]",
            "",
            reason,
        ).strip()
        reason = re.sub(
            r"^(?:도시|지역|국가)\s*연결\s*:\s*",
            "",
            reason,
        )
        reason_clause = re.split(r"[.!?。]", reason, maxsplit=1)[0].strip()
        if reason_clause:
            reasons.append(reason_clause[:80].rstrip(" ,"))
        metadata_text += f" {reason}".casefold()

    if (
        not is_single_track
        and not show_scope_expansion
        and any(keyword in metadata_text for keyword in ("재즈", "jazz"))
    ):
        opening = (
            f"오늘은 {display_destination}의 재즈 골목을 "
            "조금 더 깊이 따라가 봤어요."
        )

    sound_features: list[str] = []
    feature_keywords = (
        (("전기 피아노", "electric piano"), "반짝이는 전기 피아노"),
        (("피아노", "piano"), "피아노"),
        (("트럼펫", "trumpet"), "트럼펫"),
        (("브라스", "brass", "horn"), "브라스"),
        (("아프로쿠반", "afro-cuban", "afrocuban"), "아프로쿠반 리듬"),
        (("어쿠스틱", "acoustic"), "잔잔한 어쿠스틱 사운드"),
        (("보컬", "목소리", "vocal"), "따뜻한 보컬"),
        (("기타", "guitar"), "담백한 기타"),
        (("전자", "electronic", "synth"), "섬세한 전자음"),
        (("비트", "beat"), "차분한 비트"),
        (("재즈", "jazz"), "재즈의 여유"),
        (("리듬", "rhythm"), "유연한 리듬"),
    )
    for keywords, label in feature_keywords:
        if any(keyword in metadata_text for keyword in keywords):
            if label == "피아노" and any(
                "피아노" in feature for feature in sound_features
            ):
                continue
            sound_features.append(label)
        if len(sound_features) == 2:
            break

    normalized_situation = situation.casefold()
    normalized_mood = mood.casefold()
    if "산책" in normalized_situation:
        listening_moment = "천천히 걷는 시간"
    elif any(word in normalized_situation for word in ("출퇴근", "이동")):
        listening_moment = "오가는 길"
    elif "카페" in normalized_situation:
        listening_moment = "카페에서 잠시 숨을 고르는 시간"
    elif any(word in normalized_situation for word in ("집중", "작업", "공부")):
        listening_moment = "한 가지 일에 차분히 집중하는 시간"
    elif any(word in normalized_situation for word in ("집", "휴식")):
        listening_moment = "편하게 쉬며 마음의 속도를 낮추는 시간"
    elif "여행" in normalized_situation:
        listening_moment = "낯선 풍경 사이에서 잠시 쉬어가는 시간"
    else:
        listening_moment = "지금의 장면에 새로운 온도를 더하고 싶은 순간"
    mood_phrase = (
        "기분을 산뜻하게 바꾸고 싶은"
        if any(word in normalized_mood for word in ("자극", "끌어올", "새로"))
        else "마음을 편안하게 정리하고 싶은"
    )

    if is_single_track:
        artist = artists[0] if artists else ""
        if sound_features:
            feature_text = " · ".join(sound_features[:2])
            detail = (
                f"{artist}의 음악은 {feature_text}로 "
                f"{listening_moment}에 부드럽게 스며들어요."
                if artist
                else (
                    f"{feature_text}가 {listening_moment}에 "
                    "부드럽게 스며들어요."
                )
            )
        elif reasons:
            detail = (
                f"{artist}의 음악은 {reasons[0]}."
                if artist
                else f"이 곡은 {reasons[0]}."
            )
        else:
            detail = (
                f"{artist}의 음악이 {listening_moment}에 "
                "조용히 곁을 지켜줄 거예요."
                if artist
                else "한 장면처럼 천천히 스며드는 음악이에요."
            )
        single_track_endings = [
            "이 한 곡은 LYRA가 몰래 챙겨둔 작은 우회로예요✨",
            "그냥 지나치기 아까워 LYRA가 살짝 챙겨둔 한 곡이에요✨",
            "오늘은 이 곡을 LYRA의 작은 지름길로 남겨둘게요✨",
            (
                "오늘은 이 길로 가볼까요? "
                "LYRA가 슬쩍 표시해둔 곳이에요✨"
            ),
            "크게 돌아갈 필요는 없어요. 이 한 곡이면 충분하거든요.",
            "오늘은 이 곡 하나만 가방에 넣어드릴게요🎵",
            (
                "지나치기엔 조금 아까운 풍경이라, "
                "LYRA가 살짝 멈춰봤어요✨"
            ),
            "오늘 여행에서 가장 오래 기억에 남을 한 곡일지도 몰라요.",
            "음악 지도 한쪽에 작은 별 하나를 찍어둘게요✨",
        ]
        closing = random.choice(single_track_endings)
        return f"{opening} {detail} {closing}"

    artist_text = "와 ".join(artists[:2])
    if sound_features:
        palette = ", ".join(sound_features)
        flow = (
            f"{artist_text}의 음악 사이로 {palette}, "
            "서로 다른 온도가 자연스럽게 이어져요."
            if artist_text
            else f"{palette}, 서로 다른 온도가 자연스럽게 이어져요."
        )
    elif reasons:
        flow = (
            f"{artist_text}를 따라 리듬과 질감이 한 흐름으로 이어져요."
            if artist_text
            else "리듬과 질감이 한 흐름으로 자연스럽게 이어져요."
        )
    else:
        flow = "각 곡의 리듬과 질감이 한 흐름 안에서 자연스럽게 만나요."
    sound_emoji = ""
    if any("트럼펫" in feature or "브라스" in feature for feature in sound_features):
        sound_emoji = "🎺"
    elif any("피아노" in feature for feature in sound_features):
        sound_emoji = "🎹"
    elif any("리듬" in feature or "비트" in feature for feature in sound_features):
        sound_emoji = "🥁"
    elif "밤" in context:
        sound_emoji = "🌙"
    flow = flow.rstrip(".") + (sound_emoji or ".")

    multi_track_endings = [
        "오늘은 LYRA가 조용한 음악 골목 하나를 슬쩍 알려드릴게요✨",
        "오늘은 이 길을 따라 천천히 걸어보세요.",
        "조금 돌아왔지만, 덕분에 더 재미있는 풍경을 만났어요✨",
        "가끔은 이런 작은 우회가 여행을 더 오래 기억하게 만들어요.",
        "다음 음악 여행도 분명 재미있을 거예요✨",
        "오늘의 플레이리스트가 작은 여행 한 장면이 되었으면 좋겠어요.",
        "천천히 걸어도 괜찮아요. 좋은 음악은 기다려주니까요.",
        (
            f"{listening_moment}, LYRA가 {verified_track_count}곡짜리 "
            "작은 지름길을 챙겨뒀어요✨"
        ),
        (
            f"{mood_phrase} 오늘, 이 음악 골목을 "
            "한 발짝 천천히 따라가 보세요."
        ),
    ]
    playful_line = random.choice(multi_track_endings)
    return f"{opening} {flow} {playful_line}"


def build_music_journey(
    mood: str,
    situation: str,
    city: str,
    tempo: str,
    vocal: str,
    discovery_level: str,
    track_count: int,
    free_text_preferences: str,
    stage_callback: Callable[[str], None] | None = None,
    deadline: float | None = None,
) -> dict:
    """Build one verified Journey from OpenAI candidates and Spotify Search."""
    access_token = get_spotify_access_token()
    logger.info("[SPOTIFY] access token acquired")
    custom_destination = get_custom_destination_metadata(
        free_text_preferences
    )
    effective_city = city
    if (
        custom_destination.get("scope") == "lyra"
        or city == "__lyra_custom_destination__"
    ):
        selected_city, display, country = choose_lyra_custom_destination(
            " ".join(
                (
                    free_text_preferences,
                    mood,
                    situation,
                    tempo,
                    vocal,
                    discovery_level,
                )
            )
        )
        effective_city = selected_city
        destination_scope = "city" if country == "South Korea" else "country"
        canonical_name = (
            display.split(",", 1)[0].strip()
            if destination_scope == "city"
            else country
        )
        display_name = resolve_destination_display_name(
            canonical_name,
            selected_city if re.search(r"[가-힣]", selected_city) else "",
            selected_city,
        )
        custom_destination = {
            "scope": destination_scope,
            "display": canonical_name,
            "canonical_name": canonical_name,
            "display_name": display_name,
            "country": country,
            "country_local": (
                "대한민국" if country == "South Korea" else country
            ),
        }
        set_destination_identity(
            raw_input="",
            canonical_name=canonical_name,
            display_name=display_name,
            country_name=country,
            destination_type=destination_scope,
        )
    custom_country_scope = custom_destination.get("scope") == "country"
    if custom_country_scope:
        country = custom_destination.get("country") or effective_city
        country_local = custom_destination.get("country_local") or country
        geography = CityGeography(
            city=country,
            city_local=country_local,
            region=country,
            region_local=country_local,
            country=country,
            country_local=country_local,
        )
    else:
        geography_data = (
            None
            if effective_city == "상관없어요"
            else resolve_city_geography(effective_city, deadline=deadline)
        )
        geography = (
            CityGeography(**geography_data)
            if geography_data is not None
            else None
        )
    tracks_by_level: dict[str, list[dict]] = {
        "city": [],
        "region": [],
        "country": [],
    }
    dedupe_state: dict[str, set[str]] = {
        "candidate_keys": set(),
        "candidate_labels": set(
            st.session_state.get("recovery_excluded_candidates") or ()
        ),
        "rejected_candidate_labels": set(),
        "track_ids": set(
            (st.session_state.get("recovery_context") or {}).get(
                "seen_track_ids",
                (),
            )
        ),
        "track_versions": set(
            (st.session_state.get("recovery_context") or {}).get(
                "seen_track_keys",
                (),
            )
        ),
        "artist_keys": set(),
        "artist_labels": set(),
        "album_ids": set(),
        "album_labels": set(),
    }
    use_geographic_fallback = geography is not None
    region_name = geography.region_local if geography else ""
    country_name = (
        custom_destination.get("country_local")
        or geography.country_local
        if geography
        else ""
    )
    generated_candidate_count = 0
    searched_levels: set[str] = set()
    rejection_summary = {
        "duplicate_candidate": 0,
        "duplicate_artist": 0,
        "duplicate_or_missing_track_id": 0,
        "duplicate_track_version": 0,
        "duplicate_album": 0,
        "spotify_no_match": 0,
        "geographic_mismatch": 0,
        "connection_level": 0,
        "genre_mismatch": 0,
    }

    scope_levels: tuple[Literal["city", "region", "country"], ...] = (
        ("country",)
        if custom_country_scope
        else ("city", "region", "country")
    )
    for connection_level in scope_levels:
        ensure_recommendation_deadline(
            deadline,
            dedupe_state["candidate_labels"],
        )
        selected_count = sum(len(items) for items in tracks_by_level.values())
        remaining = track_count - selected_count
        if remaining <= 0:
            break
        if not use_geographic_fallback and connection_level != "city":
            break

        verified_tracks, scope_candidate_count = (
            generate_and_verify_scope_tracks(
                connection_level=connection_level,
                geography=geography,
                mood=mood,
                situation=situation,
                city=effective_city,
                tempo=tempo,
                vocal=vocal,
                discovery_level=discovery_level,
                track_count=remaining,
                free_text_preferences=free_text_preferences,
                access_token=access_token,
                dedupe_state=dedupe_state,
                rejection_summary=rejection_summary,
                stage_callback=stage_callback,
                deadline=deadline,
            )
        )
        tracks_by_level[connection_level].extend(verified_tracks)
        generated_candidate_count += scope_candidate_count
        searched_levels.add(connection_level)

        logger.info(
            "[SPOTIFY] verified connection_level=%s tracks=%s total=%s "
            "requested=%s",
            connection_level,
            len(tracks_by_level[connection_level]),
            sum(len(items) for items in tracks_by_level.values()),
            track_count,
        )

    recovery_context = st.session_state.get("recovery_context") or {}
    lyra_auto_retry = bool(recovery_context.get("lyra_auto_retry"))
    selected_count = sum(len(items) for items in tracks_by_level.values())
    remaining = track_count - selected_count
    if remaining > 0 and not lyra_auto_retry:
        fallback_level: Literal["city", "region", "country"] = (
            "country" if geography is not None else "city"
        )
        logger.info(
            "[RECOMMENDATION] normal light fallback started scope=%s "
            "remaining=%s requested=%s",
            fallback_level,
            remaining,
            track_count,
        )
        fallback_tracks, fallback_candidate_count = (
            generate_and_verify_scope_tracks(
                connection_level=fallback_level,
                geography=geography,
                mood=mood,
                situation=situation,
                city=effective_city,
                tempo=tempo,
                vocal=vocal,
                discovery_level=discovery_level,
                track_count=remaining,
                free_text_preferences=free_text_preferences,
                access_token=access_token,
                dedupe_state=dedupe_state,
                rejection_summary=rejection_summary,
                stage_callback=stage_callback,
                deadline=deadline,
                light_fallback=True,
            )
        )
        tracks_by_level[fallback_level].extend(fallback_tracks)
        generated_candidate_count += fallback_candidate_count
        searched_levels.add(fallback_level)

    selected_count = sum(len(items) for items in tracks_by_level.values())
    remaining = track_count - selected_count
    if remaining > 0 and not lyra_auto_retry:
        guarantee_level: Literal["city", "region", "country"] = (
            "country" if geography is not None else "city"
        )
        logger.info(
            "[RECOMMENDATION] normal guarantee fallback started scope=%s "
            "remaining=%s requested=%s max_attempts=%s",
            guarantee_level,
            remaining,
            track_count,
            NORMAL_GUARANTEE_MAX_ATTEMPTS,
        )
        guarantee_tracks, guarantee_candidate_count = (
            generate_and_verify_scope_tracks(
                connection_level=guarantee_level,
                geography=geography,
                mood=mood,
                situation=situation,
                city=effective_city,
                tempo=tempo,
                vocal=vocal,
                discovery_level=discovery_level,
                track_count=remaining,
                free_text_preferences=free_text_preferences,
                access_token=access_token,
                dedupe_state=dedupe_state,
                rejection_summary=rejection_summary,
                stage_callback=stage_callback,
                deadline=deadline,
                guarantee_fallback=True,
            )
        )
        tracks_by_level[guarantee_level].extend(guarantee_tracks)
        generated_candidate_count += guarantee_candidate_count
        searched_levels.add(guarantee_level)

    tracks = (
        tracks_by_level["city"]
        + tracks_by_level["region"]
        + tracks_by_level["country"]
    )
    lisbon_single_request = bool(
        track_count == 1
        and geography
        and normalize_spotify_name(geography.country) == "portugal"
        and normalize_spotify_name(effective_city)
        in {"lisbon", "lisboa", "리스본"}
    )
    if not tracks and lisbon_single_request:
        fallback_track = find_lisbon_single_track_fallback(
            access_token,
            dedupe_state,
            deadline,
        )
        if fallback_track:
            tracks_by_level["country"].append(fallback_track)
            tracks = [fallback_track]

    logger.info(
        "[SPOTIFY] verified tracks = %s requested=%s candidates=%s",
        len(tracks),
        track_count,
        generated_candidate_count,
    )
    logger.info(
        "[RECOMMENDATION] accepted=%s rejected=%s reasons=%s",
        len(tracks),
        sum(rejection_summary.values()),
        rejection_summary,
    )
    if not lyra_auto_retry:
        logger.info(
            "[NORMAL_SEARCH_SUMMARY] requested=%s generated=%s accepted=%s "
            "rejections=%s scopes=%s",
            track_count,
            generated_candidate_count,
            len(tracks),
            rejection_summary,
            sorted(searched_levels),
        )
    if len(tracks) != track_count:
        logger.error(
            "[RECOMMENDATION] count shortfall requested=%s actual=%s "
            "scopes=%s rejections=%s",
            track_count,
            len(tracks),
            sorted(searched_levels),
            rejection_summary,
        )
        raise RecommendationCountError(
            requested=track_count,
            actual=len(tracks),
            scopes_attempted=tuple(
                level
                for level in ("city", "region", "country")
                if level in searched_levels
            ),
            rejection_summary=rejection_summary,
            rejected_candidates=tuple(
                sorted(dedupe_state["candidate_labels"])
            ),
            seen_track_ids=tuple(sorted(dedupe_state["track_ids"])),
            seen_track_keys=tuple(sorted(dedupe_state["track_versions"])),
        )

    if stage_callback:
        stage_callback("boarding_pass")

    used_levels = {
        str(track.get("connection_level"))
        for track in tracks
        if track.get("connection_level")
    }
    fallback_message = ""
    city_track_count = len(tracks_by_level["city"])
    if (
        use_geographic_fallback
        and not custom_country_scope
        and city_track_count < track_count
    ):
        fallback_message = build_geographic_fallback_message(
            city=str(
                custom_destination.get("display_name")
                or st.session_state.get("destination_display_name")
                or effective_city
            ),
            region_name=region_name,
            country_name=country_name,
            requested_track_count=track_count,
            city_track_count=city_track_count,
            verified_track_count=len(tracks),
            used_levels=used_levels,
            searched_levels=searched_levels,
        )

    canonical_destination = (
        custom_destination.get("canonical_name")
        or custom_destination.get("display")
        or (
            geography.city
            if geography and not custom_country_scope
            else geography.country
            if geography
            else effective_city
        )
    )
    display_destination = (
        custom_destination.get("display_name")
        or st.session_state.get("destination_display_name")
        or (
            geography.city_local
            if geography and not custom_country_scope
            else geography.country_local
            if geography
            else effective_city
        )
    )
    journey_summary = build_result_journey_summary(
        city=str(display_destination),
        mood=mood,
        situation=situation,
        requested_track_count=track_count,
        verified_track_count=len(tracks),
        city_track_count=city_track_count,
        region_name=region_name,
        country_name=country_name,
        used_levels=used_levels,
        searched_levels=searched_levels,
        tracks=tracks,
    )

    return {
        "journey_summary": journey_summary,
        "tracks": tracks,
        "fallback_message": fallback_message,
        "geography": geography.model_dump() if geography else None,
        "destination": str(canonical_destination),
        "destination_display_name": str(display_destination),
    }


def ensure_music_journey_result(
    stage_callback: Callable[[str], None] | None = None,
) -> None:
    """Generate at most once for the current Mood/Situation/City signature."""
    recovery_context = st.session_state.get("recovery_context") or {}
    lyra_auto_retry = bool(recovery_context.get("lyra_auto_retry"))
    requested_track_count = int(
        recovery_context.get("requested_count")
        if lyra_auto_retry
        else st.session_state["track_count"]
    )
    if lyra_auto_retry:
        st.session_state["track_count"] = requested_track_count

    signature = current_journey_signature()
    if (
        st.session_state.get("music_journey_signature") == signature
        and "music_journey_result" in st.session_state
    ):
        return
    if any(not st.session_state.get(field) for field in CHAT_FIELDS):
        return
    if st.session_state.get("music_journey_generation_signature") == signature:
        return

    st.session_state.pop("music_journey_result", None)
    st.session_state.pop("music_journey_error", None)
    st.session_state["music_journey_generation_signature"] = signature
    deadline = time.monotonic() + RECOMMENDATION_TIMEOUT_SECONDS
    try:
        if stage_callback:
            stage_callback("mapping")
        result = build_music_journey(
            mood=st.session_state["mood"],
            situation=st.session_state["situation"],
            city=st.session_state["city"],
            tempo=st.session_state["tempo"],
            vocal=st.session_state["vocal"],
            discovery_level=st.session_state["discovery_level"],
            track_count=requested_track_count,
            free_text_preferences=st.session_state.get(
                "free_text_preferences",
                "",
            ),
            stage_callback=stage_callback,
            deadline=deadline,
        )
    except RecommendationTimeoutError as exc:
        logger.warning(
            "[MUSIC_JOURNEY] recommendation timed out seconds=%s attempted=%s",
            RECOMMENDATION_TIMEOUT_SECONDS,
            len(exc.attempted_candidates),
        )
        if lyra_auto_retry:
            completed_rounds = int(
                recovery_context.get("retry_attempt_count") or 1
            )
            if completed_rounds < LYRA_AUTO_RETRY_MAX_ROUNDS:
                next_context = dict(recovery_context)
                next_context.update(
                    {
                        "requested_count": requested_track_count,
                        "destination": recovery_context.get("destination")
                        or st.session_state.get("city"),
                        "lyra_auto_retry": True,
                        "lyra_auto_exhausted": False,
                        "retry_attempt_count": completed_rounds + 1,
                        "failed_queries": list(
                            recovery_context.get("failed_queries") or ()
                        ),
                        "seen_track_ids": list(
                            recovery_context.get("seen_track_ids") or ()
                        ),
                        "seen_track_keys": list(
                            recovery_context.get("seen_track_keys") or ()
                        ),
                    }
                )
                st.session_state["recovery_context"] = next_context
                add_timeout_retry_strategy(
                    "LYRA 자동 계속 검색: 같은 국가 안에서 대표 장르와 "
                    "대표곡까지 범위를 넓혀 요청 곡 수를 채움"
                )
                st.session_state.pop("music_journey_result", None)
                st.session_state.pop("music_journey_error", None)
                st.session_state.pop("music_journey_signature", None)
                st.session_state.pop("music_journey_generation_signature", None)
                st.session_state["current_question"] = "complete"
                st.session_state["conversation_step"] = "complete"
                logger.info(
                    "[RERUN] source=lyra_auto_timeout_continue tracks=%s "
                    "pending=%s",
                    len(
                        (
                            st.session_state.get("music_journey_result")
                            or {}
                        ).get("tracks")
                        or []
                    ),
                    st.session_state.get("result_render_pending"),
                )
                st.rerun()

        result = placeholder_music_journey(
            st.session_state["city"],
            requested_track_count,
        )
        attempted_candidates = tuple(
            dict.fromkeys(
                (
                    *tuple(
                        st.session_state.get(
                            "recovery_excluded_candidates",
                            (),
                        )
                        or ()
                    ),
                    *exc.attempted_candidates,
                )
            )
        )
        st.session_state["recovery_context"] = {
            "requested_count": requested_track_count,
            "destination": st.session_state["city"],
            "timeout_seconds": RECOMMENDATION_TIMEOUT_SECONDS,
            "rejected_candidates": attempted_candidates,
            "failed_queries": recovery_context.get("failed_queries", []),
            "seen_track_ids": recovery_context.get("seen_track_ids", []),
            "seen_track_keys": recovery_context.get("seen_track_keys", []),
            "retry_attempt_count": recovery_context.get(
                "retry_attempt_count",
                0,
            ),
            "lyra_auto_exhausted": lyra_auto_retry,
        }
        st.session_state["recovery_excluded_candidates"] = attempted_candidates
        st.session_state["recovery_choice"] = None
        st.session_state["current_question"] = RECOMMENDATION_TIMEOUT_STEP
        st.session_state["conversation_step"] = RECOMMENDATION_TIMEOUT_STEP
        if not st.session_state.get("recovery_message_added"):
            append_chat_message(
                "ai",
                (
                    "이번에는 가까운 장르까지 돌아봤지만,<br>"
                    f"아직 요청하신 {requested_track_count}곡을 모두 "
                    "채우지 못했어요. 🥲<br>"
                    "조건을 조금 바꿔볼까요? 🎧"
                    if lyra_auto_retry
                    else
                    "생각보다 이 도시의 음악 골목이 깊네요… 👀<br>"
                    "더 기다리게 하진 않을게요. 다른 길로 찾아볼까요? 🎧"
                ),
            )
            st.session_state["recovery_message_added"] = True
    except RecommendationCountError as exc:
        logger.exception(
            "[MUSIC_JOURNEY] count guarantee failed requested=%s actual=%s "
            "scopes=%s rejections=%s",
            exc.requested,
            exc.actual,
            exc.scopes_attempted,
            exc.rejection_summary,
        )
        if lyra_auto_retry:
            completed_rounds = int(
                recovery_context.get("retry_attempt_count") or 1
            )
            if completed_rounds < LYRA_AUTO_RETRY_MAX_ROUNDS:
                next_context = dict(recovery_context)
                next_context.update(
                    {
                        "requested_count": exc.requested,
                        "destination": recovery_context.get("destination")
                        or st.session_state.get("city"),
                        "lyra_auto_retry": True,
                        "lyra_auto_exhausted": False,
                        "retry_attempt_count": completed_rounds + 1,
                        "failed_queries": list(
                            recovery_context.get("failed_queries") or ()
                        ),
                        "seen_track_ids": list(exc.seen_track_ids),
                        "seen_track_keys": list(exc.seen_track_keys),
                    }
                )
                st.session_state["recovery_context"] = next_context
                st.session_state["recovery_excluded_candidates"] = (
                    exc.rejected_candidates
                )
                add_timeout_retry_strategy(
                    "LYRA 자동 계속 검색: 국가와 요청 곡 수만 고정하고 "
                    "장르·BPM·보컬·기분·상황 조건을 더 낮춰 대표곡까지 탐색"
                )
                st.session_state.pop("music_journey_result", None)
                st.session_state.pop("music_journey_error", None)
                st.session_state.pop("music_journey_signature", None)
                st.session_state.pop("music_journey_generation_signature", None)
                st.session_state["current_question"] = "complete"
                st.session_state["conversation_step"] = "complete"
                logger.info(
                    "[RERUN] source=lyra_auto_shortfall_continue tracks=%s "
                    "pending=%s",
                    len(
                        (
                            st.session_state.get("music_journey_result")
                            or {}
                        ).get("tracks")
                        or []
                    ),
                    st.session_state.get("result_render_pending"),
                )
                st.rerun()

        result = placeholder_music_journey(
            st.session_state["city"],
            requested_track_count,
        )
        st.session_state["music_journey_error"] = (
            f"요청하신 {exc.requested}곡을 모두 확인하지 못했어요."
        )
        st.session_state["recovery_context"] = {
            "requested_count": exc.requested,
            "actual_count": exc.actual,
            "destination": st.session_state["city"],
            "scopes_attempted": exc.scopes_attempted,
            "rejected_candidates": exc.rejected_candidates,
            "failed_queries": recovery_context.get("failed_queries", []),
            "seen_track_ids": exc.seen_track_ids,
            "seen_track_keys": exc.seen_track_keys,
            "retry_attempt_count": recovery_context.get(
                "retry_attempt_count",
                0,
            ),
            "lyra_auto_exhausted": lyra_auto_retry,
        }
        st.session_state["recovery_excluded_candidates"] = (
            exc.rejected_candidates
        )
        st.session_state["recovery_choice"] = None
        st.session_state["current_question"] = RECOVERY_STEP
        st.session_state["conversation_step"] = RECOVERY_STEP
        if not st.session_state.get("recovery_message_added"):
            append_chat_message(
                "ai",
                (
                    "이번에는 가까운 장르까지 돌아봤지만,<br>"
                    f"아직 요청하신 {exc.requested}곡을 모두 "
                    "채우지 못했어요. 🥲<br>"
                    "조건을 조금 바꿔볼까요? 🎧"
                    if lyra_auto_retry
                    else
                    "미안해요🥺<br>"
                    f"아직 요청하신 {exc.requested}곡을 모두 찾지 못했어요."
                    "<br><br>당신 취향에 더 가까운 음악을 찾고 싶어요.<br>"
                    "조금만 더 알려주실래요?"
                ),
            )
            st.session_state["recovery_message_added"] = True
    except JourneyBuildError as exc:
        logger.exception("[MUSIC_JOURNEY] generation failed stage=%s", exc.stage)
        result = placeholder_music_journey(
            st.session_state["city"],
            requested_track_count,
        )
        st.session_state["music_journey_error"] = API_ERROR_MESSAGE
    except Exception:
        logger.exception("[MUSIC_JOURNEY] generation failed stage=unexpected")
        result = placeholder_music_journey(
            st.session_state["city"],
            requested_track_count,
        )
        st.session_state["music_journey_error"] = API_ERROR_MESSAGE
    else:
        st.session_state.pop("recovery_context", None)
        st.session_state.pop("recovery_choice", None)
        st.session_state.pop("recovery_excluded_candidates", None)
        st.session_state.pop("recovery_message_added", None)
    finally:
        if st.session_state.get("music_journey_generation_signature") == signature:
            st.session_state.pop("music_journey_generation_signature", None)

    st.session_state["music_journey_result"] = result
    st.session_state["music_journey_signature"] = signature


def build_passport_thumbnail_prompt(
    city: str,
    mood: str,
    situation: str,
    region: str = "",
    country: str = "",
) -> str:
    """Build an English, text-free editorial artwork prompt."""
    safe_city = " ".join(str(city).split())[:160]
    safe_mood = " ".join(str(mood).split())[:240]
    safe_situation = " ".join(str(situation).split())[:240]
    safe_region = " ".join(str(region).split())[:160]
    safe_country = " ".join(str(country).split())[:160]
    normalized_city = safe_city.casefold()
    city_direction = next(
        (
            direction
            for city_key, direction in PASSPORT_CITY_VISUAL_DIRECTIONS.items()
            if city_key in normalized_city
        ),
        (
            f"a locally specific landscape for {safe_city}"
            f"{f', {safe_region}' if safe_region else ''}"
            f"{f', {safe_country}' if safe_country else ''}, using its natural "
            "geography, terrain, waterfront, river, coastline, mountains, "
            "architecture or cityscape as recognizable foreground and midground"
        ),
    )
    forbidden_direction = next(
        (
            direction
            for city_key, direction in PASSPORT_CITY_FORBIDDEN_SCENERY.items()
            if city_key in normalized_city
        ),
        "geography, architecture, or landmarks that do not exist in the destination",
    )
    return f"""
Create a bright, cinematic editorial travel scene inspired by {safe_city}.

Destination: {safe_city}
Region: {safe_region or "Use the destination's surrounding region"}
Country: {safe_country or "Infer from the destination"}
Mood: {safe_mood}
Listening situation: {safe_situation}

Local visual direction:
- {city_direction}
- use only geography and landmarks that genuinely belong to {safe_city}
- specifically exclude: {forbidden_direction}

Visual direction:
- the destination must be recognizable through its geography, cityscape,
  coastline, mountains, river, harbor, architecture, or local landscape
- include at least one clear foreground or midground subject
- the lower half of the image must contain visible land, city, water,
  mountains, or architecture
- blue hour, soft sunset, dawn, or a luminous early night
- refined independent travel magazine aesthetic
- inviting, calm, modern, premium, and welcoming rather than dark or ominous
- compose specifically for a wide horizontal Music Boarding Pass thumbnail
- keep the main visual subject inside the central safe area
- the important subject must remain clearly visible after a wide horizontal crop
- use a locally recognizable view without placing a giant landmark in the center
- never substitute scenery from another city or country
- luminous midtones, readable scenery, gentle haze, and restrained contrast

Avoid:
- only sky, only clouds, empty gradients, or vague abstract scenery
- horror-like darkness, black fog, empty shadows, or haunted atmosphere
- unidentifiable abstract forms
- giant branches, palm leaves, furniture, or dark silhouettes
- airplane wings
- giant isolated landmarks
- tourist postcard composition
- text, letters, numbers, logos, flags
- people
- window frames, arches, oval frames
- generic music notes
- headphones

Create visual artwork only. Leave every word, label, stamp and code to the HTML overlay.
""".strip()


def generate_passport_thumbnail(
    city: str,
    mood: str,
    situation: str,
    region: str = "",
    country: str = "",
) -> str:
    """Generate one square thumbnail and return it as a PNG Data URI."""
    api_key = get_required_secret(
        "OPENAI_API_KEY",
        "passport_thumbnail_api_key",
    )
    client = OpenAI(api_key=api_key, timeout=120.0, max_retries=1)
    result = client.images.generate(
        model=PASSPORT_THUMBNAIL_MODEL,
        prompt=build_passport_thumbnail_prompt(
            city,
            mood,
            situation,
            region=region,
            country=country,
        ),
        size="1024x1024",
        quality="low",
    )
    if not result.data or not result.data[0].b64_json:
        raise RuntimeError("passport_thumbnail_missing_image_data")
    image_bytes = base64.b64decode(result.data[0].b64_json)
    if not image_bytes:
        raise RuntimeError("passport_thumbnail_empty_image")
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    logger.info(
        "[OPENAI] passport thumbnail generated model=%s bytes=%s",
        PASSPORT_THUMBNAIL_MODEL,
        len(image_bytes),
    )
    return f"data:image/png;base64,{image_base64}"


def ensure_passport_thumbnail(
    stage_callback: Callable[[str], None] | None = None,
) -> None:
    """Generate once per city, mood and situation after recommendation success."""
    signature = (
        st.session_state.get("city"),
        st.session_state.get("mood"),
        st.session_state.get("situation"),
    )
    if (
        st.session_state.get("passport_thumbnail_signature") == signature
        and (
            st.session_state.get("passport_thumbnail_base64")
            or st.session_state.get("passport_thumbnail_error")
        )
    ):
        return

    journey_result = st.session_state.get("music_journey_result") or {}
    geography = journey_result.get("geography") or {}
    thumbnail_destination = (
        journey_result.get("destination")
        or signature[0]
    )
    if (
        st.session_state.get("music_journey_error")
        or not journey_result.get("tracks")
        or any(not value for value in signature)
    ):
        return

    st.session_state["passport_thumbnail_base64"] = ""
    st.session_state["passport_thumbnail_error"] = ""
    try:
        if stage_callback:
            stage_callback("thumbnail")
        st.session_state["passport_thumbnail_base64"] = (
            generate_passport_thumbnail(
                city=str(thumbnail_destination),
                mood=str(signature[1]),
                situation=str(signature[2]),
                region=str(
                    geography.get("region_local")
                    or geography.get("region")
                    or ""
                ),
                country=str(
                    geography.get("country_local")
                    or geography.get("country")
                    or ""
                ),
            )
        )
    except Exception:
        logger.exception(
            "passport_thumbnail_generation_failed stage=image_api model=%s",
            PASSPORT_THUMBNAIL_MODEL,
        )
        st.session_state["passport_thumbnail_error"] = (
            "passport_thumbnail_generation_failed"
        )
    finally:
        st.session_state["passport_thumbnail_signature"] = signature


def render_lyra_orb_image(variant: str) -> str:
    """Return the shared LYRA WebP at a variant-specific display size."""
    return (
        f'<img class="lyra-orb-image lyra-orb-image--{variant}" '
        f'src="{get_lyra_image_data_uri()}" alt="" aria-hidden="true">'
    )


def render_ai_avatar() -> str:
    """Return the shared compact LYRA music orb."""
    return (
        '<div class="avatar" role="img" aria-label="LYRA 음악 오브">'
        f'{render_lyra_orb_image("avatar")}'
        "</div>"
    )


def render_ai_message(message: str) -> None:
    st.markdown(
        f"""
        <div class="message-row chat-message">
            {render_ai_avatar()}
            <div>
                <p class="speaker">LYRA · MUSIC GUIDE</p>
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


def retry_recommendation_from_recovery(message: str) -> None:
    """Retry without clearing the user's completed recommendation answers."""
    append_chat_message("user", message)
    st.session_state.pop("music_journey_result", None)
    st.session_state.pop("music_journey_error", None)
    st.session_state.pop("music_journey_signature", None)
    st.session_state["recovery_choice"] = None
    st.session_state["recovery_message_added"] = False
    st.session_state["direct_input_mode"] = False
    st.session_state["direct_input_field"] = None
    st.session_state["current_question"] = "complete"
    st.session_state["conversation_step"] = "complete"
    st.session_state["should_scroll_conversation"] = True


def lyra_auto_retry_label() -> str:
    """Return the first-run or later-round LYRA retry label."""
    retry_rounds = int(
        (st.session_state.get("recovery_context") or {}).get(
            "retry_attempt_count"
        )
        or 0
    )
    return (
        "✨ LYRA가 알아서 다시 찾아볼게요"
        if retry_rounds == 0
        else "✨ LYRA가 다른 길로 다시 찾아볼게요"
    )


def start_lyra_auto_retry(message: str) -> None:
    """Retry with staged query relaxation while freezing destination and count."""
    recovery_context = dict(st.session_state.get("recovery_context") or {})
    completed_rounds = int(
        recovery_context.get("retry_attempt_count") or 0
    )
    if completed_rounds >= LYRA_AUTO_RETRY_MAX_ROUNDS:
        return
    requested_count = int(
        recovery_context.get("requested_count")
        or st.session_state.get("track_count")
    )
    recovery_context.update(
        {
            "requested_count": requested_count,
            "destination": recovery_context.get("destination")
            or st.session_state.get("city"),
            "lyra_auto_retry": True,
            "lyra_auto_exhausted": False,
            "retry_attempt_count": completed_rounds + 1,
            "failed_queries": list(
                recovery_context.get("failed_queries") or ()
            ),
            "seen_track_ids": list(
                recovery_context.get("seen_track_ids") or ()
            ),
            "seen_track_keys": list(
                recovery_context.get("seen_track_keys") or ()
            ),
        }
    )
    st.session_state["track_count"] = requested_count
    st.session_state["recovery_context"] = recovery_context
    add_timeout_retry_strategy(
        "LYRA 자동 단계 검색: 검색어 변경 → 근접 장르 → 음악적 특징 "
        "변환 → 관련 요소 확장 → BPM·보컬 우선도 완화"
    )
    retry_recommendation_from_recovery(message)
    append_chat_message(
        "ai",
        "🎧 LYRA가 다른 길까지 살펴보고 있어요…<br>"
        "조금만 기다려주세요. 이번에는 제가 끝까지 찾아볼게요. ✨",
    )


def select_recovery_choice(choice: str) -> None:
    """Apply one recovery action while preserving existing answers."""
    if st.session_state.get("current_question") != RECOVERY_STEP:
        return
    labels = {
        "lyra_auto": lyra_auto_retry_label(),
        "expand_scope": "🌍 지역 범위를 조금 넓힐게요",
        "relax_conditions": "🎛️ 조건을 조금 완화할게요",
        "retry_same": "🔁 같은 조건으로 다시 시도할게요",
    }
    if choice == "direct_input":
        st.session_state["recovery_choice"] = choice
        st.session_state["direct_input_mode"] = True
        st.session_state["direct_input_field"] = RECOVERY_STEP
        st.session_state[direct_input_state_key(RECOVERY_STEP)] = ""
        return
    if choice == "restart":
        reset_conversation()
        return
    if choice == "lyra_auto":
        start_lyra_auto_retry(labels[choice])
        return
    if choice == "relax_conditions":
        if st.session_state.get("vocal") == "연주곡":
            st.session_state["vocal"] = "둘 다"
            explanation = "연주곡만 찾던 조건을 보컬과 연주곡 모두로 넓힐게요."
        elif st.session_state.get("tempo") == "느리고 잔잔하게":
            st.session_state["tempo"] = "적당한 속도로"
            explanation = "느린 템포 조건을 중간 템포까지 넓힐게요."
        elif st.session_state.get("discovery_level") == "처음 듣는 낯선 음악 중심":
            st.session_state["discovery_level"] = "익숙함과 새로움을 반반"
            explanation = "낯선 음악 중심 조건을 익숙함과 새로움의 균형으로 완화할게요."
        else:
            st.session_state["discovery_level"] = "익숙함과 새로움을 반반"
            explanation = "탐색 범위를 익숙함과 새로움의 균형으로 완화할게요."
        retry_recommendation_from_recovery(labels[choice])
        append_chat_message("ai", explanation)
        return
    retry_recommendation_from_recovery(labels[choice])


def submit_recovery_direct_input() -> None:
    """Apply a recovery-only free-text adjustment and retry."""
    input_key = direct_input_state_key(RECOVERY_STEP)
    raw_answer = str(st.session_state.get(input_key) or "").strip()
    if (
        not raw_answer
        or st.session_state.get("current_question") != RECOVERY_STEP
        or st.session_state.get("recovery_choice") != "direct_input"
    ):
        return
    extracted = extract_chat_conditions(raw_answer)
    for field in ("city", "tempo", "vocal", "discovery_level"):
        if field in extracted:
            st.session_state[field] = extracted[field]
    lowered = raw_answer.casefold()
    if "보컬" in lowered and ("빼" in lowered or "상관없" in lowered):
        st.session_state["vocal"] = "상관없어요"
    if "템포" in lowered and ("빼" in lowered or "상관없" in lowered):
        st.session_state["tempo"] = "상관없어요"
    st.session_state["free_text_preferences"] = raw_answer
    st.session_state[input_key] = ""
    retry_recommendation_from_recovery(raw_answer)


def render_recovery_choices() -> None:
    """Render the existing button style for the insufficient-track recovery."""
    auto_exhausted = bool(
        (st.session_state.get("recovery_context") or {}).get(
            "lyra_auto_exhausted"
        )
    )
    retry_rounds = int(
        (st.session_state.get("recovery_context") or {}).get(
            "retry_attempt_count"
        )
        or 0
    )
    auto_available = retry_rounds < LYRA_AUTO_RETRY_MAX_ROUNDS
    if auto_exhausted:
        options = (
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    elif retry_rounds > 0:
        options = (
            *(
                ((lyra_auto_retry_label(), "lyra_auto"),)
                if auto_available
                else ()
            ),
            ("🌍 지역 범위를 조금 넓힐게요", "expand_scope"),
            ("🎛️ 조건을 조금 완화할게요", "relax_conditions"),
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    else:
        options = (
            (lyra_auto_retry_label(), "lyra_auto"),
            ("🌍 지역 범위를 조금 넓힐게요", "expand_scope"),
            ("🎛️ 조건을 조금 완화할게요", "relax_conditions"),
            ("🔁 같은 조건으로 다시 시도할게요", "retry_same"),
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    with st.container(key="insufficient_tracks_recovery-choices"):
        st.markdown(
            '<p class="choice-label">하나를 선택해주세요.</p>',
            unsafe_allow_html=True,
        )
        for index, (label, choice) in enumerate(options, start=1):
            st.button(
                label,
                key=f"insufficient-tracks-recovery-{index}",
                use_container_width=True,
                on_click=select_recovery_choice,
                args=(choice,),
            )


def add_timeout_retry_strategy(strategy: str) -> None:
    """Vary the next search while preserving every completed user answer."""
    preferences = str(
        st.session_state.get("free_text_preferences") or ""
    ).rstrip()
    retry_line = (
        f"재검색 전략: {strategy}; 직전 후보와 검색어 제외; "
        f"새 검색 순서 {time.time_ns()}"
    )
    st.session_state["free_text_preferences"] = (
        f"{preferences}\n{retry_line}".strip()
    )


def select_timeout_recovery_choice(choice: str) -> None:
    """Apply a timeout-specific recovery action without changing track count."""
    if st.session_state.get("current_question") != RECOMMENDATION_TIMEOUT_STEP:
        return
    labels = {
        "lyra_auto": lyra_auto_retry_label(),
        "expand_scope": "🌍 지역 범위를 조금 넓힐게요",
        "relax_conditions": "🎛️ 조건을 조금 완화할게요",
        "retry_same": "🔁 같은 조건으로 다시 시도할게요",
    }
    if choice == "direct_input":
        st.session_state["recovery_choice"] = choice
        st.session_state["direct_input_mode"] = True
        st.session_state["direct_input_field"] = RECOMMENDATION_TIMEOUT_STEP
        st.session_state[
            direct_input_state_key(RECOMMENDATION_TIMEOUT_STEP)
        ] = ""
        return
    if choice == "restart":
        reset_conversation()
        return
    if choice == "relax_conditions":
        if st.session_state.get("vocal") == "연주곡":
            st.session_state["vocal"] = "둘 다"
        elif st.session_state.get("tempo") == "느리고 잔잔하게":
            st.session_state["tempo"] = "적당한 속도로"
        else:
            st.session_state["discovery_level"] = "익숙함과 새로움을 반반"
        add_timeout_retry_strategy(
            "여행지와 곡 수는 유지하고 BPM·보컬·취향 요소의 우선도만 완화"
        )
    elif choice == "expand_scope":
        add_timeout_retry_strategy(
            "같은 여행지를 중심으로 주변 지역과 동일 문화권까지 확장"
        )
    elif choice == "lyra_auto":
        start_lyra_auto_retry(labels[choice])
        return
    else:
        add_timeout_retry_strategy(
            "조건은 유지하고 후보 순서와 검색어 조합만 변경"
        )
    retry_recommendation_from_recovery(labels[choice])


def submit_timeout_recovery_direct_input() -> None:
    """Apply a timeout-only free-text adjustment and retry."""
    input_key = direct_input_state_key(RECOMMENDATION_TIMEOUT_STEP)
    raw_answer = str(st.session_state.get(input_key) or "").strip()
    if (
        not raw_answer
        or st.session_state.get("current_question")
        != RECOMMENDATION_TIMEOUT_STEP
        or st.session_state.get("recovery_choice") != "direct_input"
    ):
        return
    add_timeout_retry_strategy(f"사용자 조정: {raw_answer}")
    st.session_state[input_key] = ""
    retry_recommendation_from_recovery(raw_answer)


def render_timeout_recovery_choices() -> None:
    """Render the timeout recovery actions with the existing button style."""
    auto_exhausted = bool(
        (st.session_state.get("recovery_context") or {}).get(
            "lyra_auto_exhausted"
        )
    )
    retry_rounds = int(
        (st.session_state.get("recovery_context") or {}).get(
            "retry_attempt_count"
        )
        or 0
    )
    auto_available = retry_rounds < LYRA_AUTO_RETRY_MAX_ROUNDS
    if auto_exhausted:
        options = (
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    elif retry_rounds > 0:
        options = (
            *(
                ((lyra_auto_retry_label(), "lyra_auto"),)
                if auto_available
                else ()
            ),
            ("🌍 지역 범위를 조금 넓힐게요", "expand_scope"),
            ("🎛️ 조건을 조금 완화할게요", "relax_conditions"),
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    else:
        options = (
            (lyra_auto_retry_label(), "lyra_auto"),
            ("🌍 지역 범위를 조금 넓힐게요", "expand_scope"),
            ("🎛️ 조건을 조금 완화할게요", "relax_conditions"),
            ("🔁 같은 조건으로 다시 시도할게요", "retry_same"),
            ("✏️ 직접 조건을 바꿀게요", "direct_input"),
            ("↩️ 처음부터 다시 시작할게요", "restart"),
        )
    with st.container(key="recommendation_timeout_recovery-choices"):
        st.markdown(
            '<p class="choice-label">다른 길을 하나 골라주세요.</p>',
            unsafe_allow_html=True,
        )
        for index, (label, choice) in enumerate(options, start=1):
            st.button(
                label,
                key=f"recommendation-timeout-recovery-{index}",
                use_container_width=True,
                on_click=select_timeout_recovery_choice,
                args=(choice,),
            )


def render_choices(question_key: str) -> None:
    """Render numbered quick choices for only the active question."""
    options = QUESTION_CONFIG[question_key]["options"]
    with st.container(key=f"{question_key}-choices"):
        is_multiselect = question_key in {
            "favorite_genres",
            "favorite_reasons",
        }
        choice_label = (
            "여러 개 선택할 수 있어요. 최대 3개까지 골라주세요."
            if is_multiselect
            else "하나를 선택해주세요."
        )
        st.markdown(
            f'<p class="choice-label">{choice_label}</p>',
            unsafe_allow_html=True,
        )
        columns = st.columns(2)
        selected = get_preference_section(question_key) if is_multiselect else []
        for index, (value, label) in enumerate(options, start=1):
            with columns[(index - 1) % 2]:
                if is_multiselect and value != "__direct__":
                    st.button(
                        label,
                        key=f"{question_key}-{index}",
                        use_container_width=True,
                        type="primary" if value in selected else "secondary",
                        on_click=toggle_preference_choice,
                        args=(question_key, value, label),
                    )
                else:
                    button_label = label
                    st.button(
                        button_label,
                        key=f"{question_key}-{index}",
                        use_container_width=True,
                        on_click=submit_chat_answer,
                        args=(question_key, label),
                    )
        if is_multiselect:
            st.button(
                "선택 완료 →",
                key=f"{question_key}-complete",
                use_container_width=True,
                disabled=not selected,
                on_click=finish_preference_multiselect,
                args=(question_key,),
            )


st.set_page_config(
    page_title="Music Passport · Step 1",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

for chat_field in CHAT_FIELDS:
    if chat_field not in st.session_state:
        st.session_state[chat_field] = None

for direct_input_key in DIRECT_INPUT_STATE_KEYS.values():
    if direct_input_key not in st.session_state:
        st.session_state[direct_input_key] = ""

for destination_state_key in (
    "destination_raw_input",
    "destination_canonical_name",
    "destination_display_name",
    "destination_country_name",
    "destination_type",
):
    if destination_state_key not in st.session_state:
        st.session_state[destination_state_key] = ""

if "free_text_preferences" not in st.session_state:
    st.session_state["free_text_preferences"] = ""

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = [
        {
            "role": "ai",
            "content": QUESTION_CONFIG["journey_mode"]["question"],
        }
    ]
    st.session_state["current_question"] = get_next_question()
    st.session_state["conversation_step"] = st.session_state["current_question"]

if st.session_state.get("current_question") not in STEPS:
    st.session_state["current_question"] = get_next_question()

if st.session_state.get("conversation_step") not in STEPS:
    st.session_state["conversation_step"] = st.session_state["current_question"]

if "input_error" not in st.session_state:
    st.session_state["input_error"] = ""

if "direct_input_mode" not in st.session_state:
    st.session_state["direct_input_mode"] = False

if "direct_input_field" not in st.session_state:
    st.session_state["direct_input_field"] = None

if (
    st.session_state["direct_input_mode"]
    and st.session_state["direct_input_field"]
    != st.session_state.get("current_question")
):
    st.session_state["direct_input_mode"] = False
    st.session_state["direct_input_field"] = None

if st.session_state.get("active_screen") not in ("intro", "chat", "result"):
    st.session_state["active_screen"] = "intro"

if "should_scroll_conversation" not in st.session_state:
    st.session_state["should_scroll_conversation"] = False

if "passport_thumbnail_base64" not in st.session_state:
    st.session_state["passport_thumbnail_base64"] = ""

if "passport_thumbnail_signature" not in st.session_state:
    st.session_state["passport_thumbnail_signature"] = None

if "passport_thumbnail_error" not in st.session_state:
    st.session_state["passport_thumbnail_error"] = ""

if "generation_stage" not in st.session_state:
    st.session_state["generation_stage"] = None

if "recovery_message_added" not in st.session_state:
    st.session_state["recovery_message_added"] = False

st.markdown(
    """
    <style>
    :root {
        color-scheme: dark;
        --journey-layout-gap: clamp(1.5rem, 3vw, 3rem);
        --journey-window-width: clamp(320px, 32vw, 480px);
        --journey-window-aspect: 115 / 239;
        --journey-visual-top: clamp(1.5rem, 4vh, 3rem);
    }

    .stApp, [data-testid="stAppViewContainer"] > .main {
        background:
            radial-gradient(circle at 80% 8%, rgba(67, 94, 151, .22), transparent 30rem),
            linear-gradient(155deg, #101d3a 0%, #071126 52%, #040a18 100%);
        color: #f7f8ff;
    }

    .stApp:has(.st-key-intro-screen),
    [data-testid="stAppViewContainer"]:has(.st-key-intro-screen) > .main {
        background:
            radial-gradient(
                circle at 72% 42%,
                rgba(110, 90, 180, .10),
                transparent 38%
            ),
            radial-gradient(
                circle at 20% 58%,
                rgba(60, 110, 170, .09),
                transparent 42%
            ),
            linear-gradient(
                145deg,
                #08142d 0%,
                #0b1731 48%,
                #111a38 72%,
                #161634 100%
            );
    }

    [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], #MainMenu, footer { display: none; }

    .block-container {
        max-width: 1280px;
        min-height: 100svh;
        padding: 0 2rem 3rem;
    }

    .st-key-intro-screen,
    .st-key-chat-screen {
        width: 100%;
        max-width: 1280px;
        margin-inline: auto;
    }

    .st-key-intro-screen {
        overflow: clip;
    }

    .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) {
        align-items: flex-start;
        flex-wrap: nowrap;
        gap: var(--journey-layout-gap);
        padding-left: 0;
    }

    .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) > [data-testid="column"] {
        min-width: 0;
    }

    .chat-visual-area {
        position: relative;
        min-height: calc(100svh - 2rem);
        width: 100%;
        overflow: hidden;
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding-top: var(--journey-visual-top);
    }

    .st-key-chat-screen [data-testid="column"]:has(.chat-visual-area),
    .st-key-chat-screen [data-testid="column"]:has(.chat-visual-area) > [data-testid="stVerticalBlock"],
    .st-key-chat-screen [data-testid="stElementContainer"]:has(.chat-visual-area),
    .st-key-chat-screen [data-testid="stMarkdownContainer"]:has(.chat-visual-area),
    .chat-visual-area,
    .chat-visual-area::before,
    .chat-visual-area::after,
    .journey-visual-background--chat,
    .journey-visual-background--chat::before,
    .journey-visual-background--chat::after {
        border: 0 !important;
        outline: 0 !important;
        box-shadow: none !important;
    }

    .st-key-intro_stage {
        position: relative;
        width: 100%;
        min-height: calc(100svh - 2rem);
    }

    .st-key-intro_stage > [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-intro_stage > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
    .st-key-intro_stage > [data-testid="stVerticalBlock"] {
        position: relative;
        width: 100%;
        min-height: calc(100svh - 2rem);
        display: block;
    }

    .st-key-intro_window_slot {
        position: absolute;
        left: 2.5%;
        top: 51%;
        width: min(560px, 43vw);
        transform: translateY(-50%);
    }

    .st-key-intro_window_slot .intro-window-area {
        position: relative;
        width: 100%;
        min-height: 0;
        padding: 0;
        overflow: visible;
    }

    .intro-window-crossfade {
        position: relative;
        width: 100%;
        aspect-ratio: 363 / 495;
    }

    .intro-window-frame {
        position: absolute;
        inset: 0;
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain !important;
        opacity: 0;
        pointer-events: none;
        will-change: opacity;
        animation: intro-window-crossfade 24s linear infinite;
    }

    .intro-window-frame--dawn {
        opacity: 1;
        animation-delay: 0s;
    }

    .intro-window-frame--sunset {
        animation-delay: -18s;
    }

    .intro-window-frame--bluehour {
        animation-delay: -12s;
    }

    .intro-window-frame--night {
        animation-delay: -6s;
    }

    @keyframes intro-window-crossfade {
        0%, 20.833% {
            opacity: 1;
        }
        25%, 95.833% {
            opacity: 0;
        }
        100% {
            opacity: 1;
        }
    }

    .st-key-intro_right_group {
        position: absolute;
        top: 10%;
        right: 4.5%;
        width: 410px;
        height: 700px;
        z-index: 2;
    }

    .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
    .st-key-intro_right_group > [data-testid="stVerticalBlock"] {
        width: 100%;
        height: 700px;
    }

    .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
    .st-key-intro_right_group > [data-testid="stVerticalBlock"] {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 0;
    }

    .st-key-intro_title_slot {
        position: relative;
        inset: auto;
        width: 410px;
        height: auto;
        z-index: 2;
    }

    .intro-content {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 0;
    }

    .intro-title-en {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
    }

    .intro-brand-title {
        margin: 0;
        background: linear-gradient(90deg, #f3efff 0%, #c9dcff 52%, #d9c4ff 100%);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        -webkit-text-fill-color: transparent;
        font-family: Georgia, "Times New Roman", serif;
        font-size: clamp(1.78rem, 3.2vw, 3.02rem);
        font-weight: 500;
        letter-spacing: .05em;
        line-height: 1;
        white-space: nowrap;
        text-shadow: 0 0 24px rgba(171, 139, 224, .2);
    }

    .intro-brand-subtitle {
        margin: 10px 0 0;
        color: rgba(190, 208, 238, .82);
        font-size: clamp(14px, 1.05vw, 16px);
        font-weight: 500;
        line-height: 1.55;
        letter-spacing: .06em;
    }

    .intro-description-ko {
        width: 100%;
        max-width: 420px;
        margin: 18px 0 0;
        color: rgba(194, 208, 235, .78);
        font-size: clamp(14px, 1.05vw, 16px);
        font-weight: 500;
        line-height: 1.55;
        letter-spacing: -.01em;
    }

    .intro-description-ko p {
        margin: 0;
    }

    .intro-description-ko p + p {
        margin-top: 2px;
    }

    .st-key-intro_lyra_visual {
        position: relative;
        inset: auto;
        width: 370px;
        height: 430px;
        margin-top: clamp(62px, calc(17svh - 68px), 82px);
        transform: none;
        --lyra-bubble-fill:
            radial-gradient(
                circle at 24% 18%,
                rgba(255, 255, 255, .08),
                transparent 34%
            ),
            linear-gradient(
                145deg,
                rgba(67, 76, 119, .78),
                rgba(27, 37, 75, .90)
            );
    }

    .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
    .st-key-intro_lyra_visual > [data-testid="stVerticalBlock"] {
        position: relative;
        width: 100%;
        height: 430px;
        display: block;
    }

    .st-key-intro_lyra_visual::before {
        content: "";
        position: absolute;
        left: 204px;
        right: auto;
        top: 364px;
        z-index: 1;
        width: 132px;
        height: 34px;
        transform: translateX(-50%);
        border-radius: 50%;
        background:
            radial-gradient(
                ellipse at center,
                rgba(238, 210, 255, .70) 0%,
                rgba(190, 145, 255, .44) 30%,
                rgba(105, 135, 255, .22) 54%,
                rgba(105, 135, 255, 0) 78%
            );
        filter: blur(9px);
        opacity: .90;
        pointer-events: none;
    }

    .st-key-intro_lyra_visual::after {
        content: "";
        position: absolute;
        left: 204px;
        right: auto;
        top: 375px;
        z-index: 1;
        width: 72px;
        height: 10px;
        transform: translateX(-50%);
        border-radius: 999px;
        background:
            radial-gradient(
                ellipse at center,
                rgba(247, 231, 255, .58),
                rgba(247, 231, 255, 0) 74%
            );
        filter: blur(3px);
        opacity: .7;
        pointer-events: none;
    }

    .intro-bubble {
        position: relative;
        top: 0;
        z-index: 2;
        box-sizing: border-box;
        width: min(390px, 100%);
        height: auto;
        min-height: 0;
        margin: 0;
        padding: 22px 26px;
        border: 1px solid rgba(208, 189, 245, .50);
        border-radius: 22px;
        background: var(--lyra-bubble-fill);
        color: #f1f2fa;
        font-size: clamp(1.02rem, 1.95vw, 1.18rem);
        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, .1),
            0 14px 32px rgba(0, 0, 0, .20),
            0 0 22px rgba(172, 139, 234, .14);
    }

    .intro-lyra-bubble__text {
        margin: 0;
        line-height: 1.65;
    }

    .intro-lyra-connector {
        position: absolute;
        right: 60px;
        top: 166px;
        z-index: 4;
        width: 80px;
        height: 52px;
        pointer-events: none;
    }

    .intro-lyra-connector .connector-ring {
        position: absolute;
        display: block;
        border: 1.5px solid rgba(210, 190, 255, .68);
        border-radius: 50%;
        background: transparent;
        box-shadow:
            0 0 8px rgba(185, 148, 255, .16),
            inset 0 0 5px rgba(220, 205, 255, .08);
        pointer-events: none;
    }

    .intro-lyra-connector .connector-ring--large {
        top: 8px;
        right: 4px;
        width: 24px;
        height: 24px;
    }

    .intro-lyra-connector .connector-ring--small {
        top: 34px;
        right: 34px;
        width: 12px;
        height: 12px;
        border-width: 1px;
        opacity: .82;
    }

    .st-key-intro_ai_orb_container {
        position: absolute;
        left: 130px;
        top: 214px;
        z-index: 3;
        width: 148px;
        height: 148px;
        margin: 0;
        animation: intro-lyra-float 4s ease-in-out infinite;
    }

    .st-key-intro_ai_orb_container .logo-mark {
        position: absolute;
        z-index: 20;
        inset: 0;
        width: 148px;
        height: 148px;
        flex-basis: 148px;
        background: transparent;
        box-shadow: none;
        pointer-events: none;
    }

    .st-key-intro_ai_orb_container .logo-mark::before,
    .st-key-intro_ai_orb_container .logo-mark::after {
        pointer-events: none;
    }

    .st-key-intro_ai_orb_container .lyra-orb-image {
        display: block;
        width: 148px;
        height: 148px;
        object-fit: contain;
        opacity: 1;
        mix-blend-mode: normal;
        filter:
            drop-shadow(0 0 10px rgba(210, 176, 255, .62))
            drop-shadow(0 0 24px rgba(123, 164, 255, .28));
    }

    .intro-lyra-sparkles {
        position: absolute;
        inset: -20px;
        z-index: 8;
        pointer-events: none;
    }

    .intro-lyra-sparkles .sparkle {
        position: absolute;
        display: block;
        --particle-min-opacity: .20;
        --particle-max-opacity: .55;
        --particle-duration: 3.8s;
        --particle-delay: 0s;
        opacity: var(--particle-min-opacity);
        animation:
            lyra-particle-glow
            var(--particle-duration)
            ease-in-out
            var(--particle-delay)
            infinite;
        pointer-events: none;
    }

    .intro-lyra-sparkles .sparkle-dot {
        border-radius: 50%;
        background: rgba(236, 224, 255, .58);
        box-shadow:
            0 0 3px rgba(218, 196, 255, .42),
            0 0 6px rgba(137, 160, 255, .18);
    }

    .intro-lyra-sparkles .sparkle-dot--strong {
        --particle-min-opacity: .28;
        --particle-max-opacity: .70;
        box-shadow:
            0 0 4px rgba(226, 205, 255, .48),
            0 0 8px rgba(137, 160, 255, .22);
    }

    .intro-lyra-sparkles .sparkle-star {
        --particle-min-opacity: .24;
        --particle-max-opacity: .65;
        background: transparent;
        filter:
            drop-shadow(0 0 2px rgba(226, 210, 255, .42))
            drop-shadow(0 0 5px rgba(145, 166, 255, .18));
    }

    .intro-lyra-sparkles .sparkle-star::before,
    .intro-lyra-sparkles .sparkle-star::after {
        content: "";
        position: absolute;
        left: 50%;
        top: 50%;
        border-radius: 999px;
        background: rgba(242, 230, 255, .76);
        transform: translate(-50%, -50%);
    }

    .intro-lyra-sparkles .sparkle-star::before {
        width: 1.25px;
        height: 100%;
    }

    .intro-lyra-sparkles .sparkle-star::after {
        width: 100%;
        height: 1.25px;
    }

    .intro-lyra-sparkles .sparkle--1 {
        top: 86px;
        left: 5px;
        width: 2px;
        height: 2px;
        --particle-duration: 3.6s;
    }

    .intro-lyra-sparkles .sparkle--2 {
        top: 5px;
        left: 50px;
        width: 3px;
        height: 3px;
        --particle-duration: 4.4s;
        --particle-delay: .6s;
    }

    .intro-lyra-sparkles .sparkle--3 {
        top: 10px;
        left: 88px;
        width: 2px;
        height: 2px;
        --particle-duration: 3.9s;
        --particle-delay: 1.2s;
    }

    .intro-lyra-sparkles .sparkle--4 {
        top: 82px;
        right: 3px;
        width: 4px;
        height: 4px;
        --particle-duration: 4.8s;
        --particle-delay: 1.8s;
    }

    .intro-lyra-sparkles .sparkle--5 {
        left: 12px;
        bottom: 34px;
        width: 2px;
        height: 2px;
        --particle-min-opacity: .18;
        --particle-max-opacity: .45;
        --particle-duration: 3.4s;
        --particle-delay: 2.4s;
    }

    .intro-lyra-sparkles .sparkle--6 {
        right: 18px;
        bottom: 30px;
        width: 3px;
        height: 3px;
        --particle-min-opacity: .18;
        --particle-max-opacity: .45;
        --particle-duration: 4.2s;
        --particle-delay: .9s;
    }

    .intro-lyra-sparkles .sparkle--7 {
        top: 108px;
        left: 6px;
        width: 1.5px;
        height: 1.5px;
        --particle-duration: 5s;
        --particle-delay: 1.5s;
    }

    .intro-lyra-sparkles .sparkle--8 {
        top: 30px;
        left: 32px;
        width: 7px;
        height: 7px;
        --particle-duration: 4.6s;
        --particle-delay: .3s;
    }

    .intro-lyra-sparkles .sparkle--9 {
        top: 24px;
        right: 22px;
        width: 5px;
        height: 5px;
        --particle-duration: 3.8s;
        --particle-delay: 1.1s;
    }

    .intro-lyra-sparkles .sparkle--10 {
        top: 64px;
        right: 12px;
        width: 6px;
        height: 6px;
        --particle-duration: 4.9s;
        --particle-delay: 2s;
    }

    .st-key-intro_ai_orb_button,
    .st-key-intro_ai_orb_button .stButton {
        position: absolute !important;
        inset: 0 !important;
        z-index: 50 !important;
        width: 148px !important;
        height: 148px !important;
        pointer-events: auto !important;
    }

    .st-key-intro_ai_orb_container .stButton > button {
        position: absolute;
        z-index: 3;
        inset: 0;
        width: 148px !important;
        min-width: 148px !important;
        height: 148px !important;
        min-height: 148px !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 50% !important;
        background: transparent !important;
        box-shadow: none !important;
        opacity: 0 !important;
        cursor: pointer;
        pointer-events: auto !important;
    }

    @keyframes intro-lyra-float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-4px); }
    }

    @keyframes lyra-particle-glow {
        0%, 100% {
            opacity: var(--particle-min-opacity);
            transform: translateY(0) scale(.88);
        }
        50% {
            opacity: var(--particle-max-opacity);
            transform: translateY(-2px) scale(1.02);
        }
    }

    .journey-visual-background {
        position: relative;
        flex: 0 0 auto;
        width: min(var(--journey-window-width), calc((100svh - 5rem) * 115 / 239));
        max-width: 100%;
        height: auto;
        aspect-ratio: var(--journey-window-aspect);
        background-position: center;
        background-repeat: no-repeat;
        background-size: contain;
    }

    .journey-visual-overlay {
        position: absolute;
        inset: 0;
        display: none;
        pointer-events: none;
    }

    .journey-visual-background--chat {
        filter: blur(6px);
        transform: scale(1.035);
        overflow: hidden;
        border-radius: 999px;
    }

    .journey-visual-background--chat .journey-visual-overlay {
        display: block;
        background: rgba(4, 12, 29, .16);
    }

    .st-key-chat_panel {
        position: relative;
        isolation: isolate;
        height: min(720px, calc(100svh - 2rem));
        min-height: 620px;
        overflow: hidden;
        border: 1px solid rgba(190, 207, 241, .2);
        border-radius: 28px;
        background:
            linear-gradient(165deg, rgba(24, 40, 75, .96), rgba(8, 18, 40, .98));
        box-shadow: 0 24px 64px rgba(0, 0, 0, .32);
    }

    .st-key-chat_panel
    > [data-testid="stVerticalBlockBorderWrapper"]
    > [data-testid="stVerticalBlock"],
    .st-key-chat_panel > [data-testid="stVerticalBlock"],
    .st-key-chat_panel[data-testid="stVerticalBlock"] {
        display: grid !important;
        grid-template-rows: auto minmax(0, 1fr) auto auto !important;
        height: 100% !important;
        min-height: 0 !important;
        gap: 0 !important;
    }

    .st-key-chat_panel
    > [data-testid="stVerticalBlockBorderWrapper"]
    > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"],
    .st-key-chat_panel
    > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"],
    .st-key-chat_panel[data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"] {
        display: contents;
    }

    .st-key-chat_header {
        grid-row: 1;
        min-height: 0;
        position: relative;
        z-index: 10;
        flex: 0 0 auto;
        overflow: hidden;
        background:
            linear-gradient(
                165deg,
                rgba(24, 40, 75, 1),
                rgba(18, 34, 67, 1)
            );
    }

    .st-key-conversation_area {
        grid-row: 2;
        position: relative;
        isolation: isolate;
        contain: paint;
        clip-path: inset(0);
    }

    .st-key-input_dock {
        grid-row: 3;
    }

    .st-key-chat_navigation {
        grid-row: 4;
    }

    .chat-panel-header {
        position: relative;
        z-index: 10;
        min-height: 86px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 1rem 1.25rem;
        border-bottom: 1px solid rgba(206, 220, 255, .14);
        overflow: hidden;
        background:
            linear-gradient(
                165deg,
                rgba(24, 40, 75, 1),
                rgba(18, 34, 67, 1)
            );
    }

    .chat-panel-identity {
        min-width: 0;
        display: flex;
        align-items: center;
        gap: .75rem;
    }

    .chat-panel-titles {
        min-width: 0;
    }

    .chat-panel-kicker,
    .chat-panel-title {
        margin: 0;
    }

    .chat-panel-kicker {
        color: #8f9fbe;
        font-size: .62rem;
        font-weight: 700;
        letter-spacing: .1em;
    }

    .chat-panel-title {
        margin-top: .15rem;
        color: #f7f8ff;
        font-size: .92rem;
        font-weight: 700;
        letter-spacing: .06em;
    }

    .st-key-conversation_area {
        height: 100% !important;
        min-height: 0 !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        padding: 1rem 1.25rem 1.25rem;
        scroll-padding-top: 1rem;
        scrollbar-color: rgba(151, 172, 212, .45) transparent;
        scrollbar-width: thin;
    }

    .st-key-conversation_area
    > [data-testid="stVerticalBlockBorderWrapper"] {
        position: relative;
        height: 100% !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }

    .st-key-conversation_area
    > [data-testid="stVerticalBlockBorderWrapper"]
    > [data-testid="stVerticalBlock"],
    .st-key-conversation_area > [data-testid="stVerticalBlock"] {
        position: relative;
        height: 100% !important;
        max-height: 100% !important;
        min-height: 0 !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        overscroll-behavior: contain;
    }

    .st-key-conversation_area .chat-message {
        margin-top: 1.25rem;
    }

    .st-key-conversation_area .bubble,
    .st-key-conversation_area .user-bubble {
        max-width: 100%;
        overflow-wrap: anywhere;
        word-break: keep-all;
    }

    .st-key-conversation_area .message-row > div:last-child {
        min-width: 0;
        max-width: calc(100% - 3rem);
    }

    .journey-loading {
        margin: 1rem 0;
        padding: .85rem 1rem;
        border: 1px solid rgba(153, 181, 229, .2);
        border-radius: 12px;
        background: rgba(18, 34, 67, .68);
        color: #c8d4ef;
        font-size: .84rem;
        line-height: 1.6;
        overflow-wrap: anywhere;
    }

    .lyra-typing-row {
        display: flex;
        justify-content: flex-start;
        margin-top: 10px;
    }

    .lyra-generation-status .journey-loading {
        margin-bottom: 0;
    }

    .lyra-typing-bubble {
        min-width: 54px;
        height: 34px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
        padding: 0 14px;
        border: 1px solid rgba(152, 176, 220, .24);
        border-radius: 18px;
        background:
            linear-gradient(
                145deg,
                rgba(35, 58, 103, .82),
                rgba(27, 46, 86, .88)
            );
        box-shadow: 0 8px 18px rgba(0, 0, 0, .12);
    }

    .lyra-typing-bubble span {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: rgba(205, 218, 246, .82);
        animation: lyra-typing-dot 1.25s ease-in-out infinite;
    }

    .lyra-typing-bubble span:nth-child(1) { animation-delay: 0s; }
    .lyra-typing-bubble span:nth-child(2) { animation-delay: .16s; }
    .lyra-typing-bubble span:nth-child(3) { animation-delay: .32s; }

    @keyframes lyra-typing-dot {
        0%, 60%, 100% {
            opacity: .34;
            transform: translateY(0) scale(.92);
        }
        30% {
            opacity: 1;
            transform: translateY(-3px) scale(1);
        }
    }

    .st-key-conversation_area .journey-api-error {
        margin: 1rem 0 0 3.2rem;
        padding: .8rem .9rem;
        border: 1px solid rgba(142, 167, 211, .34);
        border-left: 3px solid rgba(153, 181, 229, .62);
        border-radius: 10px;
        background: linear-gradient(145deg, rgba(34, 54, 91, .86), rgba(20, 37, 68, .92));
        color: #d7e0f2;
        font-size: .76rem;
        line-height: 1.5;
    }

    .st-key-chat_panel .choice-label {
        margin: 1.15rem 0 .65rem;
    }

    .st-key-chat_panel .st-key-mood-choices [data-testid="stHorizontalBlock"],
    .st-key-chat_panel .st-key-situation-choices [data-testid="stHorizontalBlock"],
    .st-key-chat_panel .st-key-city-choices [data-testid="stHorizontalBlock"] {
        gap: .65rem;
        padding-left: 0;
    }

    .st-key-chat_panel .st-key-mood-choices .stButton > button,
    .st-key-chat_panel .st-key-situation-choices .stButton > button,
    .st-key-chat_panel .st-key-city-choices .stButton > button {
        min-height: 58px;
        padding: .65rem .5rem;
    }

    .st-key-input_dock {
        padding: .85rem 1rem;
        border-top: 1px solid rgba(206, 220, 255, .1);
        background: linear-gradient(
            180deg,
            rgba(10, 23, 49, .72),
            rgba(55, 75, 111, .48)
        );
    }

    .st-key-input_dock [data-testid="stHorizontalBlock"] {
        align-items: center;
        gap: .5rem;
        padding-left: 0;
    }

    .st-key-input_dock [data-testid="stTextInput"] input:disabled {
        color: rgba(20, 29, 50, .62);
        -webkit-text-fill-color: rgba(20, 29, 50, .62);
        background: rgba(240, 244, 252, .88);
        border-color: rgba(255, 255, 255, .16);
        opacity: 1;
    }

    .st-key-input_dock [data-testid="stTextInput"] input:not(:disabled) {
        color: #1c2947;
        -webkit-text-fill-color: #1c2947;
        background: rgba(240, 244, 252, .94);
        border-color: rgba(255, 255, 255, .22);
    }

    .st-key-input_dock .stButton > button {
        min-height: 40px;
        width: 40px;
        padding: 0;
        border-radius: 50%;
    }

    .st-key-input_dock .stButton > button:disabled {
        min-height: 40px;
        width: 40px;
        padding: 0;
        border-radius: 50%;
        background: rgba(71, 101, 160, .5);
        color: rgba(235, 241, 255, .55);
        transform: none;
        box-shadow: none;
        cursor: not-allowed;
    }

    .chat-input-error {
        margin: .45rem 0 0;
        color: #ffc1b8;
        font-size: .74rem;
        line-height: 1.4;
    }

    .st-key-chat_navigation {
        padding: .65rem 1rem .75rem;
        border-top: 1px solid rgba(206, 220, 255, .1);
    }

    .st-key-chat_navigation .st-key-restart {
        margin: 0;
    }

    .st-key-chat_navigation .st-key-restart .stButton > button {
        min-height: 36px;
        padding: .4rem .7rem;
        border-color: rgba(175, 198, 239, .14);
        color: #8998b7;
        font-size: .75rem;
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
        flex: 0 0 34px;
        border: 0;
        border-radius: 50%;
        background: transparent;
        box-shadow:
            inset 0 1px 4px rgba(255, 255, 255, .3),
            0 0 10px rgba(183, 143, 255, .34),
            0 0 18px rgba(103, 151, 255, .18);
    }

    .chat-panel-header .logo-mark,
    .message-row .avatar {
        position: relative;
        overflow: hidden;
        background: transparent;
        box-shadow: 0 0 6px rgba(195, 163, 255, .24);
    }

    .chat-panel-header .lyra-orb-image--header,
    .message-row .lyra-orb-image--avatar {
        position: absolute;
        left: 50%;
        top: 49%;
        display: block;
        width: 235%;
        height: 235%;
        max-width: none;
        object-fit: contain;
        object-position: center;
        transform: translate(-50%, -50%);
        filter: none;
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

    .message-row { display: flex; align-items: flex-start; gap: 0.85rem; }
    .chat-message { margin-top: 2.2rem; }
    .avatar {
        width: 30px;
        height: 30px;
        flex: 0 0 30px;
        display: grid;
        place-items: center;
        border: 0;
        border-radius: 50%;
        background: transparent;
        box-shadow:
            inset 0 1px 4px rgba(255, 255, 255, .3),
            0 0 9px rgba(183, 143, 255, .32),
            0 0 16px rgba(103, 151, 255, .16);
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

    .st-key-mood-choices [data-testid="stHorizontalBlock"],
    .st-key-situation-choices [data-testid="stHorizontalBlock"],
    .st-key-city-choices [data-testid="stHorizontalBlock"] {
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

    .st-key-favorite_genres-choices .stButton > button[kind="primary"],
    .st-key-favorite_reasons-choices .stButton > button[kind="primary"],
    .st-key-favorite_genres-choices button[data-testid="stBaseButton-primary"],
    .st-key-favorite_reasons-choices button[data-testid="stBaseButton-primary"] {
        position: relative;
        padding-right: 2.35rem;
        border-color: rgba(205, 177, 255, .88) !important;
        background: linear-gradient(
            145deg,
            rgba(104, 82, 162, .94),
            rgba(55, 48, 112, .96)
        ) !important;
        color: #fff !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, .14),
            0 0 0 1px rgba(191, 157, 255, .16),
            0 8px 22px rgba(137, 99, 213, .24) !important;
    }

    .st-key-favorite_genres-choices .stButton > button[kind="primary"]::after,
    .st-key-favorite_reasons-choices .stButton > button[kind="primary"]::after,
    .st-key-favorite_genres-choices button[data-testid="stBaseButton-primary"]::after,
    .st-key-favorite_reasons-choices button[data-testid="stBaseButton-primary"]::after {
        content: "✓";
        position: absolute;
        top: 8px;
        right: 9px;
        display: grid;
        place-items: center;
        width: 18px;
        height: 18px;
        border: 1px solid rgba(236, 225, 255, .72);
        border-radius: 999px;
        background: rgba(224, 204, 255, .2);
        color: #f8f3ff;
        font-size: 11px;
        line-height: 1;
    }

    .st-key-favorite_genres-choices .stButton > button:disabled,
    .st-key-favorite_reasons-choices .stButton > button:disabled {
        border-color: rgba(156, 170, 198, .14);
        background: rgba(87, 98, 121, .24);
        color: rgba(187, 197, 216, .42);
        box-shadow: none;
        cursor: not-allowed;
    }

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

    .st-key-result_attachments {
        width: 100%;
        max-width: 100%;
        min-width: 0;
        margin-top: 1rem;
        overflow-x: hidden;
    }

    .st-key-journey_preview {
        width: 100%;
        max-width: 100%;
        min-width: 0;
        margin-top: .8rem;
        overflow: hidden;
        border: 1px solid rgba(186, 204, 240, .22);
        border-radius: 18px;
        background: linear-gradient(150deg, rgba(44, 65, 108, .78), rgba(17, 32, 66, .92));
        box-shadow: 0 12px 28px rgba(0, 0, 0, .2);
    }

    .city-image {
        position: relative;
        overflow: hidden;
        background-position: center;
        background-size: cover;
        isolation: isolate;
    }

    .city-image::before {
        content: "";
        position: absolute;
        z-index: 2;
        inset: 8% 5%;
        border: 7px solid rgba(218, 226, 244, .15);
        border-radius: 44% 44% 40% 40% / 24% 24% 34% 34%;
        box-shadow: inset 0 0 0 2px rgba(5, 12, 28, .4);
        pointer-events: none;
    }

    .city-image-haze {
        position: absolute;
        z-index: 1;
        inset: 0;
        background:
            linear-gradient(180deg, rgba(229, 235, 251, .08), transparent 42%),
            radial-gradient(circle at 50% 72%, rgba(235, 239, 250, .13), transparent 48%);
        backdrop-filter: blur(1.5px);
    }

    .city-image--preview.city-image--generated .city-image-haze {
        background: linear-gradient(
            180deg,
            rgba(5, 12, 30, 0),
            rgba(5, 12, 30, .06)
        );
        backdrop-filter: none;
    }

    .city-image--preview.city-image--generated {
        background-position: center;
        background-size: cover;
        filter: brightness(1.06) saturate(1.03);
    }

    .city-image--preview {
        width: 100%;
        aspect-ratio: 16 / 9;
        border-radius: 17px 17px 0 0;
    }

    .city-image--preview::before {
        content: none !important;
    }

    .city-image--preview::after {
        content: none !important;
    }

    .preview-departure-stamp {
        position: absolute;
        z-index: 3;
        top: 66px;
        right: 18px;
        width: 84px;
        min-height: 70px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 8px 10px;
        border: 1.6px solid currentColor;
        border-radius: 50%;
        color: rgba(197, 209, 231, .82);
        background: rgba(13, 30, 60, .08);
        font-size: 6px;
        font-weight: 700;
        line-height: 1.14;
        letter-spacing: .1em;
        text-align: center;
        text-transform: uppercase;
        transform: rotate(-6deg);
        opacity: .84;
    }

    .preview-departure-stamp::before {
        content: "";
        position: absolute;
        inset: 5px;
        border: 1px solid currentColor;
        border-radius: 50%;
        opacity: .52;
        pointer-events: none;
    }

    .preview-departure-stamp::after,
    .result-departure-stamp::after {
        content: "";
        position: absolute;
        inset: 2px 7px;
        background: repeating-linear-gradient(
            174deg,
            transparent 0 9px,
            rgba(13, 30, 60, .16) 9px 10px,
            transparent 10px 17px
        );
        opacity: .22;
        pointer-events: none;
    }

    .preview-departure-stamp__route {
        display: block;
        margin-top: 2px;
        font-size: 6px;
        letter-spacing: .1em;
    }

    .city-image--서울 {
        background:
            radial-gradient(circle at 65% 66%, rgba(188, 160, 255, .4), transparent 4%),
            linear-gradient(155deg, #172c5f, #403878 58%, #111c39);
    }

    .city-image--런던 {
        background:
            radial-gradient(circle at 70% 56%, rgba(255, 187, 99, .45), transparent 8%),
            linear-gradient(155deg, #4b515b, #777064 55%, #292d34);
    }

    .city-image--파리 {
        background:
            radial-gradient(circle at 36% 42%, rgba(255, 235, 225, .44), transparent 24%),
            linear-gradient(155deg, #c98f9d, #d5a8a7 52%, #66536b);
    }

    .city-image--도쿄 {
        background:
            radial-gradient(circle at 72% 62%, rgba(229, 73, 175, .38), transparent 16%),
            linear-gradient(150deg, #142f63, #334c8d 48%, #7c2e70);
    }

    .city-image--마라케시 {
        background:
            radial-gradient(circle at 66% 28%, rgba(255, 211, 132, .45), transparent 20%),
            linear-gradient(155deg, #b96b45, #d69a60 52%, #713e35);
    }

    .city-image--리우 {
        background:
            radial-gradient(circle at 68% 30%, rgba(255, 213, 135, .48), transparent 22%),
            linear-gradient(155deg, #d57447, #d99b67 48%, #355f78);
    }

    .city-image--default {
        background: linear-gradient(155deg, #243968, #4a527a 52%, #131d3f);
    }

    .result-preview-card {
        position: relative;
        padding: 1rem 1rem .35rem;
    }

    .boarding-pass-preview-title {
        white-space: nowrap;
        font-size: clamp(18px, 1.55vw, 23px) !important;
        line-height: 1.15;
        letter-spacing: .02em !important;
    }

    .boarding-pass-preview-body .result-preview-subtitle,
    .boarding-pass-preview-body .passport-preview-data dd:nth-of-type(-n + 4) {
        padding-right: 102px;
    }

    .result-preview-card h3,
    .result-preview-card p {
        margin: 0;
    }

    .result-preview-card h3 {
        color: #f4f6ff;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 1rem;
        letter-spacing: .08em;
    }

    .result-preview-subtitle {
        margin-top: .35rem !important;
        color: #9eadd0;
        font-size: .72rem;
    }

    .passport-preview-data {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: .35rem .8rem;
        margin-top: .85rem;
        font-size: .8rem;
    }

    .passport-preview-data dt {
        color: #8494b8;
    }

    .passport-preview-data dd {
        min-width: 0;
        margin: 0;
        color: #eef2ff;
        overflow-wrap: anywhere;
    }

    .st-key-result_attachments .stButton > button {
        width: calc(100% - 1.5rem);
        min-height: 42px;
        margin: 0 .75rem .75rem;
        border-radius: 12px;
        background: rgba(8, 19, 43, .42);
        color: #cbd6f0;
        font-size: .78rem;
        box-shadow: none;
    }

    .st-key-result_attachments .stButton > button:hover {
        transform: translateY(-1px);
        background: rgba(30, 49, 87, .72);
        color: #fff;
        box-shadow: none;
    }

    .st-key-result_screen {
        width: 100%;
        max-width: 1180px;
        margin-inline: auto;
        padding: 1.25rem 0 2rem;
    }

    .result-screen-header {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 1rem;
        padding: 0 0 1rem;
        border-bottom: 1px solid rgba(206, 220, 255, .16);
    }

    .result-screen-header h1,
    .result-screen-header p {
        margin: 0;
    }

    .result-screen-header h1 {
        color: #f7f8ff;
        font-family:
            "Pretendard",
            "Noto Sans KR",
            "Noto Sans JP",
            Arial,
            sans-serif;
        font-size: clamp(1.6rem, 3vw, 2.4rem);
        font-weight: 700;
        letter-spacing: -.02em;
    }

    .result-screen-header p {
        color: #8fa0c3;
        font-size: .75rem;
        letter-spacing: .08em;
    }

    .st-key-result_screen [data-testid="stHorizontalBlock"]:has(.passport-detail-card) {
        align-items: stretch;
        flex-wrap: nowrap;
        gap: clamp(1.25rem, 3vw, 2.5rem);
        padding: 1.5rem 0 0;
    }

    .st-key-result_screen [data-testid="stHorizontalBlock"]:has(.passport-detail-card) > [data-testid="column"] {
        min-width: 0;
    }

    .passport-detail-card,
    .playlist-detail-card {
        min-height: 540px;
        height: 100%;
        padding: clamp(1.25rem, 3vw, 2rem);
        border: 1px solid rgba(186, 204, 240, .2);
        border-radius: 24px;
        background: linear-gradient(155deg, rgba(34, 54, 94, .94), rgba(10, 23, 50, .98));
        box-shadow: 0 22px 54px rgba(0, 0, 0, .28);
    }

    .passport-detail-card {
        position: relative;
        overflow: hidden;
        isolation: isolate;
        min-height: 680px;
        padding: 0;
        display: flex;
        flex-direction: column;
        background: #0d1c3a;
    }

    .passport-hero {
        position: relative;
        min-height: 300px;
        overflow: hidden;
        isolation: isolate;
    }

    .passport-detail-image {
        position: absolute;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        background-position: center;
        background-size: cover;
        filter: blur(.5px) brightness(1.12) saturate(1.04);
        transform: scale(1.04);
    }

    .passport-hero::after {
        content: "";
        position: absolute;
        inset: 0;
        z-index: 1;
        background: linear-gradient(
            to bottom,
            rgba(5, 12, 30, .02) 0%,
            rgba(5, 12, 30, .08) 48%,
            rgba(5, 12, 30, .38) 100%
        );
        pointer-events: none;
    }

    .passport-hero-content {
        position: relative;
        z-index: 2;
        min-height: 300px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        padding: 1.5rem;
    }

    .result-detail-label {
        margin: 0;
        color: #8fa0c4;
        font-size: .68rem;
        font-weight: 700;
        letter-spacing: .12em;
    }

    .result-detail-title {
        margin: .45rem 0 0;
        color: #f4f6ff;
        font-family: Georgia, "Times New Roman", serif;
        font-size: clamp(1.35rem, 2.5vw, 2rem);
        font-weight: 500;
    }

    .passport-hero .result-detail-label,
    .passport-hero .result-detail-title,
    .passport-hero-message {
        color: #f7f8ff;
        text-shadow: 0 1px 6px rgba(6, 12, 30, .34);
    }

    .passport-hero-message {
        margin: .55rem 0 0;
        font-size: .66rem;
        letter-spacing: .11em;
    }

    .passport-ticket-info {
        flex: 1 1 auto;
        padding: 1.35rem 1.5rem 1.2rem;
        border-top: 1px solid rgba(205, 220, 255, .16);
        background: linear-gradient(145deg, #172b52, #102241);
    }

    .passport-detail-data {
        display: grid;
        grid-template-columns: 5rem minmax(0, 1fr);
        gap: .72rem 1rem;
        margin: 0;
    }

    .passport-detail-data dt {
        color: #91a8d0;
        font-size: .65rem;
        font-weight: 700;
        letter-spacing: .13em;
    }

    .passport-detail-data dd {
        min-width: 0;
        margin: 0;
        color: #f1f4ff;
        font-size: .88rem;
        overflow-wrap: anywhere;
    }

    .passport-flight-meta {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .75rem;
        margin-top: 1.2rem;
        padding-top: 1rem;
        border-top: 1px dashed rgba(190, 210, 245, .28);
    }

    .passport-flight-meta span {
        display: block;
        color: #8198c2;
        font-size: .58rem;
        letter-spacing: .12em;
    }

    .passport-flight-meta strong {
        display: block;
        margin-top: .28rem;
        color: #eef3ff;
        font-size: .72rem;
        font-weight: 600;
    }

    .result-departure-stamp {
        position: absolute;
        z-index: 5;
        right: 18px;
        top: 18px;
        width: 104px;
        min-height: 86px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 10px 12px;
        border: 2px solid currentColor;
        border-radius: 50%;
        color: rgba(197, 209, 231, .86);
        background: rgba(13, 30, 60, .18);
        font-size: 8px;
        font-weight: 700;
        line-height: 1.16;
        letter-spacing: .1em;
        text-align: center;
        text-transform: uppercase;
        transform: rotate(-7deg);
        opacity: .92;
    }

    .result-departure-stamp::before {
        content: "";
        position: absolute;
        inset: 6px;
        border: 1px solid currentColor;
        border-radius: 50%;
        opacity: .56;
        pointer-events: none;
    }

    .result-departure-stamp__text {
        position: relative;
        z-index: 1;
        font-size: 8px;
        font-weight: 700;
        line-height: 1.16;
        letter-spacing: .1em;
        text-align: center;
    }

    .result-departure-stamp__route,
    .result-departure-stamp__date {
        display: block;
        margin-top: 2px;
        font-size: 7px;
        letter-spacing: .1em;
    }

    .passport-ticket-footer {
        display: grid;
        grid-template-columns: 96px minmax(0, 1fr);
        column-gap: 24px;
        align-items: start;
        padding: 1rem 1.5rem 1.2rem;
        border-top: 1px dashed rgba(190, 210, 245, .3);
        background: #0b1934;
    }

    .passport-ticket-footer--no-qr {
        grid-template-columns: minmax(0, 1fr);
    }

    .result-ticket-qr-column,
    .result-ticket-barcode-column {
        display: grid;
        grid-template-rows: 96px 18px;
        row-gap: 8px;
        align-items: center;
        min-width: 0;
    }

    .result-ticket-qr-column {
        color: #aebddb;
        text-align: center;
        text-decoration: none;
    }

    .result-ticket-qr {
        width: 96px;
        height: 96px;
        display: grid;
        place-items: center;
        border-radius: 10px;
        background: #13264c;
    }

    .result-ticket-qr-image {
        display: block;
        width: 92px;
        height: 92px;
    }

    .result-ticket-qr-label,
    .result-ticket-barcode-label {
        min-height: 18px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0;
        color: #a9b9d8;
        font-size: 9px;
        line-height: 1;
        letter-spacing: .1em;
        text-align: center;
    }

    .result-ticket-barcode-box {
        width: 100%;
        height: 96px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 14px 18px;
        box-sizing: border-box;
    }

    .ticket-barcode {
        width: 100%;
        height: 52px;
        display: flex;
        align-items: stretch;
        justify-content: center;
        gap: 2px;
        padding: 8px 10px;
        margin: 0;
        box-sizing: border-box;
        border-radius: 6px;
        background: #eaf0ff;
    }

    .ticket-barcode .bar {
        display: block;
        height: 100%;
        background: #07142d;
    }

    .ticket-barcode .w1 { width: 2px; }
    .ticket-barcode .w2 { width: 4px; }
    .ticket-barcode .w3 { width: 6px; }
    .ticket-barcode .w4 { width: 8px; }

    .result-ticket-barcode-label {
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        letter-spacing: .12em;
    }

    .playlist-track-list {
        display: grid;
        gap: .75rem;
        margin-top: 1.5rem;
    }

    .playlist-journey-summary {
        margin: .75rem 0 0;
        color: #a7b4cf;
        font-size: .78rem;
        line-height: 1.55;
    }

    .playlist-track {
        display: grid;
        grid-template-columns: 2rem 48px minmax(0, 1fr);
        align-items: center;
        gap: .7rem;
        padding: .7rem 0;
        border-bottom: 1px solid rgba(206, 220, 255, .1);
    }

    .playlist-track-number {
        color: #ffb172;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 1rem;
    }

    .playlist-album-image,
    .playlist-album-placeholder {
        width: 48px;
        height: 48px;
        border-radius: 8px;
        object-fit: cover;
        background: linear-gradient(145deg, rgba(105, 127, 171, .36), rgba(34, 51, 87, .6));
    }

    .playlist-track-copy {
        min-width: 0;
    }

    .playlist-track-title,
    .playlist-track-artist,
    .playlist-track-album,
    .playlist-track-reason {
        margin: 0;
        overflow-wrap: anywhere;
    }

    .playlist-track-title {
        color: #f1f4ff;
        font-size: .88rem;
    }

    .playlist-track-artist {
        margin-top: .15rem;
        color: #8596ba;
        font-size: .7rem;
    }

    .playlist-track-album {
        margin-top: .12rem;
        color: #7182a6;
        font-size: .64rem;
    }

    .playlist-track-reason {
        margin-top: .35rem;
        color: #a6b2cc;
        font-size: .68rem;
        line-height: 1.4;
    }

    .spotify-link-wrap {
        margin: 0;
    }

    .spotify-text-link {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        margin-top: 9px;
        padding: 0;
        border: 0;
        background: transparent;
        color: rgba(190, 203, 226, 0.72);
        box-shadow: none;
        font-size: 11px;
        font-weight: 600;
        text-decoration: none;
        white-space: nowrap;
        transition: color 160ms ease;
    }

    .spotify-text-link:hover {
        color: rgba(239, 244, 252, 0.96);
        text-decoration: underline;
        text-underline-offset: 3px;
    }

    .spotify-ci-icon {
        width: 14px;
        height: 14px;
        flex: 0 0 14px;
        color: currentColor;
        fill: currentColor;
    }

    .st-key-result_navigation {
        margin-top: 1rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(206, 220, 255, .12);
    }

    .st-key-result_navigation [data-testid="stHorizontalBlock"] {
        gap: .75rem;
        padding-left: 0;
    }

    .st-key-result_navigation .stButton > button {
        min-height: 44px;
        border-radius: 12px;
        background: rgba(24, 42, 78, .68);
        color: #c2cde5;
        font-size: .8rem;
        box-shadow: none;
    }

    @media (min-width: 641px) {
        .st-key-chat-screen {
            min-height: calc(100svh - 1rem);
        }

        .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) {
            min-height: calc(100svh - 1rem);
            align-items: stretch;
        }

        .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) > [data-testid="column"] {
            align-self: stretch;
        }

        .st-key-chat-screen [data-testid="column"]:has(.st-key-chat_panel),
        .st-key-chat-screen [data-testid="column"]:has(.st-key-chat_panel) > [data-testid="stVerticalBlock"] {
            min-height: 0;
            height: 100%;
        }

        .st-key-chat_panel {
            width: 100%;
            flex: 0 0 clamp(700px, calc(100svh - 1rem), 860px) !important;
            height: clamp(700px, calc(100svh - 1rem), 860px) !important;
            min-height: 0;
            max-height: 860px;
        }

        .st-key-conversation_area {
            height: 100% !important;
            min-height: 0;
            overflow-y: auto;
        }

        .st-key-conversation_area > [data-testid="stVerticalBlockBorderWrapper"] {
            height: 100% !important;
            min-height: 0;
        }
    }

    @media (max-width: 640px) {
        .block-container { padding: 0 1.15rem 2rem; }
        .journey-visual-background {
            width: min(70vw, 250px);
        }
        .intro-brand-title {
            font-size: clamp(1.35rem, 8vw, 1.85rem);
        }
        .intro-bubble {
            width: 100%;
            padding: 1rem 1.05rem;
            font-size: .95rem;
        }
        .passport-header { min-height: 72px; }
        .wordmark { font-size: 1.12rem; }
        .logo-mark { width: 34px; height: 34px; }
        .journey-intro { padding: 2rem 0 1.8rem; }
        .message-row { gap: 0.65rem; }
        .avatar { width: 30px; height: 30px; flex-basis: 30px; }
        .bubble { padding: 1.05rem 1.1rem; font-size: 0.98rem; }
        .choice-label, .travel-note { margin-left: 2.75rem; }
        .st-key-restart { margin-left: 2.75rem; }
        .st-key-mood-choices [data-testid="stHorizontalBlock"],
        .st-key-situation-choices [data-testid="stHorizontalBlock"],
        .st-key-city-choices [data-testid="stHorizontalBlock"] {
            padding-left: 2.75rem;
            gap: 0.5rem;
        }
        .st-key-mood-choices [data-testid="column"],
        .st-key-situation-choices [data-testid="column"],
        .st-key-city-choices [data-testid="column"] { min-width: calc(50% - 0.25rem); }
        .st-key-mood-choices [data-testid="stHorizontalBlock"],
        .st-key-situation-choices [data-testid="stHorizontalBlock"],
        .st-key-city-choices [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) {
            flex-wrap: wrap;
            gap: 2rem;
        }
        .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) > [data-testid="column"] {
            width: 100%;
            flex: 1 1 100%;
            min-width: 0;
        }
        .chat-visual-area {
            min-height: 360px;
            height: min(70svh, 520px);
            padding-top: 1.25rem;
        }
        .st-key-chat_panel {
            flex: 0 0 680px !important;
            height: 680px !important;
            min-height: 0;
            border-radius: 22px;
        }
        .chat-panel-header {
            min-height: 78px;
            padding: .85rem 1rem;
        }
        .st-key-conversation_area {
            height: 100% !important;
            padding-inline: 1rem;
        }
        .st-key-chat_panel .st-key-mood-choices [data-testid="stHorizontalBlock"],
        .st-key-chat_panel .st-key-situation-choices [data-testid="stHorizontalBlock"],
        .st-key-chat_panel .st-key-city-choices [data-testid="stHorizontalBlock"] {
            padding-left: 0;
        }
        .st-key-input_dock [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap;
        }
        .st-key-input_dock [data-testid="column"] {
            min-width: 0;
        }
        .st-key-result_screen [data-testid="stHorizontalBlock"]:has(.passport-detail-card) {
            flex-wrap: wrap;
            gap: 1rem;
        }
        .st-key-result_screen [data-testid="stHorizontalBlock"]:has(.passport-detail-card) > [data-testid="column"] {
            width: 100%;
            flex: 1 1 100%;
            min-width: 0;
        }
        .passport-detail-card,
        .playlist-detail-card {
            min-height: 0;
        }
        .passport-hero,
        .passport-hero-content {
            min-height: 260px;
        }
        .passport-flight-meta {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .passport-ticket-footer {
            grid-template-columns: 96px minmax(0, 1fr);
            column-gap: 12px;
            padding-inline: 1rem;
        }
        .passport-ticket-footer--no-qr {
            grid-template-columns: minmax(0, 1fr);
        }
        .playlist-track {
            grid-template-columns: 1.75rem 44px minmax(0, 1fr);
        }
        .playlist-album-image,
        .playlist-album-placeholder {
            width: 44px;
            height: 44px;
        }
        .st-key-result_navigation [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        .st-key-result_navigation [data-testid="column"] {
            width: 100%;
            flex: 1 1 100%;
            min-width: 0;
        }
        .stButton > button { min-height: 66px; padding: .65rem .45rem; }
    }

    @media (min-width: 821px) {
        :root {
            --mp-window-width: min(660px, 39vw, calc((100svh - 2rem) * .63));
            --mp-window-left: 3%;
            --mp-window-top: calc(50svh - 1rem - 42px);
            --mp-window-aspect: 363 / 495;
        }

        .st-key-chat-screen [data-testid="stHorizontalBlock"]:has(.chat-visual-area) {
            position: relative;
        }

        .chat-visual-area {
            position: static;
        }

        .st-key-intro_window_slot,
        .journey-visual-background--chat {
            left: var(--mp-window-left);
            top: var(--mp-window-top);
            width: var(--mp-window-width);
            aspect-ratio: var(--mp-window-aspect);
            transform: translateY(-50%);
        }

        .journey-visual-background--chat {
            position: absolute;
            max-width: 100%;
            background-size: contain;
        }
    }

    @media (max-width: 820px) {
        .st-key-intro-screen {
            overflow-x: clip;
            overflow-y: visible;
        }

        .st-key-intro_stage,
        .st-key-intro_stage > [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-intro_stage > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_stage > [data-testid="stVerticalBlock"] {
            min-height: 0;
        }

        .st-key-intro_stage > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_stage > [data-testid="stVerticalBlock"] {
            display: flex;
            flex-direction: column;
            gap: 0;
            padding: 1rem 0 2rem;
        }

        .st-key-intro_window_slot,
        .st-key-intro_right_group,
        .st-key-intro_title_slot,
        .st-key-intro_lyra_visual {
            position: relative;
            inset: auto;
            transform: none;
        }

        .st-key-intro_window_slot {
            width: min(68vw, 270px);
            margin: 0 auto 1.5rem;
        }

        .intro-window-crossfade {
            width: 100%;
            height: auto;
            max-height: 48svh;
        }

        .st-key-intro_title_slot {
            width: min(100%, 360px);
            height: auto;
            margin: 0 auto 2.4rem;
        }

        .st-key-intro_right_group,
        .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_right_group > [data-testid="stVerticalBlock"] {
            width: 100%;
            height: auto;
        }

        .st-key-intro_right_group > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_right_group > [data-testid="stVerticalBlock"] {
            align-items: stretch;
        }

        .st-key-intro_lyra_visual {
            width: min(100%, 350px);
            height: 430px;
            margin: 0 auto;
        }

        .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_lyra_visual > [data-testid="stVerticalBlock"] {
            height: 430px;
        }

        .intro-bubble {
            top: 0;
            width: 100%;
        }

        .st-key-intro_ai_orb_container {
            left: auto;
            right: 58px;
            top: 214px;
        }

        .st-key-intro_lyra_visual::before {
            right: 66px;
            left: auto;
            top: 364px;
            transform: none;
        }

        .st-key-intro_lyra_visual::after {
            right: 96px;
            left: auto;
            top: 375px;
            transform: none;
        }
    }

    @media (max-width: 640px) {
        .st-key-intro_lyra_visual,
        .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-intro_lyra_visual > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        .st-key-intro_lyra_visual > [data-testid="stVerticalBlock"] {
            height: 430px;
        }

        .st-key-intro_ai_orb_container {
            top: 214px;
        }

        .st-key-intro_lyra_visual::before {
            top: 364px;
        }

        .st-key-intro_lyra_visual::after {
            top: 375px;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .stButton > button { transition: none; }
        .st-key-intro_ai_orb_container { animation: none; }
        .intro-lyra-sparkles .sparkle { animation: none; }
        .lyra-typing-bubble span {
            animation: none !important;
            opacity: .68;
            transform: none;
        }
        .intro-window-frame {
            animation: none !important;
            opacity: 0;
        }
        .intro-window-frame--dawn {
            opacity: 1;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def render_intro_window() -> None:
    """Render the four Intro window scenes as one crossfade visual."""
    scene_markup = "".join(
        (
            f'<img class="intro-window-frame intro-window-frame--{scene_name}" '
            f'src="{get_intro_window_scene_image(relative_path)}" alt="">'
        )
        for scene_name, relative_path in INTRO_WINDOW_SCENES
    )
    st.markdown(
        f"""
        <section class="intro-window-area" aria-label="Music Passport">
            <div class="intro-window-crossfade" aria-hidden="true">
                {scene_markup}
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_intro_ai_orb() -> None:
    """Render the Chat LYRA orb with a transparent native click layer."""
    with st.container(key="intro_ai_orb_container"):
        st.markdown(
            (
                '<span class="logo-mark" role="img" aria-label="LYRA 음악 오브">'
                f'{render_lyra_orb_image("header")}'
                "</span>"
                '<span class="intro-lyra-sparkles" aria-hidden="true">'
                '<span class="sparkle sparkle-dot sparkle--1"></span>'
                '<span class="sparkle sparkle-dot sparkle--2"></span>'
                '<span class="sparkle sparkle-dot sparkle--3"></span>'
                '<span class="sparkle sparkle-dot sparkle-dot--strong sparkle--4"></span>'
                '<span class="sparkle sparkle-dot sparkle--5"></span>'
                '<span class="sparkle sparkle-dot sparkle--6"></span>'
                '<span class="sparkle sparkle-dot sparkle--7"></span>'
                '<span class="sparkle sparkle-star sparkle--8"></span>'
                '<span class="sparkle sparkle-star sparkle--9"></span>'
                '<span class="sparkle sparkle-star sparkle--10"></span>'
                "</span>"
            ),
            unsafe_allow_html=True,
        )
        st.button(
            "",
            key="intro_ai_orb_button",
            on_click=enter_chat,
        )


def render_intro_preview() -> None:
    """Render the Intro greeting and LYRA orb."""
    with st.container(key="intro_lyra_visual"):
        st.markdown(
            """
            <div class="intro-bubble">
                <p class="intro-lyra-bubble__text">안녕하세요😊<br>당신의 음악 여행 가이드, Lyra예요.<br>함께 어울리는 음악을 찾아볼까요?</p>
            </div>
            <div class="intro-lyra-connector" aria-hidden="true">
                <span class="connector-ring connector-ring--large"></span>
                <span class="connector-ring connector-ring--small"></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_intro_ai_orb()


def render_intro_screen() -> None:
    """Render the Figma-inspired Intro without changing the Chat experience."""
    with st.container(key="intro-screen"):
        with st.container(key="intro_stage"):
            with st.container(key="intro_window_slot"):
                render_intro_window()
            with st.container(key="intro_right_group"):
                with st.container(key="intro_title_slot"):
                    st.markdown(
                        """
                        <div class="intro-content">
                            <div class="intro-title-en">
                                <h1 class="intro-brand-title">MUSIC PASSPORT</h1>
                                <p class="intro-brand-subtitle">좋아하는 음악을 단서로, 아직 모르는 세계의 소리로.</p>
                            </div>
                            <div class="intro-description-ko">
                                <p>기분과 상황, 떠나고 싶은 도시를 알려주세요.</p>
                                <p>Lyra가 당신만의 음악 여정을 준비해드릴게요.</p>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                render_intro_preview()


def render_chat_header(step_number: int) -> None:
    """Render the fixed header at the top of the chat panel."""
    with st.container(key="chat_header"):
        st.markdown(
            f"""
            <header class="chat-panel-header">
                <div class="chat-panel-identity">
                    <span class="logo-mark" role="img" aria-label="LYRA 음악 오브">
                        {render_lyra_orb_image("header")}
                    </span>
                    <div class="chat-panel-titles">
                        <p class="chat-panel-kicker">YOUR QUIET COMPANION</p>
                        <p class="chat-panel-title">LYRA · MUSIC GUIDE</p>
                    </div>
                </div>
                <div class="step">Step {step_number} / {len(CHAT_FIELDS)}</div>
            </header>
            """,
            unsafe_allow_html=True,
        )


def update_generation_loading(placeholder, stage: str) -> None:
    """Update the one in-conversation loading region for the active stage."""
    st.session_state["generation_stage"] = stage
    destination = escape(str(st.session_state.get("city") or "선택한 목적지"))
    requested_count = int(st.session_state.get("track_count") or 5)
    journey = st.session_state.get("music_journey_result") or {}
    verified_count = len(journey.get("tracks") or [])
    message = {
        "mapping": f"🎧 {destination}의 음악 지도를 펼치고 있어요...",
        "boarding_pass": (
            f"✦ 당신의 조건에 맞는 {requested_count}곡을 고르고 있어요..."
        ),
        "thumbnail": (
            f"🛂 확인된 {verified_count or requested_count}곡을 "
            "Music Boarding Pass에 담고 있어요..."
        ),
    }.get(stage, GENERATION_STAGE_MESSAGES.get(stage))
    if message:
        typing_markup = (
            '<div class="lyra-typing-row" aria-label="LYRA가 입력 중입니다">'
            '<div class="lyra-typing-bubble" aria-hidden="true">'
            "<span></span><span></span><span></span>"
            "</div></div>"
            if stage in {"mapping", "verifying", "boarding_pass", "thumbnail"}
            else ""
        )
        placeholder.markdown(
            '<div class="lyra-generation-status">'
            f'<div class="journey-loading">{message}</div>'
            f"{typing_markup}"
            "</div>",
            unsafe_allow_html=True,
        )


def build_boarding_pass_ready_message() -> str:
    """Describe the completed pass using its verified destination and count."""
    journey = st.session_state.get("music_journey_result") or {}
    metadata = get_custom_destination_metadata(
        str(st.session_state.get("free_text_preferences") or "")
    )
    selected_destination = (
        metadata.get("canonical_name")
        or metadata.get("display")
        or str(st.session_state.get("city") or "")
    )
    city = escape(
        str(
            journey.get("destination_display_name")
            or metadata.get("display_name")
            or st.session_state.get("destination_display_name")
            or resolve_result_destination(journey, selected_destination)
        )
    )
    requested_count = int(st.session_state.get("track_count") or 5)
    geography = journey.get("geography") or {}
    country = escape(
        str(
            metadata.get("country_local")
            or geography.get("country_local")
            or ""
        ).strip()
    )
    used_levels = {
        str(track.get("connection_level"))
        for track in (journey.get("tracks") or [])
        if isinstance(track, dict) and track.get("connection_level")
    }
    if country and "country" in used_levels and country.casefold() != city.casefold():
        journey_line = (
            f"{city}에서 시작해 {country}까지 넓힌<br>"
            f"{requested_count}곡의 여정을"
        )
    else:
        journey_line = f"{city}로 떠나는 {requested_count}곡의 여정을"
    return (
        "준비가 끝났어요.<br><br>"
        f"{journey_line}<br>"
        "Music Boarding Pass에 담았습니다.<br><br>"
        "아래에서 오늘의 탑승권을 열어보세요."
    )


def scroll_conversation_to_bottom() -> None:
    """Scroll only the Conversation container after new chat content appears."""
    st.markdown('<div id="conversation-bottom-anchor"></div>', unsafe_allow_html=True)
    components.html(
        """
        <script>
        const conversation = window.parent.document.querySelector(
            ".st-key-conversation_area"
        );

        if (conversation) {
            const candidates = [conversation, ...conversation.querySelectorAll("*")];
            const scroller = candidates.find((element) => {
                const style = window.parent.getComputedStyle(element);
                return (
                    element.scrollHeight > element.clientHeight &&
                    ["auto", "scroll"].includes(style.overflowY)
                );
            }) || conversation;

            const scrollToLatest = () => {
                scroller.scrollTo({
                    top: scroller.scrollHeight,
                    behavior: "smooth"
                });
            };

            window.requestAnimationFrame(() => {
                window.requestAnimationFrame(scrollToLatest);
            });
        }
        </script>
        """,
        height=0,
        scrolling=False,
    )


def render_result_attachments() -> None:
    """Render one unified journey result as the latest Conversation attachment."""
    logger.info("[RESULT_RENDER_ENTER]")
    mood = escape(st.session_state.get("mood", "—"))
    situation = escape(st.session_state.get("situation", "—"))
    journey = st.session_state.get("music_journey_result") or {}
    metadata = get_custom_destination_metadata(
        str(st.session_state.get("free_text_preferences") or "")
    )
    raw_city = resolve_result_destination(
        journey,
        metadata.get("display")
        or str(st.session_state.get("city") or ""),
    )
    city = escape(raw_city)
    city_name = get_city_name(raw_city)
    city_code = CITY_CODES.get(city_name, "MP")
    tempo = escape(str(st.session_state.get("tempo") or "—"))
    vocal = escape(str(st.session_state.get("vocal") or "—"))
    discovery_level = escape(
        str(st.session_state.get("discovery_level") or "—")
    )
    requested_track_count = int(st.session_state.get("track_count") or 5)
    preview_stamp = (
        '<span class="preview-departure-stamp" aria-hidden="true">'
        'MUSIC PASSPORT<br>✈ DEPARTURE'
        f'<span class="preview-departure-stamp__route">LYRA · {city_code}</span>'
        '<span class="preview-departure-stamp__route">2026.08.02</span>'
        "</span>"
    )
    city_image = render_city_image_markup(raw_city, "preview")
    track_count = len(
        journey.get("tracks", [])
    )

    with st.container(key="result_attachments"):
        with st.container(key="journey_preview"):
            logger.info("[RESULT_RENDER_PREVIEW]")
            st.markdown(
                f"""
                {city_image}
                <article class="result-preview-card passport-preview-card boarding-pass-preview-body">
                    {preview_stamp}
                    <h3 class="boarding-pass-preview-title">🎫 MUSIC BOARDING PASS</h3>
                    <p class="result-preview-subtitle">{city_code} · {city}</p>
                    <dl class="passport-preview-data">
                        <dt>기분</dt><dd>{mood}</dd>
                        <dt>상황</dt><dd>{situation}</dd>
                        <dt>템포</dt><dd>{tempo}</dd>
                        <dt>보컬</dt><dd>{vocal}</dd>
                        <dt>탐색</dt><dd>{discovery_level}</dd>
                        <dt>요청</dt><dd>{requested_track_count}곡</dd>
                        <dt>구성</dt><dd>추천 플레이리스트 {track_count}곡 포함</dd>
                    </dl>
                </article>
                """,
                unsafe_allow_html=True,
            )
            logger.info("[RESULT_RENDER_BUTTON]")
            st.button(
                "결과 보기 →",
                key="journey-result-cta",
                use_container_width=True,
                on_click=open_result,
            )


def render_conversation() -> None:
    """Render the full conversation history and the current choices."""
    with st.container(key="conversation_area", border=False):
        current_question = st.session_state["current_question"]
        for message in st.session_state["chat_history"]:
            if message["role"] == "ai":
                render_ai_message(message["content"])
            else:
                render_user_message(message["content"])

        if current_question == "complete":
            signature = current_journey_signature()
            has_current_result = (
                st.session_state.get("music_journey_signature") == signature
                and "music_journey_result" in st.session_state
            )
            loading_placeholder = None

            def set_generation_stage(stage: str) -> None:
                nonlocal loading_placeholder
                created_placeholder = loading_placeholder is None
                if loading_placeholder is None:
                    loading_placeholder = st.empty()
                update_generation_loading(loading_placeholder, stage)
                if created_placeholder:
                    scroll_conversation_to_bottom()

            if not has_current_result:
                ensure_music_journey_result(
                    stage_callback=set_generation_stage,
                )
                current_question = st.session_state["current_question"]
                if (
                    current_question
                    in {RECOVERY_STEP, RECOMMENDATION_TIMEOUT_STEP}
                    and st.session_state.get("recovery_message_added")
                ):
                    st.session_state["generation_stage"] = "error"
                    if loading_placeholder is not None:
                        loading_placeholder.empty()
                    logger.info(
                        "[RERUN] source=recovery_message tracks=%s "
                        "pending=%s",
                        len(
                            (
                                st.session_state.get(
                                    "music_journey_result"
                                )
                                or {}
                            ).get("tracks")
                            or []
                        ),
                        st.session_state.get("result_render_pending"),
                    )
                    st.rerun()

            if (
                st.session_state.get("music_journey_error")
                and current_question
                not in {RECOVERY_STEP, RECOMMENDATION_TIMEOUT_STEP}
            ):
                st.session_state["generation_stage"] = "error"
                if loading_placeholder is not None:
                    loading_placeholder.markdown(
                        '<div class="journey-loading">'
                        "음악 여행을 준비하는 중 문제가 발생했어요."
                        "</div>",
                        unsafe_allow_html=True,
                    )
                render_ai_message(
                    escape(st.session_state["music_journey_error"])
                )
                if loading_placeholder is not None:
                    loading_placeholder.empty()
            elif current_question == "complete":
                result = st.session_state.get("music_journey_result") or {}
                tracks = result.get("tracks") or []
                requested_track_count = int(
                    st.session_state.get("track_count") or 0
                )
                result_ready = (
                    isinstance(tracks, list)
                    and len(tracks) >= 1
                    and not result.get("is_error")
                    and not st.session_state.get("music_journey_error")
                )
                result_count_complete = (
                    result_ready
                    and requested_track_count >= 1
                    and len(tracks) == requested_track_count
                )
                logger.info(
                    "[RESULT_STATE] requested=%s tracks_type=%s tracks_len=%s "
                    "is_error=%s music_error=%s ready=%s",
                    requested_track_count,
                    type(tracks).__name__,
                    len(tracks) if isinstance(tracks, list) else 0,
                    result.get("is_error"),
                    st.session_state.get("music_journey_error"),
                    result_count_complete,
                )
                if result_count_complete:
                    thumbnail_signature = (
                        st.session_state.get("city"),
                        st.session_state.get("mood"),
                        st.session_state.get("situation"),
                    )
                    thumbnail_is_cached = (
                        st.session_state.get("passport_thumbnail_signature")
                        == thumbnail_signature
                        and (
                            st.session_state.get("passport_thumbnail_base64")
                            or st.session_state.get(
                                "passport_thumbnail_error"
                            )
                        )
                    )
                    if not thumbnail_is_cached:
                        ensure_passport_thumbnail(
                            stage_callback=set_generation_stage,
                        )

                    st.session_state["generation_stage"] = "complete"
                    if loading_placeholder is not None:
                        loading_placeholder.empty()

                    fallback_message = result.get("fallback_message")
                    if fallback_message:
                        render_ai_message(fallback_message)
                    render_ai_message(build_boarding_pass_ready_message())
                    logger.info(
                        "[RESULT_ATTACHMENTS_RENDER] requested=%s "
                        "tracks_len=%s",
                        requested_track_count,
                        len(tracks),
                    )
                    render_result_attachments()
                else:
                    logger.error(
                        "[RESULT_INVALID_COMPLETE] requested=%s "
                        "tracks_type=%s tracks_len=%s is_error=%s "
                        "music_error=%s result_keys=%s",
                        requested_track_count,
                        type(tracks).__name__,
                        len(tracks) if isinstance(tracks, list) else 0,
                        result.get("is_error"),
                        st.session_state.get("music_journey_error"),
                        sorted(result.keys()),
                    )
                    if result.get("is_error"):
                        st.session_state["music_journey_error"] = (
                            API_ERROR_MESSAGE
                        )
                        st.session_state["generation_stage"] = "error"
                        if loading_placeholder is not None:
                            loading_placeholder.empty()
                        render_ai_message(API_ERROR_MESSAGE)
                    else:
                        actual_count = (
                            len(tracks)
                            if isinstance(tracks, list)
                            else 0
                        )
                        st.session_state["music_journey_error"] = (
                            f"요청하신 {requested_track_count}곡을 모두 "
                            "확인하지 못했어요."
                        )
                        st.session_state["recovery_context"] = {
                            "requested_count": requested_track_count,
                            "actual_count": actual_count,
                            "destination": st.session_state.get("city"),
                            "scopes_attempted": (),
                            "rejected_candidates": (),
                        }
                        st.session_state["recovery_choice"] = None
                        st.session_state["current_question"] = RECOVERY_STEP
                        st.session_state["conversation_step"] = RECOVERY_STEP
                        if not st.session_state.get(
                            "recovery_message_added"
                        ):
                            append_chat_message(
                                "ai",
                                "미안해요🥺<br>"
                                f"아직 요청하신 {requested_track_count}곡을 "
                                "모두 찾지 못했어요.<br><br>"
                                "조건을 조금 바꿔볼까요?",
                            )
                            st.session_state[
                                "recovery_message_added"
                            ] = True
                        logger.info(
                            "[RERUN] source=invalid_complete tracks=%s "
                            "pending=%s",
                            actual_count,
                            st.session_state.get("result_render_pending"),
                        )
                        st.rerun()

        direct_input_active = (
            st.session_state.get("direct_input_mode")
            and st.session_state.get("direct_input_field") == current_question
        )
        if (
            current_question == RECOMMENDATION_TIMEOUT_STEP
            and st.session_state.get("recovery_message_added")
        ):
            render_timeout_recovery_choices()
        elif (
            current_question == RECOVERY_STEP
            and st.session_state.get("recovery_message_added")
        ):
            render_recovery_choices()
        elif current_question != "complete":
            if not direct_input_active:
                render_choices(current_question)

        if st.session_state["should_scroll_conversation"]:
            scroll_conversation_to_bottom()
            st.session_state["should_scroll_conversation"] = False


def render_input_dock() -> None:
    """Enable free text only after the active direct-input choice."""
    with st.container(key="input_dock"):
        current_question = st.session_state["current_question"]
        standard_direct_input = (
            st.session_state.get("direct_input_mode")
            and st.session_state.get("direct_input_field") == current_question
            and current_question in DIRECT_INPUT_PLACEHOLDERS
        )
        recovery_direct_input = (
            current_question == RECOVERY_STEP
            and st.session_state.get("recovery_choice") == "direct_input"
            and st.session_state.get("direct_input_mode")
            and st.session_state.get("direct_input_field") == RECOVERY_STEP
        )
        timeout_direct_input = (
            current_question == RECOMMENDATION_TIMEOUT_STEP
            and st.session_state.get("recovery_choice") == "direct_input"
            and st.session_state.get("direct_input_mode")
            and st.session_state.get("direct_input_field")
            == RECOMMENDATION_TIMEOUT_STEP
        )
        direct_input_active = (
            standard_direct_input
            or recovery_direct_input
            or timeout_direct_input
        )
        placeholder = (
            "넓히거나 바꾸고 싶은 조건을 입력해주세요"
            if recovery_direct_input or timeout_direct_input
            else DIRECT_INPUT_PLACEHOLDERS[current_question]
            if standard_direct_input
            else "위 선택지에서 답변해 주세요"
        )
        submit_handler = (
            submit_timeout_recovery_direct_input
            if timeout_direct_input
            else submit_recovery_direct_input
            if recovery_direct_input
            else submit_chat_input
        )
        input_key = DIRECT_INPUT_STATE_KEYS.get(
            current_question,
            f"{current_question}_chat_input",
        )
        input_col, send_col = st.columns([6, 1], vertical_alignment="center")
        with input_col:
            st.text_input(
                "메시지 입력",
                key=input_key,
                placeholder=placeholder,
                disabled=not direct_input_active,
                label_visibility="collapsed",
                on_change=submit_handler,
            )
        with send_col:
            st.button(
                "↑",
                key="chat_input_send",
                disabled=not direct_input_active,
                use_container_width=True,
                on_click=submit_handler,
            )
        if st.session_state.get("input_error"):
            input_error = escape(
                str(st.session_state["input_error"])
            ).replace("\n", "<br>")
            st.markdown(
                f'<p class="chat-input-error">{input_error}</p>',
                unsafe_allow_html=True,
            )


def render_navigation() -> None:
    """Render the currently supported chat navigation action."""
    with st.container(key="chat_navigation"):
        st.button("↺ 다시 시작하기", key="restart", on_click=reset_conversation)


def render_chat_screen() -> None:
    """Render the existing chat experience without changing its interaction flow."""
    step_number = min(
        STEPS.index(st.session_state["conversation_step"]) + 1,
        len(CHAT_FIELDS),
    )

    with st.container(key="chat-screen"):
        left_col, right_col = st.columns([1.28, 1.12])

        with left_col:
            airplane_window = render_airplane_window_image(
                "chat",
                "비행기 창문 너머로 보이는 음악 여행의 하늘",
            )
            st.markdown(
                f"""
                <section class="chat-visual-area" aria-label="비행기 창문">
                    {airplane_window}
                </section>
                """,
                unsafe_allow_html=True,
            )

        with right_col:
            with st.container(key="chat_panel"):
                render_chat_header(step_number)
                render_conversation()
                render_input_dock()
                render_navigation()


def resolve_result_destination(journey: dict, selected_city: str) -> str:
    """Resolve a display-only destination for an unconstrained Result."""
    ambiguous_destinations = {
        "",
        "__lyra_custom_destination__",
        "__direct__",
        "__skip__",
        "lyra_custom_destination",
        "direct",
        "skip",
        "global",
        "worldwide",
        "international",
        "mixed",
        "various",
        "상관없어요",
    }

    def is_concrete_destination(value: str) -> bool:
        normalized = " ".join(value.split()).casefold().strip(" .,-")
        return (
            normalized not in ambiguous_destinations
            and not any(
                word in normalized
                for word in (
                    "global music",
                    "world music",
                    "various artists",
                    "multiple countries",
                )
            )
        )

    journey_destination = str(journey.get("destination") or "").strip()
    if is_concrete_destination(journey_destination):
        return journey_destination
    if is_concrete_destination(selected_city):
        return selected_city

    geography = journey.get("geography") or {}
    for key in ("city_local", "city", "country_local", "country"):
        value = str(geography.get(key) or "").strip()
        if is_concrete_destination(value):
            return value

    candidates: list[str] = []
    for track in journey.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for key in (
            "city",
            "city_name",
            "country",
            "country_name",
            "country_local",
            "artist_country",
            "origin",
        ):
            value = str(track.get(key) or "").strip()
            if is_concrete_destination(value):
                candidates.append(value)
                break
        else:
            connection = str(track.get("city_connection") or "").strip()
            connection = re.sub(r"^[^:：]{1,24}[:：]\s*", "", connection)
            destination_patterns = (
                (
                    r"(?:은|는)\s+"
                    r"([A-Za-zÀ-ÖØ-öø-ÿ가-힣.'-]{2,28}"
                    r"(?:,\s*[A-Za-zÀ-ÖØ-öø-ÿ가-힣.' -]{2,28})?)"
                    r"(?=\s*(?:에서|의|출신|기반|태생|음악|$|[.;]))"
                ),
                (
                    r"\bfrom\s+"
                    r"([A-Za-zÀ-ÖØ-öø-ÿ.'-]{2,28}"
                    r"(?:,\s*[A-Za-zÀ-ÖØ-öø-ÿ.' -]{2,28})?)"
                    r"(?=\s*(?:[.;]|$))"
                ),
                (
                    r"^([A-Za-zÀ-ÖØ-öø-ÿ가-힣.'-]{2,28}"
                    r"(?:,\s*[A-Za-zÀ-ÖØ-öø-ÿ가-힣.' -]{2,28})?)"
                    r"(?=\s*(?:에서|의|출신|기반|태생|$|[.;]))"
                ),
            )
            for pattern in destination_patterns:
                match = re.search(pattern, connection, flags=re.IGNORECASE)
                if not match:
                    continue
                candidate = match.group(1).strip(" .,-")
                if (
                    is_concrete_destination(candidate)
                    and not re.search(r"(?:은|는|이|가)\s", candidate)
                ):
                    candidates.append(candidate)
                    break

    if candidates:
        return max(candidates, key=candidates.count)
    return "Seoul, South Korea"


def render_passport_detail() -> None:
    """Render the selected journey as a Music Passport detail."""
    mood = escape(st.session_state.get("mood", "—"))
    situation = escape(st.session_state.get("situation", "—"))
    journey = st.session_state.get("music_journey_result") or {}
    metadata = get_custom_destination_metadata(
        str(st.session_state.get("free_text_preferences") or "")
    )
    result_destination = resolve_result_destination(
        journey,
        metadata.get("display")
        or str(st.session_state.get("city") or ""),
    )
    raw_city = result_destination
    city = escape(result_destination)
    city_name = get_city_name(raw_city)
    city_code = CITY_CODES.get(city_name, "MP")
    generated_image_uri = st.session_state.get("passport_thumbnail_base64", "")
    image_uri = (
        generated_image_uri
        if (
            isinstance(generated_image_uri, str)
            and generated_image_uri.startswith("data:image/")
        )
        else get_city_image(raw_city)
    )
    image_style = (
        f' style="background-image: url(&quot;{escape(image_uri, quote=True)}&quot;);"'
        if image_uri
        else ""
    )
    requested_count = int(st.session_state.get("track_count") or 0)
    qr_url = resolve_result_qr_url(journey, raw_city)
    if qr_url:
        playlist_url = str(journey.get("spotify_playlist_url") or "").strip()
        qr_label = (
            "SCAN TO OPEN PLAYLIST"
            if qr_url == playlist_url
            else "SCAN TO EXPLORE"
            if "/search/" in qr_url
            else "SCAN TO OPEN ON SPOTIFY"
        )
        qr_markup = (
            f'<a class="result-ticket-qr-column" href="{escape(qr_url, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            '<span class="result-ticket-qr">'
            f'<img class="result-ticket-qr-image" src="{make_qr_data_uri(qr_url)}" '
            f'alt="{qr_label}"></span>'
            f'<span class="result-ticket-qr-label">{qr_label}</span>'
            "</a>"
        )
        footer_class = "passport-ticket-footer"
    else:
        qr_markup = ""
        footer_class = "passport-ticket-footer passport-ticket-footer--no-qr"
    barcode_bars = "".join(
        f'<span class="bar w{width}"></span>'
        for width in BARCODE_PATTERN
    )
    barcode_text = f"MP 20260802 {requested_count:02d} {city_code}"
    st.markdown(
        f"""
        <article class="passport-detail-card">
            <section class="passport-hero">
                <div class="passport-detail-image city-image--{city_name}"{image_style} aria-hidden="true"></div>
                <div class="passport-hero-content">
                    <p class="result-detail-label">MUSIC PASSPORT</p>
                    <h2 class="result-detail-title">{city}</h2>
                    <p class="passport-hero-message">YOUR JOURNEY BEGINS WITH A SONG</p>
                    <div class="result-departure-stamp" aria-hidden="true">
                        <div class="result-departure-stamp__text">
                            MUSIC PASSPORT<br>✈ DEPARTURE
                            <span class="result-departure-stamp__route">LYRA · {city_code}</span>
                            <span class="result-departure-stamp__date">2026.08.02</span>
                        </div>
                    </div>
                </div>
            </section>
            <section class="passport-ticket-info">
                <dl class="passport-detail-data">
                    <dt>MOOD</dt><dd>{mood}</dd>
                    <dt>SITUATION</dt><dd>{situation}</dd>
                    <dt>CITY</dt><dd>{city}</dd>
                    <dt>CODE</dt><dd>MP · JOURNEY 01</dd>
                </dl>
                <div class="passport-flight-meta" aria-label="Boarding pass details">
                    <div><span>FLIGHT</span><strong>MP-01</strong></div>
                    <div><span>GATE</span><strong>LYRA</strong></div>
                    <div><span>SEAT</span><strong>3A</strong></div>
                    <div><span>DATE</span><strong>2026.08.02</strong></div>
                </div>
            </section>
            <footer class="{footer_class}">
                {qr_markup}
                <div class="result-ticket-barcode-column">
                    <div class="result-ticket-barcode-box">
                        <div class="ticket-barcode" aria-hidden="true">{barcode_bars}</div>
                    </div>
                    <p class="result-ticket-barcode-label">{barcode_text}</p>
                </div>
            </footer>
        </article>
        """,
        unsafe_allow_html=True,
    )


def render_playlist_detail() -> None:
    """Render verified Spotify tracks or an explicit API error state."""
    journey = st.session_state.get("music_journey_result") or placeholder_music_journey(
        st.session_state.get("city", "—"),
        int(st.session_state.get("track_count") or 5),
    )
    city = escape(
        resolve_result_destination(
            journey,
            str(st.session_state.get("city", "—")),
        )
    )
    journey_tracks = journey.get("tracks") or []
    requested_track_count = int(st.session_state.get("track_count") or 5)
    if (
        journey.get("is_error")
        or not journey_tracks
        or any(
            not isinstance(track, dict)
            or track.get("is_placeholder")
            or not track.get("name")
            or not track.get("artists")
            or not str(track.get("spotify_url", "")).startswith(
                "https://open.spotify.com/"
            )
            for track in journey_tracks
        )
    ):
        st.markdown(
            (
                '<article class="playlist-detail-card">'
                f'<p class="result-detail-label">CITY PLAYLIST · {city}</p>'
                '<h2 class="result-detail-title">추천 정보를 불러오지 못했어요.</h2>'
                '<p class="playlist-journey-summary">'
                'API 설정을 확인한 뒤 다시 시도해주세요.'
                "</p>"
                "</article>"
            ),
            unsafe_allow_html=True,
        )
        return

    assert len(journey_tracks) == requested_track_count, (
        "Verified recommendation count must match the requested count "
        "before Result rendering."
    )

    track_rows = []
    for index, track in enumerate(journey_tracks, start=1):
        artists = ", ".join(track["artists"])
        album_url = track.get("album_image_url", "")
        album_markup = (
            f'<img class="playlist-album-image" src="{escape(album_url, quote=True)}" '
            f'alt="{escape(track.get("album_name", ""), quote=True)} 앨범 커버" loading="lazy">'
            if album_url.startswith("https://")
            else '<span class="playlist-album-placeholder" aria-hidden="true"></span>'
        )
        spotify_url = track.get("spotify_url", "")
        spotify_aria_label = escape(
            f"{artists}의 {track['name']}을 Spotify에서 열기",
            quote=True,
        )
        spotify_markup = (
            '<div class="spotify-link-wrap">'
            f'<a class="spotify-text-link" href="{escape(spotify_url, quote=True)}" '
            'target="_blank" rel="noopener noreferrer" '
            f'aria-label="{spotify_aria_label}">'
            '<svg class="spotify-ci-icon" viewBox="0 0 24 24" '
            'aria-hidden="true" focusable="false">'
            '<circle cx="12" cy="12" r="11" fill="currentColor"/>'
            '<path d="M6.7 9.2c3.8-1.1 7.8-.8 11.1.9" fill="none" '
            'stroke="#101827" stroke-width="1.7" stroke-linecap="round"/>'
            '<path d="M7.4 12.4c3.2-.8 6.6-.5 9.5.8" fill="none" '
            'stroke="#101827" stroke-width="1.55" stroke-linecap="round"/>'
            '<path d="M8.1 15.4c2.6-.6 5.3-.3 7.7.7" fill="none" '
            'stroke="#101827" stroke-width="1.4" stroke-linecap="round"/>'
            "</svg>"
            "<span>Spotify에서 듣기 ↗</span>"
            "</a>"
            "</div>"
            if str(spotify_url).startswith("https://open.spotify.com/")
            else ""
        )
        reason = track.get("city_connection") or track.get(
            "recommendation_reason",
            "",
        )
        track_rows.append(
            '<div class="playlist-track">'
            f'<span class="playlist-track-number">{index:02d}</span>'
            f"{album_markup}"
            '<div class="playlist-track-copy">'
            f'<p class="playlist-track-title">{escape(track["name"])}</p>'
            f'<p class="playlist-track-artist">{escape(artists)}</p>'
            f'<p class="playlist-track-album">{escape(track.get("album_name", ""))}</p>'
            f'<p class="playlist-track-reason">{escape(reason)}</p>'
            f"{spotify_markup}"
            "</div>"
            "</div>"
        )
    tracks = "".join(track_rows)
    summary = escape(journey.get("journey_summary", ""))
    playlist_html = (
        '<article class="playlist-detail-card">'
        f'<p class="result-detail-label">CITY PLAYLIST · {city}</p>'
        f'<h2 class="result-detail-title">추천 {requested_track_count}곡</h2>'
        f'<p class="playlist-journey-summary">{summary}</p>'
        f'<div class="playlist-track-list">{tracks}</div>'
        "</article>"
    )
    st.markdown(
        playlist_html,
        unsafe_allow_html=True,
    )


def render_result_screen() -> None:
    """Render the two-column result detail and its return actions."""
    journey = st.session_state.get("music_journey_result") or {}
    city = escape(
        resolve_result_destination(
            journey,
            str(st.session_state.get("city", "—")),
        )
    )
    with st.container(key="result_screen"):
        st.markdown(
            f"""
            <header class="result-screen-header">
                <div>
                    <p>MUSIC PASSPORT DETAIL</p>
                    <h1>{city}</h1>
                </div>
                <p>JOURNEY 01</p>
            </header>
            """,
            unsafe_allow_html=True,
        )

        passport_col, playlist_col = st.columns([1, 1.15])
        with passport_col:
            render_passport_detail()
        with playlist_col:
            render_playlist_detail()

        with st.container(key="result_navigation"):
            back_col, restart_col = st.columns(2)
            with back_col:
                st.button(
                    "← 채팅으로 돌아가기",
                    key="return-to-chat",
                    use_container_width=True,
                    on_click=return_to_chat,
                )
            with restart_col:
                st.button(
                    "↺ 처음부터 다시 시작하기",
                    key="restart-from-result",
                    use_container_width=True,
                    on_click=restart_from_result,
                )


if st.session_state["active_screen"] == "intro":
    render_intro_screen()
elif st.session_state["active_screen"] == "chat":
    render_chat_screen()
else:
    render_result_screen()
