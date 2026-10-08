"""Excel 导出：仿用户提供的 WPS 蓝色报表版式。

版式结构（与参考截图一致）：
    第 1 行      细留白
    第 2 行      报表大标题（合并单元格、16px 加粗）
    第 3 行      数据来源 + 官网超链接
    第 4 行      留白
    第 5 行      深蓝底白字表头
    第 6 行起    浅蓝隔行条纹数据区，冻结窗格 + 自动筛选
    Sheet 2     「省份汇总」：各省份机构数量 / 新增 / 变更 / 最近更新日期
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADERS = ["省份", "序号", "行政区划代码", "机构编号", "机构全称", "机构层级",
           "通讯地址", "联系电话", "更新状态", "更新日期"]
WIDTHS = [10, 6, 12, 12, 44, 10, 54, 26, 10, 12]

SUM_HEADERS = ["省份", "机构数量", "本次新增", "信息变更", "最近更新日期"]
SUM_WIDTHS = [14, 12, 12, 12, 16]

# 配色（取样自参考截图）
HEADER_BG = "2F5597"     # 深蓝表头
BAND_ODD = "DDEBF7"      # 浅蓝条纹
BAND_EVEN = "EBF4FB"     # 更浅蓝条纹
GRID = "B4C6E7"          # 边框
SUM_TOTAL_BG = "BDD7EE"  # 合计行
# 语义色沿用工作台规范
NEW_BG, UPD_BG, UPD_TX = "F6FFED", "FFFBE6", "D48806"

THIN = Side(style="thin", color=GRID)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
SRC_URL = "https://chrm.mohrss.gov.cn/流动人员人事档案管理服务机构信息/"
TITLE = "全国流动人员人事档案管理服务机构全部信息"


def _sheet_header(ws, headers: list[str], widths: list[int], title: str) -> int:
    """写标题 / 来源 / 表头三段，返回表头所在行号。"""
    ncols = len(headers)
    # 第 1 行细留白
    ws.row_dimensions[1].height = 8
    # 第 2 行大标题
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    c = ws.cell(row=2, column=1, value=title)
    c.font = Font(size=16, bold=True)
    c.alignment = LEFT
    ws.row_dimensions[2].height = 30
    # 第 3 行数据来源（超链接）
    ws.cell(row=3, column=1, value="数据来源：").font = Font(size=10, bold=True)
    link = ws.cell(row=3, column=2, value=SRC_URL)
    link.hyperlink = SRC_URL
    link.font = Font(size=10, color="0563C1", underline="single")
    ws.merge_cells(start_row=3, start_column=2, end_row=3, end_column=ncols)
    ws.row_dimensions[3].height = 16
    ws.row_dimensions[4].height = 8
    # 第 5 行表头
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=5, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = PatternFill("solid", fgColor=HEADER_BG)
        cell.alignment = CENTER
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = widths[col - 1]
    ws.row_dimensions[5].height = 22
    ws.freeze_panes = "A6"
    return 5


def _fill_cell(ws, row: int, col: int, value, band: str, align: Alignment = LEFT):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = PatternFill("solid", fgColor=band)
    cell.border = BORDER
    cell.alignment = align
    cell.font = Font(size=11)
    return cell


def _write_main_sheet(wb: Workbook, rows: list[dict]) -> None:
    ws = wb.active
    ws.title = "全部服务机构"
    last = _sheet_header(ws, HEADERS, WIDTHS, TITLE)

    st_label = {"new": "新增", "upd": "已变更"}
    for i, r in enumerate(rows):
        row = last + 1 + i
        band = BAND_ODD if i % 2 == 0 else BAND_EVEN
        if r["status"] == "new":
            band = NEW_BG      # 新增行语义底色优先于条纹
        elif r["status"] == "upd":
            band = UPD_BG
        vals = [r["province"], i + 1, r["admin_code"], r["org_code"], r["name"],
                r["level"], r["addr"], r["tel"],
                st_label.get(r["status"], "—"), r["updated_at"] or "—"]
        for c, v in enumerate(vals, 1):
            cell = _fill_cell(ws, row, c, v, band,
                              CENTER if c in (1, 2, 6, 9, 10) else LEFT)
            if c in (3, 4):
                cell.number_format = "@"  # 代码列按文本，防止丢前导 0
            if c == 10 and r["updated_at"]:
                cell.font = Font(size=11, color=UPD_TX)

    last_row = last + len(rows)
    ws.auto_filter.ref = f"A5:{get_column_letter(len(HEADERS))}{last_row}"


def _write_summary_sheet(wb: Workbook, rows: list[dict]) -> None:
    ws = wb.create_sheet("省份汇总")
    last = _sheet_header(ws, SUM_HEADERS, SUM_WIDTHS, "各省份机构数量汇总")

    # 按省份聚合（保持省份首次出现顺序）
    agg: dict[str, dict] = {}
    for r in rows:
        item = agg.setdefault(r["province"], {"count": 0, "new": 0, "upd": 0, "last": ""})
        item["count"] += 1
        if r["status"] == "new":
            item["new"] += 1
        elif r["status"] == "upd":
            item["upd"] += 1
        if r["updated_at"] and r["updated_at"] > item["last"]:
            item["last"] = r["updated_at"]

    items = sorted(agg.items(), key=lambda kv: kv[1]["count"], reverse=True)
    for i, (prov, s) in enumerate(items):
        row = last + 1 + i
        band = BAND_ODD if i % 2 == 0 else BAND_EVEN
        vals = [prov, s["count"], s["new"], s["upd"], s["last"] or "—"]
        for c, v in enumerate(vals, 1):
            _fill_cell(ws, row, c, v, band, LEFT if c == 1 else CENTER)
        if s["last"]:
            ws.cell(row=row, column=5).font = Font(size=11, color=UPD_TX)

    # 合计行
    row = last + 1 + len(items)
    vals = ["合计", len(rows), sum(s["new"] for _, s in items),
            sum(s["upd"] for _, s in items), "—"]
    for c, v in enumerate(vals, 1):
        cell = _fill_cell(ws, row, c, v, SUM_TOTAL_BG, LEFT if c == 1 else CENTER)
        cell.font = Font(size=11, bold=True)


def export(rows: list[dict], path: Path) -> None:
    """导出机构列表到 xlsx（报表版式，含省份汇总页）。

    Args:
        rows: 筛选后的机构字典列表（database.all_orgs 的结构）。
        path: 目标文件路径。

    Raises:
        OSError: 目标路径不可写（如文件被 Excel/WPS 占用）。
    """
    wb = Workbook()
    _write_main_sheet(wb, rows)
    _write_summary_sheet(wb, rows)
    wb.save(path)
