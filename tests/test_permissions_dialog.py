"""Permission setup remains usable without notification delivery or TCC access."""
import os
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

from rekounts.permissions import PermissionState
from rekounts.ui.permissions_dialog import PermissionsDialog


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def dialog(app):
    states = [PermissionState(name, state, "guidance") for name, state in (
        ("Input Monitoring", False), ("Accessibility", True), ("Microphone", None))]
    widget = PermissionsDialog(probe=lambda: states, requester=Mock(return_value=True),
                               opener=Mock(return_value=True), frozen=False)
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_unknown_access_is_distinct_from_denial_and_does_not_request_automatically(dialog):
    assert dialog.needs_setup()
    assert dialog.status_labels["Microphone"].text() == "Not confirmed"
    assert dialog.status_labels["Input Monitoring"].text() == "Needs access"
    assert dialog.status_labels["Accessibility"].text() == "Allowed"
    assert not dialog.allow_buttons["Accessibility"].isEnabled()
    dialog._requester.assert_not_called()
    assert "terminal" in dialog.guidance.text()


def test_clicking_allow_requests_only_the_selected_permission(dialog):
    dialog.allow_buttons["Microphone"].click()
    dialog._requester.assert_called_once_with("Microphone")


def test_settings_button_opens_the_matching_privacy_pane(dialog):
    dialog.settings_buttons["Input Monitoring"].click()
    dialog._opener.assert_called_once_with(QtCore.QUrl(
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"))


def test_grant_changes_update_status_and_require_restart(dialog):
    for state in dialog.states:
        state.granted = True
    dialog.refresh()
    assert not dialog.needs_setup()
    assert all(label.text() == "Allowed" for label in dialog.status_labels.values())
    assert "Quit and reopen" in dialog.summary.text()


def test_polling_only_runs_while_setup_is_visible(dialog, app):
    assert not dialog._timer.isActive()
    dialog.show()
    app.processEvents()
    assert dialog._timer.isActive()
    dialog.close()
    assert not dialog._timer.isActive()


def test_failed_request_offers_manual_settings(dialog):
    dialog._requester.return_value = False
    dialog.request("Microphone")
    assert "Open Settings" in dialog.summary.text()
