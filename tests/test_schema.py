from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_required_runtime_components_are_present():
    required = [
        ROOT / "app" / "main.py",
        ROOT / "app" / "database" / "models.py",
        ROOT / "app" / "database" / "base.py",
        ROOT / "app" / "handlers" / "group" / "welcome.py",
        ROOT / "app" / "handlers" / "group" / "premium_membership.py",
        ROOT / "app" / "handlers" / "user" / "start.py",
        ROOT / "app" / "handlers" / "user" / "verification.py",
        ROOT / "app" / "handlers" / "user" / "dashboard.py",
        ROOT / "app" / "handlers" / "admin" / "broadcast.py",
        ROOT / "app" / "services" / "backup_service.py",
    ]
    assert all(p.exists() for p in required)


def test_no_legacy_or_docker_artifacts():
    forbidden = [
        ROOT / "Dockerfile", ROOT / "docker-compose.yml", ROOT / "docker-entrypoint.sh",
        ROOT / "storage.py", ROOT / "services.py", ROOT / "models.py",
    ]
    assert all(not p.exists() for p in forbidden)
    text = "\n".join(p.read_text(errors="ignore") for p in ROOT.rglob("*.py") if "tests" not in p.parts)
    assert "Json" + "Store" not in text
    assert "aio" + "sqlite" not in text


def test_environment_and_dependencies_are_postgres_redis_only():
    req = (ROOT / "requirements.txt").read_text()
    assert "asyncpg==0.30.0" in req
    assert "redis==5.2.1" in req
    assert "aio" + "sqlite" not in req
    assert "DATABASE_URL=postgresql+asyncpg://" in (ROOT / ".env.example").read_text()


def test_migration_chain_is_single_and_linear():
    revisions = {}
    for path in sorted((ROOT / "alembic" / "versions").glob("*.py")):
        text = path.read_text()
        rev = re.search(r'revision\s*=\s*"([^"]+)"', text)
        parent = re.search(r'down_revision\s*=\s*([^\n]+)', text)
        assert rev and parent
        revisions[rev.group(1)] = parent.group(1).strip().strip('"\'')
    assert revisions["0001_initial_schema"] == "None"
    assert revisions["0005_production_constraints"] == "0004_broadcast_resume_cursor"
    assert revisions["0006_referral_invite_integrity"] == "0005_production_constraints"
    assert revisions["0007_event_idempotency_invite"] == "0006_referral_invite_integrity"
    assert revisions["0008_release_hardening"] == "0007_event_idempotency_invite"
    assert revisions["0009_ui_cleanup_schedule"] == "0008_release_hardening"
    assert len(revisions) == 9


def test_critical_telegram_lifecycle_guards():
    main = (ROOT / "app" / "main.py").read_text()
    premium = (ROOT / "app" / "services" / "premium_service.py").read_text()
    start = (ROOT / "app" / "handlers" / "user" / "start.py").read_text()
    middleware = (ROOT / "app" / "middlewares" / "idempotency.py").read_text()
    broadcast = (ROOT / "app" / "handlers" / "admin" / "broadcast.py").read_text()
    assert "drop_pending_updates=False" in main
    assert "drop_pending_updates=True" not in main
    assert "member_limit=1" not in premium
    assert "creates_join_request=True" in premium
    assert "pending_joined" in start
    assert "ProcessedUpdate" in middleware
    assert "broadcast_recovery_loop" in broadcast
    assert "_renew_broadcast_lease" in broadcast
