from app.db import normalize_async_database_url


def test_normalize_managed_postgres_urls_for_asyncpg():
    assert normalize_async_database_url("postgres://user:pass@db.example/callpay") == (
        "postgresql+asyncpg://user:pass@db.example/callpay"
    )
    assert normalize_async_database_url("postgresql://user:pass@db.example/callpay") == (
        "postgresql+asyncpg://user:pass@db.example/callpay"
    )


def test_keep_explicit_asyncpg_and_sqlite_urls():
    postgres = "postgresql+asyncpg://user:pass@db.example/callpay"
    sqlite = "sqlite+aiosqlite:///./callpay.db"
    assert normalize_async_database_url(postgres) == postgres
    assert normalize_async_database_url(sqlite) == sqlite
