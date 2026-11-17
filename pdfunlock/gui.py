"""Native, offline desktop interface for known-password PDF batches."""

import os
import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, QUrl, Signal, Slot, QStandardPaths
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from pdfunlock.batch import FileResult, decrypt_file, parse_passwords, prepare_output_directory


STYLE = """
QMainWindow, QWidget#root { background: #f4f7fb; }
QWidget { color: #24354b; font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 20px; font-weight: 700; color: #132d46; }
QLabel#title { font-size: 28px; font-weight: 700; color: #142b43; }
QLabel#subtitle, QLabel#muted { color: #738398; }
QLabel#section { font-size: 15px; font-weight: 700; color: #1b344c; }
QLabel#eyebrow { color: #009b8a; font-size: 11px; font-weight: 700; }
QLabel#local { color: #138777; background: #e1f4ed; border-radius: 12px; padding: 6px 12px; font-size: 11px; }
QFrame#card { background: white; border: 1px solid #e3e9f1; border-radius: 14px; }
QFrame#drop { background: #f4fbfa; border: 2px dashed #aad5ce; border-radius: 12px; }
QFrame#drop[hover="true"] { background: #def5ee; border-color: #009b8a; }
QLabel#dropTitle { font-size: 18px; font-weight: 700; }
QLabel#dropIcon { font-size: 30px; color: #009b8a; }
QPushButton { background: white; border: 1px solid #dce4ed; border-radius: 7px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #edf7f5; border-color: #8dbfb5; }
QPushButton:pressed { background: #dbeee9; }
QPushButton:disabled { color: #a0adbc; background: #f4f6f9; border-color: #e6ebf1; }
QPushButton#primary { background: #008d7f; color: white; border: none; padding: 12px 25px; font-size: 14px; }
QPushButton#primary:hover { background: #007e71; }
QPushButton#primary:disabled { background: #c2d6d3; color: #f5f9f8; }
QPushButton#quiet { border: none; color: #728297; background: transparent; padding: 5px 8px; }
QPushButton#quiet:hover { color: #008d7f; background: #eef8f5; }
QLineEdit, QPlainTextEdit { background: #fafbfd; border: 1px solid #dce4ed; border-radius: 7px; padding: 10px; selection-background-color: #b5e8df; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #009b8a; }
QLineEdit:disabled, QPlainTextEdit:disabled { color: #8b98a7; background: #f4f6f8; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QTableWidget { background: white; border: none; gridline-color: #eff2f7; selection-background-color: #e9f6f2; selection-color: #24354b; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #edf1f6; }
QHeaderView::section { background: #f7f9fc; color: #8a97a7; border: none; padding: 10px; font-size: 11px; }
QProgressBar { background: #e8edf3; border: none; border-radius: 4px; min-height: 7px; max-height: 7px; }
QProgressBar::chunk { background: #009b8a; border-radius: 4px; }
QToolTip { background: #20344c; color: white; border: none; padding: 6px; }
"""


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#008d7f"))
    painter.drawRoundedRect(1, 1, 62, 62, 17, 17)
    painter.setPen(QPen(QColor("white"), 3.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(19, 28, 27, 22, 4, 4)
    painter.drawArc(26, 12, 18, 25, 0, 180 * 16)
    painter.drawLine(26, 24, 26, 28)
    painter.drawLine(32, 36, 32, 42)
    painter.end()
    return QIcon(pixmap)


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class DropFilter(QObject):
    """Accept Explorer file drops on the entire window, including child controls."""

    files_dropped = Signal(list)

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if not isinstance(obj, QWidget) or obj.window() is not self.window:
            return False
        kind = event.type()
        if kind not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.DragLeave, QEvent.Type.Drop):
            return False
        if kind == QEvent.Type.DragLeave:
            self.window.set_drop_hover(False)
            return False
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if self.window.busy or not paths:
                event.ignore()
                return True
            event.acceptProposedAction()
            if kind == QEvent.Type.Drop:
                self.window.set_drop_hover(False)
                self.files_dropped.emit(paths)
            else:
                self.window.set_drop_hover(True)
            return True
        return False


class BatchWorker(QThread):
    started_file = Signal(int)
    result_ready = Signal(int, object)

    def __init__(self, jobs, passwords, output_dir, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.passwords = passwords
        self.output_dir = output_dir
        self.cancel = Event()

    def run(self):
        try:
            for row, path in self.jobs:
                if not self.cancel.is_set():
                    self.started_file.emit(row)
                result = decrypt_file(path, self.passwords, self.output_dir, self.cancel)
                self.result_ready.emit(row, result)
        finally:
            self.passwords = []


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.paths: list[Path] = []
        self.results: dict[int, FileResult] = {}
        self.worker = None
        self.busy = False
        self.close_pending = False
        self.completed = 0
        self.batch_total = 0
        self.last_output_dir = None
        self.setWindowTitle("PDFUnlock · PDF 批量解密")
        self.setWindowIcon(app_icon())
        self.resize(1160, 820)
        self.setMinimumSize(1000, 760)
        self.setAcceptDrops(True)
        self._build_ui()
        self.drop_filter = DropFilter(self)
        self.drop_filter.files_dropped.connect(self.add_files)
        QApplication.instance().installEventFilter(self.drop_filter)
        self._update_queue()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 26, 32, 22)
        layout.setSpacing(20)

        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(QSize(38, 38)))
        brand.addWidget(icon)
        brand.addSpacing(3)
        brand.addWidget(label("PDFUnlock", "brand"))
        brand.addStretch()
        brand.addWidget(label("●  离线运行 · 文件留在本机", "local"))
        layout.addLayout(brand)

        intro = QVBoxLayout()
        intro.setSpacing(7)
        intro.addWidget(label("让 PDF 自由打开", "title"))
        intro.addWidget(label("添加文件，使用已知密码批量解密，将无密码副本导出到指定文件夹。", "subtitle"))
        layout.addLayout(intro)

        columns = QHBoxLayout()
        columns.setSpacing(20)
        file_card = QFrame()
        file_card.setObjectName("card")
        files = QVBoxLayout(file_card)
        files.setContentsMargins(20, 20, 20, 16)
        files.setSpacing(15)
        row = QHBoxLayout()
        row.addWidget(label("待处理文件", "section"))
        self.count_label = label("0 个文件", "muted")
        row.addWidget(self.count_label)
        row.addStretch()
        self.remove_button = QPushButton("移除选中")
        self.remove_button.setObjectName("quiet")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("quiet")
        self.clear_button.clicked.connect(self.clear_files)
        row.addWidget(self.clear_button)
        files.addLayout(row)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("drop")
        drop = QVBoxLayout(self.drop_zone)
        drop.setContentsMargins(18, 18, 18, 18)
        drop.setSpacing(7)
        drop.addWidget(label("↓", "dropIcon"), alignment=Qt.AlignmentFlag.AlignCenter)
        drop.addWidget(label("拖拽 PDF 文件到这里", "dropTitle"), alignment=Qt.AlignmentFlag.AlignCenter)
        drop.addWidget(label("支持一次添加多个文件，也可以", "muted"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.add_button = QPushButton("＋  选择 PDF 文件")
        self.add_button.clicked.connect(self.choose_files)
        drop.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignCenter)
        files.addWidget(self.drop_zone)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件名称", "大小", "处理状态"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 75)
        self.table.setColumnWidth(2, 180)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.cellDoubleClicked.connect(self.open_result)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_layout.addWidget(label("文件列表会显示在这里", "muted"), alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(label("导入后可查看每个文件的处理状态", "muted"), alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        self.stack.addWidget(empty)
        self.stack.addWidget(self.table)
        files.addWidget(self.stack, 1)
        self.file_hint = label("原文件始终保留 · 同名文件自动编号 · 双击成功项打开副本", "muted", True)
        files.addWidget(self.file_hint)
        columns.addWidget(file_card, 1)

        settings_card = QFrame()
        settings_card.setObjectName("card")
        settings_card.setFixedWidth(312)
        settings = QVBoxLayout(settings_card)
        settings.setContentsMargins(22, 20, 22, 20)
        settings.setSpacing(8)
        settings.addWidget(label("01  /  PASSWORD", "eyebrow"))
        settings.addWidget(label("输入已知密码", "section"))
        settings.addWidget(label("每个文件依次尝试这些密码。", "muted"))
        single = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setPlaceholderText("输入 PDF 打开密码")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("已知 PDF 密码")
        self.show_password = QPushButton("显示")
        self.show_password.setCheckable(True)
        self.show_password.setObjectName("quiet")
        self.show_password.toggled.connect(self._show_password)
        single.addWidget(self.password)
        single.addWidget(self.show_password)
        self.single_container = QWidget()
        self.single_container.setLayout(single)
        single.setContentsMargins(0, 0, 0, 0)
        settings.addWidget(self.single_container)
        self.multiple = QCheckBox("尝试多个已知密码")
        self.multiple.toggled.connect(self._toggle_multiple)
        settings.addWidget(self.multiple)
        self.passwords = QPlainTextEdit()
        self.passwords.setPlaceholderText("每行一个密码（明文显示）\n例如：\npassword123\nreport2026")
        self.passwords.setAccessibleName("多个已知密码，每行一个，明文显示")
        self.passwords.setFixedHeight(90)
        self.passwords.hide()
        settings.addWidget(self.passwords)
        settings.addWidget(label("留空可处理无打开密码的文件。\n密码仅在内存中使用，不会保存。", "muted", True))
        settings.addSpacing(4)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #e8edf3;")
        settings.addWidget(separator)
        settings.addSpacing(2)
        settings.addWidget(label("02  /  EXPORT", "eyebrow"))
        settings.addWidget(label("选择导出目录", "section"))
        self.output_dir = QLineEdit()
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        self.output_dir.setText(str(Path(documents or Path.home()) / "PDFUnlock"))
        self.output_dir.setAccessibleName("导出目录")
        self.output_dir.textChanged.connect(self.output_dir.setToolTip)
        self.output_dir.setToolTip(self.output_dir.text())
        self.output_dir.setCursorPosition(0)
        settings.addWidget(self.output_dir)
        self.browse_button = QPushButton("选择文件夹…")
        self.browse_button.clicked.connect(self.choose_directory)
        settings.addWidget(self.browse_button)
        settings.addWidget(label("导出为「原名_已解密.pdf」\n输出文件无需密码即可打开。", "muted", True))
        settings.addStretch()
        self.open_folder_button = QPushButton("打开导出目录  ↗")
        self.open_folder_button.clicked.connect(self.open_output_directory)
        self.open_folder_button.setEnabled(False)
        settings.addWidget(self.open_folder_button)
        columns.addWidget(settings_card)
        layout.addLayout(columns, 1)

        footer = QHBoxLayout()
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(10)
        self.summary = label("准备就绪，请添加 PDF 文件", "muted")
        self.summary.setWordWrap(True)
        progress_layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        progress_layout.addWidget(self.progress)
        footer.addLayout(progress_layout, 1)
        footer.addSpacing(24)
        self.cancel_button = QPushButton("取消处理")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_batch)
        footer.addWidget(self.cancel_button)
        self.start_button = QPushButton("开始批量解密  →")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_batch)
        footer.addWidget(self.start_button)
        layout.addLayout(footer)

    def set_drop_hover(self, value):
        self.drop_zone.setProperty("hover", value)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def _show_password(self, checked):
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.show_password.setText("隐藏" if checked else "显示")

    def _toggle_multiple(self, checked):
        if checked and not self.passwords.toPlainText() and self.password.text():
            self.passwords.setPlainText(self.password.text())
        self.single_container.setVisible(not checked)
        self.passwords.setVisible(checked)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加 PDF 文件", "", "PDF 文件 (*.pdf *.PDF)")
        self.add_files(paths)

    @Slot(list)
    def add_files(self, paths):
        if self.busy:
            return
        existing = {os.path.normcase(str(p)) for p in self.paths}
        added = ignored = 0
        for value in paths:
            try:
                path = Path(value).expanduser().resolve()
                key = os.path.normcase(str(path))
                if path.suffix.lower() != ".pdf" or not path.is_file() or key in existing:
                    ignored += 1
                    continue
                size = path.stat().st_size
            except (OSError, ValueError):
                ignored += 1
                continue
            existing.add(key)
            row = len(self.paths)
            self.paths.append(path)
            self.table.insertRow(row)
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.table.setItem(row, 0, item)
            size_text = f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{max(1, size / 1024):.0f} KB"
            self.table.setItem(row, 1, QTableWidgetItem(size_text))
            self._set_status(row, "等待处理", "#8392a5")
            added += 1
        self._update_queue()
        if added or ignored:
            self.summary.setText(f"已添加 {added} 个文件，共 {len(self.paths)} 个" + (f"；已忽略 {ignored} 个重复或非 PDF 项" if ignored else ""))

    def _update_queue(self):
        self.count_label.setText(f"{len(self.paths)} 个文件")
        self.stack.setCurrentIndex(1 if self.paths else 0)
        self._update_actions()

    def _update_actions(self):
        pending = any(i not in self.results or self.results[i].status != "success" for i in range(len(self.paths)))
        self.start_button.setEnabled(not self.busy and pending)
        self.clear_button.setEnabled(not self.busy and bool(self.paths))
        self.remove_button.setEnabled(not self.busy and bool(self.table.selectionModel().selectedRows()))

    def remove_selected(self):
        if self.busy:
            return
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        kept_results = {}
        new_row = 0
        for old_row in range(len(self.paths)):
            if old_row not in rows:
                if old_row in self.results:
                    kept_results[new_row] = self.results[old_row]
                new_row += 1
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
            self.paths.pop(row)
        self.results = kept_results
        self._update_queue()
        self.summary.setText(f"已保留 {len(self.paths)} 个文件")

    def clear_files(self):
        if self.busy:
            return
        self.table.setRowCount(0)
        self.paths.clear()
        self.results.clear()
        self.progress.setValue(0)
        self.summary.setText("准备就绪，请添加 PDF 文件")
        self._update_queue()

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择导出目录", self.output_dir.text())
        if path:
            self.output_dir.setText(path)
            self.output_dir.setCursorPosition(0)

    def _set_status(self, row, text, color, detail=""):
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))
        item.setToolTip(detail or text)
        self.table.setItem(row, 2, item)

    def start_batch(self):
        if self.busy:
            return
        jobs = [(i, path) for i, path in enumerate(self.paths)
                if i not in self.results or self.results[i].status != "success"]
        if not jobs:
            return
        directory = self.output_dir.text().strip()
        if not directory:
            QMessageBox.warning(self, "请选择导出目录", "请先选择或输入一个导出文件夹。")
            return
        try:
            output_dir = prepare_output_directory(directory)
        except (OSError, ValueError):
            QMessageBox.warning(self, "无法使用导出目录", "请检查目录路径、写入权限和磁盘空间。")
            return
        passwords = parse_passwords(self.passwords.toPlainText()) if self.multiple.isChecked() else [self.password.text()]
        for row, _ in jobs:
            self.results.pop(row, None)
            self._set_status(row, "等待处理", "#8392a5")
        self.last_output_dir = output_dir
        self.open_folder_button.setEnabled(True)
        self.batch_total = len(jobs)
        self.completed = 0
        self.progress.setRange(0, self.batch_total)
        self.progress.setValue(0)
        self._set_busy(True)
        self.summary.setText(f"正在处理 0 / {self.batch_total} 个文件…")
        self.worker = BatchWorker(jobs, passwords, output_dir, self)
        self.worker.started_file.connect(self._on_started)
        self.worker.result_ready.connect(self._on_result)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _set_busy(self, busy):
        self.busy = busy
        for widget in (self.add_button, self.password, self.show_password, self.passwords,
                       self.multiple, self.output_dir, self.browse_button):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.start_button.setText("正在解密…" if busy else "开始批量解密  →")
        self._update_actions()

    @Slot(int)
    def _on_started(self, row):
        self._set_status(row, "正在解密…", "#008d7f")

    @Slot(int, object)
    def _on_result(self, row, result):
        self.results[row] = result
        color = {"success": "#008d7f", "failed": "#ce5a49", "cancelled": "#9a7a37"}[result.status]
        detail = str(result.output) if result.output else result.message
        short_message = {"密码不匹配，请检查已知密码": "密码不匹配",
                         "未加密，已导出副本": "未加密 · 已导出",
                         "已取消，可重新开始": "已取消"}.get(result.message, result.message)
        self._set_status(row, short_message, color, detail)
        self.completed += 1
        self.progress.setValue(self.completed)
        self.summary.setText(f"正在处理 {self.completed} / {self.batch_total} 个文件…")

    @Slot()
    def _on_finished(self):
        self._set_busy(False)
        counts = {s: sum(r.status == s for r in self.results.values()) for s in ("success", "failed", "cancelled")}
        self.summary.setText(f"处理结束 · 成功 {counts['success']} 个 · 失败 {counts['failed']} 个 · 取消 {counts['cancelled']} 个"
                             + ("  |  修改密码后可重试未成功项" if counts["failed"] or counts["cancelled"] else ""))
        self.worker.deleteLater()
        self.worker = None
        if self.close_pending:
            self.close()

    def cancel_batch(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText("正在取消，当前文件保存完成后停止…")

    def open_output_directory(self):
        if self.last_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output_dir)))

    def open_result(self, row, _column):
        result = self.results.get(row)
        if result and result.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.output)))

    def closeEvent(self, event):
        if self.busy:
            self.close_pending = True
            self.cancel_batch()
            event.ignore()
            return
        self.password.clear()
        self.passwords.clear()
        QApplication.instance().removeEventFilter(self.drop_filter)
        event.accept()


def create_application(argv=None):
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("PDFUnlock")
    app.setOrganizationName("PDFUnlock")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    return app


def main(argv=None):
    app = create_application(argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
