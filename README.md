# CNinfo-Local-Sync
专业的 A 股财报与重要公告本地化抓取工具，专为本地大模型（RAG）知识库设计。

## 特色功能
- **动态解析**：无需维护股票数据库，输入名称或代码自动匹配。
- **结构化归档**：按 `代码_简称_年份_Qx` 规范命名，完美适配本地大模型检索。
- **多维度捕获**：不仅下载财报，还自动筛选问询函、业绩预告、重大合同等排雷信号。
- **高度自定义**：支持指定年份区间、下载类型及保存路径。

## 致谢
本项目受 **jarodise/CNinfo2Notebookllm** 启发并在其基础上进行重构。感谢 jarodise 提供的核心思路。

## 快速开始
```bash
# 安装依赖
pip install httpx

# 下载单只股票（默认近3年，全部下载）
python sync_reports_v2.py 300308

# 自定义年份和类型 (P=定期报告, I=重要公告, B=两者皆下载)
python sync_reports_v2.py 云南锗业 --years 2021-2026 --type P --out D:\MyData

# 批量下载 (通过 TXT 文件列表)
python sync_reports_v2.py pool.txt --years 2023-2026 --type B