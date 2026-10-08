"""档案机构监测工作台 — Windows 桌面应用入口（PySide6）。

界面结构（与确认的 HTML 原型 v2 一致）：
    顶栏：标题 + 导出 Excel + 刷新数据
    筛选：省份 / 层级 / 状态 + 关键词搜索
    表格：官网 7 字段 + 更新状态 + 更新日期
    弹窗：点击「已变更」标签展示 旧值 → 新值（点空白处关闭）
    状态栏：上次刷新时间 | 数据源 | 定时开关 | 刷新进度
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QStatusBar, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from database import Database
from exporter import export
from scraper import fetch_all

COLS = ["序号", "行政区划代码", "机构编号", "机构全称", "机构层级",
        "通讯地址", "联系电话", "更新状态", "更新日期"]
COL_STATUS = 7  # 更新状态列索引

C_ACCENT = "#1677ff"
C_GREEN_BG, C_GREEN_BD, C_GREEN_TX = "#f6ffed", "#b7eb8f", "#389e0d"
C_AMBER_BG, C_AMBER_BD, C_AMBER_TX = "#fffbe6", "#ffe58f", "#d48806"
C_GREY_TX = "#8c8c8c"


# ---------------------------------------------------------------- 刷新线程

class RefreshWorker(QThread):
    """后台抓取线程：网络请求不阻塞界面。"""

    progress = Signal(str)
    done = Signal(dict)   # {"fresh": [...], "stats": {...}}
    failed = Signal(str)

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db

    def run(self) -> None:
        try:
            fresh = fetch_all(progress=self.progress.emit)
            stats = self.db.apply_refresh(fresh)
            self.done.emit({"fresh": fresh, "stats": stats})
        except Exception as exc:  # noqa: BLE001 — 网络异常统一上报到界面
            self.failed.emit(str(exc))


# ---------------------------------------------------------------- 变更弹窗

class ChangeDialog(QDialog):
    """变更详情弹窗：点弹窗外空白处即关闭。"""

    def __init__(self, org: dict, diffs: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        st_label = {"new": "新增", "upd": "已变更"}.get(org["status"], "—")
        title = QLabel("变更详情")
        title.setStyleSheet("font-size:14px;font-weight:600;")
        close = QLabel("✕")
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet("color:#8c8c8c;font-size:14px;")
        close.mousePressEvent = lambda _: self.reject()

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(close)

        org_lab = QLabel(org["name"])
        org_lab.setStyleSheet("font-size:14px;font-weight:600;")
        meta = QLabel(f"{org['province']} · {org['level']} · 机构编号 {org['org_code']}")
        meta.setStyleSheet(f"color:{C_GREY_TX};font-size:12px;")

        body = QVBoxLayout()
        body.addLayout(head)
        body.addSpacing(10)
        body.addWidget(org_lab)
        body.addWidget(meta)
        body.addSpacing(6)

        if diffs:
            for d in diffs:
                row = QLabel(
                    f"<span style='color:{C_GREY_TX}'>{d['field']}：</span>"
                    f"<span style='color:{C_GREY_TX};text-decoration:line-through'>{d['old_val']}</span>"
                    f" → <span style='color:{C_GREEN_TX}'>{d['new_val']}</span>"
                )
                row.setWordWrap(True)
                row.setStyleSheet(
                    "background:#fafafa;border-radius:6px;padding:8px 12px;font-size:13px;"
                )
                body.addWidget(row)
        else:
            tip = QLabel("该机构在本轮刷新中发生了变更，历史明细已记录。")
            tip.setStyleSheet(f"color:{C_GREY_TX};")
            body.addWidget(tip)

        body.addSpacing(8)
        foot = QHBoxLayout()
        date_lab = QLabel(f"更新日期：{org['updated_at'] or '—'}")
        date_lab.setStyleSheet(f"color:{C_AMBER_TX};font-size:12px;")
        btn = QPushButton("关闭")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.reject)
        foot.addWidget(date_lab)
        foot.addStretch()
        foot.addWidget(btn)
        body.addLayout(foot)

        card = QFrame()
        card.setLayout(body)
        card.setStyleSheet(
            "QFrame{background:white;border-radius:10px;}"
            "QLabel{border:none;background:transparent;}"
        )
        card.setFixedWidth(540)

        outer = QVBoxLayout(self)
        outer.addStretch()
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()

    # 点击弹窗外的遮罩区域关闭
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and not self.childAt(event.position().toPoint()):
            self.reject()
        super().mousePressEvent(event)


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.db = Database()
        self.all_rows: list[dict] = []
        self.worker: RefreshWorker | None = None
        self.setWindowTitle("流动人员人事档案管理机构监测工作台")
        self.resize(1280, 760)
        self._build_ui()
        self._load()

        # 可选每日自动刷新（24 小时定时器，勾选后启动）
        self.timer = QTimer(self)
        self.timer.setInterval(24 * 3600 * 1000)
        self.timer.timeout.connect(self.start_refresh)
        self.auto_check.toggled.connect(
            lambda on: self.timer.start() if on else self.timer.stop()
        )

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 0, 24, 0)
        root.setSpacing(10)

        # 顶栏
        top = QHBoxLayout()
        title = QLabel("流动人员人事档案管理机构监测工作台")
        title.setStyleSheet("font-size:15px;font-weight:600;")
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_refresh = QPushButton("刷新数据")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:white;border:none;"
            "border-radius:6px;padding:6px 18px;}"
            "QPushButton:hover{background:#4096ff;}"
            "QPushButton:disabled{background:#91caff;}"
        )
        self.btn_refresh.clicked.connect(self.start_refresh)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.btn_export)
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        # 筛选行
        filt = QHBoxLayout()
        self.cb_prov = QComboBox()
        self.cb_level = QComboBox()
        self.cb_status = QComboBox()
        for combo, items in (
            (self.cb_prov, ["全部省份"]),
            (self.cb_level, ["全部层级", "省", "市、地区", "县（区）"]),
            (self.cb_status, ["全部状态", "新增", "已变更", "无变化"]),
        ):
            combo.addItems(items)
            combo.currentIndexChanged.connect(self.refresh_table)
            filt.addWidget(combo)
        self.cb_prov.currentIndexChanged.connect(self.refresh_table)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索机构名称 / 地址 / 电话")
        self.ed_search.setFixedWidth(260)
        self.ed_search.textChanged.connect(self.refresh_table)
        filt.addWidget(self.ed_search)
        filt.addStretch()
        self.lab_count = QLabel("共 0 条")
        self.lab_count.setStyleSheet(f"color:{C_GREY_TX};font-size:12px;")
        filt.addWidget(self.lab_count)
        root.addLayout(filt)

        # 表格
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget{border:1px solid #e8e8e8;border-radius:8px;}"
            "QHeaderView::section{border:none;border-bottom:1px solid #e8e8e8;"
            "padding:8px;background:white;color:#8c8c8c;font-weight:500;}"
        )
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        for col in (3, 5):  # 机构全称、通讯地址自适应拉伸
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setStretchLastSection(True)
        self.table.cellClicked.connect(self.on_cell_clicked)
        root.addWidget(self.table, 1)

        self.setCentralWidget(central)

        # 状态栏
        bar = QStatusBar()
        bar.setStyleSheet("color:#8c8c8c;font-size:12px;")
        self.setStatusBar(bar)
        last = self.db.get_meta("last_refresh") or "—"
        self.lab_last = QLabel(f"上次刷新：{last}")
        self.lab_source = QLabel("数据源：chrm.mohrss.gov.cn")
        self.auto_check = QCheckBox("每日自动刷新")
        self.auto_check.setStyleSheet(f"color:{C_GREY_TX};font-size:12px;")
        self.lab_state = QLabel("就绪")
        for w in (self.lab_last, self.lab_source):
            bar.addWidget(w)
        bar.addPermanentWidget(self.auto_check)
        bar.addPermanentWidget(self.lab_state)

    # ---------- 数据加载与筛选 ----------

    def _load(self) -> None:
        self.all_rows = self.db.all_orgs()
        provs = sorted({r["province"] for r in self.all_rows if r["province"]})
        cur = self.cb_prov.currentText()
        self.cb_prov.blockSignals(True)
        self.cb_prov.clear()
        self.cb_prov.addItem("全部省份")
        self.cb_prov.addItems(provs)
        if cur in ("", "全部省份") or cur in provs:
            self.cb_prov.setCurrentText(cur if cur in provs or cur == "全部省份" else "全部省份")
        self.cb_prov.blockSignals(False)
        self.refresh_table()

    def _filtered(self) -> list[dict]:
        prov = self.cb_prov.currentText()
        lv = self.cb_level.currentText()
        st = self.cb_status.currentText()
        kw = self.ed_search.text().strip().lower()
        st_map = {"新增": "new", "已变更": "upd", "无变化": "ok"}
        rows = self.all_rows
        if prov and prov != "全部省份":
            rows = [r for r in rows if r["province"] == prov]
        if lv != "全部层级":
            rows = [r for r in rows if r["level"] == lv]
        if st != "全部状态":
            rows = [r for r in rows if r["status"] == st_map[st]]
        if kw:
            rows = [r for r in rows if kw in
                    (r["name"] + r["addr"] + r["tel"] + r["org_code"]).lower()]
        return rows

    def refresh_table(self) -> None:
        rows = self._filtered()
        table = self.table
        table.setRowCount(len(rows))
        st_label = {"new": "新增", "upd": "已变更"}

        for i, r in enumerate(rows):
            vals = [str(i + 1), r["admin_code"], r["org_code"], r["name"], r["level"],
                    r["addr"], r["tel"],
                    st_label.get(r["status"], "—"), r["updated_at"] or "—"]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if c in (0, 1, 2):
                    item.setForeground(QColor(C_GREY_TX))
                if c == 3:
                    f = item.font()
                    f.setWeight(QFont.DemiBold)
                    item.setFont(f)
                if c == 5:
                    item.setForeground(QColor(C_GREY_TX))
                if c == 7:
                    if r["status"] == "new":
                        item.setBackground(QColor(C_GREEN_BG))
                        item.setForeground(QColor(C_GREEN_TX))
                        item.setTextAlignment(Qt.AlignCenter)
                    elif r["status"] == "upd":
                        item.setBackground(QColor(C_AMBER_BG))
                        item.setForeground(QColor(C_AMBER_TX))
                        item.setTextAlignment(Qt.AlignCenter)
                    else:
                        item.setForeground(QColor("#d9d9d9"))
                        item.setTextAlignment(Qt.AlignCenter)
                if c == 8 and not r["updated_at"]:
                    item.setForeground(QColor("#d9d9d9"))
                item.setData(Qt.UserRole, i)
                table.setItem(i, c, item)

        self.lab_count.setText(f"共 {len(rows)} 条")
        # 「已变更」标签显示手型光标
        table.setCursor(
            Qt.PointingHandCursor
            if any(r["status"] == "upd" for r in rows) else Qt.ArrowCursor
        )

    # ---------- 交互 ----------

    def on_cell_clicked(self, row: int, col: int) -> None:
        if col != COL_STATUS:
            return
        item = self.table.item(row, col)
        if not item or item.text() != "已变更":
            return
        src_row = item.data(Qt.UserRole)
        org = self._filtered()[src_row]
        dlg = ChangeDialog(org, self.db.get_diffs(org["org_code"], org["last_batch"]), self)
        dlg.exec()

    def start_refresh(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.lab_state.setText("正在抓取 31 个省份页面…")
        self.worker = RefreshWorker(self.db)
        self.worker.progress.connect(lambda m: self.lab_state.setText(m))
        self.worker.done.connect(self.on_refresh_done)
        self.worker.failed.connect(self.on_refresh_failed)
        self.worker.start()

    def on_refresh_done(self, payload: dict) -> None:
        stats = payload["stats"]
        self.btn_refresh.setEnabled(True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.lab_state.setText("就绪")
        self.lab_last.setText(f"上次刷新：{now}")
        self._load()
        QMessageBox.information(
            self, "刷新完成",
            f"刷新完成：\n新增 {stats['new']} 条 · 变更 {stats['upd']} 条"
            f" · 撤销 {stats['del']} 条\n当前机构总数：{stats['total']}",
        )

    def on_refresh_failed(self, msg: str) -> None:
        self.btn_refresh.setEnabled(True)
        self.lab_state.setText("刷新失败")
        QMessageBox.critical(self, "刷新失败", f"抓取数据时出错：\n{msg}\n\n请检查网络后重试。")

    def on_export(self) -> None:
        rows = self._filtered()
        if not rows:
            QMessageBox.information(self, "提示", "当前筛选结果为空，没有可导出的数据。")
            return
        default = f"档案管理机构_{datetime.now():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel", default, "Excel 工作簿 (*.xlsx)"
        )
        if not path:
            return
        try:
            export(rows, Path(path))
            self.lab_state.setText(f"已导出 {len(rows)} 条")
            QMessageBox.information(self, "导出成功", f"已导出 {len(rows)} 条记录到：\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", f"写入文件失败：\n{exc}\n\n若文件已打开请先关闭。")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.wait(2000)
        self.db.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(
        "QWidget{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
        "font-size:13px;color:#262626;background:#fafafa;}"
        "QLineEdit,QComboBox{background:white;border:1px solid #e8e8e8;"
        "border-radius:6px;padding:5px 10px;}"
        "QLineEdit:focus,QComboBox:focus{border-color:#1677ff;}"
        "QPushButton{border:1px solid #e8e8e8;border-radius:6px;padding:6px 16px;background:white;}"
        "QPushButton:hover{border-color:#bfbfbf;color:#1677ff;}"
        "QTableWidget::item{border-bottom:1px solid #f5f5f5;}"
        "QTableWidget::item:selected{background:#f0f7ff;color:#262626;}"
        "QToolTip{background:white;color:#262626;border:1px solid #e8e8e8;}"
    )
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
