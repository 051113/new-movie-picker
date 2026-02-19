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
        "like": "Like",
        "seen_it": "Seen it",
        "skip": "Skip",
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
        "language": "Language",
        "soft_reset": "Soft reset (last 20 interactions)",
        "full_reset": "Full reset",
        "tmdb_required": "TMDB_API_KEY is required. Add it in .env or Streamlit secrets.",
        "openai_missing": "OPENAI_API_KEY missing. Running in fallback mode.",
        "updating": "Finding your three picks...",
        "runtime_na": "Runtime not available",
        "availability_unknown": "Availability unknown",
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
        "seen_it": "이미 봤어요",
        "skip": "넘기기",
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


def init_state(storage: Storage) -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
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
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(label, options, default=default, selection_mode="single", key=key)
        return value or default
    return st.radio(label, options, index=options.index(default) if default in options else 0, horizontal=True, key=key)


def quick_input_panel(tmdb: TMDBClient) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    st.markdown(f"## {t('quick_pick')}")
    times = ["20", "45", "90", "120+"]
    who_options = ["Alone", "Partner", "Friends", "Family"]
    intentions = [
        "Comfort & Cozy",
        "Light & Fun",
        "Engaging Story",
        "Intense & Thrilling",
        "Emotional & Deep",
        "Surprise Me",
    ]
    energies = ["Chill", "Balanced", "High"]

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            time_choice = pick_single(t("time_available"), times, "90", "qp_time")
        with c2:
            who = pick_single(t("who"), who_options, "Alone", "qp_who")
        with c3:
            energy = pick_single(t("energy"), energies, "Balanced", "qp_energy")

        intention = pick_single(t("intention"), intentions, "Engaging Story", "qp_intention")

        c4, c5 = st.columns([1, 1])
        with c4:
            streaming_only = st.toggle(t("streaming_only"), value=True)
        with c5:
            region = st.selectbox(t("region"), ["KR", "US", "JP", "GB", "CA", "AU", "DE", "FR", "IN"], index=0)

        provider_names: List[str] = []
        if streaming_only:
            try:
                options = tmdb.region_streaming_providers(region=region)
            except Exception:
                options = []
            provider_names = st.multiselect(t("providers"), options, default=[])

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
        """
        <div style="aspect-ratio:2/3;background:#e9eef5;border:1px solid #d8e2f0;border-radius:10px;
                    display:flex;align-items:center;justify-content:center;color:#63758a;font-weight:600;">
            No Image Found
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


def render_why(
    slot_key: str,
    movie: Dict[str, Any],
    quick_result: Dict[str, Any],
    openai_service: OpenAIService,
    storage: Storage,
) -> None:
    reasons = quick_result.get("reasons", {}).get(slot_key, [])[:3]
    if not reasons:
        reasons = ["Good match for your selected context.", "Fits your current time and energy setting.", "Valid for current streaming constraints."]
    for r in reasons:
        st.markdown(f"- {r}")
    if openai_service.enabled and st.button(t("add_ai_angle"), key=f"ai_why_{slot_key}_{movie['id']}", type="secondary"):
        extra = openai_service.generate_why_spoiler_free(
            movie=movie,
            deterministic_bullets=reasons,
            user_context={"context": st.session_state.qp_context, "constraints": st.session_state.qp_constraints, "refinement": st.session_state.qp_refinement},
            profile_hash=quick_result.get("profile_hash", ""),
            context_hash=quick_result.get("context_hash", ""),
        )
        for line in extra:
            st.markdown(f"- {line}")


def action_buttons(slot_key: str, movie: Dict[str, Any], storage: Storage) -> None:
    cols = st.columns(3)
    with cols[0]:
        if st.button(t("like"), key=f"like_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "like", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
    with cols[1]:
        if st.button(t("seen_it"), key=f"seen_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "seen", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
    with cols[2]:
        if st.button(t("skip"), key=f"skip_{slot_key}_{movie['id']}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, int(movie["id"]), "dislike", session_id=st.session_state.qp_session_id, ranking_version="quick_pick")
            st.session_state.skip_reason_slot = (slot_key, int(movie["id"]))


def skip_reason_panel(storage: Storage) -> None:
    slot = st.session_state.skip_reason_slot
    if not slot:
        return
    _, movie_id = slot
    options = [t("reason_default"), t("reason_mood"), t("reason_long"), t("reason_seen"), t("reason_service")]
    with st.container(border=True):
        st.caption(t("tell_us_why"))
        if hasattr(st, "pills"):
            reason = st.pills(t("tell_us_why"), options, selection_mode="single", default=options[0])
        else:
            reason = st.selectbox(t("tell_us_why"), options, index=0)
        if st.button(t("save_reason"), type="secondary"):
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
            st.info("No candidate found.")
            return
        poster_or_placeholder(movie, tmdb)
        st.markdown(f"**{movie.get('title', '-') }**")
        st.caption(movie_meta_line(movie))
        st.write(textwrap.shorten(movie.get("overview", ""), width=180, placeholder="..."))
        action_buttons(slot_key, movie, storage)
        with st.expander(t("why_this")):
            render_why(slot_key, movie, quick_result, openai_service, storage)


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
                st.rerun()


def main() -> None:
    st.title("VibeRecs")
    storage = Storage()
    init_state(storage)

    st.sidebar.markdown(f"### {t('settings')}")
    current = "한국어" if st.session_state.lang == "ko" else "English"
    picked = st.sidebar.selectbox(t("language"), ["English", "한국어"], index=["English", "한국어"].index(current))
    st.session_state.lang = "ko" if picked == "한국어" else "en"
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

        result = st.session_state.qp_results
        if result:
            render_card("top", t("top_pick"), result.get("top"), tmdb, openai_service, storage, result)
            c1, c2 = st.columns(2)
            with c1:
                render_card("backup", t("backup"), result.get("backup"), tmdb, openai_service, storage, result)
            with c2:
                render_card("wildcard", t("wildcard"), result.get("wildcard"), tmdb, openai_service, storage, result)
            skip_reason_panel(storage)
            render_refine(tmdb, openai_service, storage)
    except TMDBError as exc:
        st.error(f"TMDB error: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
