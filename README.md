# VibeRecs (Streamlit MVP)

VibeRecs is a vibe-driven movie recommender built with Streamlit, TMDB, OpenAI (optional), and SQLite.

## What It Does

- Onboards users with 10 swipe actions (Like / Dislike / Skip).
- Stores persistent user profile and interactions in SQLite for returning users.
- Adds a **Tonight's context** banner:
  - Mood: `chill`, `high-energy`, `emotional`, `spooky`, `thoughtful`, `romantic`
  - Who: `solo`, `date`, `friends`, `family`
  - Time: `<90m`, `90-120m`, `120m+`
- Adds beginner **Tonight's Vibe** dials:
  - Cozy ↔ Intense
  - Light ↔ Dark
  - Mainstream ↔ Hidden Gems
- Adds advanced **Fine tune** sliders with semantic labels.
- Applies hard constraints **before** ranking:
  - less violent
  - more hopeful
  - shorter
  - non-English ok
  - no jump scares
  - Only streaming now
- Produces 12 recommendations in clustered rows:
  - Top matches for you (4)
  - Short & easy to start (2)
  - Because you liked ... (3)
  - Wildcard picks (3)
- Shows richer cards:
  - runtime badge
  - provider badges
  - availability age (`checked X days ago`)
  - feedback buttons (`👍`, `👎`, `👀`) + reason buttons
  - deterministic “Why this?” bullets
  - optional OpenAI extra spoiler-free bullets (cached)
- Collections sidebar always shows at least 3 collections:
  - curated JSON when available
  - dynamic fallback collections when not

## Recommender Pipeline

Two-stage ranking in `services/recs.py`:

1. Candidate generation:
   - liked-seed recommendations
   - trending/popular
   - collection recipe candidates
2. Hard-filter pass:
   - region/provider constraints
   - streaming-only
   - time/runtime rules
   - language rules
   - jump-scare/horror approximation
3. Re-rank pass:
   - embedding similarity (if OpenAI available) or fallback lexical similarity
   - slider/vibe similarity
   - popularity/rating normalization
   - novelty/diversity adjustments
   - dislike/seen penalties

## Data and Caching

SQLite tables include:

- `user_profiles`
- `interactions`
- `provider_cache`
- `embeddings_cache`
- `why_cache`
- `cached_tmdb`

Caching:

- TMDB endpoint cache (`cached_tmdb`)
- provider cache with timestamps (`provider_cache`)
- embeddings (`embeddings_cache`)
- AI why cache keyed by `movie_id + profile_hash + context_hash` (`why_cache`)

## Setup

1. Create a virtual environment and activate it.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example`:

```bash
TMDB_API_KEY=your_tmdb_key
OPENAI_API_KEY=your_openai_key
TMDB_REGION=US
```

4. Run:

```bash
streamlit run app.py
```

## API Key Behavior

- `TMDB_API_KEY` is required (app stops without it).
- `OPENAI_API_KEY` is optional:
  - without it, app still works with fallback similarity and deterministic explanations.
