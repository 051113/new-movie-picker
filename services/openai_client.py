import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from services.storage import Storage


class OpenAIService:
    def __init__(self, api_key: Optional[str], storage: Storage) -> None:
        self.storage = storage
        self.client = OpenAI(api_key=api_key) if api_key else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _pseudo_movie_id(self, cache_namespace: str) -> int:
        # Negative IDs keep non-movie vectors in the same cache table.
        return -int(cache_namespace[:7], 16)

    def embed_text(self, cache_movie_id: int, text: str) -> Optional[List[float]]:
        if not self.client:
            return None
        text_hash = self.storage.stable_hash(text)
        cached = self.storage.embeddings_cache_get(cache_movie_id, text_hash)
        if cached is not None:
            return cached

        resp = self.client.embeddings.create(model="text-embedding-3-small", input=text)
        vector = resp.data[0].embedding
        self.storage.embeddings_cache_set(cache_movie_id, text_hash, vector)
        return vector

    def embed_movie_text(self, movie_id: int, movie_text: str) -> Optional[List[float]]:
        return self.embed_text(movie_id, movie_text)

    def embed_user_profile(self, profile_text: str) -> Optional[List[float]]:
        pseudo_id = self._pseudo_movie_id(self.storage.stable_hash(f"user:{profile_text}"))
        return self.embed_text(pseudo_id, profile_text)

    def embed_collection(self, collection_id: str, text: str) -> Optional[List[float]]:
        pseudo_id = self._pseudo_movie_id(self.storage.stable_hash(f"col:{collection_id}"))
        return self.embed_text(pseudo_id, text)

    def generate_why_spoiler_free(
        self,
        movie: Dict[str, Any],
        deterministic_bullets: List[str],
        user_context: Dict[str, Any],
        profile_hash: str,
        context_hash: str,
        language: str = "en",
    ) -> List[str]:
        movie_id = int(movie.get("id", 0))
        cached = self.storage.why_cache_get(movie_id, profile_hash, context_hash)
        if cached:
            return [line.strip("- ").strip() for line in cached.splitlines() if line.strip()]

        if not self.client:
            return []

        target_language = "Korean" if language == "ko" else "English"
        payload = {
            "movie": {
                "title": movie.get("title"),
                "overview": movie.get("overview", ""),
                "genres": movie.get("genres", []),
                "runtime": movie.get("runtime"),
            },
            "context": user_context,
            "deterministic_bullets": deterministic_bullets,
            "task": "Add 1-2 extra spoiler-free bullets. No plot reveals, twists, deaths, endings.",
            "language": target_language,
        }
        instructions = (
            "Return exactly 1-2 concise bullet points. Keep them spoiler-free. "
            "Do not mention specific plot events. "
            f"Write all output in {target_language}."
        )
        try:
            resp = self.client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_output_tokens=120,
                temperature=0.2,
            )
            raw = (resp.output_text or "").strip()
            lines = [line.strip("- ").strip() for line in raw.splitlines() if line.strip()]
            lines = lines[:2]
        except Exception:
            lines = []

        if lines:
            serialized = "\n".join(f"- {line}" for line in lines)
            self.storage.why_cache_set(movie_id, profile_hash, context_hash, serialized)
        return lines

    def translate_lines(self, lines: List[str], target_language: str) -> List[str]:
        if not lines:
            return []
        if not self.client:
            return lines
        instructions = (
            f"Translate each input line into {target_language}. "
            "Preserve line count and order. Return plain lines only."
        )
        payload = {"lines": lines}
        try:
            resp = self.client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_output_tokens=220,
                temperature=0.0,
            )
            raw = (resp.output_text or "").strip()
            translated = [line.strip("- ").strip() for line in raw.splitlines() if line.strip()]
            if len(translated) == len(lines):
                return translated
            return translated[: len(lines)] if translated else lines
        except Exception:
            return lines
