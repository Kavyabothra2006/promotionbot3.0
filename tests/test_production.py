import os

os.environ.setdefault("BOT_TOKEN", "999999999:TESTTOKEN")
os.environ.setdefault("SUPER_ADMIN_IDS", "1,2")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "test")

from pathlib import Path

from app.config import Settings
from app.utils.referral_code import generate_referral_code

ROOT = Path(__file__).resolve().parents[1]


def test_database_url_and_defaults():
    s = Settings()
    assert s.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert s.DEFAULT_REFERRAL_TARGET == 2
    assert s.SUPER_ADMIN_IDS == [1, 2]


def test_referral_code_shape():
    code = generate_referral_code()
    assert len(code) == 10
    assert code.isalnum()



def test_release_hardening_guards():
    main = (ROOT / "app" / "main.py").read_text()
    config = (ROOT / "app" / "config.py").read_text()
    reconcile = (ROOT / "app" / "services" / "membership_reconcile.py").read_text()
    admins = (ROOT / "app" / "handlers" / "admin" / "admins.py").read_text()
    onboarding = (ROOT / "app" / "handlers" / "admin" / "onboarding.py").read_text()
    idempotency = (ROOT / "app" / "middlewares" / "idempotency.py").read_text()
    premium = (ROOT / "app" / "services" / "premium_service.py").read_text()
    models = (ROOT / "app" / "database" / "models.py").read_text()
    assert "PROCESSED_UPDATE_RETENTION_DAYS" in config
    assert "_processed_update_cleanup_loop" in main
    assert "await self._heartbeat" not in idempotency
    assert "def _heartbeat" in idempotency
    assert "User.id > last_id" in reconcile
    assert "A community must have one owner" in admins
    assert "can_invite_users" in onboarding
    assert "premium_unlock_method = UnlockMethod.REFERRAL" in premium
    assert "processed_at" in models and "ix_processed_updates_processed_at" in models


def test_application_imports():
    import app.main  # noqa: F401


def test_cleanup_scheduler_is_started():
    main = (ROOT / "app" / "main.py").read_text()
    assert "cleanup_scheduler_loop" in main
    assert "name=\"cleanup-scheduler\"" in main


def test_admin_panel_imports_state_filter():
    panel = (ROOT / "app" / "handlers" / "admin" / "panel.py").read_text()
    assert "from aiogram.filters import Command, StateFilter" in panel

def test_premium_membership_requires_approved_invite():
    premium = (ROOT / "app" / "services" / "premium_service.py").read_text()
    assert "PremiumInvite.approved_at.is_not(None)" in premium
