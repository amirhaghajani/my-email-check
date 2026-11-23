from datetime import datetime, timezone

from fakes import FakeClient, FakeItem, FakeMailbox, make_settings
from mailagent.crawler import Crawler


class FakeConn:
    def commit(self):
        pass


class FakeDB:
    def __init__(self):
        self.emails = []
        self.embeddings = []
        self.runs = []

    def connect(self, settings):
        return object()

    def init_db(self, conn):
        pass

    def start_crawl_run(self, conn, until_date, folder):
        self.runs.append((until_date, folder))
        return 1

    def update_crawl_run(self, conn, run_id, processed, status, error=None):
        pass

    def get_last_sent_at(self, conn, folder):
        return None

    def upsert_emails(self, conn, rows):
        self.emails.extend(rows)

    def upsert_embeddings(self, conn, rows):
        self.embeddings.extend(rows)


def _items():
    return [
        FakeItem(
            "1",
            "Password reset",
            FakeMailbox("Alice", "alice@example.com"),
            [FakeMailbox("Bala", "bala@example.com")],
            sent=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            body="my password is hunter2",
        ),
        FakeItem(
            "2",
            "Hello",
            FakeMailbox("Bob", "bob@example.com"),
            [FakeMailbox("Cara", "cara@example.com")],
            sent=datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc),
            body="hi",
        ),
    ]


def test_crawl_folder_stores_emails_and_embeddings():
    settings = make_settings(database_url="postgresql://fake", embedding_model="test-embed")
    fake_db = FakeDB()
    crawler = Crawler(
        settings,
        FakeClient(_items()),
        embed_fn=lambda texts: [[0.1, 0.2] for _ in texts],
        db_module=fake_db,
    )

    crawler._crawl_folder(FakeConn(), "sentitems", "2025-01-01")

    assert len(fake_db.emails) == 2
    assert len(fake_db.embeddings) == 2
    assert crawler.state.processed == 2
    assert fake_db.emails[0]["sender_email"] == "alice@example.com"
    assert "bala@example.com" in fake_db.emails[0]["to_recipients"][0]
    assert "hunter2" in fake_db.emails[0]["body_text"]


def test_crawl_embedding_failure_still_stores_emails():
    settings = make_settings(database_url="postgresql://fake", embedding_model="test-embed")
    fake_db = FakeDB()

    def boom(texts):
        raise RuntimeError("embedding model missing")

    crawler = Crawler(settings, FakeClient(_items()), embed_fn=boom, db_module=fake_db)
    crawler._crawl_folder(FakeConn(), "sentitems", "2025-01-01")

    assert len(fake_db.emails) == 2
    assert fake_db.embeddings == []