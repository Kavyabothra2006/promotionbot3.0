# Telegram Premium Community Management Bot

Production-oriented Python Telegram bot for managing multiple independent verification/premium communities from one bot.

## Stack

- Python 3.10+
- aiogram 3.16.0
- PostgreSQL + SQLAlchemy async + Alembic
- Redis for FSM state and distributed throttling
- Telegram `file_id` storage for welcome/broadcast media
- Long polling; no Docker required

## Production startup

1. Create a Python virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and provide `BOT_TOKEN`, `SUPER_ADMIN_IDS`, `DATABASE_URL`, and `REDIS_URL`.
3. Run the complete production entrypoint:

```bash
python scripts/start.py
```

`scripts/start.py` runs `alembic upgrade head` before starting the bot.

For Railway, use **Start Command**: `python scripts/start.py`. No Dockerfile is required. Attach managed PostgreSQL and Redis services and provide their connection URLs as environment variables.

## Telegram setup

The bot must be an administrator in each verification and premium group it manages. It needs permission to:

- delete join/leave messages;
- create/revoke invite links and approve/decline Premium join requests;
- receive chat-member updates;
- send/delete unlock notifications.

The bot also needs the administrator permissions required by the actions you enable in a particular community.

## Main commands

- `/newcommunity` — super-admin onboarding for a new managed community.
- `/admin` — community admin dashboard and analytics.
- `/dashboard` — user premium/referral dashboard.
- `/setwelcometext <community_id> <text>` — supports `{name}`, `{username}`, `{group}`, `{member_count}`.
- `/setwelcomebutton <community_id> <button text>`
- `/setwelcomemedia <community_id>` — reply to photo/video/GIF/sticker.
- `/setreferraltarget <community_id> <1-10>`
- `/toggleleavecleanup <community_id>`
- `/toggleremoveonleave <community_id>`
- `/broadcast <community_id> <all|premium>` — then send text/photo/video/GIF/sticker; one URL button is supported.
- `/ban`, `/unban`, `/search`, `/export_users`, `/analytics` — community-scoped moderation/search/export/analytics.
- `/backup <community_id>` and super-admin `/restore` — JSON backup/restore.

## Data model and isolation

Every user, referral, premium invite, purchase request, broadcast log, and admin relationship is scoped to a community. PostgreSQL unique constraints and row-level locking protect referral and premium-unlock flows against duplicate/concurrent processing.

## Backups and media

Welcome and broadcast media are never persisted to local disk. Telegram `file_id` values are stored in PostgreSQL. Backup JSON contains community configuration, users, referrals, premium invite state, purchase state, and admin state.

## Operational notes

The codebase intentionally contains no Docker artifacts, file-based persistence implementation, or project-level secrets. The included validation suite performs source, migration, configuration, and packaging checks. Real Telegram API, PostgreSQL, and Redis integration testing still requires a staging environment with valid services and a test bot; this sandbox cannot install external dependencies or reach those services.

### Production-hardening additions

- Telegram `update_id` idempotency is stored in PostgreSQL and guarded by a Redis lock.
- Pending Telegram updates are preserved across restarts; startup does not drop them.
- Premium join-request links use Telegram's approval flow without `member_limit`, and approved invites are tracked in PostgreSQL.
- Referral-earned Premium unlocks are retried after transient Telegram/API failures.
- Broadcast workers use a Redis lease heartbeat and a continuous recovery supervisor.
- Premium membership reconciliation runs periodically for communities configured to remove access on leave.
- Community owners can use `/addadmin`, `/removeadmin`, and `/listadmins`.
- Runtime errors are logged and reported to configured super-admins.

## Testing / staging

Use a dedicated Telegram test bot, verification group, Premium test group, PostgreSQL database, and Redis instance/database. Do not point the test bot at production communities.

1. Copy `.env.testing.example` to `.env` and replace the placeholders. Set `ENVIRONMENT=testing`.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Check real service connectivity: `python scripts/test_ready_check.py`.
4. Apply migrations: `python -m alembic upgrade head`.
5. Run automated tests: `pytest -q`.
6. Start the staging bot: `python scripts/staging_start.py`.

The test-ready package does not include Docker and does not require Docker. It is designed for testing against real PostgreSQL, Redis, and Telegram services.

Recommended manual staging flow: create one Verification group and one Premium group, add the bot as administrator with invite/member/message permissions, create one managed community with `/newcommunity`, then test referral unlock, manual purchase, Premium join requests, leave/banned-user cleanup, broadcast, backup/restore, and bot restart/recovery.
