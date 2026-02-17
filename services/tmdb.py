import json
from typing import Any, Dict, List, Optional

import requests

from services.storage import Storage


TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p"


class TMDBError(RuntimeError):
    pass


class TMDBClient:
    def __init__(self, api_key: str, storage: Storage, region: str = "US") -> None:
        self.api_key = api_key
        self.storage = storage
        self.region = region

    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        payload = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        return self.storage.stable_hash(payload)

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        merged = {"api_key": self.api_key, **params}
        cache_key = self._cache_key(endpoint, merged)
        cached = self.storage.get_tmdb_cache(cache_key)
        if cached is not None:
            return cached

        url = f"{TMDB_BASE_URL}{endpoint}"
        try:
            response = requests.get(url, params=merged, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise TMDBError(f"TMDB request failed for {endpoint}: {exc}") from exc

        self.storage.set_tmdb_cache(cache_key, endpoint, merged, data)
        return data

    def trending_movies(self, page: int = 1) -> List[Dict[str, Any]]:
        data = self._get("/trending/movie/week", {"page": page})
        return data.get("results", [])

    def popular_movies(self, page: int = 1) -> List[Dict[str, Any]]:
        data = self._get("/movie/popular", {"page": page})
        return data.get("results", [])

    def movie_recommendations(self, movie_id: int, page: int = 1) -> List[Dict[str, Any]]:
        data = self._get(f"/movie/{movie_id}/recommendations", {"page": page})
        return data.get("results", [])

    def discover_movies(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = self._get("/discover/movie", params)
        return data.get("results", [])

    def movie_details(self, movie_id: int) -> Dict[str, Any]:
        return self._get(
            f"/movie/{movie_id}",
            {"append_to_response": "keywords,credits", "language": "en-US"},
        )

    def watch_providers(self, movie_id: int, region: Optional[str] = None) -> Dict[str, Any]:
        data = self._get(f"/movie/{movie_id}/watch/providers")
        chosen = (region or self.region or "US").upper()
        return data.get("results", {}).get(chosen, {})

    @staticmethod
    def image_url(path: Optional[str], size: str = "w342") -> str:
        if not path:
            return ""
        return f"{IMAGE_BASE_URL}/{size}{path}"

    @staticmethod
    def movie_year(movie: Dict[str, Any]) -> str:
        raw = movie.get("release_date") or ""
        return raw[:4] if raw else "-"

    @staticmethod
    def flatten_watch_providers(provider_payload: Dict[str, Any]) -> str:
        if not provider_payload:
            return "No provider data"
        buckets = []
        for bucket in ["flatrate", "rent", "buy"]:
            providers = provider_payload.get(bucket, [])
            names = [p.get("provider_name") for p in providers if p.get("provider_name")]
            if names:
                buckets.append(f"{bucket}: {', '.join(names[:4])}")
        return " | ".join(buckets) if buckets else "No streaming providers listed"

