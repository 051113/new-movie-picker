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
        self.region = region.upper()

    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        payload = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        return self.storage.stable_hash(payload)

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        merged = {"api_key": self.api_key, **params}
        key = self._cache_key(endpoint, merged)
        cached = self.storage.get_tmdb_cache(key)
        if cached is not None:
            return cached

        url = f"{TMDB_BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, params=merged, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise TMDBError(f"TMDB request failed for {endpoint}: {exc}") from exc

        self.storage.set_tmdb_cache(key, endpoint, merged, payload)
        return payload

    def trending_movies(self, page: int = 1, region: Optional[str] = None) -> List[Dict[str, Any]]:
        reg = (region or self.region).upper()
        data = self._get("/trending/movie/week", {"page": page, "watch_region": reg})
        return data.get("results", [])

    def popular_movies(self, page: int = 1, region: Optional[str] = None) -> List[Dict[str, Any]]:
        reg = (region or self.region).upper()
        data = self._get("/movie/popular", {"page": page, "region": reg})
        return data.get("results", [])

    def movie_recommendations(self, movie_id: int, page: int = 1) -> List[Dict[str, Any]]:
        data = self._get(f"/movie/{movie_id}/recommendations", {"page": page})
        return data.get("results", [])

    def discover_movies(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = self._get("/discover/movie", params)
        return data.get("results", [])

    def get_movie_details(self, movie_id: int) -> Dict[str, Any]:
        return self._get(
            f"/movie/{movie_id}",
            {"append_to_response": "keywords,credits", "language": "en-US"},
        )

    def get_watch_providers(self, movie_id: int, region: Optional[str] = None) -> Dict[str, Any]:
        reg = (region or self.region).upper()
        cached, _ = self.storage.provider_cache_get(movie_id=movie_id, region=reg)
        if cached is not None:
            return cached

        payload = self._get(f"/movie/{movie_id}/watch/providers")
        region_payload = payload.get("results", {}).get(reg, {})
        self.storage.provider_cache_set(movie_id=movie_id, region=reg, payload=region_payload)
        return region_payload

    def provider_age_days(self, movie_id: int, region: Optional[str] = None) -> Optional[int]:
        reg = (region or self.region).upper()
        _, age = self.storage.provider_cache_get(movie_id=movie_id, region=reg)
        return age

    def get_movie_bundle(self, movie_id: int, region: Optional[str] = None) -> Dict[str, Any]:
        details = self.get_movie_details(movie_id)
        providers = self.get_watch_providers(movie_id, region=region)
        age_days = self.provider_age_days(movie_id, region=region)
        return {
            "details": details,
            "providers": providers,
            "provider_age_days": age_days,
            "runtime": details.get("runtime"),
        }

    @staticmethod
    def image_url(path: Optional[str], size: str = "w342") -> str:
        if not path:
            return ""
        return f"{IMAGE_BASE_URL}/{size}{path}"

    @staticmethod
    def movie_year(movie: Dict[str, Any]) -> str:
        date = movie.get("release_date") or ""
        return date[:4] if date else "-"

    @staticmethod
    def runtime_label(runtime: Optional[int]) -> str:
        if not runtime:
            return "Unknown runtime"
        return f"{runtime}m"

    @staticmethod
    def provider_badges(provider_payload: Dict[str, Any]) -> List[str]:
        badges: List[str] = []
        if not provider_payload:
            return badges
        for bucket in ["flatrate", "rent", "buy"]:
            providers = provider_payload.get(bucket, [])
            for p in providers[:4]:
                name = p.get("provider_name")
                if name:
                    prefix = "Stream" if bucket == "flatrate" else bucket.capitalize()
                    badges.append(f"{prefix}: {name}")
        return badges
