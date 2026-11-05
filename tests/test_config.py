import pytest

from app.config import DEFAULT_CORS_ORIGINS, Settings


def origins(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")  # never connected to
    monkeypatch.setenv("CORS_ORIGINS", value)
    return Settings(_env_file=None).cors_origins


@pytest.mark.parametrize(
    "value,expected",
    [
        ('["https://a.workers.dev"]', ["https://a.workers.dev"]),
        ("https://a.workers.dev", ["https://a.workers.dev"]),
        ("https://a.workers.dev/", ["https://a.workers.dev"]),
        ("https://a.dev, http://localhost:5173", ["https://a.dev", "http://localhost:5173"]),
        ("", DEFAULT_CORS_ORIGINS),
    ],
)
def test_cors_origins_formats(monkeypatch, value, expected):
    assert origins(monkeypatch, value) == expected
