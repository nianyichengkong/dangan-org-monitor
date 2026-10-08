"""抓取模块：中国人力资源市场网 - 流动人员人事档案管理服务机构信息。

入口页列出 31 个省级一览表链接；省级页为服务端直出的 tablepress 表格，
共 7 列：序号 / 行政区划代码 / 机构编号 / 机构全称 / 机构层级 / 通讯地址 / 联系电话。
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field

import httpx
from parsel import Selector

HUB_URL = "https://chrm.mohrss.gov.cn/%E6%B5%81%E5%8A%A8%E4%BA%BA%E5%91%98%E4%BA%BA%E4%BA%8B%E6%A1%A3%E6%A1%88%E7%AE%A1%E7%90%86%E6%9C%8D%E5%8A%A1%E6%9C%BA%E6%9E%84%E4%BF%A1%E6%81%AF/"

# 官网对无 UA 请求返回空响应，必须携带浏览器 UA
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TIMEOUT = httpx.Timeout(30.0, connect=15.0)


def _ssl_context() -> ssl.SSLContext:
    """构建兼容性 SSL 上下文。

    该 gov 站点启用了 TLS 旧版重协商（RFC 5746 之前的行为），OpenSSL 3.x 默认
    拒绝并抛 UNSAFE_LEGACY_RENEGOTIATION_DISABLED，需显式放行（仅对本站点使用）。
    """
    ctx = ssl.create_default_context()
    op_legacy = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    ctx.options |= op_legacy
    return ctx


@dataclass
class Org:
    """单条机构记录（官网公开的 7 个字段 + 所属省份）。"""

    admin_code: str  # 行政区划代码
    org_code: str    # 机构编号（主键）
    name: str        # 机构全称
    level: str       # 机构层级：省 / 市、地区 / 县（区）
    addr: str        # 通讯地址
    tel: str         # 联系电话（多号码以 " / " 拼接）
    province: str = ""  # 来自入口页链接文字，如 "河南"
    status: str = "ok"     # ok / new / upd
    updated_at: str = ""   # 最近一次变更日期
    diffs: list = field(default_factory=list)  # [(field, old, new), ...]


def fetch_provinces(client: httpx.Client) -> list[tuple[str, str]]:
    """抓取入口页，返回 [(省份名, 省级页 URL), ...]，按页面出现顺序。

    Args:
        client: 已初始化的 httpx.Client。

    Returns:
        省份名与对应一览表 URL 的有序列表。

    Raises:
        RuntimeError: 入口页请求失败或未解析到任何省份链接。
    """
    resp = client.get(HUB_URL)
    resp.raise_for_status()
    sel = Selector(resp.text)
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    base = "https://chrm.mohrss.gov.cn/"
    for a in sel.css("a[href]"):
        href = a.attrib.get("href", "")
        # 链接文字可能在子元素中，需拼接全部文本节点
        text = "".join(t.strip() for t in a.css("::text").getall())
        # 只保留指向具体省份一览表的链接（排除入口页自身与导航链接）
        if not text or not href.rstrip("/").endswith("一览表"):
            continue
        if href in seen:
            continue
        seen.add(href)
        if href.startswith("/"):
            href = base.rstrip("/") + href
        elif not href.startswith("http"):
            href = base + href
        result.append((text, href))
    if not result:
        raise RuntimeError("入口页解析失败：未找到任何省份链接")
    return result


def _cell_text(td: Selector) -> str:
    """提取单元格文本；<br> 分隔的多个值以 ' / ' 拼接（多电话场景）。"""
    parts = [t.strip() for t in td.xpath(".//text()").getall() if t.strip()]
    return " / ".join(parts)


def fetch_province(client: httpx.Client, province: str, url: str) -> list[Org]:
    """抓取单个省份的一览表，返回机构列表。

    Args:
        client: httpx.Client。
        province: 省份名（来自入口页链接文字）。
        url: 省级一览表 URL。

    Returns:
        该省全部机构记录。

    Raises:
        RuntimeError: 页面请求失败或表格缺失。
    """
    resp = client.get(url)
    resp.raise_for_status()
    sel = Selector(resp.text)
    rows = sel.css("table[id^=tablepress] tbody tr")
    orgs: list[Org] = []
    for tr in rows:
        tds = tr.css("td")
        if len(tds) < 7:
            continue
        vals = [_cell_text(td) for td in tds[:7]]
        orgs.append(
            Org(
                admin_code=vals[1],
                org_code=vals[2],
                name=vals[3],
                level=vals[4],
                addr=vals[5],
                tel=vals[6],
                province=province,
            )
        )
    if not orgs:
        raise RuntimeError(f"{province} 页面解析失败：表格无数据行")
    return orgs


def fetch_all(progress=None) -> list[Org]:
    """全量抓取 31 个省份。

    Args:
        progress: 可选回调 ``fn(text: str)``，用于向界面汇报进度。

    Returns:
        全部机构记录（顺序：省份 → 页面行序）。
    """
    results: list[Org] = []
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True,
                      verify=_ssl_context()) as client:
        provinces = fetch_provinces(client)
        if progress:
            progress(f"发现 {len(provinces)} 个省份，开始抓取…")
        for i, (name, url) in enumerate(provinces, 1):
            if progress:
                progress(f"正在抓取 {name}（{i}/{len(provinces)}）…")
            results.extend(fetch_province(client, name, url))
    if progress:
        progress(f"抓取完成，共 {len(results)} 条机构记录")
    return results
