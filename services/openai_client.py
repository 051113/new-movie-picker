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

    def embed_text(self, cache_key: str, text_version: str, text: str) -> Optional[List[float]]:
        if not self.client:
            return None

        cached = self.storage.get_embedding_cache(cache_key, text_version)
        if cached is not None:
            return cached

        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        embedding = response.data[0].embedding
        self.storage.set_embedding_cache(cache_key, text_version, embedding)
        return embedding

    def embed_user_profile(self, user_profile_hash: str, user_profile_text: str) -> Optional[List[float]]:
        key = f"user:{user_profile_hash}"
        return self.embed_text(cache_key=key, text_version=user_profile_hash, text=user_profile_text)

    def embed_movie_text(self, movie_id: int, text_version: str, movie_text: str) -> Optional[List[float]]:
        key = f"movie:{movie_id}:{text_version}"
        return self.embed_text(cache_key=key, text_version=text_version, text=movie_text)

    def explain_recommendation(
        self,
        user_id: str,
        user_profile_hash: str,
        movie_id: int,
        controls_hash: str,
        prompt_context: Dict[str, Any],
    ) -> str:
        cached = self.storage.get_explanation_cache(user_profile_hash, movie_id, controls_hash)
        if cached:
            return cached

        if not self.client:
            fallback = "- Matches your current preferences\n- Similar mood and tone to your recent likes"
            self.storage.set_explanation_cache(
                user_id=user_id,
                user_profile_hash=user_profile_hash,
                movie_id=movie_id,
                controls_hash=controls_hash,
                explanation_text=fallback,
            )
            return fallback

        instructions = (
            "You are a movie recommendation assistant. Return only 2-4 bullet points. "
            "Spoiler-free. Tie reasons to user intent and movie attributes (tone, pacing, themes)."
        )

        content = json.dumps(prompt_context, ensure_ascii=False)
        response = self.client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": content},
            ],
            temperature=0.3,
            max_output_tokens=150,
        )

        text = (response.output_text or "").strip()
        if not text:
            text = "- Good fit for your current vibe\n- Aligns with your selected pacing and tone"

        self.storage.set_explanation_cache(
            user_id=user_id,
            user_profile_hash=user_profile_hash,
            movie_id=movie_id,
            controls_hash=controls_hash,
            explanation_text=text,
        )
        return text

