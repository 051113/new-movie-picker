import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DB_PATH = Path("viberecs.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class Storage:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    @staticmethod
    def stable_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    region TEXT NOT NULL DEFAULT 'US',
                    sliders_json TEXT,
                    vibe_dials_json TEXT,
                    constraints_json TEXT,
                    context_json TEXT,
                    exploration_pref REAL DEFAULT 0.5,
                    onboarding_complete INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    movie_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    session_id TEXT,
                    ranking_version TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_cache (
                    region TEXT NOT NULL,
                    movie_id INTEGER NOT NULL,
                    providers_json TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    PRIMARY KEY(region, movie_id)
                );

                CREATE TABLE IF NOT EXISTS embeddings_cache (
                    movie_id INTEGER NOT NULL,
                    text_hash TEXT NOT NULL,
                    vector_blob TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(movie_id, text_hash)
                );

                CREATE TABLE IF NOT EXISTS why_cache (
                    movie_id INTEGER NOT NULL,
                    profile_hash TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    bullets_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(movie_id, profile_hash, context_hash)
                );

                CREATE TABLE IF NOT EXISTS cached_tmdb (
                    cache_key TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
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

            # Lightweight migration for older interactions table.
            cols = self._table_columns(conn, "interactions")
            if "reason" not in cols:
                conn.execute("ALTER TABLE interactions ADD COLUMN reason TEXT")
            if "session_id" not in cols:
                conn.execute("ALTER TABLE interactions ADD COLUMN session_id TEXT")
            if "ranking_version" not in cols:
                conn.execute("ALTER TABLE interactions ADD COLUMN ranking_version TEXT")

    def get_or_create_user(self, user_id: str, region: str = "US") -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles(user_id, region, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (user_id, region, _now_iso()),
            )
        return user_id

    def load_profile(self, user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT region, sliders_json, vibe_dials_json, constraints_json, context_json,
                       exploration_pref, onboarding_complete
                FROM user_profiles WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return {}
        return {
            "region": row["region"],
            "sliders": _from_json(row["sliders_json"], {}),
            "vibe_dials": _from_json(row["vibe_dials_json"], {}),
            "constraints": _from_json(row["constraints_json"], {}),
            "context": _from_json(row["context_json"], {}),
            "exploration_pref": row["exploration_pref"] if row["exploration_pref"] is not None else 0.5,
            "onboarding_complete": bool(row["onboarding_complete"]),
        }

    def save_profile(
        self,
        user_id: str,
        *,
        region: str,
        sliders: Dict[str, Any],
        vibe_dials: Dict[str, Any],
        constraints: Dict[str, Any],
        context: Dict[str, Any],
        exploration_pref: float,
        onboarding_complete: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles(
                    user_id, region, sliders_json, vibe_dials_json, constraints_json,
                    context_json, exploration_pref, onboarding_complete, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    region=excluded.region,
                    sliders_json=excluded.sliders_json,
                    vibe_dials_json=excluded.vibe_dials_json,
                    constraints_json=excluded.constraints_json,
                    context_json=excluded.context_json,
                    exploration_pref=excluded.exploration_pref,
                    onboarding_complete=excluded.onboarding_complete,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    region,
                    _to_json(sliders),
                    _to_json(vibe_dials),
                    _to_json(constraints),
                    _to_json(context),
                    exploration_pref,
                    1 if onboarding_complete else 0,
                    _now_iso(),
                ),
            )

    def log_interaction(
        self,
        user_id: str,
        movie_id: int,
        action: str,
        reason: Optional[str] = None,
        session_id: Optional[str] = None,
        ranking_version: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interactions(user_id, movie_id, action, reason, session_id, ranking_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, movie_id, action, reason, session_id, ranking_version, _now_iso()),
            )

    def get_interactions(self, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, movie_id, action, reason, session_id, ranking_version, created_at
            FROM interactions
            WHERE user_id=?
            ORDER BY id DESC
        """
        params: List[Any] = [user_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def get_recent_likes(self, user_id: str, limit: int = 5) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT movie_id
                FROM interactions
                WHERE user_id=? AND action='like'
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [int(r["movie_id"]) for r in rows]

    def get_recent_seen(self, user_id: str, limit: int = 200) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT movie_id
                FROM interactions
                WHERE user_id=? AND action IN ('seen', 'dislike')
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [int(r["movie_id"]) for r in rows]

    def reset_profile_soft(self, user_id: str, n: int = 20) -> None:
        with self._connect() as conn:
            ids = conn.execute(
                "SELECT id FROM interactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, n),
            ).fetchall()
            if ids:
                conn.executemany(
                    "DELETE FROM interactions WHERE id=?",
                    [(row["id"],) for row in ids],
                )

    def reset_profile_full(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM user_profiles WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM interactions WHERE user_id=?", (user_id,))

    def provider_cache_get(self, movie_id: int, region: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT providers_json, checked_at
                FROM provider_cache
                WHERE movie_id=? AND region=?
                """,
                (movie_id, region.upper()),
            ).fetchone()
        if not row:
            return None, None
        payload = _from_json(row["providers_json"], {})
        checked = datetime.fromisoformat(row["checked_at"])
        age_days = max(0, int((datetime.now(timezone.utc) - checked).total_seconds() // 86400))
        return payload, age_days

    def provider_cache_set(self, movie_id: int, region: str, payload: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_cache(region, movie_id, providers_json, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(region, movie_id) DO UPDATE SET
                    providers_json=excluded.providers_json,
                    checked_at=excluded.checked_at
                """,
                (region.upper(), movie_id, _to_json(payload), _now_iso()),
            )

    def embeddings_cache_get(self, movie_id: int, text_hash: str) -> Optional[List[float]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT vector_blob
                FROM embeddings_cache
                WHERE movie_id=? AND text_hash=?
                """,
                (movie_id, text_hash),
            ).fetchone()
        if not row:
            return None
        return _from_json(row["vector_blob"], None)

    def embeddings_cache_set(self, movie_id: int, text_hash: str, vector: List[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO embeddings_cache(movie_id, text_hash, vector_blob, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(movie_id, text_hash) DO UPDATE SET
                    vector_blob=excluded.vector_blob,
                    created_at=excluded.created_at
                """,
                (movie_id, text_hash, _to_json(vector), _now_iso()),
            )

    def why_cache_get(self, movie_id: int, profile_hash: str, context_hash: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT bullets_text
                FROM why_cache
                WHERE movie_id=? AND profile_hash=? AND context_hash=?
                """,
                (movie_id, profile_hash, context_hash),
            ).fetchone()
        if not row:
            return None
        return row["bullets_text"]

    def why_cache_set(self, movie_id: int, profile_hash: str, context_hash: str, bullets_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO why_cache(movie_id, profile_hash, context_hash, bullets_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(movie_id, profile_hash, context_hash) DO UPDATE SET
                    bullets_text=excluded.bullets_text,
                    created_at=excluded.created_at
                """,
                (movie_id, profile_hash, context_hash, bullets_text, _now_iso()),
            )

    def get_tmdb_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM cached_tmdb WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        return _from_json(row["response_json"], None)

    def set_tmdb_cache(self, cache_key: str, endpoint: str, params: Dict[str, Any], payload: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cached_tmdb(cache_key, endpoint, params_json, response_json, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    params_json=excluded.params_json,
                    response_json=excluded.response_json,
                    fetched_at=excluded.fetched_at
                """,
                (cache_key, endpoint, _to_json(params), _to_json(payload), _now_iso()),
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
                    _to_json(collection.get("query", {})),
                    _to_json(embedding) if embedding else None,
                    _now_iso(),
                ),
            )

    def get_collection_embedding(self, collection_id: str) -> Optional[List[float]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding_json FROM curated_collections WHERE id=?",
                (collection_id,),
            ).fetchone()
        if not row:
            return None
        return _from_json(row["embedding_json"], None)

    def get_metrics(self, user_id: str) -> Dict[str, Any]:
        rows = self.get_interactions(user_id, limit=2000)
        shown = [r for r in rows if r["action"] == "shown"]
        likes = [r for r in rows if r["action"] == "like"]
        skips = [r for r in rows if r["action"] == "skip"]
        why_open = [r for r in rows if r["action"] == "why_open"]
        like_rate = (len(likes) / len(shown)) if shown else 0.0
        skip_rate = (len(skips) / len(shown)) if shown else 0.0

        first_like_seconds = None
        if likes and shown:
            shown_sorted = sorted(shown, key=lambda x: x["created_at"])
            likes_sorted = sorted(likes, key=lambda x: x["created_at"])
            t0 = datetime.fromisoformat(shown_sorted[0]["created_at"])
            t1 = datetime.fromisoformat(likes_sorted[0]["created_at"])
            first_like_seconds = max(0, int((t1 - t0).total_seconds()))

        return {
            "like_rate": round(like_rate, 3),
            "skip_rate": round(skip_rate, 3),
            "time_to_first_like": first_like_seconds,
            "why_open_count": len(why_open),
        }
