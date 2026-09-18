"""
scripts/_actor_authorization.py
--------------------------------
Phase 8DF — a shared "is this a real, authorized actor?" check for every
Germany statutory activation script that performs a maker-checker action
(create/approve/publish/activate).

WHY THIS EXISTS

`publish_seeded_germany_registries.py` and
`seed_germany_compliance_pack_2026.py` (as validated on the `nikhil`
branch) both called their maker-checker service functions with hardcoded
placeholder actor ids (901/902), documented there as "obviously-fake" and
explicitly noted as something "a real deployment would pass real,
distinct Super Admin user ids instead." That was correct as an isolated-
database validation convention, but it must never be carried into
tooling that is capable of running against anything else.

This module makes the "real deployment" requirement an enforced
precondition instead of a comment: every actor id these scripts use must
resolve to a real, active `User` row with `role == UserRole.SUPER_ADMIN`
in whichever database is configured — this is the same authorization
concept (`app/modules/auth/models.py`'s `UserRole.SUPER_ADMIN`) the real
Super Admin API endpoints already require for pack/registry governance
actions; it is not invented here.

WHAT THIS DELIBERATELY DOES NOT DO

It does not accept a default actor id. There is no fallback constant
anywhere in this module. If the caller does not supply an explicit
`--maker-id`/`--checker-id` (or equivalent), the calling script's own
argument parsing already refuses to run (see its `main()`); if it does
supply ids, this module still independently verifies both resolve to
real, active Super Admin users and are distinct from each other before
returning — a script that used only its own hardcoded fallback would be
caught here even if it changed its own defaults later.
"""

from __future__ import annotations

from app.modules.auth.models import User, UserRole


class ActorAuthorizationError(SystemExit):
    """Raised (as a SystemExit subclass) to abort the process — never
    caught and silently downgraded to a warning."""

    def __init__(self, message: str):
        super().__init__(2)
        self.message = message


def require_super_admin_actor(db, user_id: int, role_label: str) -> User:
    """Refuses (raises ActorAuthorizationError) unless `user_id` resolves
    to a real, active, Super Admin `User` row. Returns the row otherwise,
    so callers can log a real name/email rather than a bare id."""
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ActorAuthorizationError(
            f"REFUSING TO RUN — {role_label} actor id must be a positive integer, got {user_id!r}."
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise ActorAuthorizationError(
            f"REFUSING TO RUN — {role_label} actor id {user_id} does not exist in the users table. "
            "This tooling requires a real, existing Super Admin user id — never a placeholder."
        )
    if not user.is_active:
        raise ActorAuthorizationError(
            f"REFUSING TO RUN — {role_label} user id {user_id} ({user.email}) exists but is not active."
        )
    if user.role != UserRole.SUPER_ADMIN:
        raise ActorAuthorizationError(
            f"REFUSING TO RUN — {role_label} user id {user_id} ({user.email}) has role "
            f"{user.role.value!r}, not 'super_admin'. Germany statutory registry/pack governance "
            "actions require a Super Admin actor, matching the same requirement the real "
            "Super Admin API enforces."
        )
    return user


def require_distinct_maker_checker(maker_id: int, checker_id: int) -> None:
    """Fails fast and clearly at the script level — the service layer
    already enforces approver != updated_by server-side, but a script
    calling it with the same id for both roles should never even reach
    that point silently."""
    if maker_id == checker_id:
        raise ActorAuthorizationError(
            f"REFUSING TO RUN — maker and checker must be distinct actors (both given as {maker_id}). "
            "Maker-checker governance requires two different real Super Admin users."
        )


def resolve_and_authorize_maker_checker(db, maker_id: int, checker_id: int) -> tuple[User, User]:
    """The single entry point every activation script should call, right
    after opening its DB session: validates both actors are real, active
    Super Admins, and that they are distinct from each other. Returns
    (maker_user, checker_user)."""
    require_distinct_maker_checker(maker_id, checker_id)
    maker = require_super_admin_actor(db, maker_id, "maker")
    checker = require_super_admin_actor(db, checker_id, "checker")
    return maker, checker
