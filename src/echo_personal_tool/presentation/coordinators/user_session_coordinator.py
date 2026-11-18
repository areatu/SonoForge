"""Main-window coordinator for local multi-user sessions, lock screen and RBAC.

Keeps authentication state, inactivity auto-lock timing, title-bar badge/menu
wiring and preference switching outside :class:`MainWindow` so the window
facade stays below its class-size ratchet and every line here is mypy-strict.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol
from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

from echo_personal_tool.application.composition import user_session_of
from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.preferences_contract import UserPreferences
from echo_personal_tool.application.user_preferences import load_user_preferences
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.models.user import Permission, UserSession
from echo_personal_tool.presentation.user_login_dialog import (
    ChangeSecretDialog,
    SessionLockDialog,
    UserLoginDialog,
    role_label,
)
from echo_personal_tool.presentation.user_management_dialog import UserManagementDialog

_INACTIVITY_POLL_MS = 15_000
_ACTIVITY_EVENTS = frozenset(
    {
        QEvent.Type.KeyPress,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
        QEvent.Type.TouchBegin,
    }
)


class UserBadgeHost(Protocol):
    """Subset of :class:`WindowTitleBar` used to render the signed-in user chip."""

    def set_user_badge(self, text: str, *, tooltip: str = "", menu: QMenu | None = None) -> None: ...


class UserSessionWindowPort(Protocol):
    """Narrow interface lent by :class:`MainWindow` to :class:`UserSessionCoordinator`."""

    def parent_widget(self) -> QWidget: ...
    def title_bar(self) -> UserBadgeHost: ...
    def preferences(self) -> UserPreferences: ...
    def apply_switched_user_preferences(self, preferences: UserPreferences) -> None: ...
    def flush_before_user_change(self) -> None: ...
    def show_status(self, text: str) -> None: ...
    def close_application(self) -> None: ...


class UserSessionCoordinator(QObject):
    """Runtime UI owner for local user switching, inactivity lock and RBAC prompts."""

    def __init__(
        self,
        service: UserSessionService | None,
        port: UserSessionWindowPort,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._port = port
        self._last_activity = time.monotonic()
        self._lock_dialog_open = False
        self._unsubscribe = service.subscribe(self._on_session_changed) if service is not None else (lambda: None)

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(_INACTIVITY_POLL_MS)
        self._idle_timer.timeout.connect(self._check_inactivity)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.sync_ui()

    @property
    def service(self) -> UserSessionService | None:
        return self._service

    def shutdown(self) -> None:
        """Stop timers and detach global event filter on window close."""
        self._idle_timer.stop()
        self._unsubscribe()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in _ACTIVITY_EVENTS:
            self._last_activity = time.monotonic()
        return super().eventFilter(watched, event)

    def record_activity(self) -> None:
        """Reset inactivity timer explicitly (also callable from tests)."""
        self._last_activity = time.monotonic()

    def idle_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._last_activity)

    def _check_inactivity(self) -> None:
        service = self._service
        if service is None or self._lock_dialog_open:
            return
        if not service.is_multi_user_enabled() or service.is_locked():
            return
        minutes = service.auto_lock_minutes()
        if minutes <= 0:
            return
        if self.idle_seconds() >= minutes * 60.0:
            self.lock_session(reason="inactivity")

    def _on_session_changed(self, _session: UserSession) -> None:
        self._last_activity = time.monotonic()
        self.sync_ui()

    def sync_ui(self) -> None:
        """Refresh the title-bar user chip and inactivity timer for the current session."""
        service = self._service
        bar = self._port.title_bar()
        if service is None or not service.is_multi_user_enabled():
            self._idle_timer.stop()
            bar.set_user_badge("", tooltip="", menu=None)
            return
        if service.auto_lock_minutes() > 0 and not service.is_locked():
            if not self._idle_timer.isActive():
                self._idle_timer.start()
        else:
            self._idle_timer.stop()
        user = service.current_user
        if user is None or service.is_locked():
            bar.set_user_badge(tr("auth.title_bar.locked"), tooltip=tr("auth.title_bar.locked"), menu=None)
            return
        role_text = role_label(user.role)
        label = tr("auth.title_bar.badge", name=user.display_name, role=role_text)
        tooltip = tr("auth.title_bar.tooltip", name=user.display_name, role=role_text)
        bar.set_user_badge(label, tooltip=tooltip, menu=self._build_user_menu())

    def _build_user_menu(self) -> QMenu:
        parent = self._port.parent_widget()
        menu = QMenu(parent)
        menu.setObjectName("activeUserMenu")
        menu.addAction(tr("app_menu.switch_user")).triggered.connect(self.switch_user)
        menu.addAction(tr("app_menu.lock_session")).triggered.connect(lambda: self.lock_session(reason="manual"))
        menu.addAction(tr("app_menu.change_secret")).triggered.connect(self.change_own_secret)
        menu.addSeparator()
        menu.addAction(tr("app_menu.users")).triggered.connect(self.open_users_dialog)
        return menu

    def populate_app_menu(self, menu: QMenu) -> None:
        """Add user/access actions into the application menu."""
        menu.addAction(tr("app_menu.users")).triggered.connect(self.open_users_dialog)
        if self._service is not None and self._service.is_multi_user_enabled():
            menu.addAction(tr("app_menu.switch_user")).triggered.connect(self.switch_user)
            menu.addAction(tr("app_menu.lock_session")).triggered.connect(lambda: self.lock_session(reason="manual"))

    def check_permission(self, permission: Permission) -> bool:
        """Return True if the active session grants *permission*; otherwise notify user."""
        service = self._service
        if service is None or service.can(permission):
            return True
        self._port.show_status(tr("auth.status.permission_denied"))
        return False

    def default_report_physician(self) -> str:
        """Fallback physician name for reports when personal preference is blank."""
        if self._service is None:
            return ""
        return self._service.default_report_physician()

    def active_user_id(self) -> str:
        if self._service is None:
            return ""
        return self._service.active_user_id

    def user_display_map(self) -> dict[str, str]:
        if self._service is None:
            return {}
        return self._service.user_display_map()

    def open_users_dialog(self) -> None:
        service = self._service
        if service is None:
            return
        previous_id = service.active_user_id
        was_enabled = service.is_multi_user_enabled()
        dialog = UserManagementDialog(
            service,
            self._port.parent_widget(),
            base_preferences=self._port.preferences(),
            on_switch_user=self.switch_user,
            on_lock_session=lambda: self.lock_session(reason="manual"),
        )
        dialog.exec()
        if (
            dialog.mode_changed
            or service.active_user_id != previous_id
            or service.is_multi_user_enabled() != was_enabled
        ):
            self._reload_active_profile_preferences()
            user = service.current_user
            if service.is_multi_user_enabled() and user is not None:
                self._port.show_status(tr("auth.manage.enabled_done", name=user.display_name))
            elif not service.is_multi_user_enabled():
                self._port.show_status(tr("auth.manage.disabled_done"))

    def change_own_secret(self) -> None:
        service = self._service
        if service is None or not service.is_multi_user_enabled():
            return
        dialog = ChangeSecretDialog(service, self._port.parent_widget())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._port.show_status(tr("auth.change_secret.done"))

    def switch_user(self) -> None:
        service = self._service
        if service is None or not service.is_multi_user_enabled():
            return
        previous_id = service.active_user_id
        self._port.flush_before_user_change()
        dialog = UserLoginDialog(
            service,
            self._port.parent_widget(),
            switch_mode=True,
            base_preferences=self._port.preferences(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and service.active_user_id != previous_id:
            self._reload_active_profile_preferences()
            self._announce_active_user()

    def lock_session(self, *, reason: str = "manual") -> None:
        service = self._service
        if service is None or not service.is_multi_user_enabled() or self._lock_dialog_open:
            return
        previous_id = service.active_user_id
        self._port.flush_before_user_change()
        service.lock_session(reason=reason)
        self._lock_dialog_open = True
        try:
            dialog = SessionLockDialog(
                service,
                self._port.parent_widget(),
                base_preferences=self._port.preferences(),
            )
            dialog.exec()
        finally:
            self._lock_dialog_open = False
        self._last_activity = time.monotonic()
        if dialog.outcome == SessionLockDialog.OUTCOME_QUIT:
            self._port.close_application()
            return
        if dialog.outcome == SessionLockDialog.OUTCOME_SWITCHED and service.active_user_id != previous_id:
            self._reload_active_profile_preferences()
            self._announce_active_user()
            return
        self.sync_ui()

    def _reload_active_profile_preferences(self) -> None:
        self._port.apply_switched_user_preferences(load_user_preferences())
        self.sync_ui()

    def _announce_active_user(self) -> None:
        service = self._service
        if service is None or service.current_user is None:
            return
        user = service.current_user
        if not user.can(Permission.EDIT_MEASUREMENTS):
            self._port.show_status(tr("auth.status.read_only"))
            return
        self._port.show_status(tr("auth.status.switched", name=user.display_name, role=role_label(user.role)))


class _CallbackWindowPort:
    """Port backed by late-bound callables so window facades add zero fields."""

    def __init__(
        self,
        *,
        parent_widget: Callable[[], QWidget],
        title_bar: Callable[[], UserBadgeHost],
        preferences: Callable[[], UserPreferences],
        apply_preferences: Callable[[UserPreferences], None],
        flush: Callable[[], None],
        show_status: Callable[[str], None],
        close_app: Callable[[], None],
    ) -> None:
        self._parent = parent_widget
        self._title_bar = title_bar
        self._preferences = preferences
        self._apply = apply_preferences
        self._flush = flush
        self._status = show_status
        self._close = close_app

    def parent_widget(self) -> QWidget:
        return self._parent()

    def title_bar(self) -> UserBadgeHost:
        return self._title_bar()

    def preferences(self) -> UserPreferences:
        return self._preferences()

    def apply_switched_user_preferences(self, preferences: UserPreferences) -> None:
        self._apply(preferences)

    def flush_before_user_change(self) -> None:
        self._flush()

    def show_status(self, text: str) -> None:
        self._status(text)

    def close_application(self) -> None:
        self._close()


_WINDOW_COORDINATORS: WeakKeyDictionary[object, UserSessionCoordinator] = WeakKeyDictionary()


def attach_window_user_session(
    window: QWidget,
    *,
    controller: object,
    title_bar: Callable[[], UserBadgeHost],
    preferences: Callable[[], UserPreferences],
    apply_preferences: Callable[[UserPreferences], None],
    flush: Callable[[], None],
    show_status: Callable[[str], None],
) -> UserSessionCoordinator:
    """Create and bind a :class:`UserSessionCoordinator` to *window*."""
    service = user_session_of(controller)
    port = _CallbackWindowPort(
        parent_widget=lambda: window,
        title_bar=title_bar,
        preferences=preferences,
        apply_preferences=apply_preferences,
        flush=flush,
        show_status=show_status,
        close_app=lambda: _ignore_bool(window.close()),
    )
    coordinator = UserSessionCoordinator(service, port, parent=window)
    _WINDOW_COORDINATORS[window] = coordinator
    return coordinator


def _ignore_bool(_value: bool) -> None:
    return None


def user_session_coordinator_of(window: object) -> UserSessionCoordinator | None:
    """Return the :class:`UserSessionCoordinator` attached to *window*, if any."""
    try:
        return _WINDOW_COORDINATORS.get(window)
    except TypeError:
        return None


def open_window_users(window: object) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.open_users_dialog()


def switch_window_user(window: object) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.switch_user()


def lock_window_session(window: object) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.lock_session(reason="manual")


def populate_window_user_menu(window: object, menu: QMenu) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.populate_app_menu(menu)
    else:
        menu.addAction(tr("app_menu.users")).triggered.connect(lambda: open_window_users(window))


def sync_window_user_session_ui(window: object) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.sync_ui()


def shutdown_window_user_session(window: object) -> None:
    coord = user_session_coordinator_of(window)
    if coord is not None:
        coord.shutdown()


def check_window_permission(window: object, permission: Permission) -> bool:
    coord = user_session_coordinator_of(window)
    return True if coord is None else coord.check_permission(permission)


class MainWindowUserHost(Protocol):
    """Attribute surface of :class:`MainWindow` needed for one-call session binding."""

    _controller: object
    _title_bar: UserBadgeHost
    _user_preferences: UserPreferences

    def _apply_user_preferences(self, preferences: UserPreferences) -> None: ...
    def _build_app_menu(self) -> QMenu: ...
    def _refresh_start_page_recents(self) -> None: ...
    def _show_status(self, text: str) -> None: ...
    def close(self) -> bool: ...


def bind_main_window_user_session(window: MainWindowUserHost, widget: QWidget) -> UserSessionCoordinator:
    """Attach user-session handling and refresh the title-bar app menu."""

    def _apply_and_refresh(prefs: UserPreferences) -> None:
        recent_store = getattr(window, "_recent_store", None)
        reload_recent = getattr(recent_store, "reload", None)
        if callable(reload_recent):
            reload_recent()
        start_page = getattr(window, "_start_page", None)
        refresh_places = getattr(start_page, "refresh_recent_places", None)
        if callable(refresh_places):
            refresh_places()
        window._apply_user_preferences(prefs)
        report_coord = getattr(window, "report_coordinator", None)
        report_page = getattr(report_coord, "_page", None)
        phrases_panel = getattr(report_page, "phrases", None)
        if phrases_panel is not None:
            store_obj = getattr(phrases_panel, "store", None)
            reload_store = getattr(store_obj, "reload", None)
            if callable(reload_store):
                reload_store()
            reload_phrases = getattr(phrases_panel, "reload_text", None)
            if callable(reload_phrases):
                reload_phrases()
        refresh_report = getattr(report_coord, "request_refresh", None)
        if callable(refresh_report):
            refresh_report()
        setter = getattr(window._title_bar, "set_app_menu", None)
        if callable(setter):
            setter(window._build_app_menu())
        window._refresh_start_page_recents()

    def _flush() -> None:
        persistence = getattr(window._controller, "measurement_persistence", None)
        save_pending = getattr(persistence, "save_pending", None)
        if callable(save_pending):
            save_pending()
        flush_io = getattr(persistence, "flush", None)
        if callable(flush_io):
            flush_io(1500)

    coord = attach_window_user_session(
        widget,
        controller=window._controller,
        title_bar=lambda: window._title_bar,
        preferences=lambda: window._user_preferences,
        apply_preferences=_apply_and_refresh,
        flush=_flush,
        show_status=window._show_status,
    )
    setter = getattr(window._title_bar, "set_app_menu", None)
    if callable(setter):
        setter(window._build_app_menu())
    return coord
