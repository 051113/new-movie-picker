import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from services.openai_client import OpenAIService
from services.recs import load_collections, pick_featured_collection, rank_collections_for_user

try:
    from services.recs import get_sectioned_recommendations
except ImportError:
    from services.recs import get_ranked_recommendations as _legacy_ranked

    def get_sectioned_recommendations(*args, **kwargs):
        recs, profile_text, profile_hash = _legacy_ranked(*args, **kwargs)
        return {
            "sections": {
                "top_matches": recs[:4],
                "short": recs[4:6],
                "because_you_liked": recs[6:9],
                "wildcards": recs[9:12],
            },
            "profile_text": profile_text,
            "profile_hash": profile_hash,
            "context_hash": profile_hash,
            "ranking_version": "legacy",
        }

from services.storage import Storage
from services.tmdb import TMDBClient, TMDBError


load_dotenv()
st.set_page_config(page_title="VibeRecs", layout="wide")

TRANSLATIONS = {
    "en": {
        "language": "Language",
        "settings": "Settings",
        "region": "Region",
        "collections": "Collections",
        "featured": "Featured",
        "reset_taste": "Reset taste",
        "soft_reset": "Soft reset (last 20 interactions)",
        "full_reset": "Full reset (wipe profile + interactions)",
        "advanced_metrics": "Advanced metrics",
        "like_rate": "Like rate: {value:.2f}",
        "skip_rate": "Skip rate: {value:.2f}",
        "why_opens": "Why opens: {value}",
        "onboarding": "Onboarding",
        "onboarding_caption": "Swipe 10 movies to bootstrap your taste profile.",
        "onboarding_done": "Onboarding complete. Set tonight's context.",
        "load_error_onboarding": "Could not load enough TMDB titles for onboarding.",
        "mood": "Mood",
        "who": "Who",
        "time": "Time",
        "start_recs": "Start recommendations",
        "context_title": "Tonight's context",
        "session_mode": "Session mode: {summary}",
        "vibe_title": "Tonight's Vibe",
        "vibe_caption": "Set the overall tone before fine tuning.",
        "cozy_intense": "Cozy <-> Intense",
        "light_dark": "Light <-> Dark",
        "mainstream_hidden": "Mainstream <-> Hidden Gems",
        "fine_tune": "Fine tune",
        "fine_tune_caption": "Use these for precise control after setting your vibe dials.",
        "constraints": "Constraints",
        "less_violent": "less violent",
        "more_hopeful": "more hopeful",
        "shorter": "shorter",
        "non_english_ok": "non-English ok",
        "no_jump_scares": "no jump scares",
        "only_streaming_now": "Only streaming now",
        "recommendations": "Recommendations",
        "top_matches": "Top matches for you",
        "short_easy": "Short & easy to start",
        "because_liked": "Because you liked ...",
        "wildcards": "Wildcard picks",
        "get_more": "Get more",
        "like": "Like",
        "skip": "Skip",
        "seen_it": "Seen it",
        "why_this": "Why this?",
        "tell_us_why": "Tell us why",
        "too_dark": "Too dark",
        "too_slow": "Too slow",
        "too_violent": "Too violent",
        "not_in_mood": "Not in the mood",
        "add_ai_angle": "Add AI angle",
        "runtime_na": "Runtime not available",
        "availability_unknown": "Availability unknown",
        "availability_checked_unknown": "Availability checked: unknown",
        "availability_checked_days": "Availability checked: {days} days ago",
        "update_vibe": "Update to this vibe",
        "updating_recs": "Updating recommendations for this vibe...",
        "tmdb_required": "TMDB_API_KEY is required. Add it in .env or Streamlit secrets.",
        "openai_missing": "OPENAI_API_KEY missing. Running in fallback mode (no embedding/AI bullets).",
        "tmdb_error": "TMDB error: {error}",
        "unexpected_error": "Unexpected error: {error}",
    },
    "ko": {
        "language": "언어",
        "settings": "설정",
        "region": "지역",
        "collections": "컬렉션",
        "featured": "이번 주 추천",
        "reset_taste": "취향 초기화",
        "soft_reset": "소프트 초기화 (최근 20개 상호작용)",
        "full_reset": "전체 초기화 (프로필 + 상호작용 삭제)",
        "advanced_metrics": "고급 지표",
        "like_rate": "좋아요 비율: {value:.2f}",
        "skip_rate": "스킵 비율: {value:.2f}",
        "why_opens": "왜 이 작품 열람 수: {value}",
        "onboarding": "온보딩",
        "onboarding_caption": "영화 10개를 스와이프해서 취향 프로필을 시작하세요.",
        "onboarding_done": "온보딩이 완료되었습니다. 오늘의 상황을 설정하세요.",
        "load_error_onboarding": "온보딩용 TMDB 영화를 충분히 불러오지 못했습니다.",
        "mood": "기분",
        "who": "함께 보는 사람",
        "time": "시간",
        "start_recs": "추천 시작",
        "context_title": "오늘의 상황",
        "session_mode": "현재 모드: {summary}",
        "vibe_title": "오늘의 바이브",
        "vibe_caption": "세부 조정 전에 전체 분위기를 먼저 정하세요.",
        "cozy_intense": "포근함 <-> 강렬함",
        "light_dark": "밝음 <-> 어두움",
        "mainstream_hidden": "메인스트림 <-> 숨은 명작",
        "fine_tune": "세부 조정",
        "fine_tune_caption": "바이브를 정한 뒤 세밀하게 조정하세요.",
        "constraints": "제약 조건",
        "less_violent": "폭력성 낮게",
        "more_hopeful": "더 희망적으로",
        "shorter": "짧은 작품",
        "non_english_ok": "비영어 작품 허용",
        "no_jump_scares": "점프 스케어 제외",
        "only_streaming_now": "지금 스트리밍 가능만",
        "recommendations": "추천",
        "top_matches": "당신을 위한 최고 매치",
        "short_easy": "짧고 가볍게 보기 좋은 작품",
        "because_liked": "좋아한 작품 기반 추천",
        "wildcards": "와일드카드 추천",
        "get_more": "더 보기",
        "like": "좋아요",
        "skip": "넘기기",
        "seen_it": "이미 봤어요",
        "why_this": "왜 이 작품인가요?",
        "tell_us_why": "이유 알려주기",
        "too_dark": "너무 어두워요",
        "too_slow": "너무 느려요",
        "too_violent": "너무 폭력적이에요",
        "not_in_mood": "지금 기분과 안 맞아요",
        "add_ai_angle": "AI 관점 추가",
        "runtime_na": "러닝타임 정보 없음",
        "availability_unknown": "시청 가능 정보 없음",
        "availability_checked_unknown": "시청 가능 정보 확인 시점: 알 수 없음",
        "availability_checked_days": "시청 가능 정보 확인: {days}일 전",
        "update_vibe": "이 바이브로 업데이트",
        "updating_recs": "현재 바이브에 맞춰 추천을 업데이트하는 중...",
        "tmdb_required": "TMDB_API_KEY가 필요합니다. .env 또는 Streamlit secrets에 추가하세요.",
        "openai_missing": "OPENAI_API_KEY가 없어도 실행됩니다. (임베딩/AI 설명 없이 동작)",
        "tmdb_error": "TMDB 오류: {error}",
        "unexpected_error": "예기치 못한 오류: {error}",
    },
}


def t(key: str, **kwargs: Any) -> str:
    lang = st.session_state.get("lang", "en")
    text = TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


def option_label(value: str) -> str:
    labels = {
        "chill": {"en": "chill", "ko": "차분한"},
        "high-energy": {"en": "high-energy", "ko": "에너지 넘치는"},
        "emotional": {"en": "emotional", "ko": "감성적인"},
        "spooky": {"en": "spooky", "ko": "무서운"},
        "thoughtful": {"en": "thoughtful", "ko": "생각할 거리 있는"},
        "romantic": {"en": "romantic", "ko": "로맨틱한"},
        "solo": {"en": "solo", "ko": "혼자"},
        "date": {"en": "date", "ko": "연인과"},
        "friends": {"en": "friends", "ko": "친구와"},
        "family": {"en": "family", "ko": "가족과"},
        "<90m": {"en": "<90m", "ko": "90분 미만"},
        "90-120m": {"en": "90-120m", "ko": "90-120분"},
        "120m+": {"en": "120m+", "ko": "120분 이상"},
        "Cozy": {"en": "Cozy", "ko": "포근함"},
        "Balanced": {"en": "Balanced", "ko": "균형"},
        "Intense": {"en": "Intense", "ko": "강렬함"},
        "Light": {"en": "Light", "ko": "밝음"},
        "Dark": {"en": "Dark", "ko": "어두움"},
        "Mainstream": {"en": "Mainstream", "ko": "메인스트림"},
        "Hidden Gems": {"en": "Hidden Gems", "ko": "숨은 명작"},
    }
    lang = st.session_state.get("lang", "en")
    return labels.get(value, {}).get(lang, value)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { max-width: 1120px; padding-top: 1.4rem; padding-bottom: 2rem; }
        .vr-section-title { font-size: 1.22rem; font-weight: 700; margin: 1.0rem 0 0.45rem 0; }
        .vr-soft-card { background:#fff; border:1px solid #e8edf3; border-radius:12px; box-shadow:0 4px 14px rgba(18,38,63,0.05); padding:0.75rem 0.9rem; margin-bottom:0.75rem; }
        .vr-chip { display:inline-block; padding:0.2rem 0.55rem; border-radius:999px; border:1px solid #dce6f2; background:#f6f9fc; color:#334e68; font-size:0.75rem; margin:0.12rem 0.18rem 0.12rem 0; }
        .vr-meta { color:#5d7085; font-size:0.88rem; margin-top:-0.1rem; margin-bottom:0.25rem; }
        .vr-muted { color:#6b7f95; font-size:0.78rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def env_or_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def semantic_label(name: str, value: int) -> str:
    labels = {
        "pace": ("slow-burn", "balanced rhythm", "fast-paced, tight editing"),
        "darkness": ("uplifting and bright", "mixed tone", "grim and heavy"),
        "humor": ("serious", "occasional levity", "humor-forward"),
        "romance": ("little romance", "some relationship focus", "romance-heavy"),
        "violence": ("minimal violence", "moderate intensity", "high-impact action"),
        "weirdness": ("grounded", "some offbeat ideas", "strange and experimental"),
    }
    low, mid, high = labels[name]
    return low if value < 35 else (high if value > 65 else mid)


def init_state(storage: Storage) -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    storage.get_or_create_user(st.session_state.user_id, region=env_or_secret("TMDB_REGION", "KR") or "KR")

    defaults = {
        "onboarding_movies": [], "swipes": [], "onboarding_complete": False,
        "region": (env_or_secret("TMDB_REGION", "KR") or "KR").upper(),
        "context": {"mood": "chill", "who": "solo", "time": "90-120m"},
        "vibe_dials": {"cozy_intense": "Balanced", "light_dark": "Balanced", "mainstream_hidden": "Balanced"},
        "sliders": {"pace": 50, "darkness": 40, "humor": 50, "romance": 40, "violence": 30, "weirdness": 35},
        "constraints": {"less_violent": False, "more_hopeful": False, "shorter": False, "non_english_ok": True, "no_jump_scares": False, "only_streaming_now": True},
        "seed_movie_id": None, "sections": {}, "profile_hash": "", "context_hash": "", "last_signature": "", "ranking_version": "v2", "loaded_profile": False,
        "section_limits": {"top_matches": 3, "short": 0, "because_you_liked": 3, "wildcards": 3},
        "lang": "en",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if not st.session_state.loaded_profile:
        profile = storage.load_profile(st.session_state.user_id)
        if profile:
            st.session_state.region = profile.get("region", st.session_state.region)
            st.session_state.context.update(profile.get("context", {}))
            st.session_state.vibe_dials.update(profile.get("vibe_dials", {}))
            st.session_state.sliders.update(profile.get("sliders", {}))
            st.session_state.constraints.update(profile.get("constraints", {}))
            st.session_state.onboarding_complete = profile.get("onboarding_complete", False)
        st.session_state.loaded_profile = True


def save_profile(storage: Storage) -> None:
    hidden = st.session_state.vibe_dials.get("mainstream_hidden", "Balanced")
    exploration = 0.2 if hidden == "Mainstream" else (0.85 if hidden == "Hidden Gems" else 0.5)
    storage.save_profile(
        st.session_state.user_id,
        region=st.session_state.region,
        sliders=st.session_state.sliders,
        vibe_dials=st.session_state.vibe_dials,
        constraints=st.session_state.constraints,
        context=st.session_state.context,
        exploration_pref=exploration,
        onboarding_complete=bool(st.session_state.onboarding_complete),
    )


def ensure_onboarding_movies(tmdb: TMDBClient) -> None:
    if st.session_state.onboarding_movies:
        return
    movies, seen = [], set()
    for source in [tmdb.trending_movies(page=1), tmdb.popular_movies(page=1), tmdb.popular_movies(page=2)]:
        for movie in source:
            if movie.get("id") in seen:
                continue
            seen.add(movie.get("id"))
            movies.append(movie)
            if len(movies) >= 24:
                st.session_state.onboarding_movies = movies
                return
    st.session_state.onboarding_movies = movies


def render_onboarding(tmdb: TMDBClient, storage: Storage) -> None:
    st.markdown(f'<div class="vr-section-title">{t("onboarding")}</div>', unsafe_allow_html=True)
    st.caption(t("onboarding_caption"))
    ensure_onboarding_movies(tmdb)
    swipe_count = len(st.session_state.swipes)
    if swipe_count < 10:
        if len(st.session_state.onboarding_movies) <= swipe_count:
            st.error(t("load_error_onboarding"))
            return
        movie = st.session_state.onboarding_movies[swipe_count]
        year = (movie.get("release_date") or "")[:4]
        st.progress(swipe_count / 10.0)
        left, right = st.columns([1, 2])
        with left:
            poster = TMDBClient.image_url(movie.get("poster_path"))
            if poster:
                st.image(poster, use_container_width=True)
        with right:
            st.markdown(f"### {movie.get('title', 'Unknown')} ({year or '-'})")
            st.write(movie.get("overview", "No overview available."))
            cols = st.columns(3)
            for label, action, col in [(t("like"), "like", cols[0]), (t("dislike"), "dislike", cols[1]), (t("skip"), "skip", cols[2])]:
                with col:
                    if st.button(label, key=f"onb_{movie['id']}_{action}", use_container_width=True):
                        st.session_state.swipes.append({"movie_id": movie["id"], "title": movie.get("title", ""), "action": action})
                        storage.log_interaction(st.session_state.user_id, int(movie["id"]), action, session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
                        save_profile(storage)
                        st.rerun()
        return

    st.success(t("onboarding_done"))
    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state.context["mood"] = st.selectbox(t("mood"), ["chill", "high-energy", "emotional", "spooky", "thoughtful", "romantic"], format_func=option_label)
    with c2:
        st.session_state.context["who"] = st.selectbox(t("who"), ["solo", "date", "friends", "family"], format_func=option_label)
    with c3:
        st.session_state.context["time"] = st.selectbox(t("time"), ["<90m", "90-120m", "120m+"], index=1, format_func=option_label)
    if st.button(t("start_recs"), type="primary"):
        st.session_state.onboarding_complete = True
        save_profile(storage)
        st.rerun()


def _pick_one(label: str, options: List[str], current: str, key: str) -> str:
    labels = {opt: option_label(opt) for opt in options}
    rev = {v: k for k, v in labels.items()}
    if hasattr(st, "segmented_control"):
        view = [labels[o] for o in options]
        default = labels.get(current, view[0])
        choice = st.segmented_control(label, view, selection_mode="single", default=default, key=key)
        return rev.get(choice or default, current)
    return st.radio(label, options, index=options.index(current) if current in options else 0, horizontal=True, key=key, format_func=option_label)


def _constraint_picker(current: Dict[str, bool]) -> Dict[str, bool]:
    labels = {
        "less_violent": t("less_violent"), "more_hopeful": t("more_hopeful"), "shorter": t("shorter"),
        "non_english_ok": t("non_english_ok"), "no_jump_scares": t("no_jump_scares"), "only_streaming_now": t("only_streaming_now"),
    }
    picked = dict(current)
    if hasattr(st, "pills"):
        defaults = [labels[k] for k, v in current.items() if v]
        selected = st.pills(t("constraints"), list(labels.values()), selection_mode="multi", default=defaults) or []
        inv = {v: k for k, v in labels.items()}
        picked = {k: False for k in labels}
        for item in selected:
            if item in inv:
                picked[inv[item]] = True
    else:
        cols = st.columns(3)
        for i, (key, label) in enumerate(labels.items()):
            with cols[i % 3]:
                picked[key] = st.checkbox(label, value=current.get(key, False), key=f"cst_{key}")
    return picked


def render_context_and_controls(storage: Storage) -> None:
    st.markdown(f'<div class="vr-section-title">{t("context_title")}</div>', unsafe_allow_html=True)
    ctx = st.session_state.context
    summary = f"{option_label(ctx.get('who','solo'))} • {option_label(ctx.get('mood','chill'))} • {option_label(ctx.get('time','90-120m'))}"
    st.markdown(f'<div class="vr-soft-card">{t("session_mode", summary=summary)}</div>', unsafe_allow_html=True)

    b1, b2, b3 = st.columns(3)
    with b1:
        st.session_state.context["mood"] = _pick_one(t("mood"), ["chill", "high-energy", "emotional", "spooky", "thoughtful", "romantic"], st.session_state.context.get("mood", "chill"), "ctx_mood")
    with b2:
        st.session_state.context["who"] = _pick_one(t("who"), ["solo", "date", "friends", "family"], st.session_state.context.get("who", "solo"), "ctx_who")
    with b3:
        st.session_state.context["time"] = _pick_one(t("time"), ["<90m", "90-120m", "120m+"], st.session_state.context.get("time", "90-120m"), "ctx_time")

    st.markdown(f'<div class="vr-section-title">{t("vibe_title")}</div>', unsafe_allow_html=True)
    st.caption(t("vibe_caption"))
    d1, d2, d3 = st.columns(3)
    with d1:
        st.session_state.vibe_dials["cozy_intense"] = _pick_one(t("cozy_intense"), ["Cozy", "Balanced", "Intense"], st.session_state.vibe_dials.get("cozy_intense", "Balanced"), "dial_cozy")
    with d2:
        st.session_state.vibe_dials["light_dark"] = _pick_one(t("light_dark"), ["Light", "Balanced", "Dark"], st.session_state.vibe_dials.get("light_dark", "Balanced"), "dial_light")
    with d3:
        st.session_state.vibe_dials["mainstream_hidden"] = _pick_one(t("mainstream_hidden"), ["Mainstream", "Balanced", "Hidden Gems"], st.session_state.vibe_dials.get("mainstream_hidden", "Balanced"), "dial_hidden")

    with st.expander(t("fine_tune"), expanded=False):
        st.caption(t("fine_tune_caption"))
        cols = st.columns(2)
        for i, name in enumerate(["pace", "darkness", "humor", "romance", "violence", "weirdness"]):
            with cols[i % 2]:
                val = st.slider(name.capitalize(), 0, 100, int(st.session_state.sliders.get(name, 50)), key=f"sld_{name}")
                st.session_state.sliders[name] = val
                st.caption(semantic_label(name, val))

    st.session_state.constraints = _constraint_picker(st.session_state.constraints)
    selected = [t(k) for k, v in st.session_state.constraints.items() if v]
    if selected:
        st.markdown("".join([f'<span class="vr-chip">{x}</span>' for x in selected]), unsafe_allow_html=True)
    save_profile(storage)


def build_signature() -> str:
    payload = {"context": st.session_state.context, "vibe_dials": st.session_state.vibe_dials, "sliders": st.session_state.sliders, "constraints": st.session_state.constraints, "seed_movie_id": st.session_state.seed_movie_id, "region": st.session_state.region}
    return Storage.stable_hash(json.dumps(payload, sort_keys=True))


def rerank_if_needed(tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage, force: bool = False) -> None:
    signature = build_signature()
    if not (force or signature != st.session_state.last_signature or not st.session_state.sections):
        return
    with st.spinner(t("updating_recs")):
        time.sleep(0.2)
        result = get_sectioned_recommendations(
            tmdb=tmdb, openai_service=openai_service, storage=storage, user_id=st.session_state.user_id,
            context=st.session_state.context, vibe_dials=st.session_state.vibe_dials, sliders=st.session_state.sliders,
            constraints=st.session_state.constraints, region=st.session_state.region,
            collections=load_collections("curated_collections.json", region=st.session_state.region),
            seed_movie_id=st.session_state.seed_movie_id, ranking_version=st.session_state.ranking_version,
        )
    st.session_state.sections = result["sections"]
    st.session_state.profile_hash = result["profile_hash"]
    st.session_state.context_hash = result["context_hash"]
    st.session_state.last_signature = signature
    st.session_state.section_limits = {"top_matches": 3, "short": 0, "because_you_liked": 3, "wildcards": 3}


def render_why(movie: Dict[str, Any], openai_service: OpenAIService, storage: Storage) -> None:
    deterministic = movie.get("_reasons", []) or ["Fits your current vibe settings", "Strong overall match score"]
    for item in deterministic:
        st.markdown(f"- {item}")
    storage.log_interaction(st.session_state.user_id, int(movie["id"]), "why_open", session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
    if openai_service.enabled and st.button(t("add_ai_angle"), key=f"why_ai_{movie['id']}", type="secondary", use_container_width=True):
        extras = openai_service.generate_why_spoiler_free(movie=movie, deterministic_bullets=deterministic, user_context={"context": st.session_state.context, "vibe_dials": st.session_state.vibe_dials, "constraints": st.session_state.constraints}, profile_hash=st.session_state.profile_hash, context_hash=st.session_state.context_hash)
        for line in extras:
            st.markdown(f"- {line}")


def _metadata_line(movie: Dict[str, Any]) -> str:
    parts = []
    rating = movie.get("vote_average")
    if rating:
        parts.append(f"* {float(rating):.1f}")
    runtime = movie.get("runtime")
    parts.append(f"{int(runtime)}m" if runtime else t("runtime_na"))
    providers = movie.get("providers", {}) or {}
    flat = providers.get("flatrate", [])
    if flat and flat[0].get("provider_name"):
        parts.append(flat[0]["provider_name"])
    elif not providers:
        parts.append(t("availability_unknown"))
    pop = movie.get("popularity") or 0
    if pop > 0:
        parts.append(f"Pop {int(pop)}")
    return " • ".join(parts)


def render_movie_card(movie: Dict[str, Any], tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage) -> None:
    movie_id = int(movie["id"])
    year = (movie.get("release_date") or "")[:4]
    poster = TMDBClient.image_url(movie.get("poster_path"), size="w342")
    if poster:
        st.image(poster, use_container_width=True)
    st.markdown(f"**{movie.get('title', '-')} ({year or '-'})**")
    st.markdown(f'<div class="vr-meta">{_metadata_line(movie)}</div>', unsafe_allow_html=True)

    badges = tmdb.provider_badges(movie.get("providers", {}))
    if badges:
        st.markdown("".join([f'<span class="vr-chip">{b}</span>' for b in badges[:4]]), unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="vr-chip">{t("availability_unknown")}</span>', unsafe_allow_html=True)

    age = movie.get("provider_age_days")
    st.markdown(f'<div class="vr-muted">{t("availability_checked_unknown") if age is None else t("availability_checked_days", days=age)}</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button(t("like"), key=f"like_{movie_id}", use_container_width=True):
            st.session_state.seed_movie_id = movie_id
            storage.log_interaction(st.session_state.user_id, movie_id, "like", session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
            st.session_state.last_signature = ""
            st.rerun()
    with c2:
        if st.button(t("skip"), key=f"skip_{movie_id}", use_container_width=True):
            storage.log_interaction(st.session_state.user_id, movie_id, "dislike", session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
            st.session_state[f"show_reason_{movie_id}"] = True
            st.session_state.last_signature = ""
            st.rerun()

    s1, s2 = st.columns(2)
    with s1:
        if st.button(t("seen_it"), key=f"seen_{movie_id}", use_container_width=True, type="secondary"):
            storage.log_interaction(st.session_state.user_id, movie_id, "seen", session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
            st.session_state.last_signature = ""
            st.rerun()
    with s2:
        with st.expander(t("why_this")):
            render_why(movie, openai_service, storage)

    if st.session_state.get(f"show_reason_{movie_id}", False):
        with st.expander(t("tell_us_why"), expanded=True):
            reasons = [(t("too_dark"), "too_dark"), (t("too_slow"), "too_slow"), (t("too_violent"), "too_violent"), (t("not_in_mood"), "not_in_mood")]
            rc = st.columns(2)
            for i, (label, code) in enumerate(reasons):
                with rc[i % 2]:
                    if st.button(label, key=f"reason_{movie_id}_{code}", use_container_width=True, type="secondary"):
                        apply_reason_adjustment(code)
                        storage.log_interaction(st.session_state.user_id, movie_id, "dislike", reason=code, session_id=st.session_state.session_id, ranking_version=st.session_state.ranking_version)
                        save_profile(storage)
                        st.session_state.last_signature = ""
                        st.rerun()


def apply_reason_adjustment(reason: str) -> None:
    if reason == "too_dark":
        st.session_state.sliders["darkness"] = max(0, st.session_state.sliders["darkness"] - 10)
    elif reason == "too_slow":
        st.session_state.sliders["pace"] = min(100, st.session_state.sliders["pace"] + 10)
    elif reason == "too_violent":
        st.session_state.sliders["violence"] = max(0, st.session_state.sliders["violence"] - 12)
        st.session_state.constraints["less_violent"] = True
    elif reason == "not_in_mood":
        st.session_state.context["mood"] = "chill"


def render_sections(tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage) -> None:
    st.markdown(f'<div class="vr-section-title">{t("recommendations")}</div>', unsafe_allow_html=True)
    labels = [(t("top_matches"), "top_matches"), (t("short_easy"), "short"), (t("because_liked"), "because_you_liked"), (t("wildcards"), "wildcards")]
    for title, key in labels:
        st.markdown(f"#### {title}")
        rows = (st.session_state.sections or {}).get(key, [])
        limit = int(st.session_state.section_limits.get(key, 3))
        visible = rows[:limit]
        cols = st.columns(3)
        for idx, movie in enumerate(visible):
            with cols[idx % 3]:
                with st.container(border=True):
                    render_movie_card(movie, tmdb, openai_service, storage)
        if len(rows) > limit:
            if st.button(t("get_more"), key=f"more_{key}", type="secondary"):
                st.session_state.section_limits[key] = limit + 3
                st.rerun()


def render_collections_sidebar(openai_service: OpenAIService, storage: Storage, region: str) -> None:
    st.sidebar.markdown(f"### {t('collections')}")
    collections = load_collections("curated_collections.json", region=region)
    profile_text = f"context={st.session_state.context}, vibe={st.session_state.vibe_dials}, sliders={st.session_state.sliders}, constraints={st.session_state.constraints}"
    ranked = rank_collections_for_user(collections, profile_text, openai_service, storage)
    featured = pick_featured_collection(ranked)
    st.sidebar.markdown(f"**{t('featured')}**")
    st.sidebar.write(featured["title"])
    st.sidebar.caption(featured.get("description", ""))
    st.sidebar.markdown("---")
    shown = [c for c in ranked if c["id"] != featured["id"]][:4]
    if len(shown) < 3:
        shown = (shown + collections)[:3]
    for col in shown[:4]:
        st.sidebar.markdown(f"- {col['title']}")


def render_sidebar(storage: Storage) -> None:
    st.sidebar.markdown(f"### {t('settings')}")
    current_lang = "한국어" if st.session_state.get("lang", "en") == "ko" else "English"
    selected = st.sidebar.selectbox(t("language"), ["English", "한국어"], index=["English", "한국어"].index(current_lang))
    st.session_state.lang = "ko" if selected == "한국어" else "en"

    region_options = ["US", "KR", "GB", "CA", "AU", "DE", "FR", "JP", "IN"]
    if st.session_state.region not in region_options:
        region_options = [st.session_state.region] + region_options
    st.session_state.region = st.sidebar.selectbox(t("region"), region_options, index=region_options.index(st.session_state.region))

    st.sidebar.markdown(f"### {t('reset_taste')}")
    if st.sidebar.button(t("soft_reset"), type="secondary", use_container_width=True):
        storage.reset_profile_soft(st.session_state.user_id, n=20)
        st.session_state.last_signature = ""
        st.rerun()
    if st.sidebar.button(t("full_reset"), type="secondary", use_container_width=True):
        storage.reset_profile_full(st.session_state.user_id)
        new_uid = str(uuid.uuid4())
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state.user_id = new_uid
        st.rerun()

    metrics = storage.get_metrics(st.session_state.user_id)
    with st.sidebar.expander(t("advanced_metrics"), expanded=False):
        st.caption(t("like_rate", value=metrics["like_rate"]))
        st.caption(t("skip_rate", value=metrics["skip_rate"]))
        st.caption(t("why_opens", value=metrics["why_open_count"]))


def main() -> None:
    inject_styles()
    st.title("VibeRecs")

    tmdb_api_key = env_or_secret("TMDB_API_KEY")
    openai_api_key = env_or_secret("OPENAI_API_KEY")

    storage = Storage()
    init_state(storage)
    render_sidebar(storage)

    if not tmdb_api_key:
        st.error(t("tmdb_required"))
        st.stop()
    if not openai_api_key:
        st.warning(t("openai_missing"))

    tmdb = TMDBClient(api_key=tmdb_api_key, storage=storage, region=st.session_state.region)
    openai_service = OpenAIService(api_key=openai_api_key, storage=storage)
    render_collections_sidebar(openai_service, storage, region=st.session_state.region)

    try:
        if not st.session_state.onboarding_complete:
            render_onboarding(tmdb, storage)
            return

        render_context_and_controls(storage)
        if st.button(t("update_vibe"), type="primary"):
            rerank_if_needed(tmdb, openai_service, storage, force=True)
        else:
            rerank_if_needed(tmdb, openai_service, storage, force=False)

        render_sections(tmdb, openai_service, storage)
        save_profile(storage)
    except TMDBError as exc:
        st.error(t("tmdb_error", error=exc))
    except Exception as exc:
        st.error(t("unexpected_error", error=exc))


if __name__ == "__main__":
    main()
