"""档案机构监测工作台 — Windows 桌面应用入口（PySide6）。

界面样式遵循《设计规范.md》：所有视觉常量集中在 Token 类 T，
规范文档中的每个令牌与本文件一一对应，改样式先改规范再改令牌。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QStatusBar,
    QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from database import Database
from divisions import division_for
from exporter import export
from postcode import postal_for
from scraper import fetch_all

COLS = ["序号", "省", "市", "县（区）", "机构层级", "机构全称",
        "通讯地址", "邮政编码", "联系电话", "更新状态", "更新日期"]
COL_STATUS = 9


# ================================================================ 设计令牌
# 与《设计规范.md》一一对应

class T:
    """Design Tokens — 修改样式先改《设计规范.md》再同步此处。

    配色体系（v1.1）：参考广东医科大学校徽「蓝 + 绿」双色——
    蓝色象征未来与希望（主操作色），绿色象征茵茵校园（生命绿，刷新/成长语义）。
    """

    # 品牌色：校徽蓝（主）+ 生命绿（辅）
    PRIMARY = "#1E7FD0"          # 医大蓝：导出、链接、选中
    PRIMARY_HOVER = "#3D96E0"
    PRIMARY_ACTIVE = "#1663A8"
    PRIMARY_BG = "#E5F2FC"       # 浅蓝底（选中行）
    ACCENT = "#3CB878"           # 生命绿：刷新按钮、图标渐变
    ACCENT_HOVER = "#54C68C"
    ACCENT_ACTIVE = "#2FA267"
    ACCENT_BG = "#E6F7EE"        # 浅绿底
    # 中性色
    BG_PAGE = "#F2F9F5"          # 薄荷白窗口底
    BG_SURFACE = "#FFFFFF"
    BG_HOVER = "#EFF7F2"
    BORDER = "#E3E9E5"
    DIVIDER = "#EEF3EF"
    TEXT_1 = "#1F2D26"
    TEXT_2 = "#5F6E66"
    TEXT_3 = "#8B9A92"
    TEXT_DISABLED = "#BDC8C1"
    # 语义色：新增 / 已变更 / 无变化
    NEW_BG, NEW_BD, NEW_TX = "#F6FFED", "#B7EB8F", "#389E0D"
    UPD_BG, UPD_BD, UPD_TX = "#FFFBE6", "#FCE57F", "#D48806"
    OK_BG, OK_TX = "#F3F6F4", "#93A39B"
    # 字体
    FONT_FAMILY = "'Microsoft YaHei UI', 'PingFang SC', 'Segoe UI', sans-serif"
    # 圆角
    RADIUS_LG = 10
    RADIUS_MD = 6
    # 尺寸
    CONTROL_H = 32
    ROW_H = 38
    PAGE_MARGIN = 24
    BLOCK_GAP = 12


ST_TAG = {"new": "新增", "upd": "已变更", "ok": "—"}


# ================================================================ 刷新线程

class RefreshWorker(QThread):
    """后台抓取线程：网络请求不阻塞界面。"""

    progress = Signal(str)
    done = Signal(dict)
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


# ================================================================ 状态徽章

class BadgeDelegate(QStyledItemDelegate):
    """状态列徽章：胶囊形绘制，替代生硬的整格填色。"""

    _STYLES = {
        "新增": (T.NEW_BG, T.NEW_BD, T.NEW_TX),
        "已变更": (T.UPD_BG, T.UPD_BD, T.UPD_TX),
        "—": (T.OK_BG, None, T.OK_TX),
    }

    def paint(self, painter: QPainter, option, index) -> None:
        text = index.data(Qt.DisplayRole) or "—"
        bg, bd, tx = self._STYLES.get(text, self._STYLES["—"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)

        fm = painter.fontMetrics()
        w = min(fm.horizontalAdvance(text) + 24, option.rect.width() - 8)
        h = 22
        pad_x = (option.rect.width() - w) // 2
        pad_y = (option.rect.height() - h) // 2
        rect = option.rect.adjusted(pad_x, pad_y, -pad_x, -pad_y)
        # 「已变更」可点击，悬停时底色加深一档
        hovered = bool(option.state & QStyle.State_MouseOver) and text == "已变更"
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FEF3C7" if hovered else bg))
        painter.drawRoundedRect(rect, 11, 11)
        if bd:
            painter.setPen(QColor(bd))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 11, 11)
        painter.setPen(QColor(tx))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(88, T.ROW_H)


# ================================================================ 状态分段器

class SegmentedControl(QFrame):
    """「全部/新增/已变更/无变化」互斥分段器，替代下拉框。"""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("segmented", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (value, label) in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)  # 固定高度防止被布局拉伸成直角块
            btn.setProperty("segBtn", True)
            btn.setProperty("role", value)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
            self.group.addButton(btn)
            lay.addWidget(btn)

    def value(self) -> str:
        return self.group.checkedButton().property("role")


# ================================================================ 变更弹窗

class ChangeDialog(QDialog):
    """变更详情弹窗：投影卡片 + 点遮罩关闭。"""

    def __init__(self, org: dict, diffs: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        title = QLabel("变更详情")
        title.setStyleSheet(f"font-size:14px;font-weight:600;color:{T.TEXT_1};")
        close = QLabel("✕")
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"color:{T.TEXT_3};font-size:14px;padding:2px 6px;border-radius:4px;")
        close.mousePressEvent = lambda _: self.reject()

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(close)

        org_lab = QLabel(org["name"])
        org_lab.setStyleSheet(f"font-size:14px;font-weight:600;color:{T.TEXT_1};")
        meta = QLabel(f"{org['province']} · {org['level']} · 机构编号 {org['org_code']}")
        meta.setStyleSheet(f"color:{T.TEXT_3};font-size:12px;")

        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 18)
        body.setSpacing(6)
        body.addLayout(head)
        body.addSpacing(8)
        body.addWidget(org_lab)
        body.addWidget(meta)
        body.addSpacing(8)

        if diffs:
            for d in diffs:
                row = QLabel(
                    f"<span style='color:{T.TEXT_2}'>{d['field']}："
                    f"<span style='text-decoration:line-through'>{d['old_val']}</span></span>"
                    f" <span style='color:{T.TEXT_3}'>→</span>"
                    f" <span style='color:{T.NEW_TX}'>{d['new_val']}</span>"
                )
                row.setWordWrap(True)
                row.setStyleSheet(
                    f"background:{T.BG_PAGE};border-radius:{T.RADIUS_MD}px;"
                    "padding:9px 14px;font-size:13px;"
                )
                body.addWidget(row)
        else:
            tip = QLabel("该机构在本轮刷新中发生了变更，历史明细已记录。")
            tip.setStyleSheet(f"color:{T.TEXT_3};")
            body.addWidget(tip)

        body.addSpacing(10)
        foot = QHBoxLayout()
        date_lab = QLabel(f"更新日期：{org['updated_at'] or '—'}")
        date_lab.setStyleSheet(f"color:{T.UPD_TX};font-size:12px;")
        btn = QPushButton("关闭")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.reject)
        foot.addWidget(date_lab)
        foot.addStretch()
        foot.addWidget(btn)
        body.addLayout(foot)

        card = QFrame()
        card.setObjectName("modalCard")
        card.setLayout(body)
        card.setFixedWidth(560)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(31, 35, 41, 46))
        card.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.addStretch()
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()

    def mousePressEvent(self, event) -> None:  # noqa: N802 — 点遮罩空白处关闭
        if event.button() == Qt.LeftButton and not self.childAt(event.position().toPoint()):
            self.reject()
        super().mousePressEvent(event)


# ================================================================ 主窗口

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.db = Database()
        self.all_rows: list[dict] = []
        self.worker: RefreshWorker | None = None
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(120)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spin_frame = 0
        self._spin_frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

        self.setWindowTitle("流动人员人事档案管理机构监测工作台")
        self.resize(1320, 780)
        self.setWindowIcon(_app_icon())
        self._build_ui()
        self._load()

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
        root.setContentsMargins(T.PAGE_MARGIN, 16, T.PAGE_MARGIN, 4)
        root.setSpacing(T.BLOCK_GAP)

        # ---- 顶栏：双色标题 + 副题 | 操作按钮
        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        t1 = QLabel()
        t1.setProperty("appTitle", True)
        t1.setTextFormat(Qt.RichText)
        # 双色标题：蓝（信息）+ 绿（监测），呼应校徽蓝绿双色
        t1.setText(
            f"<span style='color:{T.PRIMARY}'>流动人员人事档案管理机构</span>"
            f"<span style='color:{T.ACCENT}'>监测工作台</span>"
        )
        t2 = QLabel()
        t2.setProperty("appSubtitle", True)
        t2.setTextFormat(Qt.RichText)
        t2.setText(
            f"<span style='color:{T.PRIMARY}'>●</span> 数据来源：chrm.mohrss.gov.cn"
            f" &nbsp;<span style='color:{T.ACCENT}'>●</span> 全国 31 省 3551 条机构"
        )
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        head.addLayout(title_box)
        head.addStretch()

        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setProperty("secondary", True)
        self.btn_export.setProperty("tone", "blue")
        self.btn_export.setFixedHeight(T.CONTROL_H)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_refresh = QPushButton("刷新数据")
        self.btn_refresh.setProperty("primary", True)
        self.btn_refresh.setFixedHeight(T.CONTROL_H)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setMinimumWidth(96)
        self.btn_refresh.clicked.connect(self.start_refresh)
        head.addWidget(self.btn_export)
        head.addWidget(self.btn_refresh)
        root.addLayout(head)

        # ---- 分隔线：蓝→绿渐变，呼应校徽双色
        line = QFrame()
        line.setFixedHeight(2)
        line.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {T.PRIMARY}, stop:0.55 {T.ACCENT}, stop:1 {T.ACCENT_BG});"
            "border:none;border-radius:1px;"
        )
        root.addWidget(line)

        # ---- 筛选行：省份/层级 + 状态分段器 + 搜索
        filt = QHBoxLayout()
        filt.setSpacing(8)
        self.cb_prov = QComboBox()
        self.cb_level = QComboBox()
        for combo, items in (
            (self.cb_prov, ["全部省份"]),
            (self.cb_level, ["全部层级", "省", "市、地区", "县（区）"]),
        ):
            combo.addItems(items)
            combo.setFixedHeight(T.CONTROL_H)
            combo.setMinimumWidth(120)
            combo.currentIndexChanged.connect(self.refresh_table)
            filt.addWidget(combo)
        self.cb_prov.currentIndexChanged.connect(self.refresh_table)

        self.seg_status = SegmentedControl(
            [("all", "全部"), ("new", "新增"), ("upd", "已变更"), ("ok", "无变化")]
        )
        self.seg_status.changed.connect(self.refresh_table)
        filt.addWidget(self.seg_status)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索机构名称 / 地址 / 电话")
        self.ed_search.setFixedHeight(T.CONTROL_H)
        self.ed_search.setFixedWidth(260)
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self.refresh_table)
        filt.addWidget(self.ed_search)
        filt.addStretch()
        self.lab_count = QLabel("共 0 条")
        self.lab_count.setProperty("caption", True)
        filt.addWidget(self.lab_count)
        root.addLayout(filt)

        # ---- 表格
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(T.ROW_H)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMouseTracking(True)  # 徽章悬停加深
        self.table.setItemDelegateForColumn(COL_STATUS, BadgeDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setFixedHeight(44)
        # 显式列宽：把空间让给机构全称/通讯地址/联系电话三个高价值列
        # 长文本列（全称/地址/电话）超宽时省略号 + 悬浮显示全文
        for col, width in ((0, 56), (1, 64), (2, 88), (3, 106), (4, 96),
                           (7, 84), (8, 126), (COL_STATUS, 92), (10, 100)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(5, QHeaderView.Stretch)   # 机构全称
        header.setSectionResizeMode(6, QHeaderView.Stretch)   # 通讯地址
        self.table.setColumnWidth(COL_STATUS, 92)
        header.setStretchLastSection(False)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.cellClicked.connect(self.on_cell_clicked)
        root.addWidget(self.table, 1)

        self.setCentralWidget(central)

        # ---- 状态栏
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)
        last = self.db.get_meta("last_refresh") or "—"
        self.lab_last = QLabel(f"上次刷新：{last}")
        self.lab_source = QLabel("数据源正常 · chrm.mohrss.gov.cn")
        self.auto_check = QCheckBox("每日自动刷新")
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
        st = self.seg_status.value()
        kw = self.ed_search.text().strip().lower()
        rows = self.all_rows
        if prov and prov != "全部省份":
            rows = [r for r in rows if r["province"] == prov]
        if lv != "全部层级":
            rows = [r for r in rows if r["level"] == lv]
        if st != "all":
            rows = [r for r in rows if r["status"] == st]
        if kw:
            # 搜索覆盖：名称/地址/电话/编号 + 推导出的市县名（如搜"郑州"）
            rows = [r for r in rows if kw in
                    (r["name"] + r["addr"] + r["tel"] + r["org_code"]
                     + "".join(division_for(r["admin_code"]))).lower()]
        return rows

    def refresh_table(self) -> None:
        rows = self._filtered()
        table = self.table
        table.setRowCount(len(rows))

        for i, r in enumerate(rows):
            city, county = division_for(r["admin_code"])
            vals = [str(i + 1), r["province"], city, county, r["level"], r["name"],
                    r["addr"], postal_for(r["admin_code"]), r["tel"],
                    ST_TAG.get(r["status"], "—"), r["updated_at"] or "—"]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if c in (0, 1, 2, 3, 7, 8):
                    item.setForeground(QColor(T.TEXT_2))
                if c == 5:
                    f = item.font()
                    f.setWeight(QFont.DemiBold)
                    item.setFont(f)
                if c == 10:
                    item.setForeground(
                        QColor(T.UPD_TX if r["updated_at"] else T.TEXT_DISABLED)
                    )
                if c in (0, 8, 9, 10):
                    item.setTextAlignment(Qt.AlignCenter)
                # 容易被截断的列给悬浮全文
                if c in (5, 6, 8):
                    item.setToolTip(text)
                item.setData(Qt.UserRole, i)
                table.setItem(i, c, item)

        self.lab_count.setText(f"共 {len(rows)} 条")

    # ---------- 交互 ----------

    def on_cell_clicked(self, row: int, col: int) -> None:
        if col != COL_STATUS:
            return
        item = self.table.item(row, col)
        if not item or item.text() != "已变更":
            return
        org = self._filtered()[item.data(Qt.UserRole)]
        dlg = ChangeDialog(org, self.db.get_diffs(org["org_code"], org["last_batch"]), self)
        dlg.exec()

    def start_refresh(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("刷新中…")
        self._spin_frame = 0
        self._spinner_timer.start()
        self.worker = RefreshWorker(self.db)
        self.worker.progress.connect(lambda m: self.lab_state.setText(m))
        self.worker.done.connect(self.on_refresh_done)
        self.worker.failed.connect(self.on_refresh_failed)
        self.worker.start()

    def _tick_spinner(self) -> None:
        self._spin_frame = (self._spin_frame + 1) % len(self._spin_frames)
        self.lab_state.setText(
            f"{self._spin_frames[self._spin_frame]} 正在抓取并对比快照…"
        )

    def on_refresh_done(self, payload: dict) -> None:
        stats = payload["stats"]
        self._spinner_timer.stop()
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("刷新数据")
        self.lab_state.setText("就绪")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.lab_last.setText(f"上次刷新：{now}")
        self._load()
        QMessageBox.information(
            self, "刷新完成",
            f"刷新完成：\n新增 {stats['new']} 条 · 变更 {stats['upd']} 条"
            f" · 撤销 {stats['del']} 条\n当前机构总数：{stats['total']}",
        )

    def on_refresh_failed(self, msg: str) -> None:
        self._spinner_timer.stop()
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("刷新数据")
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


# ================================================================ 图标与全局样式

# Windows 运行互斥体：① 配合安装包 AppMutex 检测"程序正在运行"；
# ② 句柄保存在模块级变量，进程存活期间持锁，退出时自动释放
_win_mutex_handle = None


def _acquire_runtime_mutex() -> None:
    global _win_mutex_handle
    if sys.platform == "win32":
        import ctypes

        _win_mutex_handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, "DanganOrgMonitorMutex"
        )


def _app_icon() -> QIcon:
    """程序图标：校徽蓝→生命绿渐变圆角方块 + 白色「档」字，纯代码绘制。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0.0, QColor(T.PRIMARY))
    grad.setColorAt(1.0, QColor(T.ACCENT))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    f = QFont()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(pm.rect(), Qt.AlignCenter, "档")
    p.end()
    return QIcon(pm)


def build_qss() -> str:
    """全局 QSS，全部取值自设计令牌 T。"""
    return f"""
    * {{
        font-family: {T.FONT_FAMILY};
        font-size: 13px;
        color: {T.TEXT_1};
        background: {T.BG_PAGE};
    }}
    QLabel {{ background: transparent; }}
    QLabel[appTitle]    {{ font-size: 17px; font-weight: 600; }}
    QLabel[appSubtitle] {{ font-size: 12px; color: {T.TEXT_3}; }}
    QLabel[caption]     {{ font-size: 12px; color: {T.TEXT_3}; }}

    QPushButton {{
        background: {T.BG_SURFACE};
        border: 1px solid {T.BORDER};
        border-radius: {T.RADIUS_MD}px;
        padding: 0 18px;
        height: {T.CONTROL_H}px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{ border-color: {T.PRIMARY}; color: {T.PRIMARY}; }}
    QPushButton:pressed {{ background: {T.BG_PAGE}; }}
    QPushButton:disabled {{ opacity: 0.55; }}
    QPushButton[primary="true"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {T.ACCENT_HOVER}, stop:1 {T.ACCENT});
        border: none; color: white; padding: 0 22px;
    }}
    QPushButton[primary="true"]:hover   {{ background: {T.ACCENT_HOVER}; color: white; }}
    QPushButton[primary="true"]:pressed {{ background: {T.ACCENT_ACTIVE}; }}
    QPushButton[primary="true"]:disabled {{ background: #A5DCBE; color: white; }}
    QPushButton[tone="blue"]:hover {{ border-color: {T.PRIMARY}; color: {T.PRIMARY}; }}

    QLineEdit, QComboBox {{
        background: {T.BG_SURFACE};
        border: 1px solid {T.BORDER};
        border-radius: {T.RADIUS_MD}px;
        padding: 0 10px;
        color: {T.TEXT_1};
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {T.PRIMARY}; }}
    QLineEdit::placeholder {{ color: {T.TEXT_DISABLED}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{
        background: {T.BG_SURFACE};
        border: 1px solid {T.BORDER};
        border-radius: {T.RADIUS_MD}px;
        selection-background-color: {T.PRIMARY_BG};
        selection-color: {T.TEXT_1};
        outline: none;
    }}

    /* 状态分段器 */
    QFrame[segmented="true"] {{
        background: {T.BG_PAGE};
        border: 1px solid {T.BORDER};
        border-radius: 17px;
    }}
    QPushButton[segBtn="true"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 12px; padding: 0 14px; height: 26px;
        color: {T.TEXT_2}; font-size: 12px;
    }}
    QPushButton[segBtn="true"]:hover {{ color: {T.TEXT_1}; }}
    QPushButton[segBtn="true"]:checked {{
        background: {T.BG_SURFACE};
        border: 1px solid {T.BORDER};
        border-radius: 12px;
        color: {T.TEXT_1};
    }}
    QPushButton[segBtn="true"][role="new"]:checked {{ color: {T.NEW_TX}; background: {T.NEW_BG}; }}
    QPushButton[segBtn="true"][role="upd"]:checked {{ color: {T.UPD_TX}; background: {T.UPD_BG}; }}

    /* 表格 */
    QTableWidget {{
        background: {T.BG_SURFACE};
        alternate-background-color: {T.BG_SURFACE};
        border: 1px solid {T.BORDER};
        border-radius: {T.RADIUS_LG}px;
        gridline-color: transparent;
        selection-background-color: {T.PRIMARY_BG};
        selection-color: {T.TEXT_1};
        outline: none;
    }}
    QTableWidget::item {{ padding: 0 14px; border-bottom: 1px solid {T.DIVIDER}; }}
    QTableWidget::item:hover {{ background: {T.BG_HOVER}; }}
    QTableWidget::item:selected {{ background: {T.PRIMARY_BG}; }}
    QHeaderView::section {{
        background: {T.BG_SURFACE};
        color: {T.TEXT_3};
        border: none;
        border-bottom: 1px solid {T.BORDER};
        padding: 0 14px;
        font-size: 12px;
        font-weight: 500;
    }}
    QTableCornerButton::section {{ background: {T.BG_SURFACE}; border: none; }}

    /* 滚动条 */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 3px; }}
    QScrollBar::handle:vertical {{
        background: #D5D9E0; border-radius: 4px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #BFC4CC; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* 状态栏 */
    QStatusBar {{
        background: {T.BG_PAGE};
        color: {T.TEXT_3};
        font-size: 12px;
        border-top: 1px solid {T.DIVIDER};
    }}
    QStatusBar QLabel {{ color: {T.TEXT_3}; font-size: 12px; padding: 0 8px; }}
    QStatusBar::item {{ border: none; }}
    QCheckBox {{
        color: {T.TEXT_3}; font-size: 12px; background: transparent; spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {T.BORDER};
        border-radius: 3px; background: {T.BG_SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background: {T.ACCENT}; border-color: {T.ACCENT};
    }}

    /* 弹窗 */
    QFrame#modalCard {{ background: {T.BG_SURFACE}; border-radius: {T.RADIUS_LG}px; }}
    QFrame#modalCard QLabel {{ background: transparent; border: none; }}

    QMessageBox {{ background: {T.BG_SURFACE}; }}
    QMessageBox QLabel {{ background: transparent; font-size: 13px; }}
    QToolTip {{
        background: {T.BG_SURFACE}; color: {T.TEXT_1};
        border: 1px solid {T.BORDER}; padding: 4px 8px; font-size: 12px;
    }}
    """


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())
    app.setStyleSheet(build_qss())
    _acquire_runtime_mutex()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
