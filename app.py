import json
import os
import uuid
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from services.openai_client import OpenAIService
from services.recs import (
    build_user_profile_text,
    get_ranked_recommendations,
    load_collections,
    pick_featured_collection,
    rank_collections_for_user,
)
from services.storage import Storage
from services.tmdb import TMDBClient, TMDBError


load_dotenv()
st.set_page_config(page_title="VibeRecs", layout="wide")


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
    storage.ensure_user(st.session_state.user_id)

    defaults = {
        "onboarding_movies": [],
        "swipes": [],
        "intents": {},
        "onboarding_complete": False,
        "sliders": {
            "pace": 50,
            "darkness": 40,
            "humor": 50,
            "romance": 40,
            "violence": 30,
            "weirdness": 35,
        },
        "toggles": {
            "less_violent": False,
            "more_hopeful": False,
            "shorter": False,
            "non_english_ok": True,
            "no_jump_scares": False,
        },
        "seed_movie": None,
        "refinement": "More like this",
        "recommendations": [],
        "profile_text": "",
        "profile_hash": "",
        "region": (env_or_secret("TMDB_REGION", "US") or "US").upper(),
        "loaded_profile": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if not st.session_state.loaded_profile:
        profile = storage.load_user_profile(st.session_state.user_id)
        if profile:
            st.session_state.swipes = profile.get("swipes", st.session_state.swipes)
            st.session_state.intents = profile.get("intents", st.session_state.intents)
            st.session_state.sliders = profile.get("sliders", st.session_state.sliders)
            st.session_state.toggles = profile.get("toggles", st.session_state.toggles)
            st.session_state.onboarding_complete = profile.get("onboarding_complete", False)
            st.session_state.region = profile.get("region", st.session_state.region)
        st.session_state.loaded_profile = True


def save_profile(storage: Storage) -> None:
    profile = {
        "swipes": st.session_state.swipes,
        "intents": st.session_state.intents,
        "sliders": st.session_state.sliders,
        "toggles": st.session_state.toggles,
        "onboarding_complete": st.session_state.onboarding_complete,
        "region": st.session_state.region,
    }
    storage.save_user_profile(st.session_state.user_id, profile)


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
            if len(movies) >= 20:
                st.session_state.onboarding_movies = movies
                return
    st.session_state.onboarding_movies = movies


def render_onboarding(tmdb: TMDBClient, storage: Storage) -> None:
    st.subheader("Onboarding")
    st.caption("Swipe 10 movies, then answer 3 quick intent questions.")

    ensure_onboarding_movies(tmdb)

    swipe_count = len(st.session_state.swipes)
    if swipe_count < 10:
        if len(st.session_state.onboarding_movies) <= swipe_count:
            st.error("Not enough TMDB onboarding movies. Try again in a moment.")
            return

        movie = st.session_state.onboarding_movies[swipe_count]
        year = (movie.get("release_date") or "")[:4]

        st.progress(swipe_count / 10)
        col1, col2 = st.columns([1, 2])
        with col1:
            poster = TMDBClient.image_url(movie.get("poster_path"))
            if poster:
                st.image(poster, use_container_width=True)
        with col2:
            st.markdown(f"### {movie.get('title', 'Unknown')} ({year or '-'})")
            st.write(movie.get("overview", "No overview available."))

        c1, c2, c3 = st.columns(3)
        for label, action, col in [
            ("Like", "like", c1),
            ("Dislike", "dislike", c2),
            ("Skip", "skip", c3),
        ]:
            with col:
                if st.button(label, use_container_width=True):
                    entry = {
                        "movie_id": movie["id"],
                        "title": movie.get("title", ""),
                        "action": action,
                    }
                    st.session_state.swipes.append(entry)
                    storage.save_interaction(st.session_state.user_id, movie["id"], action)
                    save_profile(storage)
                    st.rerun()
        return

    st.success("Great. Now set your current intent.")
    with st.form("intent_form"):
        mood = st.selectbox(
            "What's your mood right now?",
            ["Comforting", "Exciting", "Thoughtful", "Romantic", "Scary", "Funny", "Surprising"],
        )
        with_whom = st.selectbox(
            "Who are you watching with?",
            ["Solo", "Partner", "Friends", "Family", "Kids"],
        )
        time_window = st.selectbox(
            "How much time do you have?",
            ["<90 min", "90-120", "120-150", "any"],
        )
        submitted = st.form_submit_button("Finish onboarding")

    if submitted:
        st.session_state.intents = {
            "mood": mood,
            "with_whom": with_whom,
            "time_window": time_window,
        }
        st.session_state.onboarding_complete = True
        save_profile(storage)
        st.rerun()


def render_controls(storage: Storage) -> None:
    st.subheader("Taste controls")

    slider_cols = st.columns(3)
    slider_names = ["pace", "darkness", "humor", "romance", "violence", "weirdness"]
    for i, name in enumerate(slider_names):
        with slider_cols[i % 3]:
            st.session_state.sliders[name] = st.slider(
                name.capitalize(),
                0,
                100,
                int(st.session_state.sliders.get(name, 50)),
            )

    toggle_cols = st.columns(3)
    toggle_specs = [
        ("less_violent", "less violent"),
        ("more_hopeful", "more hopeful"),
        ("shorter", "shorter"),
        ("non_english_ok", "non-English ok"),
        ("no_jump_scares", "no jump scares"),
    ]
    for i, (key, label) in enumerate(toggle_specs):
        with toggle_cols[i % 3]:
            st.session_state.toggles[key] = st.checkbox(label, value=st.session_state.toggles.get(key, False))

    save_profile(storage)


def controls_hash() -> str:
    payload = {
        "sliders": st.session_state.sliders,
        "toggles": st.session_state.toggles,
        "refinement": st.session_state.refinement,
        "seed_movie_id": (st.session_state.seed_movie or {}).get("id"),
        "region": st.session_state.region,
    }
    return Storage.stable_hash(json.dumps(payload, sort_keys=True))


def render_collections_sidebar(
    openai_service: OpenAIService,
    storage: Storage,
) -> None:
    st.sidebar.subheader("Collections")
    try:
        collections = load_collections("curated_collections.json")
    except Exception:
        st.sidebar.info("Collections unavailable.")
        return

    base_text = st.session_state.profile_text or build_user_profile_text(
        liked_titles=[x.get("title", "") for x in st.session_state.swipes if x.get("action") == "like"],
        disliked_titles=[x.get("title", "") for x in st.session_state.swipes if x.get("action") == "dislike"],
        intents=st.session_state.intents,
        sliders=st.session_state.sliders,
        toggles=st.session_state.toggles,
        refinement=st.session_state.refinement,
        seed_title=(st.session_state.seed_movie or {}).get("title", ""),
    )
    profile_hash = Storage.stable_hash(base_text)
    user_vec = openai_service.embed_user_profile(profile_hash, base_text)

    featured = pick_featured_collection(collections)
    ranked = rank_collections_for_user(collections, user_vec, storage, openai_service)
    ranked = [c for c in ranked if c["id"] != featured["id"]][:4]

    st.sidebar.markdown(f"**Featured (ISO week):** {featured['title']}")
    st.sidebar.caption(featured["description"])
    st.sidebar.divider()
    st.sidebar.markdown("**Personalized picks**")
    for col in ranked:
        st.sidebar.write(f"- {col['title']}")


def render_recommendations(
    tmdb: TMDBClient,
    openai_service: OpenAIService,
    storage: Storage,
) -> None:
    st.subheader("Recommendations")

    refresh = st.button("Refresh recommendations", type="primary")

    if refresh or not st.session_state.recommendations:
        recs, profile_text, profile_hash = get_ranked_recommendations(
            tmdb=tmdb,
            openai_service=openai_service,
            storage=storage,
            interactions=storage.get_interactions(st.session_state.user_id),
            intents=st.session_state.intents,
            sliders=st.session_state.sliders,
            toggles=st.session_state.toggles,
            region=st.session_state.region,
            seed_movie=st.session_state.seed_movie,
            refinement=st.session_state.refinement,
            count=12,
        )
        st.session_state.recommendations = recs
        st.session_state.profile_text = profile_text
        st.session_state.profile_hash = profile_hash

    if not st.session_state.recommendations:
        st.info("No recommendations found. Adjust filters and try again.")
        return

    if st.session_state.seed_movie:
        st.markdown("#### More like this, but...")
        st.caption(st.session_state.seed_movie.get("title", ""))
        st.session_state.refinement = st.radio(
            "Refinement",
            [
                "More like this",
                "More like this but lighter",
                "More like this but faster",
                "More like this but different country",
                "More like this but older (pre-2000)",
            ],
            horizontal=False,
        )
        if st.button("Apply refinement"):
            st.session_state.recommendations = []
            st.rerun()

    cards = st.columns(3)
    c_hash = controls_hash()

    for idx, movie in enumerate(st.session_state.recommendations):
        with cards[idx % 3]:
            details = movie.get("_details", {})
            year = (movie.get("release_date") or "")[:4]
            genres = ", ".join(g.get("name", "") for g in details.get("genres", [])[:3]) or "-"
            runtime = details.get("runtime") or "-"
            rating = movie.get("vote_average", "-")

            st.markdown(f"### {movie.get('title', '-')}")
            poster = TMDBClient.image_url(movie.get("poster_path"))
            if poster:
                st.image(poster, use_container_width=True)
            st.caption(f"{year} | {genres}")
            st.write(f"Runtime: {runtime} min")
            st.write(f"Rating: {rating}")

            providers = tmdb.watch_providers(movie["id"], region=st.session_state.region)
            st.write(f"Where to watch: {TMDBClient.flatten_watch_providers(providers)}")

            if st.button("Use as seed", key=f"seed_{movie['id']}"):
                st.session_state.seed_movie = {
                    "id": movie["id"],
                    "title": movie.get("title", ""),
                }
                st.session_state.refinement = "More like this"
                st.session_state.recommendations = []
                st.rerun()

            with st.expander("Why this?"):
                cached = storage.get_explanation_cache(
                    st.session_state.profile_hash,
                    movie["id"],
                    c_hash,
                )
                if cached:
                    st.markdown(cached)
                else:
                    if st.button("Generate why", key=f"why_{movie['id']}"):
                        prompt_context = {
                            "user_profile": st.session_state.profile_text,
                            "movie": {
                                "title": movie.get("title"),
                                "year": year,
                                "genres": genres,
                                "runtime": runtime,
                                "overview": movie.get("overview", ""),
                            },
                            "controls": {
                                "sliders": st.session_state.sliders,
                                "toggles": st.session_state.toggles,
                                "refinement": st.session_state.refinement,
                            },
                            "rules": "Spoiler-free, 2-4 bullet points",
                        }
                        text = openai_service.explain_recommendation(
                            user_id=st.session_state.user_id,
                            user_profile_hash=st.session_state.profile_hash,
                            movie_id=movie["id"],
                            controls_hash=c_hash,
                            prompt_context=prompt_context,
                        )
                        st.markdown(text)


def main() -> None:
    st.title("VibeRecs")

    tmdb_api_key = env_or_secret("TMDB_API_KEY")
    openai_api_key = env_or_secret("OPENAI_API_KEY")

    storage = Storage()
    init_state(storage)

    st.sidebar.subheader("Settings")
    region_options = ["US", "KR", "GB", "CA", "AU", "DE", "FR", "JP", "IN"]
    if st.session_state.region not in region_options:
        region_options = [st.session_state.region] + region_options
    st.session_state.region = st.sidebar.selectbox(
        "Region",
        region_options,
        index=region_options.index(st.session_state.region),
    )

    if st.sidebar.button("Reset my taste"):
        storage.clear_user_data(st.session_state.user_id)
        uid = str(uuid.uuid4())
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state.user_id = uid
        st.rerun()

    if not tmdb_api_key:
        st.error("Missing TMDB_API_KEY. Add it to your environment or Streamlit secrets.")
        st.stop()

    if not openai_api_key:
        st.warning("OPENAI_API_KEY missing. Ranking and explanations will use fallbacks.")

    tmdb = TMDBClient(api_key=tmdb_api_key, storage=storage, region=st.session_state.region)
    openai_service = OpenAIService(api_key=openai_api_key, storage=storage)

    render_collections_sidebar(openai_service, storage)

    try:
        if not st.session_state.onboarding_complete:
            render_onboarding(tmdb, storage)
            return

        render_controls(storage)
        render_recommendations(tmdb, openai_service, storage)
    except TMDBError as exc:
        st.error(f"TMDB error: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()


