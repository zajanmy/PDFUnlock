import os
import time

import pikepdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMessageBox

from pdfunlock.gui import MainWindow, create_application


@pytest.fixture(scope="module")
def app():
    return create_application([])


@pytest.fixture
def window(app):
    widget = MainWindow()
    yield widget
    if widget.worker:
        widget.worker.cancel.set()
        wait_for_batch(app, widget)
    widget.close()
    widget.deleteLater()
    app.processEvents()


def wait_for_batch(app, window):
    deadline = time.monotonic() + 15
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not window.busy, "Batch worker did not finish"


def drop_paths(target, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(target, enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(target, drop)
    assert drop.isAccepted()


def test_drop_multiple_and_filter_duplicates(window, plain_pdf, user_pw_pdf, tmp_path):
    text = tmp_path / "no.txt"
    text.write_text("no")
    drop_paths(window, [plain_pdf, user_pw_pdf, plain_pdf, text, tmp_path])
    assert window.paths == [plain_pdf, user_pw_pdf]
    assert window.table.rowCount() == 2
    assert "忽略 3" in window.summary.text()
    # URL drops on the password editor must import files, not paste paths.
    drop_paths(window.passwords.viewport(), [plain_pdf])
    assert window.passwords.toPlainText() == ""


def test_batch_retry_only_failed_items(app, window, plain_pdf, user_pw_pdf, tmp_path):
    window.add_files([str(plain_pdf), str(user_pw_pdf)])
    window.output_dir.setText(str(tmp_path / "export"))
    window.password.setText("wrong")
    window.start_batch()
    assert not window.output_dir.isEnabled()
    wait_for_batch(app, window)
    assert window.results[0].status == "success"
    assert window.results[1].status == "failed"
    assert window.start_button.isEnabled()
    first = window.results[0].output
    window.multiple.setChecked(True)
    window.passwords.setPlainText("wrong\nsecret42")
    window.start_batch()
    wait_for_batch(app, window)
    assert window.results[1].status == "success"
    assert window.results[0].output == first
    assert len(list((tmp_path / "export").iterdir())) == 2
    assert not window.start_button.isEnabled()
    with pikepdf.open(window.results[1].output) as pdf:
        assert not pdf.is_encrypted


def test_empty_destination_is_rejected(window, plain_pdf, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.add_files([str(plain_pdf)])
    window.output_dir.clear()
    window.start_batch()
    assert not window.busy
    assert messages


def test_close_during_batch_waits_for_worker(app, window, plain_pdf, tmp_path, monkeypatch):
    from pdfunlock import gui
    original = gui.decrypt_file

    def slow_decrypt(*args):
        time.sleep(0.05)
        return original(*args)

    monkeypatch.setattr(gui, "decrypt_file", slow_decrypt)
    window.add_files([str(plain_pdf)])
    window.output_dir.setText(str(tmp_path / "out"))
    window.start_batch()
    window.close()
    assert window.close_pending
    wait_for_batch(app, window)
    assert window.worker is None
    assert window.results[0].status == "cancelled"


def test_remove_and_clear(window, plain_pdf, user_pw_pdf):
    window.add_files([str(plain_pdf), str(user_pw_pdf)])
    window.table.selectRow(0)
    window.remove_selected()
    assert window.paths == [user_pw_pdf]
    window.clear_files()
    assert not window.paths
    assert not window.start_button.isEnabled()
