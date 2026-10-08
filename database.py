"""数据层：SQLite 存储 + 快照 diff 引擎。

设计要点
--------
- institutions 以机构编号 (org_code) 为主键，保存当前快照 + 状态标记。
- changes 记录每一次刷新产生的增量事件（新增 / 变更 / 撤销），供弹窗展示。
- institutions.last_batch 指向该机构最近一次发生变更的批次，弹窗按批次取旧值→新值。
- 每次刷新开始时，把上一批次遗留的 new/upd 状态归位为 ok，再基于本次 diff 重新标记，
  这样「更新日期」始终是最近一次实际变更的日期，而非刷新日期。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scraper import Org

# 需要比对的业务字段：DB 列名 -> (展示名, Org 属性)
FIELD_MAP = {
    "name": ("机构全称", "name"),
    "level": ("机构层级", "level"),
    "addr": ("通讯地址", "addr"),
    "tel": ("联系电话", "tel"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
    org_code    TEXT PRIMARY KEY,
    admin_code  TEXT,
    name        TEXT,
    level       TEXT,
    addr        TEXT,
    tel         TEXT,
    province    TEXT,
    status      TEXT DEFAULT 'ok',   -- ok / new / upd
    updated_at  TEXT DEFAULT '',     -- 最近一次实际变更日期
    last_batch  INTEGER DEFAULT 0    -- 最近一次变更所属批次
);
CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch       INTEGER NOT NULL,
    org_code    TEXT,
    org_name    TEXT,
    change_type TEXT,   -- new / upd / del
    field       TEXT,   -- 变更字段展示名；del 时为空
    old_val     TEXT,
    new_val     TEXT,
    changed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_changes_batch ON changes(batch, org_code);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def db_path() -> Path:
    """数据库文件位置。

    - 打包/安装版：Windows 下存到 %APPDATA%\\档案机构监测工作台\\，
      避免写入 Program Files 这类只读目录导致报错。
    - 开发版：脚本同目录。
    """
    import os
    import sys

    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA")
        if base:
            d = Path(base) / "档案机构监测工作台"
            d.mkdir(parents=True, exist_ok=True)
            return d / "data.db"
        return Path(sys.executable).parent / "data.db"
    return Path(__file__).parent / "data.db"


class Database:
    """SQLite 封装：读写机构快照、执行 diff、查询变更明细。"""

    def __init__(self, path: Path | None = None) -> None:
        self.conn = sqlite3.connect(str(path or db_path()))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- 基础查询 ----------

    def all_orgs(self) -> list[dict]:
        """返回全部机构（含状态/更新日期），按省份+区划代码排序。"""
        cur = self.conn.execute(
            "SELECT * FROM institutions ORDER BY province, admin_code, org_code"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ---------- diff 核心 ----------

    def apply_refresh(self, fresh: list[Org]) -> dict:
        """将一次全量抓取结果与库内快照对比并落库。

        Args:
            fresh: 本次抓取的全部机构记录。

        Returns:
            统计结果 ``{"new": n, "upd": n, "del": n, "total": n, "batch": b}``。
        """
        today = date.today().isoformat()
        old_map = {
            r["org_code"]: r for r in self.conn.execute("SELECT * FROM institutions")
        }
        batch = int(self.get_meta("next_batch") or "1")
        # 首次刷新建立基线：全部按无变化入库，不标「新增」、不写变更记录
        baseline = not old_map

        # 上一批次的状态标记归位（更新日期保留，代表历史变更日期）
        self.conn.execute("UPDATE institutions SET status='ok' WHERE status!='ok'")

        stats = {"new": 0, "upd": 0, "del": 0}
        fresh_map = {o.org_code: o for o in fresh}
        now_batch = batch

        def log_change(org: Org, ctype: str, field: str, old: str, new: str) -> None:
            self.conn.execute(
                "INSERT INTO changes(batch, org_code, org_name, change_type, field,"
                " old_val, new_val, changed_at) VALUES(?,?,?,?,?,?,?,?)",
                (batch, org.org_code, org.name, ctype, field, old, new, today),
            )

        # 1) 新增 + 变更
        for o in fresh:
            old = old_map.get(o.org_code)
            if old is None:
                if baseline:
                    o.status, o.updated_at = "ok", ""
                    self.conn.execute(
                        "INSERT INTO institutions(org_code, admin_code, name, level,"
                        " addr, tel, province, status, updated_at, last_batch)"
                        " VALUES(?,?,?,?,?,?,?,'ok','',0)",
                        (o.org_code, o.admin_code, o.name, o.level, o.addr, o.tel,
                         o.province),
                    )
                else:
                    o.status, o.updated_at = "new", today
                    self.conn.execute(
                        "INSERT INTO institutions(org_code, admin_code, name, level, addr,"
                        " tel, province, status, updated_at, last_batch)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (o.org_code, o.admin_code, o.name, o.level, o.addr, o.tel,
                         o.province, "new", today, batch),
                    )
                    log_change(o, "new", "", "", "")
                    stats["new"] += 1
                continue

            diffs = []
            for col, (label, attr) in FIELD_MAP.items():
                new_v = getattr(o, attr)
                old_v = old[col] or ""
                if new_v != old_v:
                    diffs.append((label, old_v, new_v))
            if diffs:
                o.status, o.updated_at = "upd", today
                self.conn.execute(
                    "UPDATE institutions SET admin_code=?, name=?, level=?, addr=?,"
                    " tel=?, province=?, status='upd', updated_at=?, last_batch=?"
                    " WHERE org_code=?",
                    (o.admin_code, o.name, o.level, o.addr, o.tel, o.province,
                     today, batch, o.org_code),
                )
                for label, old_v, new_v in diffs:
                    log_change(o, "upd", label, old_v, new_v)
                stats["upd"] += 1

        # 2) 撤销（本次未出现、且非刚被更新过的）
        for code, row in old_map.items():
            if code in fresh_map:
                continue
            self.conn.execute(
                "INSERT INTO changes(batch, org_code, org_name, change_type, field,"
                " old_val, new_val, changed_at) VALUES(?,?,?,?,?,?,?,?)",
                (batch, code, row["name"], "del", "", "", "", today),
            )
            self.conn.execute("DELETE FROM institutions WHERE org_code=?", (code,))
            stats["del"] += 1

        self.set_meta("next_batch", str(batch + 1))
        self.set_meta("last_refresh", today)
        self.conn.commit()
        stats["total"] = self.conn.execute(
            "SELECT COUNT(*) c FROM institutions"
        ).fetchone()["c"]
        stats["batch"] = now_batch
        return stats

    # ---------- 变更明细 ----------

    def get_diffs(self, org_code: str, batch: int) -> list[dict]:
        """取某机构在指定批次的全部字段变更（用于弹窗展示）。"""
        cur = self.conn.execute(
            "SELECT field, old_val, new_val FROM changes"
            " WHERE org_code=? AND batch=? AND change_type='upd' AND field!=''",
            (org_code, batch),
        )
        return [dict(r) for r in cur.fetchall()]

    def recent_changes(self, limit: int = 50) -> list[dict]:
        """最近一批的变更事件摘要（刷新后 toast 用）。"""
        cur = self.conn.execute(
            "SELECT change_type, COUNT(*) c FROM changes"
            " WHERE batch=(SELECT MAX(batch) FROM changes) GROUP BY change_type"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
