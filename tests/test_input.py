from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

import protocol as P
from controller.view import RemoteView
from agent.input_inject import InputInjector


def make_view():
    messages = []
    view = RemoteView(SimpleNamespace(send_json=messages.append))
    view._draw = QRectF(0, 0, 640, 400)
    return view, messages


def key_event(kind, key, text="", modifiers=Qt.NoModifier):
    return QKeyEvent(kind, key, modifiers, text)


def test_ctrl_c_sends_letter_even_when_qt_text_is_control_character(app):
    view, messages = make_view()
    view.keyPressEvent(key_event(QEvent.KeyPress, Qt.Key_C, "\x03", Qt.ControlModifier))
    view.keyReleaseEvent(key_event(QEvent.KeyRelease, Qt.Key_C, "\x03", Qt.ControlModifier))
    assert messages == [P.key(P.K_DOWN, "c"), P.key(P.K_UP, "c")]


def test_release_uses_same_character_as_press_when_shift_changes(app):
    view, messages = make_view()
    view.keyPressEvent(key_event(QEvent.KeyPress, Qt.Key_A, "A", Qt.ShiftModifier))
    view.keyReleaseEvent(key_event(QEvent.KeyRelease, Qt.Key_A, "a"))
    assert messages == [P.key(P.K_DOWN, "A"), P.key(P.K_UP, "A")]


def test_tab_is_sent_to_remote_instead_of_moving_focus(app):
    view, messages = make_view()
    QApplication.sendEvent(view, key_event(QEvent.KeyPress, Qt.Key_Tab, "\t"))
    QApplication.sendEvent(view, key_event(QEvent.KeyRelease, Qt.Key_Tab, "\t"))
    assert messages == [P.key(P.K_DOWN, "tab"), P.key(P.K_UP, "tab")]


def test_focus_loss_releases_remote_keys(app):
    view, messages = make_view()
    view.keyPressEvent(key_event(QEvent.KeyPress, Qt.Key_Control))
    view.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert messages == [P.key(P.K_DOWN, "ctrl"), P.key(P.K_UP, "ctrl")]


def test_mouse_release_outside_image_does_not_leave_drag_held(app):
    view, messages = make_view()
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(320, 200),
                                    QPointF(320, 200), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(700, 450),
                                      QPointF(700, 450), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert [m["action"] for m in messages] == [P.M_DOWN, P.M_UP]
    assert messages[-1]["x"] == 1.0
    assert messages[-1]["y"] == 1.0


def test_view_only_mode_does_not_send_input(app):
    view, messages = make_view()
    view.set_control_enabled(False)
    view.keyPressEvent(key_event(QEvent.KeyPress, Qt.Key_A, "a"))
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(320, 200),
                                    QPointF(320, 200), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert messages == []


def test_input_coordinates_stay_within_last_screen_pixel():
    injector = InputInjector(-1920, 0, 1920, 1080)
    assert injector._to_pixels(1.0, 1.0) == (-1, 1079)
    assert injector._to_pixels(-0.5, 2) == (-1920, 1079)


def test_agent_releases_pressed_inputs_when_session_ends():
    injector = InputInjector(0, 0, 1920, 1080)
    injector.keyboard = Mock()
    injector.mouse = Mock()
    injector.handle_key(P.key(P.K_DOWN, "ctrl"))
    injector.handle_mouse(P.mouse(P.M_DOWN, 0.5, 0.5))
    injector.release_all()
    injector.keyboard.release.assert_called_once()
    injector.mouse.release.assert_called_once()
    injector.release_all()
    injector.keyboard.release.assert_called_once()


def test_agent_clamps_and_positions_mouse_for_scroll():
    injector = InputInjector(0, 0, 100, 100)
    injector.mouse = Mock()
    injector.handle_mouse(P.mouse(P.M_SCROLL, 0.5, 0.5, dy=1))
    assert injector.mouse.position == (50, 50)
    injector.mouse.scroll.assert_called_once_with(0, 1)
