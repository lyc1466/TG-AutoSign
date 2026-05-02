from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.models.user import User
from backend.services.users import ensure_admin


def test_ensure_admin_uses_env_initial_credentials(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "operator")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setattr("backend.services.users.hash_password", lambda value: f"hash:{value}")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)
    db = session_local()
    try:
        user = ensure_admin(db)

        assert user.username == "operator"
        assert user.password_hash == "hash:secret-password"
        assert db.query(User).count() == 1
    finally:
        db.close()


def test_ensure_admin_keeps_existing_user_when_env_changes(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)
    db = session_local()
    try:
        existing = User(username="admin", password_hash="hash")
        db.add(existing)
        db.commit()

        monkeypatch.setenv("ADMIN_USERNAME", "operator")
        monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

        user = ensure_admin(db)

        assert user.username == "admin"
        assert db.query(User).count() == 1
    finally:
        db.close()
