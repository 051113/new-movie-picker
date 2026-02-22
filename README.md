# 지금한편 (VibeRecs Quick Pick)

`지금한편` is a Streamlit movie recommender that returns 3 personalized picks fast:
- `Top Pick`
- `Backup`
- `Wildcard`

It uses TMDB for movie data and streaming availability, SQLite for persistence/caching, and OpenAI optionally for embeddings and extra explanation bullets.

## Current App Features

- Login-based profile flow in the sidebar (`User ID` + `Log in` / `Log out`).
- Bilingual UI (`English` / `Korean`).
- Quick input panel:
  - `Minutes available` (20-180)
  - `Who` (Alone, Partner, Friends, Family)
  - `Emotional intention`
  - `Energy`
  - `Streaming only` toggle
  - `Region` selector (`KR`, `US`, `JP`, `GB`, `CA`, `AU`, `DE`, `FR`, `IN`)
- One-click recommendation generation (`Pick for me`).
- Card UI for each of the 3 picks:
  - Poster, title, overview
  - Year/runtime/genres/rating line
  - Availability line (stream/rent/buy providers)
  - Trailer link (when available)
  - `Why this?` section with deterministic bullets
  - Optional AI add-on bullets (`Add AI angle`, spoiler-free)
- Feedback actions per card:
  - `Like`
  - `Dislike` (with reason capture)
  - `Renew` (replace that slot with a fresh option)
- Refinement actions:
  - More exciting, Funnier, More emotional, Lighter, Darker, Shorter,
    More popular, More indie, Surprise me
- Reset tools in sidebar:
  - Soft reset (remove last 20 interactions)
  - Full reset (clear profile + interactions for active user)

## Recommendation Logic (Current)

Implemented in `services/recs.py` (`get_quick_pick`):

1. Build candidate pool from:
   - recommendations from recent likes
   - TMDB trending/popular
   - fallback collection-style discovery queries
2. Enrich candidates with details/providers.
3. Apply hard filters (streaming/time/runtime/provider rules).
4. Score and rerank using:
   - OpenAI embedding similarity when enabled, otherwise lexical fallback
   - vibe/slider similarity
   - popularity/rating normalization
   - diversity and interaction penalties
5. Output exactly 3 picks (`top`, `backup`, `wildcard`) with short reasons.

## Data Storage and Cache

SQLite database: `viberecs.db`

Main tables:
- `user_profiles`
- `interactions`
- `provider_cache`
- `embeddings_cache`
- `why_cache`
- `cached_tmdb`
- `curated_collections`

Caching includes TMDB responses, provider payloads, embedding vectors, and generated AI explanation bullets.

## Requirements

- Python 3.10+
- TMDB API key (required)
- OpenAI API key (optional)

Dependencies in `requirements.txt`:
- `streamlit`
- `openai`
- `requests`
- `python-dotenv`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables (for example in `.env`):

```bash
TMDB_API_KEY=your_tmdb_key
OPENAI_API_KEY=your_openai_key   # optional
TMDB_REGION=KR
```

4. Run the app:

```bash
streamlit run app.py
```

## Key Behavior Notes

- `TMDB_API_KEY` missing: app stops with an error.
- `OPENAI_API_KEY` missing: app still works in fallback mode.
- User context and interactions are persisted per `user_id`.
