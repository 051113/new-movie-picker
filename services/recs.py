import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from services.openai_client import OpenAIService
from services.storage import Storage
from services.tmdb import TMDBClient


GENRE_IDS = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "sci-fi": 878,
    "thriller": 53,
    "war": 10752,
}


def cosine_similarity(v1: Optional[List[float]], v2: Optional[List[float]]) -> float:
    if not v1 or not v2:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def normalize(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return (value - minimum) / (maximum - minimum)


def build_user_profile_text(
    liked_titles: List[str],
    disliked_titles: List[str],
    intents: Dict[str, str],
    sliders: Dict[str, int],
    toggles: Dict[str, bool],
    refinement: str,
    seed_title: str,
) -> str:
    return (
        f"Liked: {', '.join(liked_titles[:8])}. "
        f"Disliked: {', '.join(disliked_titles[:8])}. "
        f"Mood: {intents.get('mood', 'unknown')}. "
        f"Watching with: {intents.get('with_whom', 'unknown')}. "
        f"Available time: {intents.get('time_window', 'unknown')}. "
        f"Sliders: {sliders}. "
        f"Toggles: {toggles}. "
        f"Seed movie: {seed_title or 'none'}. "
        f"Refinement: {refinement or 'none'}."
    )


def _intent_discover_params(intents: Dict[str, str], region: str) -> Dict[str, Any]:
    mood = intents.get("mood", "")
    with_whom = intents.get("with_whom", "")
    time_window = intents.get("time_window", "")

    genres = []
    if mood == "Comforting":
        genres += [GENRE_IDS["comedy"], GENRE_IDS["family"], GENRE_IDS["romance"]]
    elif mood == "Exciting":
        genres += [GENRE_IDS["action"], GENRE_IDS["thriller"], GENRE_IDS["adventure"]]
    elif mood == "Thoughtful":
        genres += [GENRE_IDS["drama"], GENRE_IDS["mystery"], GENRE_IDS["history"]]
    elif mood == "Romantic":
        genres += [GENRE_IDS["romance"], GENRE_IDS["drama"]]
    elif mood == "Scary":
        genres += [GENRE_IDS["horror"], GENRE_IDS["thriller"]]
    elif mood == "Funny":
        genres += [GENRE_IDS["comedy"]]
    elif mood == "Surprising":
        genres += [GENRE_IDS["mystery"], GENRE_IDS["sci-fi"], GENRE_IDS["thriller"]]

    if with_whom == "Kids":
        genres += [GENRE_IDS["family"], GENRE_IDS["animation"]]
    if with_whom == "Family":
        genres += [GENRE_IDS["family"], GENRE_IDS["comedy"]]

    params: Dict[str, Any] = {
        "sort_by": "popularity.desc",
        "vote_count.gte": 60,
        "watch_region": region,
    }
    if genres:
        params["with_genres"] = ",".join(str(g) for g in sorted(set(genres)))

    if time_window == "<90 min":
        params["with_runtime.lte"] = 95
    elif time_window == "90-120":
        params["with_runtime.gte"] = 90
        params["with_runtime.lte"] = 120
    elif time_window == "120-150":
        params["with_runtime.gte"] = 120
        params["with_runtime.lte"] = 150

    return params


def _apply_slider_and_toggle_filters(
    movies: List[Dict[str, Any]],
    details_by_id: Dict[int, Dict[str, Any]],
    toggles: Dict[str, bool],
) -> List[Dict[str, Any]]:
    filtered = []
    for movie in movies:
        movie_id = movie["id"]
        details = details_by_id.get(movie_id, {})
        runtime = details.get("runtime") or 0
        language = movie.get("original_language") or ""
        genre_ids = set(movie.get("genre_ids") or [g["id"] for g in details.get("genres", [])])

        if toggles.get("shorter") and runtime and runtime > 115:
            continue
        if not toggles.get("non_english_ok") and language and language != "en":
            continue
        if toggles.get("less_violent") and GENRE_IDS["horror"] in genre_ids:
            continue
        if toggles.get("no_jump_scares") and GENRE_IDS["horror"] in genre_ids:
            continue

        filtered.append(movie)
    return filtered


def _apply_refinement(
    movies: List[Dict[str, Any]],
    details_by_id: Dict[int, Dict[str, Any]],
    refinement: str,
) -> List[Dict[str, Any]]:
    if not refinement:
        return movies

    output = []
    for movie in movies:
        details = details_by_id.get(movie["id"], {})
        runtime = details.get("runtime") or 0
        year = int((movie.get("release_date") or "0000")[:4] or 0)
        country_list = details.get("production_countries", [])
        origin = {c.get("iso_3166_1") for c in country_list if c.get("iso_3166_1")}
        genre_ids = set(movie.get("genre_ids") or [g["id"] for g in details.get("genres", [])])

        if refinement == "More like this but lighter" and GENRE_IDS["horror"] in genre_ids:
            continue
        if refinement == "More like this but faster" and runtime and runtime > 115:
            continue
        if refinement == "More like this but different country" and "US" in origin:
            continue
        if refinement == "More like this but older (pre-2000)" and (year == 0 or year >= 2000):
            continue

        output.append(movie)

    return output


def _movie_text(movie: Dict[str, Any], details: Dict[str, Any]) -> str:
    title = movie.get("title", "")
    year = (movie.get("release_date") or "")[:4]
    genres = ", ".join(g.get("name", "") for g in details.get("genres", []))
    overview = movie.get("overview", "")
    keywords = ", ".join(k.get("name", "") for k in details.get("keywords", {}).get("keywords", []))
    return f"{title} ({year}). Genres: {genres}. Overview: {overview}. Keywords: {keywords}."


def _collection_id(details: Dict[str, Any]) -> Optional[int]:
    collection = details.get("belongs_to_collection") or {}
    return collection.get("id")


def _lead_cast_id(details: Dict[str, Any]) -> Optional[int]:
    cast = details.get("credits", {}).get("cast", [])
    if not cast:
        return None
    return cast[0].get("id")


def _diversify_ranked(
    scored: List[Tuple[Dict[str, Any], float]],
    details_by_id: Dict[int, Dict[str, Any]],
    take: int,
) -> List[Dict[str, Any]]:
    selected = []
    seen_collections = {}
    seen_leads = {}

    for movie, base_score in scored:
        details = details_by_id.get(movie["id"], {})
        adjusted = base_score
        cid = _collection_id(details)
        lid = _lead_cast_id(details)

        if cid is not None:
            adjusted -= 0.12 * seen_collections.get(cid, 0)
        if lid is not None:
            adjusted -= 0.08 * seen_leads.get(lid, 0)

        if adjusted <= 0:
            continue

        movie = {**movie, "_score": round(adjusted, 4)}
        selected.append(movie)

        if cid is not None:
            seen_collections[cid] = seen_collections.get(cid, 0) + 1
        if lid is not None:
            seen_leads[lid] = seen_leads.get(lid, 0) + 1

        if len(selected) >= take:
            break

    return selected


def get_ranked_recommendations(
    tmdb: TMDBClient,
    openai_service: OpenAIService,
    storage: Storage,
    interactions: List[Dict[str, Any]],
    intents: Dict[str, str],
    sliders: Dict[str, int],
    toggles: Dict[str, bool],
    region: str,
    seed_movie: Optional[Dict[str, Any]] = None,
    refinement: str = "",
    count: int = 12,
) -> Tuple[List[Dict[str, Any]], str, str]:
    liked_ids = [x["movie_id"] for x in interactions if x["action"] == "like"]
    disliked_ids = {x["movie_id"] for x in interactions if x["action"] == "dislike"}

    liked_titles = []
    disliked_titles = []
    for iid in liked_ids[:8]:
        try:
            liked_titles.append(tmdb.movie_details(iid).get("title", str(iid)))
        except Exception:
            pass
    for iid in list(disliked_ids)[:8]:
        try:
            disliked_titles.append(tmdb.movie_details(iid).get("title", str(iid)))
        except Exception:
            pass

    seed_title = seed_movie.get("title") if seed_movie else ""
    profile_text = build_user_profile_text(
        liked_titles, disliked_titles, intents, sliders, toggles, refinement, seed_title
    )
    profile_hash = storage.stable_hash(profile_text)

    user_vector = openai_service.embed_user_profile(profile_hash, profile_text)

    candidates: Dict[int, Dict[str, Any]] = {}

    for seed_id in liked_ids[:4]:
        for movie in tmdb.movie_recommendations(seed_id, page=1):
            if movie.get("id") not in disliked_ids:
                candidates[movie["id"]] = movie

    discover_params = _intent_discover_params(intents, region)
    for movie in tmdb.discover_movies(discover_params):
        if movie.get("id") not in disliked_ids:
            candidates[movie["id"]] = movie

    if seed_movie:
        for movie in tmdb.movie_recommendations(seed_movie["id"], page=1):
            if movie.get("id") not in disliked_ids:
                candidates[movie["id"]] = movie

    if not candidates:
        for movie in tmdb.trending_movies(page=1) + tmdb.popular_movies(page=1):
            if movie.get("id") not in disliked_ids:
                candidates[movie["id"]] = movie

    candidate_list = list(candidates.values())
    candidate_list = sorted(candidate_list, key=lambda x: x.get("popularity", 0), reverse=True)[:90]

    details_by_id: Dict[int, Dict[str, Any]] = {}
    for movie in candidate_list:
        try:
            details_by_id[movie["id"]] = tmdb.movie_details(movie["id"])
        except Exception:
            details_by_id[movie["id"]] = {}

    candidate_list = _apply_slider_and_toggle_filters(candidate_list, details_by_id, toggles)
    candidate_list = _apply_refinement(candidate_list, details_by_id, refinement)

    if not candidate_list:
        return [], profile_text, profile_hash

    pops = [m.get("popularity", 0.0) for m in candidate_list]
    votes = [m.get("vote_average", 0.0) for m in candidate_list]
    min_pop, max_pop = min(pops), max(pops)
    min_vote, max_vote = min(votes), max(votes)

    scored: List[Tuple[Dict[str, Any], float]] = []
    for movie in candidate_list:
        details = details_by_id.get(movie["id"], {})
        mtext = _movie_text(movie, details)
        text_version = storage.stable_hash(mtext)
        mvec = openai_service.embed_movie_text(movie["id"], text_version, mtext)

        similarity = cosine_similarity(user_vector, mvec)
        popularity_score = normalize(movie.get("popularity", 0.0), min_pop, max_pop)
        vote_score = normalize(movie.get("vote_average", 0.0), min_vote, max_vote)

        blend = 0.65 * similarity + 0.2 * popularity_score + 0.15 * vote_score

        if toggles.get("more_hopeful"):
            genres = set(movie.get("genre_ids") or [g["id"] for g in details.get("genres", [])])
            if GENRE_IDS["comedy"] in genres or GENRE_IDS["family"] in genres:
                blend += 0.05

        scored.append((movie, blend))

    scored.sort(key=lambda x: x[1], reverse=True)
    final_list = _diversify_ranked(scored, details_by_id, take=count)

    for movie in final_list:
        details = details_by_id.get(movie["id"], {})
        movie["_details"] = details

    return final_list, profile_text, profile_hash


def load_collections(path: str) -> List[Dict[str, Any]]:
    import json

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_featured_collection(collections: List[Dict[str, Any]]) -> Dict[str, Any]:
    week = date.today().isocalendar()[1]
    return collections[week % len(collections)]


def rank_collections_for_user(
    collections: List[Dict[str, Any]],
    user_vector: Optional[List[float]],
    storage: Storage,
    openai_service: OpenAIService,
) -> List[Dict[str, Any]]:
    if not user_vector:
        return collections[:5]

    scored = []
    for col in collections:
        cached = storage.get_collection_embedding(col["id"])
        if cached is None:
            text = col.get("embedding_text") or f"{col['title']}. {col['description']}"
            version = storage.stable_hash(text)
            cached = openai_service.embed_text(f"collection:{col['id']}", version, text)
            storage.upsert_collection(col, cached)

        similarity = cosine_similarity(user_vector, cached)
        scored.append((col, similarity))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in scored]

