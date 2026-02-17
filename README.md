# VibeRecs (Streamlit MVP)

VibeRecs is a Streamlit-first movie recommendation MVP using:
- TMDB API for metadata, posters, recommendations, and watch providers
- OpenAI API for embeddings and explainable "Why this?" text
- SQLite for user profile, interactions, and API caches

## Project Structure

- `app.py`
- `services/storage.py`
- `services/tmdb.py`
- `services/openai_client.py`
- `services/recs.py`
- `curated_collections.json`
- `requirements.txt`
- `.env.example`

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set keys:

```bash
TMDB_API_KEY=your_tmdb_key
OPENAI_API_KEY=your_openai_key
TMDB_REGION=US
```

4. Run:

```bash
streamlit run app.py
```

## What the MVP does

- Onboarding with 10 swipes (Like / Dislike / Skip)
- 3 intent questions (mood, who with, time)
- Taste sliders + toggles for quick control updates
- 12 recommendation cards with:
  - poster
  - title/year
  - genres/runtime/rating
  - watch provider availability by region
  - expandable "Why this?" (cached)
- Weekly featured curated collection + personalized collection ranking
- SQLite persistence so returning users keep taste profile
- "Reset my taste" to clear user rows

## Caching behavior

- TMDB: cached by endpoint + params
- Embeddings: cached by key + text version hash
- Explanations: cached by user profile hash + movie id + controls hash

## Notes

- If `OPENAI_API_KEY` is missing, the app still runs with fallback ranking/explanations.
- If `TMDB_API_KEY` is missing, app startup stops with an error.
- This MVP identifies users with local session UUID (no auth).

