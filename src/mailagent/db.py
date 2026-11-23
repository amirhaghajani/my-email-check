"""PostgreSQL storage for crawled emails and their embeddings."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import Settings

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    folder TEXT NOT NULL,
    subject TEXT,
    sender_name TEXT,
    sender_email TEXT,
    to_recipients JSONB,
    cc_recipients JSONB,
    sent_at TIMESTAMPTZ,
    body_text TEXT,
    has_attachments BOOLEAN,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_emails_sent_at ON emails (sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails (sender_email);
CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails (folder);

CREATE TABLE IF NOT EXISTS email_embeddings (
    email_id TEXT PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    embedding VECTOR,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    until_date DATE,
    folder TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    processed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
"""


def connect(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(settings.database_url, autocommit=False)
    register_vector(conn)
    return conn


def init_db(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def upsert_emails(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    sql = """
    INSERT INTO emails (
        id, folder, subject, sender_name, sender_email,
        to_recipients, cc_recipients, sent_at, body_text, has_attachments
    ) VALUES (
        %(id)s, %(folder)s, %(subject)s, %(sender_name)s, %(sender_email)s,
        %(to_recipients)s, %(cc_recipients)s, %(sent_at)s, %(body_text)s, %(has_attachments)s
    )
    ON CONFLICT (id) DO UPDATE SET
        subject = EXCLUDED.subject,
        sender_name = EXCLUDED.sender_name,
        sender_email = EXCLUDED.sender_email,
        to_recipients = EXCLUDED.to_recipients,
        cc_recipients = EXCLUDED.cc_recipients,
        sent_at = EXCLUDED.sent_at,
        body_text = EXCLUDED.body_text,
        has_attachments = EXCLUDED.has_attachments,
        crawled_at = now()
    """
    with conn.cursor() as cur:
        for row in rows:
            values = dict(row)
            values["to_recipients"] = Json(values.get("to_recipients") or [])
            values["cc_recipients"] = Json(values.get("cc_recipients") or [])
            cur.execute(sql, values)


def upsert_embeddings(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    sql = """
    INSERT INTO email_embeddings (email_id, embedding, model)
    VALUES (%(email_id)s, %(embedding)s, %(model)s)
    ON CONFLICT (email_id) DO UPDATE SET
        embedding = EXCLUDED.embedding,
        model = EXCLUDED.model,
        created_at = now()
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)


def get_last_sent_at(conn: psycopg.Connection, folder: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(sent_at) FROM emails WHERE folder = %s", (folder,))
        row = cur.fetchone()
        return row[0] if row else None


def start_crawl_run(conn: psycopg.Connection, until_date: date, folder: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO crawl_runs (until_date, folder, status) "
            "VALUES (%s, %s, 'running') RETURNING id",
            (until_date, folder),
        )
        return cur.fetchone()[0]


def update_crawl_run(
    conn: psycopg.Connection,
    run_id: int,
    processed: int,
    status: str,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE crawl_runs SET processed=%s, status=%s, error=%s, updated_at=now() "
            "WHERE id=%s",
            (processed, status, error, run_id),
        )


def search(
    conn: psycopg.Connection,
    query_text: str,
    query_embedding: list[float] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if query_embedding is not None:
        sql = """
        SELECT e.id, e.subject, e.sender_name, e.sender_email, e.sent_at,
               left(e.body_text, 300) AS snippet
        FROM emails e
        JOIN email_embeddings emb ON emb.email_id = e.id
        WHERE emb.embedding IS NOT NULL
        ORDER BY emb.embedding <=> %s
        LIMIT %s
        """
        params: tuple[Any, ...] = (query_embedding, limit)
    else:
        sql = """
        SELECT id, subject, sender_name, sender_email, sent_at,
               left(body_text, 300) AS snippet
        FROM emails
        WHERE subject ILIKE %s OR body_text ILIKE %s
        ORDER BY sent_at DESC
        LIMIT %s
        """
        like = f"%{query_text}%"
        params = (like, like, limit)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()