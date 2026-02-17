import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path("viberecs.db")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Storage:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    movie_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cached_tmdb (
                    cache_key TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cached_embeddings (
                    cache_key TEXT PRIMARY KEY,
                    text_version TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cached_explanations (
                    cache_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    user_profile_hash TEXT NOT NULL,
                    movie_id INTEGER NOT NULL,
                    controls_hash TEXT NOT NULL,
                    explanation_text TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curated_collections (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    query_json TEXT NOT NULL,
                    embedding_json TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def stable_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def ensure_user(self, user_id: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (user_id, None, now, now),
            )

    def save_user_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        now = _utc_now_iso()
        payload = _json_dumps(profile)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (user_id, payload, now, now),
            )

    def load_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
        if not row or not row["profile_json"]:
            return None
        return json.loads(row["profile_json"])

    def save_interaction(self, user_id: str, movie_id: int, action: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interactions(user_id, movie_id, action, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, movie_id, action, _utc_now_iso()),
            )

    def get_interactions(self, user_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT movie_id, action, created_at FROM interactions WHERE user_id=? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_user_data(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM interactions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM cached_explanations WHERE user_id=?", (user_id,))

    def get_tmdb_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM cached_tmdb WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["response_json"])

    def set_tmdb_cache(
        self,
        cache_key: str,
        endpoint: str,
        params: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cached_tmdb(cache_key, endpoint, params_json, response_json, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_json=excluded.response_json,
                    fetched_at=excluded.fetched_at,
                    params_json=excluded.params_json
                """,
                (
                    cache_key,
                    endpoint,
                    _json_dumps(params),
                    _json_dumps(payload),
                    _utc_now_iso(),
                ),
            )

    def get_embedding_cache(self, cache_key: str, text_version: str) -> Optional[List[float]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT embedding_json FROM cached_embeddings
                WHERE cache_key=? AND text_version=?
                """,
                (cache_key, text_version),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["embedding_json"])

    def set_embedding_cache(self, cache_key: str, text_version: str, embedding: List[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cached_embeddings(cache_key, text_version, embedding_json, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    text_version=excluded.text_version,
                    embedding_json=excluded.embedding_json,
                    fetched_at=excluded.fetched_at
                """,
                (cache_key, text_version, _json_dumps(embedding), _utc_now_iso()),
            )

    def get_explanation_cache(
        self,
        user_profile_hash: str,
        movie_id: int,
        controls_hash: str,
    ) -> Optional[str]:
        cache_key = self.stable_hash(f"{user_profile_hash}:{movie_id}:{controls_hash}")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT explanation_text FROM cached_explanations WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        return row["explanation_text"]

    def set_explanation_cache(
        self,
        user_id: str,
        user_profile_hash: str,
        movie_id: int,
        controls_hash: str,
        explanation_text: str,
    ) -> None:
        cache_key = self.stable_hash(f"{user_profile_hash}:{movie_id}:{controls_hash}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cached_explanations(
                    cache_key, user_id, user_profile_hash, movie_id, controls_hash, explanation_text, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    explanation_text=excluded.explanation_text,
                    fetched_at=excluded.fetched_at
                """,
                (
                    cache_key,
                    user_id,
                    user_profile_hash,
                    movie_id,
                    controls_hash,
                    explanation_text,
                    _utc_now_iso(),
                ),
            )

    def upsert_collection(self, collection: Dict[str, Any], embedding: Optional[List[float]]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO curated_collections(id, title, description, query_json, embedding_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    query_json=excluded.query_json,
                    embedding_json=excluded.embedding_json,
                    updated_at=excluded.updated_at
                """,
                (
                    collection["id"],
                    collection["title"],
                    collection["description"],
                    _json_dumps(collection["query"]),
                    _json_dumps(embedding) if embedding else None,
                    _utc_now_iso(),
                ),
            )

    def get_collection_embedding(self, collection_id: str) -> Optional[List[float]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding_json FROM curated_collections WHERE id=?", (collection_id,)
            ).fetchone()
        if not row or not row["embedding_json"]:
            return None
        return json.loads(row["embedding_json"])

