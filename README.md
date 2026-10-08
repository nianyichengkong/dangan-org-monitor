# 档案机构监测工作台

监测人社部「流动人员人事档案管理服务机构信息」公开目录（chrm.mohrss.gov.cn）的 Windows 桌面应用。

- 全国 31 省 + 新疆兵团，3551 条机构数据
- 刷新自动 diff：新增 / 变更 / 撤销，变更点标签弹窗查看旧值 → 新值
- 筛选搜索 + Excel 导出 + 可选每日自动刷新

## 构建

GitHub Actions（windows-latest）自动构建：
- PyInstaller 打包绿色版 `DanganOrgMonitor.exe`
- Inno Setup 打包安装版 `DanganOrgMonitor-Setup.exe`

产物发布到 GitHub Releases。本地构建：`pip install -r requirements.txt pyinstaller` 后
`pyinstaller --onefile --windowed --name DanganOrgMonitor main.py`。
