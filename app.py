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


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 1.4rem;
            padding-bottom: 2rem;
        }
        .vr-section-title {
            font-size: 1.22rem;
            font-weight: 700;
            margin: 1.0rem 0 0.45rem 0;
            letter-spacing: 0.01em;
        }
        .vr-soft-card {
            background: #ffffff;
            border: 1px solid #e8edf3;
            border-radius: 12px;
            box-shadow: 0 4px 14px rgba(18, 38, 63, 0.05);
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.75rem;
        }
        .vr-session-line {
            color: #425466;
            font-size: 0.92rem;
            margin-bottom: 0.4rem;
        }
        .vr-chip {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            border: 1px solid #dce6f2;
            background: #f6f9fc;
            color: #334e68;
            font-size: 0.75rem;
            margin: 0.12rem 0.18rem 0.12rem 0;
        }
        .vr-meta {
            color: #5d7085;
            font-size: 0.88rem;
            margin-top: -0.1rem;
            margin-bottom: 0.25rem;
        }
        .vr-muted {
            color: #6b7f95;
            font-size: 0.78rem;
        }
        .vr-why-item {
            margin-bottom: 0.2rem;
            font-size: 0.9rem;
            color: #2d3e50;
        }
        .vr-divider {
            margin: 0.4rem 0 0.6rem 0;
        }
        .stButton button {
            border-radius: 10px;
        }
        .stButton button[kind="secondary"] {
            border-color: #d9e3ef;
            color: #334e68;
            background: #f8fbff;
        }
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
    if value < 35:
        return low
    if value > 65:
        return high
    return mid


def init_state(storage: Storage) -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    storage.get_or_create_user(st.session_state.user_id, region=env_or_secret("TMDB_REGION", "US") or "US")

    defaults = {
        "onboarding_movies": [],
        "swipes": [],
        "onboarding_complete": False,
        "region": (env_or_secret("TMDB_REGION", "US") or "US").upper(),
        "context": {"mood": "chill", "who": "solo", "time": "90-120m"},
        "vibe_dials": {
            "cozy_intense": "Balanced",
            "light_dark": "Balanced",
            "mainstream_hidden": "Balanced",
        },
        "sliders": {
            "pace": 50,
            "darkness": 40,
            "humor": 50,
            "romance": 40,
            "violence": 30,
            "weirdness": 35,
        },
        "constraints": {
            "less_violent": False,
            "more_hopeful": False,
            "shorter": False,
            "non_english_ok": True,
            "no_jump_scares": False,
            "only_streaming_now": False,
        },
        "seed_movie_id": None,
        "sections": {},
        "profile_hash": "",
        "context_hash": "",
        "last_signature": "",
        "ranking_version": "v2",
        "loaded_profile": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

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
    exploration = 0.5
    if hidden == "Mainstream":
        exploration = 0.2
    elif hidden == "Hidden Gems":
        exploration = 0.85
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
    movies: List[Dict[str, Any]] = []
    seen = set()
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
    st.markdown('<div class="vr-section-title">Onboarding</div>', unsafe_allow_html=True)
    st.caption("Swipe 10 movies to bootstrap your taste profile.")
    ensure_onboarding_movies(tmdb)
    swipe_count = len(st.session_state.swipes)

    if swipe_count < 10:
        if len(st.session_state.onboarding_movies) <= swipe_count:
            st.error("Could not load enough TMDB titles for onboarding.")
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
            for label, action, col in [("Like", "like", cols[0]), ("Dislike", "dislike", cols[1]), ("Skip", "skip", cols[2])]:
                with col:
                    if st.button(label, key=f"onb_{movie['id']}_{action}", use_container_width=True):
                        st.session_state.swipes.append({"movie_id": movie["id"], "title": movie.get("title", ""), "action": action})
                        storage.log_interaction(
                            st.session_state.user_id,
                            movie_id=int(movie["id"]),
                            action=action,
                            session_id=st.session_state.session_id,
                            ranking_version=st.session_state.ranking_version,
                        )
                        save_profile(storage)
                        st.rerun()
        return

    st.success("Onboarding complete. Set tonight's context.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state.context["mood"] = st.selectbox("Mood", ["chill", "high-energy", "emotional", "spooky", "thoughtful", "romantic"], index=0)
    with c2:
        st.session_state.context["who"] = st.selectbox("Who", ["solo", "date", "friends", "family"], index=0)
    with c3:
        st.session_state.context["time"] = st.selectbox("Time", ["<90m", "90-120m", "120m+"], index=1)

    if st.button("Start recommendations", type="primary"):
        st.session_state.onboarding_complete = True
        save_profile(storage)
        st.rerun()


def _pick_one(label: str, options: List[str], current: str, key: str) -> str:
    if hasattr(st, "segmented_control"):
        choice = st.segmented_control(label, options, selection_mode="single", default=current, key=key)
        return choice or current
    return st.radio(label, options, index=options.index(current) if current in options else 0, horizontal=True, key=key)


def _constraint_picker(current: Dict[str, bool]) -> Dict[str, bool]:
    labels = {
        "less_violent": "less violent",
        "more_hopeful": "more hopeful",
        "shorter": "shorter",
        "non_english_ok": "non-English ok",
        "no_jump_scares": "no jump scares",
        "only_streaming_now": "Only streaming now",
    }
    picked = dict(current)
    if hasattr(st, "pills"):
        defaults = [labels[k] for k, v in current.items() if v]
        selected = st.pills("Constraints", list(labels.values()), selection_mode="multi", default=defaults)
        selected = selected or []
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
    st.markdown('<div class="vr-section-title">Tonight\'s context</div>', unsafe_allow_html=True)
    ctx = st.session_state.context
    summary = f"{ctx.get('who', 'solo').title()} • {ctx.get('mood', 'chill').title()} • {ctx.get('time', '90-120m')}"
    st.markdown(f'<div class="vr-soft-card"><div class="vr-session-line">Session mode: {summary}</div></div>', unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    with b1:
        st.session_state.context["mood"] = _pick_one("Mood", ["chill", "high-energy", "emotional", "spooky", "thoughtful", "romantic"], st.session_state.context.get("mood", "chill"), "ctx_mood")
    with b2:
        st.session_state.context["who"] = _pick_one("Who", ["solo", "date", "friends", "family"], st.session_state.context.get("who", "solo"), "ctx_who")
    with b3:
        st.session_state.context["time"] = _pick_one("Time", ["<90m", "90-120m", "120m+"], st.session_state.context.get("time", "90-120m"), "ctx_time")

    st.markdown('<div class="vr-section-title">Tonight\'s Vibe</div>', unsafe_allow_html=True)
    st.markdown('<div class="vr-soft-card"><div class="vr-session-line">Set the overall tone before fine tuning.</div></div>', unsafe_allow_html=True)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.session_state.vibe_dials["cozy_intense"] = _pick_one("Cozy <-> Intense", ["Cozy", "Balanced", "Intense"], st.session_state.vibe_dials.get("cozy_intense", "Balanced"), "dial_cozy")
    with d2:
        st.session_state.vibe_dials["light_dark"] = _pick_one("Light <-> Dark", ["Light", "Balanced", "Dark"], st.session_state.vibe_dials.get("light_dark", "Balanced"), "dial_light")
    with d3:
        st.session_state.vibe_dials["mainstream_hidden"] = _pick_one("Mainstream <-> Hidden Gems", ["Mainstream", "Balanced", "Hidden Gems"], st.session_state.vibe_dials.get("mainstream_hidden", "Balanced"), "dial_hidden")

    with st.expander("Fine tune", expanded=False):
        st.caption("Use these for precise control after setting your vibe dials.")
        slider_cols = st.columns(2)
        names = ["pace", "darkness", "humor", "romance", "violence", "weirdness"]
        for i, slider_name in enumerate(names):
            with slider_cols[i % 2]:
                value = st.slider(
                    slider_name.capitalize(),
                    min_value=0,
                    max_value=100,
                    value=int(st.session_state.sliders.get(slider_name, 50)),
                    key=f"sld_{slider_name}",
                )
                st.session_state.sliders[slider_name] = value
                st.caption(semantic_label(slider_name, value))

    st.session_state.constraints = _constraint_picker(st.session_state.constraints)
    selected_constraints = [k.replace("_", " ") for k, v in st.session_state.constraints.items() if v]
    if selected_constraints:
        chips = "".join([f'<span class="vr-chip">{c}</span>' for c in selected_constraints])
        st.markdown(chips, unsafe_allow_html=True)
    save_profile(storage)


def build_signature() -> str:
    payload = {
        "context": st.session_state.context,
        "vibe_dials": st.session_state.vibe_dials,
        "sliders": st.session_state.sliders,
        "constraints": st.session_state.constraints,
        "seed_movie_id": st.session_state.seed_movie_id,
        "region": st.session_state.region,
    }
    return Storage.stable_hash(json.dumps(payload, sort_keys=True))


def rerank_if_needed(tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage, force: bool = False) -> None:
    signature = build_signature()
    must_rerank = force or (signature != st.session_state.last_signature) or not st.session_state.sections
    if not must_rerank:
        return
    with st.spinner("Updating recommendations for this vibe..."):
        time.sleep(0.2)
        collections = load_collections("curated_collections.json", region=st.session_state.region)
        result = get_sectioned_recommendations(
            tmdb=tmdb,
            openai_service=openai_service,
            storage=storage,
            user_id=st.session_state.user_id,
            context=st.session_state.context,
            vibe_dials=st.session_state.vibe_dials,
            sliders=st.session_state.sliders,
            constraints=st.session_state.constraints,
            region=st.session_state.region,
            collections=collections,
            seed_movie_id=st.session_state.seed_movie_id,
            ranking_version=st.session_state.ranking_version,
        )
    st.session_state.sections = result["sections"]
    st.session_state.profile_hash = result["profile_hash"]
    st.session_state.context_hash = result["context_hash"]
    st.session_state.last_signature = signature


def log_shown_cards(storage: Storage, sections: Dict[str, List[Dict[str, Any]]]) -> None:
    seen_key = "shown_once_ids"
    if seen_key not in st.session_state:
        st.session_state[seen_key] = set()
    for rows in sections.values():
        for movie in rows:
            if movie["id"] in st.session_state[seen_key]:
                continue
            st.session_state[seen_key].add(movie["id"])
            storage.log_interaction(
                st.session_state.user_id,
                movie_id=int(movie["id"]),
                action="shown",
                session_id=st.session_state.session_id,
                ranking_version=st.session_state.ranking_version,
            )


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


def render_why(movie: Dict[str, Any], openai_service: OpenAIService, storage: Storage) -> None:
    deterministic = movie.get("_reasons", []) or ["Fits your current vibe settings", "Strong overall match score"]
    for item in deterministic:
        st.markdown(f'<div class="vr-why-item">[x] {item}</div>', unsafe_allow_html=True)

    storage.log_interaction(
        st.session_state.user_id,
        movie_id=int(movie["id"]),
        action="why_open",
        session_id=st.session_state.session_id,
        ranking_version=st.session_state.ranking_version,
    )

    if openai_service.enabled:
        if st.button("Add AI angle", key=f"why_ai_{movie['id']}", type="secondary", use_container_width=True):
            extras = openai_service.generate_why_spoiler_free(
                movie=movie,
                deterministic_bullets=deterministic,
                user_context={
                    "context": st.session_state.context,
                    "vibe_dials": st.session_state.vibe_dials,
                    "constraints": st.session_state.constraints,
                },
                profile_hash=st.session_state.profile_hash,
                context_hash=st.session_state.context_hash,
            )
            for line in extras:
                st.markdown(f'<div class="vr-why-item">[x] {line}</div>', unsafe_allow_html=True)


def _metadata_line(movie: Dict[str, Any], tmdb: TMDBClient) -> str:
    parts: List[str] = []
    rating = movie.get("vote_average")
    if rating:
        parts.append(f"* {float(rating):.1f}")

    runtime = movie.get("runtime")
    if runtime:
        parts.append(f"{int(runtime)}m")
    elif runtime is None:
        parts.append("Runtime not available")

    providers = movie.get("providers", {}) or {}
    flat = providers.get("flatrate", [])
    if flat:
        name = flat[0].get("provider_name")
        if name:
            parts.append(name)
    elif not providers:
        parts.append("Availability unknown")

    popularity = movie.get("popularity") or 0
    if popularity and popularity > 0:
        parts.append(f"Pop {int(popularity)}")

    return " • ".join(parts)


def render_movie_card(movie: Dict[str, Any], tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage) -> None:
    movie_id = int(movie["id"])
    year = (movie.get("release_date") or "")[:4]
    poster = TMDBClient.image_url(movie.get("poster_path"), size="w342")
    if poster:
        st.image(poster, use_container_width=True)
    st.markdown(f"**{movie.get('title', '-')} ({year or '-'})**")
    st.markdown(f'<div class="vr-meta">{_metadata_line(movie, tmdb)}</div>', unsafe_allow_html=True)

    badges = tmdb.provider_badges(movie.get("providers", {}))
    if badges:
        chips = "".join([f'<span class="vr-chip">{b}</span>' for b in badges[:4]])
        st.markdown(chips, unsafe_allow_html=True)
    else:
        st.markdown('<span class="vr-chip">Availability unknown</span>', unsafe_allow_html=True)

    age_days = movie.get("provider_age_days")
    if age_days is None:
        st.markdown('<div class="vr-muted">Availability checked: unknown</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="vr-muted">Availability checked: {age_days} days ago</div>', unsafe_allow_html=True)

    like_col, skip_col = st.columns(2)
    with like_col:
        if st.button("Like", key=f"like_{movie_id}", use_container_width=True):
            st.session_state.seed_movie_id = movie_id
            storage.log_interaction(
                st.session_state.user_id,
                movie_id=movie_id,
                action="like",
                session_id=st.session_state.session_id,
                ranking_version=st.session_state.ranking_version,
            )
            st.session_state.last_signature = ""
            st.rerun()
    with skip_col:
        if st.button("Skip", key=f"skip_{movie_id}", use_container_width=True):
            storage.log_interaction(
                st.session_state.user_id,
                movie_id=movie_id,
                action="dislike",
                session_id=st.session_state.session_id,
                ranking_version=st.session_state.ranking_version,
            )
            st.session_state[f"show_reason_{movie_id}"] = True
            st.session_state.last_signature = ""
            st.rerun()

    sec1, sec2 = st.columns(2)
    with sec1:
        if st.button("Seen it", key=f"seen_{movie_id}", use_container_width=True, type="secondary"):
            storage.log_interaction(
                st.session_state.user_id,
                movie_id=movie_id,
                action="seen",
                session_id=st.session_state.session_id,
                ranking_version=st.session_state.ranking_version,
            )
            st.session_state.last_signature = ""
            st.rerun()
    with sec2:
        with st.expander("Why this?"):
            render_why(movie, openai_service, storage)

    if st.session_state.get(f"show_reason_{movie_id}", False):
        with st.expander("Tell us why", expanded=True):
            reasons = [
                ("Too dark", "too_dark"),
                ("Too slow", "too_slow"),
                ("Too violent", "too_violent"),
                ("Not in the mood", "not_in_mood"),
            ]
            reason_cols = st.columns(2)
            for i, (label, code) in enumerate(reasons):
                with reason_cols[i % 2]:
                    if st.button(label, key=f"reason_{movie_id}_{code}", use_container_width=True, type="secondary"):
                        apply_reason_adjustment(code)
                        storage.log_interaction(
                            st.session_state.user_id,
                            movie_id=movie_id,
                            action="dislike",
                            reason=code,
                            session_id=st.session_state.session_id,
                            ranking_version=st.session_state.ranking_version,
                        )
                        save_profile(storage)
                        st.session_state.last_signature = ""
                        st.rerun()

    st.markdown('<div class="vr-divider"></div>', unsafe_allow_html=True)


def render_sections(tmdb: TMDBClient, openai_service: OpenAIService, storage: Storage) -> None:
    st.markdown('<div class="vr-section-title">Recommendations</div>', unsafe_allow_html=True)
    sections = st.session_state.sections or {}
    log_shown_cards(storage, sections)

    labels = [
        ("Top matches for you", "top_matches"),
        ("Short & easy to start", "short"),
        ("Because you liked ...", "because_you_liked"),
        ("Wildcard picks", "wildcards"),
    ]
    for title, key in labels:
        st.markdown(f"#### {title}")
        rows = sections.get(key, [])
        cols = st.columns(3)
        for idx, movie in enumerate(rows):
            with cols[idx % 3]:
                with st.container(border=True):
                    render_movie_card(movie, tmdb, openai_service, storage)


def render_collections_sidebar(openai_service: OpenAIService, storage: Storage, region: str) -> None:
    st.sidebar.markdown("### Collections")
    collections = load_collections("curated_collections.json", region=region)
    profile_text = (
        f"context={st.session_state.context}, vibe={st.session_state.vibe_dials}, "
        f"sliders={st.session_state.sliders}, constraints={st.session_state.constraints}"
    )
    ranked = rank_collections_for_user(collections, profile_text, openai_service, storage)
    featured = pick_featured_collection(ranked)
    st.sidebar.markdown(f"**Featured**")
    st.sidebar.write(featured["title"])
    st.sidebar.caption(featured.get("description", ""))
    st.sidebar.markdown("---")
    shown = [c for c in ranked if c["id"] != featured["id"]][:4]
    if len(shown) < 3:
        shown = (shown + collections)[:3]
    for col in shown[:4]:
        st.sidebar.markdown(f"- {col['title']}")


def render_sidebar(storage: Storage) -> None:
    st.sidebar.markdown("### Settings")
    region_options = ["US", "KR", "GB", "CA", "AU", "DE", "FR", "JP", "IN"]
    if st.session_state.region not in region_options:
        region_options = [st.session_state.region] + region_options
    st.session_state.region = st.sidebar.selectbox("Region", region_options, index=region_options.index(st.session_state.region))

    st.sidebar.markdown("### Reset taste")
    if st.sidebar.button("Soft reset (last 20 interactions)", type="secondary", use_container_width=True):
        storage.reset_profile_soft(st.session_state.user_id, n=20)
        st.session_state.last_signature = ""
        st.rerun()
    if st.sidebar.button("Full reset (wipe profile + interactions)", type="secondary", use_container_width=True):
        storage.reset_profile_full(st.session_state.user_id)
        next_uid = str(uuid.uuid4())
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state.user_id = next_uid
        st.rerun()

    metrics = storage.get_metrics(st.session_state.user_id)
    with st.sidebar.expander("Advanced metrics", expanded=False):
        st.caption(f"Like rate: {metrics['like_rate']:.2f}")
        st.caption(f"Skip rate: {metrics['skip_rate']:.2f}")
        st.caption(f"Why opens: {metrics['why_open_count']}")


def main() -> None:
    inject_styles()
    st.title("VibeRecs")
    tmdb_api_key = env_or_secret("TMDB_API_KEY")
    openai_api_key = env_or_secret("OPENAI_API_KEY")

    storage = Storage()
    init_state(storage)
    render_sidebar(storage)

    if not tmdb_api_key:
        st.error("TMDB_API_KEY is required. Add it in .env or Streamlit secrets.")
        st.stop()
    if not openai_api_key:
        st.warning("OPENAI_API_KEY missing. Running in fallback mode (no embedding/AI bullets).")

    tmdb = TMDBClient(api_key=tmdb_api_key, storage=storage, region=st.session_state.region)
    openai_service = OpenAIService(api_key=openai_api_key, storage=storage)
    render_collections_sidebar(openai_service, storage, region=st.session_state.region)

    try:
        if not st.session_state.onboarding_complete:
            render_onboarding(tmdb, storage)
            return

        render_context_and_controls(storage)
        if st.button("Update to this vibe", type="primary", use_container_width=False):
            rerank_if_needed(tmdb, openai_service, storage, force=True)
        else:
            rerank_if_needed(tmdb, openai_service, storage, force=False)

        render_sections(tmdb, openai_service, storage)
        save_profile(storage)
    except TMDBError as exc:
        st.error(f"TMDB error: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
