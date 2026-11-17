"""Opt-in packaged-app smoke test: PDF engine + Qt window + background worker.

Run PDFUnlock.exe --self-test <report-directory>. Only generated fixtures are
processed. No user documents are read. Used by the Windows build script and CI.
"""

import json
import sys
import time
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory

import pikepdf
from PySide6.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, Qt, QUrl, qVersion
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from pdfunlock.gui import MainWindow, create_application


def main(report_directory):
    report_dir = Path(report_directory).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "qt": qVersion(), "pikepdf": pikepdf.__version__}
    window = None
    try:
        app = create_application([])
        with TemporaryDirectory(prefix="pdfunlock-check-") as temp:
            root = Path(temp)
            sources = []
            for name, password, owner in [("年度报告.pdf", "report2026", "owner"),
                                          ("合同扫描件.pdf", "private-user", "contract"),
                                          ("发票汇总.pdf", "", "owner"),
                                          ("密码待确认.pdf", "unknown", "owner")]:
                path = root / name
                with pikepdf.new() as pdf:
                    pdf.add_blank_page(page_size=(300, 400))
                    pdf.docinfo["/Title"] = name
                    pdf.save(path, encryption=pikepdf.Encryption(user=password, owner=owner))
                sources.append(path)
            original_bytes = [p.read_bytes() for p in sources]
            window = MainWindow()
            assert window.windowTitle() == "PDFUnlock · PDF 批量解密"
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            window.show()
            app.processEvents()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path)) for path in sources])
            enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QCoreApplication.sendEvent(window, enter)
            drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QCoreApplication.sendEvent(window, drop)
            assert enter.isAccepted() and drop.isAccepted() and len(window.paths) == 4
            window.multiple.setChecked(True)
            window.passwords.setPlainText("report2026\ncontract")
            output = root / "导出 目录"
            window.output_dir.setText(str(output))
            window.start_batch()
            deadline = time.monotonic() + 30
            while window.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()
            assert not window.busy, "GUI batch timed out"
            assert [r.status for r in window.results.values()] == ["success", "success", "success", "failed"]
            for result in window.results.values():
                if result.output:
                    with pikepdf.open(result.output) as pdf:
                        assert not pdf.is_encrypted and len(pdf.pages) == 1
                        assert str(pdf.docinfo["/Title"]) == result.source.name
            assert original_bytes == [p.read_bytes() for p in sources]
            # Grab the real Qt widget tree; no desktop screenshot or user data.
            window.output_dir.setText(r"D:\Documents\已解密 PDF")
            window.output_dir.setCursorPosition(0)
            window.ensurePolished()
            app.processEvents()
            window.grab().save(str(report_dir / "ui-preview.png"))
            report.update(ok=True, window_title=window.windowTitle(), tested=["Qt window and native plugin", "multi-file drop", "worker thread",
                                         "user and owner passwords", "multiple passwords", "wrong password isolation", "unencrypted outputs",
                                         "page count and metadata", "unchanged source files"])
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if window is not None:
            if window.worker:
                window.worker.cancel.set()
                window.worker.wait()
            window.close()
        (report_dir / "self-test.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
