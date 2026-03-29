import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/raw/staging.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS search_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT,
            domain      TEXT,
            title       TEXT,
            snippet     TEXT,
            query       TEXT,
            tier_guess  INTEGER,
            tier_final  INTEGER,
            score       INTEGER,
            source      TEXT,
            status      TEXT DEFAULT 'pending'
        );

        CREATE INDEX IF NOT EXISTS idx_sr_status ON search_results(status);
        CREATE INDEX IF NOT EXISTS idx_sr_score  ON search_results(score DESC);

        CREATE TABLE IF NOT EXISTS raw_company (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT,
            phone     TEXT,
            email     TEXT,
            website   TEXT,
            raw_json  TEXT,
            status    TEXT DEFAULT 'pending'
        );
        """)


def save_search_result(
    url: str,
    domain: str,
    title: str = "",
    snippet: str = "",
    query: str = "",
    tier_guess: int = 0,
    tier_final: int = 0,
    score: int = 0,
    source: str = "ddg",
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO search_results
                (url, domain, title, snippet, query,
                 tier_guess, tier_final, score, source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (url, domain, title, snippet, query,
             tier_guess, tier_final, score, source),
        )


def get_pending_search_results(limit: int = 50) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM search_results
            WHERE status = 'pending'
            ORDER BY score DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cursor.fetchall()


def mark_search_result(url: str, status: str):
    """Met à jour le statut d'un résultat (ex: 'scraped', 'error', 'done')."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE search_results SET status = ? WHERE url = ?",
            (status, url),
        )


def get_known_domains() -> set[str]:
    """Retourne les domaines déjà présents dans search_results."""
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT domain FROM search_results").fetchall()
        return {row["domain"] for row in rows if row["domain"]}


def save_raw_company(data: dict):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO raw_company (name, phone, email, website, raw_json, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (
                data.get("name"),
                data.get("phone"),
                data.get("email"),
                data.get("website"),
                json.dumps(data, ensure_ascii=False),
            ),
        )