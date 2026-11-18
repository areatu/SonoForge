"""Application service owning local multi-user sessions, RBAC and audit trail.

Qt-widget-free application coordinator: presentation dialogs and coordinators
talk exclusively to :class:`UserSessionService` and never import
``infrastructure.user_repository``, ``infrastructure.user_crypto`` or
``infrastructure.audit_log`` directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from echo_personal_tool.application.preferences_contract import UserPreferences
from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.audit import (
    AuditAction,
    AuditEntry,
    AuditVerificationResult,
    DetailScalar,
)
from echo_personal_tool.domain.models.user import (
    DEFAULT_AUTO_LOCK_MINUTES,
    Permission,
    SecretKind,
    SigningKeyPublic,
    UserProfile,
    UserRole,
    UserSession,
    normalize_username,
)
from echo_personal_tool.infrastructure.audit_log import AuditLogError, LocalAuditLog
from echo_personal_tool.infrastructure.paths import (
    set_active_user_profile,
    user_preferences_ini,
    user_profile_dir,
)
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure
from echo_personal_tool.infrastructure.user_crypto import (
    DEFAULT_SCRYPT_N,
    sign_with_user_key,
    verify_ed25519_signature,
)
from echo_personal_tool.infrastructure.user_repository import LocalUserRepository, UserStoreState

logger = logging.getLogger(__name__)
_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310

SessionListener = Callable[[UserSession], None]
RecordScope = Literal["all", "mine"]


class UserSessionService:
    """Authoritative runtime owner of local accounts, active session and audit events."""

    def __init__(
        self,
        users_root: Path,
        *,
        scope_paths: bool = True,
        scrypt_n: int = DEFAULT_SCRYPT_N,
    ) -> None:
        self._root = Path(users_root)
        self._repository = LocalUserRepository(self._root, scrypt_n=scrypt_n)
        self._audit = LocalAuditLog(self._root)
        self._scope_paths = scope_paths
        self._listeners: list[SessionListener] = []
        state = self._safe_initial_state()
        self._session = UserSession(
            user=None,
            multi_user_enabled=state.multi_user_enabled,
            locked=state.multi_user_enabled,
            started_at="",
            auto_lock_minutes=state.auto_lock_minutes,
        )

    @property
    def users_root(self) -> Path:
        return self._root

    def _safe_initial_state(self) -> UserStoreState:
        try:
            return self._repository.load_state()
        except UserAuthError as exc:
            log_boundary_failure(logger, "auth.startup", exc, code=exc.code)
            # Fail closed if an existing users.json was tampered with or damaged:
            # treat multi-user as enabled + locked rather than silently dropping to
            # unauthenticated access.
            if self._repository.path.exists():
                return UserStoreState(multi_user_enabled=True, auto_lock_minutes=DEFAULT_AUTO_LOCK_MINUTES)
            return UserStoreState()

    def subscribe(self, listener: SessionListener) -> Callable[[], None]:
        """Register a session-change callback; returns an unsubscribe callable."""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    def _emit(self) -> None:
        snapshot = self._session
        for listener in tuple(self._listeners):
            listener(snapshot)

    def _apply_path_scope(self, user_id: str | None) -> None:
        if not self._scope_paths:
            return
        set_active_user_profile(user_id, users_root=self._root)

    def _record_audit(
        self,
        action: AuditAction,
        *,
        actor_id: str,
        target_id: str = "",
        study_key: str = "",
        details: Mapping[str, DetailScalar] | None = None,
    ) -> None:
        try:
            self._audit.append(
                action,
                actor_id=actor_id,
                target_id=target_id,
                study_key=study_key,
                details=details,
            )
        except (AuditLogError, ValueError) as exc:
            code = exc.code if isinstance(exc, AuditLogError) else "invalid"
            log_boundary_failure(logger, "audit.append", exc, code=code)

    # ── Session & capability queries ──────────────────────────────────────────

    @property
    def session(self) -> UserSession:
        return self._session

    @property
    def current_user(self) -> UserProfile | None:
        return self._session.user

    @property
    def active_user_id(self) -> str:
        """Opaque ID of the active unlocked user, or ``''`` in single-user/locked states."""
        return self._session.active_user_id

    def is_multi_user_enabled(self) -> bool:
        return self._session.multi_user_enabled

    def is_locked(self) -> bool:
        return self._session.multi_user_enabled and (self._session.locked or self._session.user is None)

    def has_users(self) -> bool:
        return bool(self._repository.load_state().users)

    def last_username(self) -> str:
        return self._repository.load_state().last_username

    def auto_lock_minutes(self) -> int:
        return self._session.auto_lock_minutes

    def can(self, permission: Permission) -> bool:
        return self._session.can(permission)

    def require(self, permission: Permission) -> None:
        if not self._session.can(permission):
            code = "session_locked" if self.is_locked() else "permission_denied"
            raise UserAuthError(code)

    def default_report_physician(self) -> str:
        """Return signed-in user's formatted name/title for report headers, or ``''``."""
        user = self._session.user
        if self._session.authenticated and user is not None:
            return user.report_physician_label
        return ""

    def list_users(self, *, include_inactive: bool = False) -> tuple[UserProfile, ...]:
        users = self._repository.load_state().users
        if include_inactive:
            return users
        return tuple(user for user in users if user.active)

    def user_display_map(self) -> dict[str, str]:
        """Map ``user_id -> display_name`` across active and deactivated accounts."""
        try:
            users = self._repository.load_state().users
        except UserAuthError:
            return {}
        return {user.user_id: user.display_name for user in users}

    def profile_dir_for(self, user_id: str) -> Path:
        return user_profile_dir(user_id, root=self._root)

    def preferences_ini_for(self, user_id: str) -> Path:
        return user_preferences_ini(user_id, root=self._root)

    def seed_user_preferences(self, user: UserProfile, base: UserPreferences | None = None) -> None:
        """Initialize a user's personal INI once so they inherit theme/language, not another user's identity."""
        if not self._scope_paths:
            return
        ini_path = self.preferences_ini_for(user.user_id)
        if ini_path.exists():
            return
        from echo_personal_tool.application.user_preferences import (
            default_user_preferences,
            save_user_preferences,
        )

        template = default_user_preferences()
        if base is not None:
            for attr in (
                "ui_scale_percent",
                "ui_font_size",
                "theme_mode",
                "accent_palette",
                "language",
                "reduce_motion",
                "native_window_frame",
                "measurement_persistence_enabled",
                "orthanc_cache_clear_on_exit",
                "anonymize_frames",
                "length_display_unit",
                "report_institution",
                "report_equipment",
                "study_profile",
            ):
                if hasattr(base, attr):
                    setattr(template, attr, getattr(base, attr))
        template.report_physician = user.report_physician_label
        self._apply_path_scope(user.user_id)
        save_user_preferences(template)

    # ── Bootstrap, login, switch, lock & disable ──────────────────────────────

    def bootstrap_first_admin(
        self,
        *,
        username: str,
        display_name: str,
        secret: str,
        secret_kind: SecretKind = SecretKind.PASSWORD,
        title: str = "",
        external_id: str = "",
        base_preferences: UserPreferences | None = None,
    ) -> UserSession:
        """Create the first workstation admin, activate multi-user mode and sign them in."""
        if self.has_users():
            raise UserAuthError("already_initialized")
        now = datetime.now(_UTC)
        profile = self._repository.create_user(
            username=username,
            display_name=display_name,
            role=UserRole.ADMIN,
            secret=secret,
            secret_kind=secret_kind,
            title=title,
            external_id=external_id,
            enable_multi_user=True,
            now=now,
        )
        state = self._repository.load_state()
        self.seed_user_preferences(profile, base_preferences)
        self._apply_path_scope(profile.user_id)
        self._session = UserSession(
            user=profile,
            multi_user_enabled=True,
            locked=False,
            started_at=now.isoformat(),
            auto_lock_minutes=state.auto_lock_minutes,
        )
        key_id = profile.signing_key.key_id if profile.signing_key else ""
        self._record_audit(
            AuditAction.USER_CREATED,
            actor_id=profile.user_id,
            target_id=profile.user_id,
            details={
                "role": profile.role.value,
                "secret_kind": profile.secret_kind.value,
                "target_username": profile.username,
                "key_id": key_id,
            },
        )
        self._record_audit(AuditAction.MULTI_USER_ENABLED, actor_id=profile.user_id)
        self._record_audit(AuditAction.LOGIN_SUCCESS, actor_id=profile.user_id)
        self._emit()
        return self._session

    def enable_multi_user(
        self,
        username: str,
        secret: str,
        *,
        base_preferences: UserPreferences | None = None,
    ) -> UserSession:
        """Re-enable multi-user mode by authenticating an existing active admin."""
        now = datetime.now(_UTC)
        try:
            profile = self._repository.authenticate(
                username,
                secret,
                enable_multi_user=True,
                require_role=UserRole.ADMIN,
                now=now,
            )
        except UserAuthError as exc:
            self._audit_failed_login(username, exc)
            raise
        state = self._repository.load_state()
        self.seed_user_preferences(profile, base_preferences)
        self._apply_path_scope(profile.user_id)
        self._session = UserSession(
            user=profile,
            multi_user_enabled=True,
            locked=False,
            started_at=now.isoformat(),
            auto_lock_minutes=state.auto_lock_minutes,
        )
        self._record_audit(AuditAction.MULTI_USER_ENABLED, actor_id=profile.user_id)
        self._record_audit(AuditAction.LOGIN_SUCCESS, actor_id=profile.user_id)
        self._emit()
        return self._session

    def disable_multi_user(self, admin_secret: str) -> UserSession:
        """Return to single-user mode after re-verifying the signed-in admin's secret."""
        self.require(Permission.MANAGE_USERS)
        admin = self._session.user
        if admin is None or admin.role is not UserRole.ADMIN:
            raise UserAuthError("permission_denied")
        self._repository.authenticate(
            admin.username,
            admin_secret,
            require_role=UserRole.ADMIN,
            record_login=False,
        )
        self._repository.set_multi_user_enabled(False)
        state = self._repository.load_state()
        self._apply_path_scope(None)
        self._session = UserSession(
            user=None,
            multi_user_enabled=False,
            locked=False,
            started_at="",
            auto_lock_minutes=state.auto_lock_minutes,
        )
        self._record_audit(AuditAction.MULTI_USER_DISABLED, actor_id=admin.user_id)
        self._emit()
        return self._session

    def login(
        self,
        username: str,
        secret: str,
        *,
        base_preferences: UserPreferences | None = None,
    ) -> UserSession:
        """Authenticate *username* and open or switch the active workstation session."""
        previous = self._session.user
        now = datetime.now(_UTC)
        try:
            profile = self._repository.authenticate(username, secret, now=now)
        except UserAuthError as exc:
            self._audit_failed_login(username, exc)
            raise
        state = self._repository.load_state()
        if not state.multi_user_enabled:
            raise UserAuthError("multi_user_disabled")
        self.seed_user_preferences(profile, base_preferences)
        self._apply_path_scope(profile.user_id)
        self._session = UserSession(
            user=profile,
            multi_user_enabled=True,
            locked=False,
            started_at=now.isoformat(),
            auto_lock_minutes=state.auto_lock_minutes,
        )
        if previous is not None and previous.user_id != profile.user_id:
            self._record_audit(
                AuditAction.SESSION_SWITCHED,
                actor_id=profile.user_id,
                target_id=previous.user_id,
            )
        else:
            self._record_audit(AuditAction.LOGIN_SUCCESS, actor_id=profile.user_id)
        self._emit()
        return self._session

    def lock_session(self, *, reason: str = "manual") -> UserSession:
        """Lock the active multi-user session without closing open studies."""
        if not self._session.multi_user_enabled or self._session.locked:
            return self._session
        actor = self._session.user.user_id if self._session.user is not None else "system"
        clean_reason = reason if reason in ("manual", "inactivity") else "manual"
        self._session = UserSession(
            user=self._session.user,
            multi_user_enabled=True,
            locked=True,
            started_at=self._session.started_at,
            auto_lock_minutes=self._session.auto_lock_minutes,
        )
        self._record_audit(
            AuditAction.SESSION_LOCKED,
            actor_id=actor,
            details={"reason": clean_reason},
        )
        self._emit()
        return self._session

    def unlock_session(self, secret: str) -> UserSession:
        """Unlock the currently locked session by verifying the same user's secret."""
        if not self._session.multi_user_enabled:
            return self._session
        user = self._session.user
        if user is None:
            raise UserAuthError("user_not_found")
        try:
            refreshed = self._repository.authenticate(user.username, secret)
        except UserAuthError as exc:
            self._audit_failed_login(user.username, exc, target_id=user.user_id)
            raise
        state = self._repository.load_state()
        self._apply_path_scope(refreshed.user_id)
        self._session = UserSession(
            user=refreshed,
            multi_user_enabled=True,
            locked=False,
            started_at=self._session.started_at or datetime.now(_UTC).isoformat(),
            auto_lock_minutes=state.auto_lock_minutes,
        )
        self._record_audit(AuditAction.SESSION_UNLOCKED, actor_id=refreshed.user_id)
        self._emit()
        return self._session

    def logout(self) -> UserSession:
        """Sign out the current user and leave the workstation locked."""
        if not self._session.multi_user_enabled:
            return self._session
        previous = self._session.user
        self._apply_path_scope(None)
        self._session = UserSession(
            user=None,
            multi_user_enabled=True,
            locked=True,
            started_at="",
            auto_lock_minutes=self._session.auto_lock_minutes,
        )
        if previous is not None:
            self._record_audit(AuditAction.LOGOUT, actor_id=previous.user_id)
        self._emit()
        return self._session

    def _audit_failed_login(self, username: str, exc: UserAuthError, *, target_id: str = "") -> None:
        safe_name = normalize_username(username)[:32]
        details: dict[str, DetailScalar] = {"reason": exc.code}
        if safe_name and all(32 <= ord(ch) < 127 for ch in safe_name):
            details["target_username"] = safe_name
        if exc.retry_after_seconds > 0:
            details["retry_after_seconds"] = exc.retry_after_seconds
        self._record_audit(
            AuditAction.LOGIN_FAILED,
            actor_id="anonymous",
            target_id=target_id,
            details=details,
        )

    # ── Account & credential management ───────────────────────────────────────

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        role: UserRole,
        secret: str,
        secret_kind: SecretKind = SecretKind.PASSWORD,
        title: str = "",
        external_id: str = "",
        base_preferences: UserPreferences | None = None,
    ) -> UserProfile:
        """Create a new workstation account (admin only)."""
        self.require(Permission.MANAGE_USERS)
        actor = self.active_user_id or "system"
        profile = self._repository.create_user(
            username=username,
            display_name=display_name,
            role=role,
            secret=secret,
            secret_kind=secret_kind,
            title=title,
            external_id=external_id,
        )
        if self._scope_paths and base_preferences is not None:
            # Seed the new user's profile INI, then restore the admin's active scope.
            current_id = self.active_user_id or None
            try:
                self.seed_user_preferences(profile, base_preferences)
            finally:
                self._apply_path_scope(current_id)
        key_id = profile.signing_key.key_id if profile.signing_key else ""
        self._record_audit(
            AuditAction.USER_CREATED,
            actor_id=actor,
            target_id=profile.user_id,
            details={
                "role": profile.role.value,
                "secret_kind": profile.secret_kind.value,
                "target_username": profile.username,
                "key_id": key_id,
            },
        )
        return profile

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str,
        title: str,
        external_id: str,
        role: UserRole,
    ) -> UserProfile:
        """Update profile fields and role (admin only, preserves at least one admin)."""
        self.require(Permission.MANAGE_USERS)
        actor = self.active_user_id or "system"
        updated = self._repository.update_user(
            user_id,
            display_name=display_name,
            title=title,
            external_id=external_id,
            role=role,
        )
        self._record_audit(
            AuditAction.USER_UPDATED,
            actor_id=actor,
            target_id=updated.user_id,
            details={"role": updated.role.value, "target_username": updated.username},
        )
        if self._session.user is not None and self._session.user.user_id == updated.user_id:
            self._session = UserSession(
                user=updated,
                multi_user_enabled=self._session.multi_user_enabled,
                locked=self._session.locked,
                started_at=self._session.started_at,
                auto_lock_minutes=self._session.auto_lock_minutes,
            )
            self._emit()
        return updated

    def set_user_active(self, user_id: str, *, active: bool) -> UserProfile:
        """Activate or deactivate an account (cannot deactivate self or last admin)."""
        self.require(Permission.MANAGE_USERS)
        if not active and self._session.user is not None and self._session.user.user_id == user_id:
            raise UserAuthError("cannot_deactivate_self")
        actor = self.active_user_id or "system"
        updated = self._repository.set_user_active(user_id, active=active)
        action = AuditAction.USER_REACTIVATED if active else AuditAction.USER_DEACTIVATED
        self._record_audit(
            action,
            actor_id=actor,
            target_id=updated.user_id,
            details={"target_username": updated.username},
        )
        return updated

    def change_own_secret(
        self,
        *,
        old_secret: str,
        new_secret: str,
        new_kind: SecretKind,
    ) -> UserProfile:
        """Change the signed-in user's password/PIN while keeping their Ed25519 key."""
        if not self._session.authenticated or self._session.user is None:
            raise UserAuthError("session_locked")
        updated = self._repository.change_own_secret(
            self._session.user.user_id,
            old_secret=old_secret,
            new_secret=new_secret,
            new_kind=new_kind,
        )
        self._session = UserSession(
            user=updated,
            multi_user_enabled=self._session.multi_user_enabled,
            locked=False,
            started_at=self._session.started_at,
            auto_lock_minutes=self._session.auto_lock_minutes,
        )
        self._record_audit(
            AuditAction.SECRET_CHANGED,
            actor_id=updated.user_id,
            target_id=updated.user_id,
            details={"secret_kind": new_kind.value},
        )
        self._emit()
        return updated

    def admin_reset_secret(
        self,
        user_id: str,
        *,
        new_secret: str,
        new_kind: SecretKind,
    ) -> UserProfile:
        """Reset a user's forgotten secret, rotating their Ed25519 key & archiving the old one."""
        self.require(Permission.MANAGE_USERS)
        actor = self.active_user_id or "system"
        updated, previous_key_id = self._repository.admin_reset_secret(
            user_id,
            new_secret=new_secret,
            new_kind=new_kind,
        )
        new_key_id = updated.signing_key.key_id if updated.signing_key else ""
        self._record_audit(
            AuditAction.SECRET_RESET,
            actor_id=actor,
            target_id=updated.user_id,
            details={
                "secret_kind": new_kind.value,
                "previous_key_id": previous_key_id,
                "key_id": new_key_id,
                "target_username": updated.username,
            },
        )
        if self._session.user is not None and self._session.user.user_id == updated.user_id:
            self._session = UserSession(
                user=updated,
                multi_user_enabled=self._session.multi_user_enabled,
                locked=self._session.locked,
                started_at=self._session.started_at,
                auto_lock_minutes=self._session.auto_lock_minutes,
            )
            self._emit()
        return updated

    def set_auto_lock_minutes(self, minutes: int) -> UserSession:
        """Update inactivity auto-lock timeout (admin only)."""
        self.require(Permission.MANAGE_USERS)
        clamped = self._repository.set_auto_lock_minutes(minutes)
        self._session = UserSession(
            user=self._session.user,
            multi_user_enabled=self._session.multi_user_enabled,
            locked=self._session.locked,
            started_at=self._session.started_at,
            auto_lock_minutes=clamped,
        )
        actor = self.active_user_id or "system"
        self._record_audit(
            AuditAction.SETTINGS_CHANGED,
            actor_id=actor,
            details={"auto_lock_minutes": clamped},
        )
        self._emit()
        return self._session

    # ── Local Ed25519 key operations (ready for Stage 2 protocol signing) ─────

    def sign_payload(self, *, secret: str, payload: bytes) -> tuple[SigningKeyPublic, bytes]:
        """Re-authenticate the current signer and sign *payload* with their Ed25519 key."""
        self.require(Permission.SIGN_REPORT)
        user = self._session.user
        if user is None:
            raise UserAuthError("session_locked")
        # Verify through repository so lockout counters also protect signing prompts.
        self._repository.authenticate(user.username, secret, record_login=False)
        envelope = self._repository.get_signing_envelope(user.user_id)
        signature = sign_with_user_key(envelope, user_id=user.user_id, secret=secret, payload=payload)
        return envelope.public_key(), signature

    def verify_user_signature(
        self,
        *,
        user_id: str,
        key_id: str,
        payload: bytes,
        signature: bytes,
    ) -> bool:
        """Verify *signature* against active or archived public keys (including deactivated users)."""
        users = self._repository.load_state().users
        profile = next((item for item in users if item.user_id == user_id), None)
        if profile is None:
            return False
        pub = profile.find_public_key(key_id)
        if pub is None:
            return False
        return verify_ed25519_signature(pub.public_key_b64, payload, signature)

    # ── Study & audit hooks ───────────────────────────────────────────────────

    def record_study_audit(
        self,
        action: AuditAction,
        *,
        study_key: str = "",
        details: Mapping[str, DetailScalar] | None = None,
    ) -> None:
        """Record a PHI-free study storage event when multi-user mode is active."""
        if not self._session.multi_user_enabled:
            return
        actor = self.active_user_id or (self._session.user.user_id if self._session.user else "system")
        self._record_audit(action, actor_id=actor, study_key=study_key, details=details)

    def recent_audit_entries(self, *, limit: int = 200) -> tuple[AuditEntry, ...]:
        self.require(Permission.VIEW_AUDIT)
        return self._audit.read_recent(limit=limit)

    def verify_audit_log(self) -> AuditVerificationResult:
        self.require(Permission.VIEW_AUDIT)
        return self._audit.verify()

    def export_audit_log(self, destination: Path) -> int:
        self.require(Permission.VIEW_AUDIT)
        return self._audit.export_copy(destination)
