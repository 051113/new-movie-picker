import os
import textwrap
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv

from services.openai_client import OpenAIService
try:
    from services.recs import get_quick_pick
except ImportError:
    # Backward-compatible fallback for environments that don't have get_quick_pick yet.
    from services.recs import get_sectioned_recommendations as _legacy_sectioned

    def get_quick_pick(
        user_id: str,
        context: Dict[str, Any],
        constraints: Dict[str, Any],
        refinement: Optional[str] = None,
        *,
        tmdb: Any,
        openai_service: Any,
        storage: Any,
    ) -> Dict[str, Any]:
        time_minutes = context.get("time_minutes", 90)
        if time_minutes <= 30:
            time_bucket = "<90m"
        elif time_minutes <= 100:
            time_bucket = "90-120m"
        else:
            time_bucket = "120m+"

        legacy_context = {
            "mood": "thoughtful",
            "who": str(context.get("who", "Alone")).lower(),
            "time": time_bucket,
        }
        vibe_dials = {"cozy_intense": "Balanced", "light_dark": "Balanced", "mainstream_hidden": "Balanced"}
        sliders = {"pace": 55, "darkness": 45, "humor": 45, "romance": 35, "violence": 35, "weirdness": 30}
        legacy_constraints = {
            "less_violent": False,
            "more_hopeful": False,
            "shorter": bool(refinement == "Shorter"),
            "non_english_ok": True,
            "no_jump_scares": False,
            "only_streaming_now": bool(constraints.get("streaming_only")),
        }
        region = (constraints.get("region") or context.get("region") or "KR").upper()
        sections_payload = _legacy_sectioned(
            tmdb=tmdb,
            openai_service=openai_service,
            storage=storage,
            user_id=user_id,
            context=legacy_context,
            vibe_dials=vibe_dials,
            sliders=sliders,
            constraints=legacy_constraints,
            region=region,
            collections=[],
            seed_movie_id=None,
            ranking_version="quick_pick_fallback",
        )
        top = (sections_payload.get("sections", {}).get("top_matches") or [None])[0]
        backup = (sections_payload.get("sections", {}).get("because_you_liked") or [None])[0]
        wildcard = (sections_payload.get("sections", {}).get("wildcards") or [None])[0]
        return {
            "top": top,
            "backup": backup,
            "wildcard": wildcard,
            "reasons": {"top": [], "backup": [], "wildcard": []},
            "profile_hash": sections_payload.get("profile_hash", ""),
            "context_hash": sections_payload.get("context_hash", ""),
        }
from services.storage import Storage
from services.tmdb import TMDBClient, TMDBError


load_dotenv()
st.set_page_config(page_title="VibeRecs", layout="wide")


TRANSLATIONS = {
    "en": {
        "title": "VibeRecs",
        "quick_pick": "Quick Pick",
        "time_available": "Time available",
        "who": "Who",
        "intention": "Emotional intention",
        "energy": "Energy",
        "streaming_only": "Streaming only",
        "region": "Region",
        "providers": "Providers",
        "pick_for_me": "Pick for me",
        "top_pick": "Top Pick",
        "backup": "Backup",
        "wildcard": "Wildcard",
        "why_this": "Why this?",
        "add_ai_angle": "Add AI angle",
        "like": "👍 Like",
        "renew": "🔄 Renew",
        "dislike": "👎 Dislike",
        "tell_us_why": "Tell us why",
        "reason_default": "Doesn't look interesting",
        "reason_mood": "Not in the mood",
        "reason_long": "Too long",
        "reason_seen": "Already saw it",
        "reason_service": "Don't have this service",
        "save_reason": "Save reason",
        "refine": "Refine",
        "refine_more_exciting": "More exciting",
        "refine_funnier": "Funnier",
        "refine_more_emotional": "More emotional",
        "refine_lighter": "Lighter",
        "refine_darker": "Darker",
        "refine_shorter": "Shorter",
        "refine_more_popular": "More popular",
        "refine_more_indie": "More indie",
        "refine_surprise": "Surprise me",
        "settings": "Settings",
        "user_id": "User ID",
        "user_id_help": "Use your own ID to keep a separate recommendation profile.",
        "active_user": "Active user",
        "switch_user": "Switch user",
        "language": "Language",
        "language_english": "English",
        "language_korean": "Korean",
        "who_alone": "Alone",
        "who_partner": "Partner",
        "who_friends": "Friends",
        "who_family": "Family",
        "intention_comfort_cozy": "Comfort & Cozy",
        "intention_light_fun": "Light & Fun",
        "intention_engaging_story": "Engaging Story",
        "intention_intense_thrilling": "Intense & Thrilling",
        "intention_emotional_deep": "Emotional & Deep",
        "intention_surprise_me": "Surprise Me",
        "energy_chill": "Chill",
        "energy_balanced": "Balanced",
        "energy_high": "High",
        "soft_reset": "Soft reset (last 20 interactions)",
        "full_reset": "Full reset",
        "tmdb_required": "TMDB_API_KEY is required. Add it in .env or Streamlit secrets.",
        "openai_missing": "OPENAI_API_KEY missing. Running in fallback mode.",
        "updating": "Finding your three picks...",
        "runtime_na": "Runtime not available",
        "availability_unknown": "Availability unknown",
        "no_image_found": "No Image Found",
        "no_candidate_found": "No candidate found.",
        "fallback_reason_1": "Good match for your selected context.",
        "fallback_reason_2": "Fits your current time and energy setting.",
        "fallback_reason_3": "Valid for current streaming constraints.",
        "watch_trailer": "Watch trailer",
    },
    "ko": {
        "title": "VibeRecs",
        "quick_pick": "빠른 추천",
        "time_available": "가능 시간",
        "who": "누구와 함께 보나요?",
        "intention": "감정/분위기 의도",
        "energy": "에너지",
        "streaming_only": "스트리밍 가능만",
        "region": "지역",
        "providers": "플랫폼",
        "pick_for_me": "추천 받기",
        "top_pick": "최우선 추천",
        "backup": "대안 추천",
        "wildcard": "와일드카드",
        "why_this": "왜 이 작품인가요?",
        "add_ai_angle": "AI 관점 추가",
        "like": "좋아요",
        "renew": "새로 고침",
        "dislike": "싫어요",
        "tell_us_why": "이유 알려주기",
        "reason_default": "흥미가 없어요",
        "reason_mood": "지금 기분이 아니에요",
        "reason_long": "너무 길어요",
        "reason_seen": "이미 봤어요",
        "reason_service": "이 서비스를 사용하지 않아요",
        "save_reason": "이유 저장",
        "refine": "세부 조정",
        "refine_more_exciting": "더 짜릿하게",
        "refine_funnier": "더 웃기게",
        "refine_more_emotional": "더 감성적으로",
        "refine_lighter": "더 가볍게",
        "refine_darker": "더 어둡게",
        "refine_shorter": "더 짧게",
        "refine_more_popular": "더 대중적으로",
        "refine_more_indie": "더 인디하게",
        "refine_surprise": "깜짝 추천",
        "settings": "설정",
        "language": "언어",
        "soft_reset": "소프트 초기화 (최근 20개)",
        "full_reset": "전체 초기화",
        "tmdb_required": "TMDB_API_KEY가 필요합니다. .env 또는 Streamlit secrets에 추가하세요.",
        "openai_missing": "OPENAI_API_KEY 없이도 동작합니다.",
        "updating": "맞춤 3개를 찾는 중...",
        "runtime_na": "러닝타임 정보 없음",
        "availability_unknown": "시청 가능 정보 없음",
    },
}

# Override critical Korean labels with clean UTF-8 values to avoid mojibake issues.
TRANSLATIONS["ko"].update(
    {
        "like": "👍 좋아요",
        "renew": "🔄 새로고침",
        "dislike": "👎 싫어요",
        "add_ai_angle": "AI 관점 추가",
        "tell_us_why": "이유 알려주기",
        "save_reason": "이유 저장",
        "user_id": "사용자 ID",
        "user_id_help": "고유 ID를 사용하면 추천 프로필이 분리 저장됩니다.",
        "active_user": "현재 사용자",
        "switch_user": "사용자 전환",
        "language_english": "영어",
        "language_korean": "한국어",
        "who_alone": "혼자",
        "who_partner": "연인",
        "who_friends": "친구",
        "who_family": "가족",
        "intention_comfort_cozy": "편안하고 포근하게",
        "intention_light_fun": "가볍고 재미있게",
        "intention_engaging_story": "몰입되는 이야기",
        "intention_intense_thrilling": "강렬하고 스릴 있게",
        "intention_emotional_deep": "감성적이고 깊게",
        "intention_surprise_me": "랜덤 추천",
        "energy_chill": "차분하게",
        "energy_balanced": "적당히",
        "energy_high": "에너지 높게",
        "no_image_found": "이미지를 찾을 수 없어요",
        "no_candidate_found": "추천 후보를 찾지 못했어요.",
        "fallback_reason_1": "지금 선택한 상황과 잘 맞는 작품이에요.",
        "fallback_reason_2": "현재 시간/에너지 설정에 잘 맞아요.",
        "fallback_reason_3": "현재 스트리밍 조건에서 시청 가능해요.",
        "watch_trailer": "예고편 보기",
    }
)


def t(key: str) -> str:
    lang = st.session_state.get("lang", "en")
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))


def env_or_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def normalize_user_id(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return "guest"
    # Keep user-chosen IDs as-is, only enforce a safe max length.
    return cleaned[:64]


def load_user_profile_into_state(storage: Storage, user_id: str) -> None:
    profile = storage.load_profile(user_id) or {}
    context = dict(profile.get("context") or {})
    constraints = dict(profile.get("constraints") or {})
    refinement = context.pop("refinement", None)

    st.session_state.qp_context = context
    st.session_state.qp_constraints = constraints
    st.session_state.qp_refinement = refinement
    st.session_state.qp_results = None
    st.session_state.skip_reason_slot = None
    st.session_state.localized_movie_text = {}

    time_minutes = context.get("time_minutes")
    if time_minutes is None:
        st.session_state.qp_time = "90"
    elif time_minutes <= 20:
        st.session_state.qp_time = "20"
    elif time_minutes <= 45:
        st.session_state.qp_time = "45"
    elif time_minutes <= 110:
        st.session_state.qp_time = "90"
    else:
        st.session_state.qp_time = "120+"

    st.session_state.qp_who = context.get("who", "Alone")
    st.session_state.qp_intention = context.get("intention", "Engaging Story")
    st.session_state.qp_energy = context.get("energy", "Balanced")
    st.session_state.qp_streaming_only = bool(constraints.get("streaming_only", True))
    st.session_state.qp_region = (constraints.get("region") or context.get("region") or st.session_state.get("qp_region") or "KR").upper()
    st.session_state.qp_providers = list(constraints.get("provider_names") or [])


def persist_profile(storage: Storage) -> None:
    context = dict(st.session_state.get("qp_context") or {})
    constraints = dict(st.session_state.get("qp_constraints") or {})
    context["refinement"] = st.session_state.get("qp_refinement")
    region = (constraints.get("region") or context.get("region") or env_or_secret("TMDB_REGION", "KR") or "KR").upper()
    storage.save_profile(
        st.session_state.user_id,
        region=region,
        sliders={},
        vibe_dials={},
        constraints=constraints,
        context=context,
        exploration_pref=0.5,
        onboarding_complete=True,
    )


def init_state(storage: Storage) -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = "guest"
    if "lang" not in st.session_state:
        st.session_state.lang = "en"
    if "qp_session_id" not in st.session_state:
        st.session_state.qp_session_id = str(uuid.uuid4())
    if "qp_started_at" not in st.session_state:
        st.session_state.qp_started_at = time.time()
    if "qp_context" not in st.session_state:
        st.session_state.qp_context = {}
    if "qp_constraints" not in st.session_state:
        st.session_state.qp_constraints = {}
    if "qp_refinement" not in st.session_state:
        st.session_state.qp_refinement = None
    if "qp_results" not in st.session_state:
        st.session_state.qp_results = None
    if "skip_reason_slot" not in st.session_state:
        st.session_state.skip_reason_slot = None
    if "localized_movie_text" not in st.session_state:
        st.session_state.localized_movie_text = {}
    if "qp_streaming_only" not in st.session_state:
        st.session_state.qp_streaming_only = True
    if "qp_region" not in st.session_state:
        st.session_state.qp_region = (env_or_secret("TMDB_REGION", "KR") or "KR").upper()
    if "qp_providers" not in st.session_state:
        st.session_state.qp_providers = []
    if "profile_loaded_for_user" not in st.session_state:
        st.session_state.profile_loaded_for_user = None
    if "user_id_input" not in st.session_state:
        st.session_state.user_id_input = st.session_state.user_id
    storage.get_or_create_user(st.session_state.user_id, region=env_or_secret("TMDB_REGION", "KR") or "KR")


def soft_reset(storage: Storage) -> None:
    storage.reset_profile_soft(st.session_state.user_id, n=20)
    st.session_state.qp_results = None
    st.session_state.qp_refinement = None


def full_reset(storage: Storage) -> None:
    storage.reset_profile_full(st.session_state.user_id)
    uid = str(uuid.uuid4())
    for key in list(st.session_state.keys()):
        del st.session_state[key]
        st.session_state.user_id = uid


def pick_single(label: str, options: List[str], default: str, key: str) -> str:
    if not options:
        return default
    safe_default = default if default in options else options[0]
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state[key] = safe_default

    if hasattr(st, "segmented_control"):
        if key in st.session_state:
            value = st.segmented_control(label, options, selection_mode="single", key=key)
        else:
            value = st.segmented_control(label, options, default=safe_default, selection_mode="single", key=key)
        return value or safe_default
    if key in st.session_state:
        return st.radio(label, options, horizontal=True, key=key)
    return st.radio(label, options, index=options.index(safe_default), horizontal=True, key=key)


def pick_single_mapped(label: str, options: List[Tuple[str, str]], default_value: str, key: str) -> str:
    localized_options = [t(label_key) for label_key, _ in options]
    value_by_label = {t(label_key): value for label_key, value in options}
    default_label = next((t(label_key) for label_key, value in options if value == default_value), localized_options[0])
    picked_label = pick_single(label, localized_options, default_label, key)
    return value_by_label.get(picked_label, default_value)


def quick_input_panel(tmdb: TMDBClient) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    st.markdown(f"## {t('quick_pick')}")
    times = ["20", "45", "90", "120+"]
    who_options = [
        ("who_alone", "Alone"),
        ("who_partner", "Partner"),
        ("who_friends", "Friends"),
        ("who_family", "Family"),
    ]
    intentions = [
        ("intention_comfort_cozy", "Comfort & Cozy"),
        ("intention_light_fun", "Light & Fun"),
        ("intention_engaging_story", "Engaging Story"),
        ("intention_intense_thrilling", "Intense & Thrilling"),
        ("intention_emotional_deep", "Emotional & Deep"),
        ("intention_surprise_me", "Surprise Me"),
    ]
    energies = [
        ("energy_chill", "Chill"),
        ("energy_balanced", "Balanced"),
        ("energy_high", "High"),
    ]

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            time_choice = pick_single(t("time_available"), times, "90", "qp_time")
        with c2:
            who = pick_single_mapped(t("who"), who_options, "Alone", "qp_who")
        with c3:
            energy = pick_single_mapped(t("energy"), energies, "Balanced", "qp_energy")

        intention = pick_single_mapped(t("intention"), intentions, "Engaging Story", "qp_intention")

        c4, c5 = st.columns([1, 1])
        with c4:
            streaming_only = st.toggle(t("streaming_only"), key="qp_streaming_only")
        with c5:
            region_options = ["KR", "US", "JP", "GB", "CA", "AU", "DE", "FR", "IN"]
            active_region = st.session_state.get("qp_region", "KR")
            if active_region not in region_options:
                active_region = "KR"
            region = st.selectbox(t("region"), region_options, index=region_options.index(active_region), key="qp_region")

        provider_names: List[str] = []
        if streaming_only:
            try:
                options = tmdb.region_streaming_providers(region=region)
            except Exception:
                options = []
            defaults = [p for p in (st.session_state.get("qp_providers") or []) if p in options]
            provider_names = st.multiselect(t("providers"), options, default=defaults, key="qp_providers")
        else:
            st.session_state.qp_providers = []

        clicked = st.button(t("pick_for_me"), type="primary", use_container_width=True)

    time_minutes = {"20": 20, "45": 45, "90": 90, "120+": 150}.get(time_choice or "90", 90)
    context = {
        "time_minutes": time_minutes,
        "who": who or "Alone",
        "intention": intention or "Engaging Story",
        "energy": energy or "Balanced",
        "region": region,
    }
    constraints = {
        "streaming_only": bool(streaming_only),
        "region": region,
        "provider_names": provider_names,
    }
    return context, constraints, clicked


def poster_or_placeholder(movie: Dict[str, Any], tmdb: TMDBClient) -> None:
    poster = tmdb.image_url(movie.get("poster_path"), size="w342")
    if poster:
        st.image(poster, use_container_width=True)
        return
    st.markdown(
        f"""
        <div style="aspect-ratio:2/3;background:#e9eef5;border:1px solid #d8e2f0;border-radius:10px;
                    display:flex;align-items:center;justify-content:center;color:#63758a;font-weight:600;">
            {t("no_image_found")}
        </div>
        """,
        unsafe_allow_html=True,
    )


def movie_meta_line(movie: Dict[str, Any]) -> str:
    year = (movie.get("release_date") or "")[:4]
    runtime = movie.get("runtime")
    runtime_text = f"{runtime}m" if runtime else t("runtime_na")
    genres = ", ".join(g.get("name", "") for g in (movie.get("genres") or [])[:2]) or "-"
    rating = movie.get("vote_average")
    rating_text = f"★ {float(rating):.1f}" if rating else ""
    parts = [p for p in [year, runtime_text, genres, rating_text] if p]
    return " • ".join(parts)


def _contains_hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in (text or ""))


def localized_display_text(movie: Dict[str, Any], tmdb: TMDBClient, openai_service: OpenAIService) -> Tuple[str, str]:
    title = (movie.get("title") or "").strip()
    overview = (movie.get("overview") or "").strip()
    lang = st.session_state.get("lang", "en")
    if lang != "ko":
        return title, overview

    movie_id = int(movie.get("id") or 0)
    cache_key = f"ko:{movie_id}"
    cached = st.session_state.localized_movie_text.get(cache_key)
    if cached:
        return cached.get("title", title), cached.get("overview", overview)

    # First use TMDB localized fields.
    try:
        ko_details = tmdb.get_movie_details(movie_id, language=TMDBClient.app_language_code("ko"))
        title = (ko_details.get("title") or title or "").strip()
        overview = (ko_details.get("overview") or overview or "").strip()
    except Exception:
        pass

    # Fallback: translate to Korean when text is still not Korean.
    if openai_service.enabled:
        needs_title = bool(title) and not _contains_hangul(title)
        needs_overview = bool(overview) and not _contains_hangul(overview)
        if needs_title or needs_overview:
            translated = openai_service.translate_lines([title, overview], target_language="Korean")
            if len(translated) >= 1 and translated[0]:
                title = translated[0]
            if len(translated) >= 2 and translated[1]:
                overview = translated[1]

    st.session_state.localized_movie_text[cache_key] = {"title": title, "overview": overview}
    return title, overview


def render_why(
    slot_key: str,
    movie: Dict[str, Any],
    quick_result: Dict[str, Any],
    openai_service: OpenAIService,
    storage: Storage,
) -> None:
    lang = st.session_state.get("lang", "en")
    reasons = quick_result.get("reasons", {}).get(slot_key, [])[:3]
    if not reasons:
        reasons = [t("fallback_reason_1"), t("fallback_reason_2"), t("fallback_reason_3")]
    if lang == "ko":
        reasons = openai_service.translate_lines(reasons, target_language="Korean")
    for r in reasons:
        st.markdown(f"- {r}")
    if openai_service.enabled and st.button(t("add_ai_angle"), key=f"ai_why_{slot_key}_{movie['id']}", type="secondary"):
        extra = openai_service.generate_why_spoiler_free(
            movie=movie,
            deterministic_bullets=reasons,
            user_context={"context": st.session_state.qp_context, "constraints": st.session_state.qp_constraints, "refinement": st.session_state.qp_refinement},
            profile_hash=quick_result.get("profile_hash", ""),
            context_hash=f"{quick_result.get('context_hash', '')}|lang:{lang}",
            language=lang,
        )
        for line in extra:
            st.markdown(f"- {line}")


def action_buttons(
    slot_key: str,
    movie: Dict[str, Any],
    tmdb: TMDBClient,
    openai_service: OpenAIService,
    storage: Storage,
) -> None:
    cols = st.columns(3)
    with cols[0]:
        if st.button(t("like"), key=f"like_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "like", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
    with cols[1]:
        if st.button(t("dislike"), key=f"dislike_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "dislike", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
            st.session_state.skip_reason_slot = (slot_key, int(movie["id"]))
    with cols[2]:
        if st.button(t("renew"), key=f"renew_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "seen", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
            with st.spinner(t("updating")):
                refreshed = get_quick_pick(
                    user_id=st.session_state.user_id,
                    context=st.session_state.qp_context,
                    constraints=st.session_state.qp_constraints,
                    refinement=st.session_state.qp_refinement,
                    tmdb=tmdb,
                    openai_service=openai_service,
                    storage=storage,
                )
                current = dict(st.session_state.qp_results or {})
                current[slot_key] = refreshed.get(slot_key)
                current_reasons = dict(current.get("reasons", {}))
                refreshed_reasons = refreshed.get("reasons", {}) if isinstance(refreshed, dict) else {}
                if isinstance(refreshed_reasons, dict):
                    current_reasons[slot_key] = refreshed_reasons.get(slot_key, [])
                current["reasons"] = current_reasons
                current["profile_hash"] = refreshed.get("profile_hash", current.get("profile_hash", ""))
                current["context_hash"] = refreshed.get("context_hash", current.get("context_hash", ""))
                st.session_state.qp_results = current
            st.rerun()


def skip_reason_panel(slot_key: str, storage: Storage) -> None:
    slot = st.session_state.skip_reason_slot
    if not slot:
        return
    active_slot_key, movie_id = slot
    if active_slot_key != slot_key:
        return
    options = [t("reason_default"), t("reason_mood"), t("reason_long"), t("reason_seen"), t("reason_service")]
    with st.container(border=True):
        st.caption(t("tell_us_why"))
        if hasattr(st, "pills"):
            reason = st.pills(t("tell_us_why"), options, selection_mode="single", default=options[0], key=f"dislike_reason_{slot_key}_{movie_id}")
        else:
            reason = st.selectbox(t("tell_us_why"), options, index=0, key=f"dislike_reason_{slot_key}_{movie_id}")
        if st.button(t("save_reason"), key=f"save_dislike_reason_{slot_key}_{movie_id}", type="secondary"):
            storage.log_interaction(
                st.session_state.user_id,
                movie_id,
                "dislike",
                reason=reason or options[0],
                session_id=st.session_state.qp_session_id,
                ranking_version="quick_pick",
            )
            st.session_state.skip_reason_slot = None
            st.rerun()


def render_card(slot_key: str, slot_title: str, movie: Optional[Dict[str, Any]], tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage, quick_result: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(f"### {slot_title}")
        if not movie:
            st.info(t("no_candidate_found"))
            return
        lang_code = TMDBClient.app_language_code(st.session_state.get("lang", "en"))
        display_title, display_overview = localized_display_text(movie, tmdb, openai_service)
        poster_or_placeholder(movie, tmdb)
        st.markdown(f"**{display_title or movie.get('title', '-') }**")
        st.caption(movie_meta_line(movie))
        st.write(textwrap.shorten(display_overview or movie.get("overview", ""), width=180, placeholder="..."))
        try:
            trailer_url = tmdb.get_trailer_url(int(movie.get("id", 0)), language=lang_code)
        except Exception:
            trailer_url = None
        if trailer_url:
            st.markdown(f"[{t('watch_trailer')}]({trailer_url})")
        action_buttons(slot_key, movie, tmdb, openai_service, storage)
        with st.expander(t("why_this")):
            render_why(slot_key, movie, quick_result, openai_service, storage)
    skip_reason_panel(slot_key, storage)


def render_refine(tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage) -> None:
    st.markdown(f"### {t('refine')}")
    refine_map = [
        ("refine_more_exciting", "More exciting"),
        ("refine_funnier", "Funnier"),
        ("refine_more_emotional", "More emotional"),
        ("refine_lighter", "Lighter"),
        ("refine_darker", "Darker"),
        ("refine_shorter", "Shorter"),
        ("refine_more_popular", "More popular"),
        ("refine_more_indie", "More indie"),
        ("refine_surprise", "Surprise me"),
    ]
    cols = st.columns(3)
    for idx, (label_key, refine_value) in enumerate(refine_map):
        with cols[idx % 3]:
            if st.button(t(label_key), key=f"refine_{refine_value}", type="secondary", use_container_width=True):
                st.session_state.qp_refinement = refine_value
                with st.spinner(t("updating")):
                    st.session_state.qp_results = get_quick_pick(
                        user_id=st.session_state.user_id,
                        context=st.session_state.qp_context,
                        constraints=st.session_state.qp_constraints,
                        refinement=st.session_state.qp_refinement,
                        tmdb=tmdb,
                        openai_service=openai_service,
                        storage=storage,
                    )
                persist_profile(storage)
                st.rerun()


def main() -> None:
    st.title("VibeRecs")
    storage = Storage()
    init_state(storage)
    if st.session_state.profile_loaded_for_user != st.session_state.user_id:
        load_user_profile_into_state(storage, st.session_state.user_id)
        st.session_state.profile_loaded_for_user = st.session_state.user_id
    if st.session_state.get("user_id_input") != st.session_state.user_id:
        st.session_state.user_id_input = st.session_state.user_id

    st.sidebar.markdown(f"### {t('settings')}")
    st.sidebar.text_input(
        t("user_id"),
        key="user_id_input",
        help=t("user_id_help"),
    )
    if st.sidebar.button(t("switch_user"), type="secondary", use_container_width=True):
        chosen_user = normalize_user_id(st.session_state.get("user_id_input", ""))
        st.session_state.user_id_input = chosen_user
        if chosen_user != st.session_state.user_id:
            st.session_state.user_id = chosen_user
            st.session_state.qp_session_id = str(uuid.uuid4())
            storage.get_or_create_user(chosen_user, region=st.session_state.get("qp_region", "KR"))
            load_user_profile_into_state(storage, chosen_user)
            st.session_state.profile_loaded_for_user = chosen_user
            st.rerun()
    st.sidebar.caption(f"{t('active_user')}: `{st.session_state.user_id}`")

    language_labels = {"en": t("language_english"), "ko": t("language_korean")}
    options = [language_labels["en"], language_labels["ko"]]
    current_label = language_labels["ko"] if st.session_state.lang == "ko" else language_labels["en"]
    picked = st.sidebar.selectbox(t("language"), options, index=options.index(current_label))
    st.session_state.lang = "ko" if picked == language_labels["ko"] else "en"
    if st.sidebar.button(t("soft_reset"), type="secondary", use_container_width=True):
        soft_reset(storage)
    if st.sidebar.button(t("full_reset"), type="secondary", use_container_width=True):
        full_reset(storage)
        st.rerun()

    tmdb_api_key = env_or_secret("TMDB_API_KEY")
    openai_api_key = env_or_secret("OPENAI_API_KEY")
    if not tmdb_api_key:
        st.error(t("tmdb_required"))
        st.stop()
    if not openai_api_key:
        st.warning(t("openai_missing"))

    tmdb = TMDBClient(api_key=tmdb_api_key, storage=storage, region="KR")
    openai_service = OpenAIService(api_key=openai_api_key, storage=storage)

    try:
        context, constraints, pick_clicked = quick_input_panel(tmdb)
        if pick_clicked:
            st.session_state.qp_context = context
            st.session_state.qp_constraints = constraints
            st.session_state.qp_refinement = None
            st.session_state.qp_started_at = time.time()
            with st.spinner(t("updating")):
                st.session_state.qp_results = get_quick_pick(
                    user_id=st.session_state.user_id,
                    context=context,
                    constraints=constraints,
                    refinement=None,
                    tmdb=tmdb,
                    openai_service=openai_service,
                    storage=storage,
                )
            persist_profile(storage)

        result = st.session_state.qp_results
        if result:
            render_card("top", t("top_pick"), result.get("top"), tmdb, openai_service, storage, result)
            c1, c2 = st.columns(2)
            with c1:
                render_card("backup", t("backup"), result.get("backup"), tmdb, openai_service, storage, result)
            with c2:
                render_card("wildcard", t("wildcard"), result.get("wildcard"), tmdb, openai_service, storage, result)
            render_refine(tmdb, openai_service, storage)
    except TMDBError as exc:
        st.error(f"TMDB error: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
