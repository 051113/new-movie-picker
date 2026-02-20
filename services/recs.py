import json
import math
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

MOOD_GENRES = {
    "chill": [GENRE_IDS["comedy"], GENRE_IDS["family"], GENRE_IDS["romance"]],
    "high-energy": [GENRE_IDS["action"], GENRE_IDS["adventure"], GENRE_IDS["thriller"]],
    "emotional": [GENRE_IDS["drama"], GENRE_IDS["romance"]],
    "spooky": [GENRE_IDS["horror"], GENRE_IDS["mystery"], GENRE_IDS["thriller"]],
    "thoughtful": [GENRE_IDS["drama"], GENRE_IDS["history"], GENRE_IDS["documentary"]],
    "romantic": [GENRE_IDS["romance"], GENRE_IDS["drama"], GENRE_IDS["comedy"]],
}

TIME_BUCKETS = {
    "<90m": (0, 95),
    "90-120m": (90, 120),
    "120m+": (120, 300),
}

JUMPSCARE_TERMS = {"jump scare", "supernatural", "haunted", "demon", "possession"}


def cosine_similarity(v1: Optional[Sequence[float]], v2: Optional[Sequence[float]]) -> float:
    if not v1 or not v2:
        return 0.0
    dot = float(sum(a * b for a, b in zip(v1, v2)))
    n1 = math.sqrt(float(sum(a * a for a in v1)))
    n2 = math.sqrt(float(sum(b * b for b in v2)))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def normalize(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return (value - minimum) / (maximum - minimum)


def _genre_ids(movie: Dict[str, Any]) -> set:
    ids = set(movie.get("genre_ids") or [])
    if not ids and movie.get("genres"):
        ids = {g.get("id") for g in movie.get("genres", []) if g.get("id")}
    return ids


def _movie_text(movie: Dict[str, Any]) -> str:
    title = movie.get("title", "")
    year = (movie.get("release_date") or "")[:4]
    genres = ", ".join(g.get("name", "") for g in movie.get("genres", []))
    keywords = ", ".join(k.get("name", "") for k in movie.get("keywords", []))
    overview = movie.get("overview", "")
    return f"{title} ({year}). Genres: {genres}. Keywords: {keywords}. {overview}"


def _profile_text(context: Dict[str, str], vibe_dials: Dict[str, str], sliders: Dict[str, int], constraints: Dict[str, bool], recent_like_titles: List[str], recent_dislike_titles: List[str], seed_title: str) -> str:
    return (
        f"Context: mood={context.get('mood')}, who={context.get('who')}, time={context.get('time')}. "
        f"Vibe dials: {vibe_dials}. Sliders: {sliders}. Constraints: {constraints}. "
        f"Likes: {', '.join(recent_like_titles[:8])}. Dislikes: {', '.join(recent_dislike_titles[:8])}. "
        f"Seed: {seed_title or 'none'}."
    )


def _dial_to_numeric(vibe_dials: Dict[str, str]) -> Dict[str, float]:
    cozy_map = {"Cozy": 0.2, "Balanced": 0.5, "Intense": 0.85}
    light_map = {"Light": 0.2, "Balanced": 0.5, "Dark": 0.85}
    mainstream_map = {"Mainstream": 0.2, "Balanced": 0.5, "Hidden Gems": 0.85}
    return {
        "cozy_intense": cozy_map.get(vibe_dials.get("cozy_intense", "Balanced"), 0.5),
        "light_dark": light_map.get(vibe_dials.get("light_dark", "Balanced"), 0.5),
        "mainstream_hidden": mainstream_map.get(vibe_dials.get("mainstream_hidden", "Balanced"), 0.5),
    }


def _slider_similarity(sliders: Dict[str, int], vibe_dials: Dict[str, str], movie: Dict[str, Any]) -> float:
    genres = _genre_ids(movie)
    runtime = movie.get("runtime") or 110
    popularity = float(movie.get("popularity") or 0.0)

    dial = _dial_to_numeric(vibe_dials)
    target_dark = sliders.get("darkness", 50) / 100.0 * 0.7 + dial["light_dark"] * 0.3
    target_pace = sliders.get("pace", 50) / 100.0 * 0.7 + dial["cozy_intense"] * 0.3
    target_humor = sliders.get("humor", 50) / 100.0
    target_romance = sliders.get("romance", 50) / 100.0
    target_violence = sliders.get("violence", 50) / 100.0
    target_weird = sliders.get("weirdness", 50) / 100.0

    movie_dark = 0.8 if GENRE_IDS["horror"] in genres else (0.65 if GENRE_IDS["thriller"] in genres else 0.35)
    movie_pace = 0.75 if runtime < 105 else (0.45 if runtime > 135 else 0.6)
    movie_humor = 0.8 if GENRE_IDS["comedy"] in genres else 0.3
    movie_romance = 0.8 if GENRE_IDS["romance"] in genres else 0.25
    movie_violence = 0.75 if GENRE_IDS["action"] in genres or GENRE_IDS["horror"] in genres else 0.3
    movie_weird = 0.8 if GENRE_IDS["sci-fi"] in genres or GENRE_IDS["fantasy"] in genres else 0.3

    dims = [
        1.0 - abs(target_dark - movie_dark),
        1.0 - abs(target_pace - movie_pace),
        1.0 - abs(target_humor - movie_humor),
        1.0 - abs(target_romance - movie_romance),
        1.0 - abs(target_violence - movie_violence),
        1.0 - abs(target_weird - movie_weird),
    ]
    score = sum(max(0.0, d) for d in dims) / len(dims)

    # Hidden gems dial biases toward lower popularity.
    hidden_pref = dial["mainstream_hidden"]
    if hidden_pref > 0.6:
        score += max(0.0, (60.0 - popularity) / 200.0)
    return min(1.0, score)


def _fallback_text_similarity(profile_text: str, movie_text: str) -> float:
    a = set(profile_text.lower().split())
    b = set(movie_text.lower().split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_keywords(movie: Dict[str, Any]) -> set:
    names = {k.get("name", "").lower() for k in movie.get("keywords", []) if k.get("name")}
    names.add((movie.get("overview") or "").lower())
    return names


def _build_fallback_collections(region: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "fallback_energy",
            "title": "High energy tonight",
            "description": "Fast, punchy, momentum-heavy picks.",
            "query": {"with_genres": "28,12,53", "sort_by": "popularity.desc", "watch_region": region},
            "embedding_text": "high energy fast intense momentum",
        },
        {
            "id": "fallback_under100",
            "title": "Under 100 minutes",
            "description": "Easy-start picks you can finish quickly.",
            "query": {"with_runtime.lte": 100, "sort_by": "vote_average.desc", "watch_region": region},
            "embedding_text": "short runtime easy to start",
        },
        {
            "id": "fallback_hidden",
            "title": "Hidden gems for you",
            "description": "Lower-popularity titles with strong ratings.",
            "query": {"vote_count.gte": 100, "sort_by": "vote_average.desc", "watch_region": region},
            "embedding_text": "hidden gems underrated personal",
        },
        {
            "id": "fallback_trending",
            "title": "Trending now in your region",
            "description": "What viewers near you are watching this week.",
            "query": {"sort_by": "popularity.desc", "watch_region": region},
            "embedding_text": f"trending region {region}",
        },
    ]


def load_collections(path: str, region: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list) or not rows:
            return _build_fallback_collections(region)
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if "id" not in row or "title" not in row:
                continue
            row.setdefault("description", "")
            row.setdefault("query", {})
            cleaned.append(row)
        if len(cleaned) < 3:
            return cleaned + _build_fallback_collections(region)[: 3 - len(cleaned)]
        return cleaned
    except Exception:
        return _build_fallback_collections(region)


def pick_featured_collection(collections: List[Dict[str, Any]]) -> Dict[str, Any]:
    week = date.today().isocalendar()[1]
    return collections[week % len(collections)]


def rank_collections_for_user(
    collections: List[Dict[str, Any],
    ],
    profile_text: str,
    openai_service: OpenAIService,
    storage: Storage,
) -> List[Dict[str, Any]]:
    user_vec = openai_service.embed_user_profile(profile_text)
    scored: List[Tuple[Dict[str, Any], float]] = []
    for col in collections:
        text = col.get("embedding_text") or f"{col.get('title', '')}. {col.get('description', '')}"
        similarity = 0.0
        if user_vec:
            cached = storage.get_collection_embedding(col["id"])
            if cached is None:
                cached = openai_service.embed_collection(col["id"], text)
                storage.upsert_collection(col, cached)
            similarity = cosine_similarity(user_vec, cached)
        else:
            similarity = _fallback_text_similarity(profile_text, text)
        scored.append((col, similarity))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored]


def _candidate_generation(
    tmdb: TMDBClient,
    recent_like_ids: List[int],
    region: str,
    collections: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    candidates: Dict[int, Dict[str, Any]] = {}

    for movie_id in recent_like_ids[:5]:
        for page in [1, 2]:
            for m in tmdb.movie_recommendations(movie_id, page=page):
                candidates[m["id"]] = m

    for page in [1, 2, 3]:
        for m in tmdb.trending_movies(page=page, region=region):
            candidates[m["id"]] = m
        for m in tmdb.popular_movies(page=page, region=region):
            candidates[m["id"]] = m

    for col in collections[:3]:
        query = dict(col.get("query", {}))
        query.setdefault("page", 1)
        query.setdefault("watch_region", region)
        for m in tmdb.discover_movies(query):
            candidates[m["id"]] = m

    return dict(list(candidates.items())[:600])


def _hard_filter(
    movie: Dict[str, Any],
    context: Dict[str, str],
    constraints: Dict[str, bool],
    region: str,
) -> Tuple[bool, List[str], float]:
    reasons: List[str] = []
    score_penalty = 0.0
    runtime = movie.get("runtime")
    providers = movie.get("providers", {})
    genres = _genre_ids(movie)
    language = (movie.get("original_language") or "").lower()

    time_bucket = context.get("time", "90-120m")
    if time_bucket in TIME_BUCKETS and runtime:
        lo, hi = TIME_BUCKETS[time_bucket]
        if runtime < lo or runtime > hi:
            return False, reasons, score_penalty
    elif time_bucket in TIME_BUCKETS and runtime is None:
        score_penalty += 0.03
        reasons.append("unknown runtime")

    if constraints.get("shorter") and runtime and runtime > 100:
        return False, reasons, score_penalty
    if constraints.get("shorter") and runtime is None:
        score_penalty += 0.04
        reasons.append("unknown runtime")

    if not constraints.get("non_english_ok", True) and language != "en":
        return False, reasons, score_penalty

    keyword_blob = " ".join(_extract_keywords(movie))
    if constraints.get("no_jump_scares"):
        if GENRE_IDS["horror"] in genres:
            return False, reasons, score_penalty
        if any(term in keyword_blob for term in JUMPSCARE_TERMS):
            return False, reasons, score_penalty

    if constraints.get("only_streaming_now"):
        if not providers.get("flatrate"):
            return False, reasons, score_penalty
        reasons.append("streaming now")

    if constraints.get("less_violent"):
        if GENRE_IDS["horror"] in genres or GENRE_IDS["war"] in genres:
            return False, reasons, score_penalty
        if GENRE_IDS["action"] in genres or GENRE_IDS["crime"] in genres:
            score_penalty += 0.04
            reasons.append("reduced violence")

    return True, reasons, score_penalty


def _score_movies(
    movies: List[Dict[str, Any]],
    profile_text: str,
    vibe_dials: Dict[str, str],
    sliders: Dict[str, int],
    constraints: Dict[str, bool],
    interactions: List[Dict[str, Any]],
    openai_service: OpenAIService,
) -> List[Dict[str, Any]]:
    pop_values = [float(m.get("popularity") or 0.0) for m in movies] or [0.0]
    vote_values = [float(m.get("vote_average") or 0.0) for m in movies] or [0.0]
    pmin, pmax = min(pop_values), max(pop_values)
    vmin, vmax = min(vote_values), max(vote_values)

    seen_ids = {i["movie_id"] for i in interactions if i["action"] in {"seen", "dislike"}}
    recent_shown = [i["movie_id"] for i in interactions if i["action"] == "shown"][:50]
    recent_shown_set = set(recent_shown)

    dislike_ids = [i["movie_id"] for i in interactions if i["action"] == "dislike"][:20]
    dislike_vectors = []
    user_vector = openai_service.embed_user_profile(profile_text)

    dial = _dial_to_numeric(vibe_dials)
    hidden_pref = dial["mainstream_hidden"]
    pop_w = 0.18 * (1.0 - hidden_pref) + 0.06
    novelty_w = 0.12 + 0.16 * hidden_pref

    for m in movies:
        mvec = m.get("_embedding")
        if not mvec and openai_service.enabled:
            text = _movie_text(m)
            mvec = openai_service.embed_movie_text(int(m["id"]), text)
            m["_embedding"] = mvec
        m["_sim_embed"] = cosine_similarity(user_vector, mvec)

    if user_vector and dislike_ids:
        for did in dislike_ids:
            for m in movies:
                if m["id"] == did:
                    if m.get("_embedding"):
                        dislike_vectors.append(m["_embedding"])
                    break
        if dislike_vectors:
            dim = len(dislike_vectors[0])
            centroid = [sum(v[i] for v in dislike_vectors) / len(dislike_vectors) for i in range(dim)]
        else:
            centroid = None
    else:
        centroid = None

    scored = []
    for m in movies:
        mtext = _movie_text(m)
        embed_sim = m.get("_sim_embed") if user_vector else _fallback_text_similarity(profile_text, mtext)
        slider_sim = _slider_similarity(sliders, vibe_dials, m)
        pop_n = normalize(float(m.get("popularity") or 0.0), pmin, pmax)
        vote_n = normalize(float(m.get("vote_average") or 0.0), vmin, vmax)
        novelty = 1.0 if m["id"] not in recent_shown_set else 0.2
        if m["id"] in seen_ids:
            novelty *= 0.05

        score = 0.42 * embed_sim + 0.26 * slider_sim + pop_w * pop_n + 0.12 * vote_n + novelty_w * novelty

        if constraints.get("more_hopeful"):
            genres = _genre_ids(m)
            if GENRE_IDS["comedy"] in genres or GENRE_IDS["family"] in genres or GENRE_IDS["romance"] in genres:
                score += 0.05

        if centroid is not None and m.get("_embedding"):
            anti = cosine_similarity(centroid, m["_embedding"])
            score -= 0.12 * max(0.0, anti)

        if m.get("_hard_penalty"):
            score -= m["_hard_penalty"]

        m["_score"] = score
        scored.append(m)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def _apply_diversity(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    genre_counts: Dict[int, int] = {}
    collection_counts: Dict[int, int] = {}
    year_counts: Dict[str, int] = {}

    for m in scored:
        genres = _genre_ids(m)
        year = (m.get("release_date") or "")[:4]
        collection_id = (m.get("belongs_to_collection") or {}).get("id")

        penalty = 0.0
        for g in genres:
            penalty += 0.06 * max(0, genre_counts.get(g, 0) - 1)
        if collection_id:
            penalty += 0.12 * collection_counts.get(collection_id, 0)
        if year:
            penalty += 0.04 * max(0, year_counts.get(year, 0) - 2)

        adjusted = m["_score"] - penalty
        if adjusted < 0:
            continue
        m["_score_diverse"] = adjusted
        selected.append(m)
        for g in genres:
            genre_counts[g] = genre_counts.get(g, 0) + 1
        if collection_id:
            collection_counts[collection_id] = collection_counts.get(collection_id, 0) + 1
        if year:
            year_counts[year] = year_counts.get(year, 0) + 1
        if len(selected) >= 70:
            break
    selected.sort(key=lambda x: x["_score_diverse"], reverse=True)
    return selected


def _ensure_minimum_mix(selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    short = [m for m in selected if (m.get("runtime") or 999) <= 100]
    high_rating = [m for m in selected if (m.get("vote_average") or 0) >= 7.2]
    exploratory = [m for m in selected if (m.get("popularity") or 999) < 35]

    pool = selected[:]
    must_have = []
    must_have += short[:2]
    must_have += high_rating[:2]
    must_have += exploratory[:2]

    seen = set()
    result: List[Dict[str, Any]] = []
    for m in must_have + pool:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        result.append(m)
        if len(result) >= 30:
            break
    return result


def _build_sections(
    ranked: List[Dict[str, Any]],
    recent_like_ids: List[int],
    wildcard_source: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    used = set()

    def take(items: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        out = []
        for item in items:
            if item["id"] in used:
                continue
            out.append(item)
            used.add(item["id"])
            if len(out) >= n:
                break
        return out

    top = take(ranked, 18)
    short = take([m for m in ranked if (m.get("runtime") or 999) <= 100], 12)
    because = take(
        [m for m in ranked if set(m.get("_matched_seed_ids", [])) & set(recent_like_ids[:3])],
        12,
    )
    wild_pool = wildcard_source if wildcard_source is not None else ranked
    wild = take(
        sorted(
            wild_pool,
            key=lambda x: ((x.get("popularity") or 0), -(x.get("_score_diverse") or 0)),
        ),
        12,
    )

    # Fill deficits from ranked list.
    while len(top) < 18:
        top += take(ranked, 1)
    while len(short) < 12:
        short += take(ranked, 1)
    while len(because) < 12:
        because += take(ranked, 1)
    while len(wild) < 12:
        wild += take(ranked, 1)

    return {
        "top_matches": top[:18],
        "short": short[:12],
        "because_you_liked": because[:12],
        "wildcards": wild[:12],
    }


def _reasons_for_movie(movie: Dict[str, Any], context: Dict[str, str], constraints: Dict[str, bool]) -> List[str]:
    reasons = []
    genres = _genre_ids(movie)
    runtime = movie.get("runtime")
    providers = movie.get("providers", {})

    mood = context.get("mood")
    if mood and any(g in genres for g in MOOD_GENRES.get(mood, [])):
        reasons.append(f"Genre fit for a {mood} mood")
    if runtime and runtime <= 100:
        reasons.append("Short runtime for an easy start")
    if providers.get("flatrate"):
        reasons.append("Available on streaming subscription now")
    elif providers.get("rent") or providers.get("buy"):
        reasons.append("Available to rent or buy now")
    if constraints.get("only_streaming_now"):
        reasons.append("Matches your streaming-only constraint")
    if constraints.get("shorter") and runtime and runtime <= 100:
        reasons.append("Matches your shorter preference")
    if constraints.get("non_english_ok") and (movie.get("original_language") or "en") != "en":
        reasons.append("Includes non-English options you allowed")
    if movie.get("_matched_seed_ids"):
        reasons.append("Related to movies you previously liked")
    return reasons[:4]


def _fetch_details_and_providers(
    tmdb: TMDBClient,
    raw_candidates: Dict[int, Dict[str, Any]],
    region: str,
    recent_like_ids: List[int],
) -> List[Dict[str, Any]]:
    seed_rec_ids: Dict[int, set] = {}
    for seed_id in recent_like_ids[:3]:
        seed_rec_ids[seed_id] = {m["id"] for m in tmdb.movie_recommendations(seed_id, page=1)[:20]}

    enriched = []
    for movie_id, movie in raw_candidates.items():
        try:
            details = tmdb.get_movie_details(movie_id)
            providers = tmdb.get_watch_providers(movie_id, region)
            age_days = tmdb.provider_age_days(movie_id, region)
        except Exception:
            continue
        row = {**movie}
        row["runtime"] = details.get("runtime")
        row["genres"] = details.get("genres", [])
        row["keywords"] = details.get("keywords", {}).get("keywords", [])
        row["providers"] = providers or {}
        row["provider_age_days"] = age_days
        row["belongs_to_collection"] = details.get("belongs_to_collection")
        row["credits"] = details.get("credits", {})
        row["_matched_seed_ids"] = []
        for seed_id in recent_like_ids[:3]:
            if movie_id in seed_rec_ids.get(seed_id, set()):
                row["_matched_seed_ids"].append(seed_id)
        enriched.append(row)
    return enriched


def _normalize_provider_name(name: str) -> str:
    raw = (name or "").strip().lower()
    compact = "".join(ch for ch in raw if ch.isalnum())
    if not compact:
        return ""
    if "appletv" in compact or compact in {"itunes", "apple"}:
        return "apple_tv"
    return compact


def _provider_name_set(movie: Dict[str, Any], buckets: Sequence[str]) -> set:
    providers = movie.get("providers", {}) or {}
    names = set()
    for bucket in buckets:
        for row in providers.get(bucket, []) or []:
            normalized = _normalize_provider_name(row.get("provider_name", ""))
            if normalized:
                names.add(normalized)
    return names


def _matches_provider_filter(movie: Dict[str, Any], provider_allow_norm: set, include_transactional: bool) -> bool:
    if not provider_allow_norm:
        return True
    buckets = ["flatrate"] + (["rent", "buy"] if include_transactional else [])
    available = _provider_name_set(movie, buckets)
    return bool(available & provider_allow_norm)


def get_sectioned_recommendations(
    tmdb: TMDBClient,
    openai_service: OpenAIService,
    storage: Storage,
    user_id: str,
    context: Dict[str, str],
    vibe_dials: Dict[str, str],
    sliders: Dict[str, int],
    constraints: Dict[str, bool],
    region: str,
    collections: List[Dict[str, Any]],
    seed_movie_id: Optional[int] = None,
    ranking_version: str = "v2",
) -> Dict[str, Any]:
    interactions = storage.get_interactions(user_id, limit=1200)
    recent_like_ids = storage.get_recent_likes(user_id, limit=5)
    recent_seen_ids = set(storage.get_recent_seen(user_id, limit=400))
    recent_dislike_ids = [i["movie_id"] for i in interactions if i["action"] == "dislike"][:8]

    if seed_movie_id and seed_movie_id not in recent_like_ids:
        recent_like_ids = [seed_movie_id] + recent_like_ids

    def _title(movie_id: int) -> str:
        try:
            return tmdb.get_movie_details(movie_id).get("title", str(movie_id))
        except Exception:
            return str(movie_id)

    profile_text = _profile_text(
        context=context,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=constraints,
        recent_like_titles=[_title(mid) for mid in recent_like_ids[:5]],
        recent_dislike_titles=[_title(mid) for mid in recent_dislike_ids[:5]],
        seed_title=_title(seed_movie_id) if seed_movie_id else "",
    )
    profile_hash = storage.stable_hash(profile_text)
    context_hash = storage.stable_hash(json.dumps({"context": context, "constraints": constraints, "region": region}, sort_keys=True))

    candidate_map = _candidate_generation(tmdb, recent_like_ids=recent_like_ids, region=region, collections=collections)
    candidate_map = dict(list(candidate_map.items())[:360])
    enriched = _fetch_details_and_providers(tmdb, candidate_map, region, recent_like_ids)

    # Hard filters before ranking (main path respects all constraints, including only_streaming_now).
    filtered_main = []
    filtered_wild = []
    wildcard_constraints = dict(constraints)
    wildcard_constraints["only_streaming_now"] = False

    for movie in enriched:
        if movie["id"] in recent_seen_ids:
            continue
        ok, reasons, penalty = _hard_filter(movie, context=context, constraints=constraints, region=region)
        if not ok:
            # Wildcards ignore only_streaming_now, but keep other hard constraints.
            ok_wild, reasons_wild, penalty_wild = _hard_filter(
                movie, context=context, constraints=wildcard_constraints, region=region
            )
            if not ok_wild:
                continue
            wild_copy = dict(movie)
            wild_copy["_hard_reasons"] = reasons_wild
            wild_copy["_hard_penalty"] = penalty_wild
            filtered_wild.append(wild_copy)
            continue
        movie["_hard_reasons"] = reasons
        movie["_hard_penalty"] = penalty
        filtered_main.append(movie)
        filtered_wild.append(dict(movie))

    ranked = _score_movies(
        movies=filtered_main,
        profile_text=profile_text,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=constraints,
        interactions=interactions,
        openai_service=openai_service,
    )
    ranked = _apply_diversity(ranked)
    ranked = _ensure_minimum_mix(ranked)

    ranked_wild = _score_movies(
        movies=filtered_wild,
        profile_text=profile_text,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=wildcard_constraints,
        interactions=interactions,
        openai_service=openai_service,
    )
    ranked_wild = _apply_diversity(ranked_wild)

    for movie in ranked:
        movie["_reasons"] = _reasons_for_movie(movie, context=context, constraints=constraints)
        movie["_ranking_version"] = ranking_version

    for movie in ranked_wild:
        movie["_reasons"] = _reasons_for_movie(movie, context=context, constraints=wildcard_constraints)
        movie["_ranking_version"] = ranking_version

    sections = _build_sections(ranked, recent_like_ids=recent_like_ids, wildcard_source=ranked_wild)
    return {
        "sections": sections,
        "profile_text": profile_text,
        "profile_hash": profile_hash,
        "context_hash": context_hash,
        "ranking_version": ranking_version,
    }


def _quick_profile_components(context: Dict[str, Any], constraints: Dict[str, Any], refinement: Optional[str]) -> Tuple[Dict[str, str], Dict[str, int]]:
    intention = context.get("intention", "Engaging Story")
    energy = context.get("energy", "Balanced")

    vibe_dials = {
        "cozy_intense": "Intense" if energy == "High" else ("Cozy" if energy == "Chill" else "Balanced"),
        "light_dark": "Dark" if intention in {"Intense & Thrilling", "Emotional & Deep"} else "Light",
        "mainstream_hidden": "Hidden Gems" if intention == "Surprise Me" else "Balanced",
    }
    sliders = {"pace": 55, "darkness": 45, "humor": 45, "romance": 35, "violence": 35, "weirdness": 30}

    if intention == "Comfort & Cozy":
        sliders.update({"humor": 60, "darkness": 25, "pace": 40})
    elif intention == "Light & Fun":
        sliders.update({"humor": 80, "darkness": 20, "pace": 60})
    elif intention == "Engaging Story":
        sliders.update({"pace": 55, "darkness": 45})
    elif intention == "Intense & Thrilling":
        sliders.update({"pace": 80, "darkness": 70, "violence": 60})
    elif intention == "Emotional & Deep":
        sliders.update({"darkness": 65, "romance": 55, "pace": 45})
    elif intention == "Surprise Me":
        sliders.update({"weirdness": 75, "pace": 55})

    if refinement == "More exciting":
        sliders["pace"] = min(100, sliders["pace"] + 15)
    elif refinement == "Funnier":
        sliders["humor"] = min(100, sliders["humor"] + 20)
    elif refinement == "More emotional":
        sliders["romance"] = min(100, sliders["romance"] + 20)
    elif refinement == "Lighter":
        sliders["darkness"] = max(0, sliders["darkness"] - 20)
    elif refinement == "Darker":
        sliders["darkness"] = min(100, sliders["darkness"] + 20)
    elif refinement == "Shorter":
        constraints["shorter"] = True
    elif refinement == "More popular":
        vibe_dials["mainstream_hidden"] = "Mainstream"
    elif refinement == "More indie":
        vibe_dials["mainstream_hidden"] = "Hidden Gems"
    elif refinement == "Surprise me":
        sliders["weirdness"] = min(100, sliders["weirdness"] + 15)

    return vibe_dials, sliders


def _runtime_bucket_from_minutes(minutes: Optional[int]) -> str:
    if minutes is None:
        return "120m+"
    if minutes <= 30:
        return "<90m"
    if minutes <= 100:
        return "90-120m"
    return "120m+"


def _clip_overview(text: str, length: int = 180) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def get_quick_pick(
    user_id: str,
    context: Dict[str, Any],
    constraints: Dict[str, Any],
    refinement: Optional[str] = None,
    *,
    tmdb: TMDBClient,
    openai_service: OpenAIService,
    storage: Storage,
) -> Dict[str, Any]:
    region = (constraints.get("region") or context.get("region") or "KR").upper()
    time_minutes = context.get("time_minutes")
    provider_allow_norm = {
        _normalize_provider_name(name)
        for name in (constraints.get("provider_names") or [])
        if _normalize_provider_name(name)
    }

    quick_constraints = {
        "only_streaming_now": bool(constraints.get("streaming_only")),
        "shorter": bool(constraints.get("streaming_only") and (time_minutes is not None and time_minutes <= 45)),
        "non_english_ok": True,
        "less_violent": False,
        "more_hopeful": False,
        "no_jump_scares": False,
    }
    quick_context = {
        "mood": context.get("intention", "Engaging Story"),
        "who": context.get("who", "Alone"),
        "time": _runtime_bucket_from_minutes(time_minutes),
    }
    vibe_dials, sliders = _quick_profile_components(quick_context, quick_constraints, refinement)

    interactions = storage.get_interactions(user_id, limit=1200)
    recent_like_ids = storage.get_recent_likes(user_id, limit=5)
    recent_seen_ids = set(storage.get_recent_seen(user_id, limit=400))
    collections = _build_fallback_collections(region)

    candidate_map = _candidate_generation(tmdb, recent_like_ids=recent_like_ids, region=region, collections=collections)
    candidate_map = dict(list(candidate_map.items())[:420])
    enriched = _fetch_details_and_providers(tmdb, candidate_map, region, recent_like_ids)

    filtered: List[Dict[str, Any]] = []
    wildcard_filtered: List[Dict[str, Any]] = []
    filtered_ids: set = set()
    wildcard_filtered_ids: set = set()
    wildcard_constraints = dict(quick_constraints)
    wildcard_constraints["only_streaming_now"] = False

    def _passes_time(movie: Dict[str, Any], relax_time: bool) -> bool:
        runtime = movie.get("runtime")
        if time_minutes is None or not runtime:
            return True
        max_minutes = time_minutes + (35 if relax_time else 10)
        return runtime <= max_minutes

    def _try_append(
        movie: Dict[str, Any],
        *,
        include_transactional: bool,
        relax_time: bool,
    ) -> None:
        if movie["id"] in recent_seen_ids:
            return
        if not _passes_time(movie, relax_time=relax_time):
            return
        if provider_allow_norm and quick_constraints["only_streaming_now"]:
            if not _matches_provider_filter(movie, provider_allow_norm, include_transactional=include_transactional):
                return

        ok, reasons, penalty = _hard_filter(movie, context=quick_context, constraints=quick_constraints, region=region)
        if ok and movie["id"] not in filtered_ids:
            item = dict(movie)
            item["_hard_reasons"] = reasons
            item["_hard_penalty"] = penalty
            filtered.append(item)
            filtered_ids.add(movie["id"])

        ok_wild, reasons_w, penalty_w = _hard_filter(movie, context=quick_context, constraints=wildcard_constraints, region=region)
        if ok_wild and movie["id"] not in wildcard_filtered_ids:
            item_w = dict(movie)
            item_w["_hard_reasons"] = reasons_w
            item_w["_hard_penalty"] = penalty_w
            wildcard_filtered.append(item_w)
            wildcard_filtered_ids.add(movie["id"])

    for movie in enriched:
        _try_append(movie, include_transactional=False, relax_time=False)

    # Relaxed fallback passes when strict filters are too sparse (common with Apple TV).
    if quick_constraints["only_streaming_now"] and provider_allow_norm and len(filtered) < 3:
        for movie in enriched:
            _try_append(movie, include_transactional=True, relax_time=False)
            if len(filtered) >= 3:
                break
    if quick_constraints["only_streaming_now"] and provider_allow_norm and len(filtered) < 3:
        for movie in enriched:
            _try_append(movie, include_transactional=True, relax_time=True)
            if len(filtered) >= 3:
                break

    if not filtered:
        # Last fallback to popular list in region.
        for m in tmdb.popular_movies(page=1, region=region):
            try:
                bundle = tmdb.get_movie_bundle(m["id"], region=region)
                m = {**m, "runtime": bundle["runtime"], "providers": bundle["providers"], "provider_age_days": bundle["provider_age_days"], "genres": bundle["details"].get("genres", []), "keywords": bundle["details"].get("keywords", {}).get("keywords", [])}
                if provider_allow_norm and quick_constraints["only_streaming_now"]:
                    if not _matches_provider_filter(m, provider_allow_norm, include_transactional=True):
                        continue
                filtered.append(m)
                wildcard_filtered.append(dict(m))
                if len(filtered) >= 15:
                    break
            except Exception:
                continue

    profile_text = _profile_text(
        context=quick_context,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=quick_constraints,
        recent_like_titles=[],
        recent_dislike_titles=[],
        seed_title="",
    )
    profile_hash = storage.stable_hash(profile_text)
    context_hash = storage.stable_hash(json.dumps({"context": context, "constraints": constraints, "refinement": refinement}, sort_keys=True))

    ranked = _score_movies(
        movies=filtered,
        profile_text=profile_text,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=quick_constraints,
        interactions=interactions,
        openai_service=openai_service,
    )
    ranked = _apply_diversity(ranked)

    ranked_wild = _score_movies(
        movies=wildcard_filtered,
        profile_text=profile_text,
        vibe_dials=vibe_dials,
        sliders=sliders,
        constraints=wildcard_constraints,
        interactions=interactions,
        openai_service=openai_service,
    )
    ranked_wild = _apply_diversity(ranked_wild)

    top = ranked[0] if ranked else None
    backup = None
    wildcard = None

    if top:
        top_genres = _genre_ids(top)
        for m in ranked[1:]:
            if _genre_ids(m) & top_genres:
                backup = m
                break
        if backup is None and len(ranked) > 1:
            backup = ranked[1]

        top_year = (top.get("release_date") or "0000")[:4]
        for m in ranked_wild:
            if m["id"] == top["id"] or (backup and m["id"] == backup["id"]):
                continue
            different_genre = len(_genre_ids(m) & top_genres) == 0
            different_era = (m.get("release_date") or "0000")[:4] != top_year
            if different_genre or different_era:
                wildcard = m
                break
        if wildcard is None:
            for m in ranked_wild:
                if m["id"] != top["id"] and (not backup or m["id"] != backup["id"]):
                    wildcard = m
                    break

    # Guarantee exactly three outputs.
    picks = [p for p in [top, backup, wildcard] if p]
    if len(picks) < 3:
        for m in ranked:
            if m not in picks:
                picks.append(m)
            if len(picks) >= 3:
                break
    while len(picks) < 3:
        picks.append(None)

    top, backup, wildcard = picks[0], picks[1], picks[2]

    reasons: Dict[str, List[str]] = {}
    for name, movie in [("top", top), ("backup", backup), ("wildcard", wildcard)]:
        if not movie:
            reasons[name] = ["No matching title found for this slot."]
            continue
        bullet = _reasons_for_movie(movie, context=quick_context, constraints=quick_constraints if name != "wildcard" else wildcard_constraints)
        if movie.get("runtime") and time_minutes is not None and movie["runtime"] <= (time_minutes + 10):
            bullet.append("Fits your available time.")
        if movie.get("providers", {}).get("flatrate"):
            bullet.append("Available on streaming in your region.")
        if refinement:
            bullet.append(f"Adjusted for refinement: {refinement}.")
        reasons[name] = bullet[:3]

    def _shape(movie: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not movie:
            return None
        return {
            **movie,
            "overview": _clip_overview(movie.get("overview", ""), 180),
        }

    return {
        "top": _shape(top),
        "backup": _shape(backup),
        "wildcard": _shape(wildcard),
        "reasons": reasons,
        "profile_hash": profile_hash,
        "context_hash": context_hash,
    }
