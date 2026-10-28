from sqlalchemy.engine import make_url

from backend.app.config import Settings


def test_plain_postgres_url_uses_psycopg_without_losing_credentials():
    settings = Settings(
        database_url="postgresql://medipredict:secret%40pass@db.example.test/app"
    )

    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "medipredict"
    assert url.password == "secret@pass"
    assert url.host == "db.example.test"
    assert url.database == "app"


def test_legacy_postgres_scheme_uses_psycopg():
    settings = Settings(database_url="postgres://medipredict:secret@db.example.test/app")

    assert make_url(settings.database_url).drivername == "postgresql+psycopg"


def test_relative_sqlite_url_is_resolved_without_changing_backend():
    settings = Settings(database_url="sqlite:///local-test.db")

    url = make_url(settings.database_url)
    assert url.get_backend_name() == "sqlite"
    assert url.database is not None
    assert url.database.endswith("local-test.db")
