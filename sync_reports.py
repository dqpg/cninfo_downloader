#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNinfo-Local-Sync (小白交互向导版)
功能: 一问一答式输入参数，自动处理默认值，双击即可流畅运行。
"""

import sys
import os
import datetime
import time
import random
import argparse
import httpx

class CnInfoLocalSpider:
    def __init__(self, base_storage_dir):
        self.base_dir = base_storage_dir
        self.cookies = {"JSESSIONID": "9A110350B0056BE0C4FDD8A627EF2868", "insert_cookie": "37836164"}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "http://www.cninfo.com.cn",
        }
        self.timeout = httpx.Timeout(60.0)
        self.search_url = "http://www.cninfo.com.cn/new/information/topSearch/query"
        self.query_url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        self.download_base = "http://static.cninfo.com.cn/"

    def resolve_stock(self, keyword):
        try:
            client = httpx.Client(headers=self.headers, timeout=self.timeout)
            resp = client.post(self.search_url, data={"keyWord": keyword, "maxNum": 10}).json()
            for item in resp:
                if item.get("code") == keyword or item.get("zwjc") == keyword:
                    market = "hke" if item.get("category") == "HKH" else "szse"
                    return {"code": item["code"], "name": item["zwjc"], "orgId": item["orgId"], "market": market}
            if resp:
                item = resp[0]
                market = "hke" if item.get("category") == "HKH" else "szse"
                return {"code": item["code"], "name": item["zwjc"], "orgId": item["orgId"], "market": market}
        except Exception as e:
            pass # 静默错误
        return {}

    def _fetch_api(self, stock_info, start_date, end_date, category):
        payload = {
            "pageNum": 1, "pageSize": 30, "column": stock_info["market"], "tabName": "fulltext",
            "stock": f"{stock_info['code']},{stock_info['orgId']}",
            "category": category, "seDate": f"{start_date}~{end_date}", "isHLtitle": False,
        }
        results = []
        client = httpx.Client(headers=self.headers, cookies=self.cookies, timeout=self.timeout)
        has_more = True
        while has_more:
            try:
                resp = client.post(self.query_url, data=payload).json()
                has_more = resp.get("hasMore", False)
                if resp.get("announcements"):
                    results.extend(resp["announcements"])
                payload["pageNum"] += 1
            except Exception as e:
                break
        return results

    def _download(self, ann, out_dir, filename):
        filepath = os.path.join(out_dir, filename)
        if os.path.exists(filepath): return
        print(f"  ⬇️ 下载: {filename}")
        try:
            with httpx.Client(headers=self.headers, timeout=self.timeout) as client:
                resp = client.get(self.download_base + ann["adjunctUrl"])
                with open(filepath, "wb") as f:
                    f.write(resp.content)
            time.sleep(random.uniform(0.5, 1.2))
        except:
            print(f"  ❌ 失败: {filename}")

    def sync(self, keyword, p_years, i_years):
        stock = self.resolve_stock(keyword)
        if not stock: 
            print(f"❌ 解析失败: {keyword}")
            return False, keyword
            
        print(f"\n📊 目标: {stock['code']} ({stock['name']})")
        out_dir = os.path.join(self.base_dir, f"{stock['code']}_{stock['name']}")
        os.makedirs(out_dir, exist_ok=True)

        # ================= 阶段一：定期报告 =================
        if p_years:
            print(f"  📥 提取定期财报 ({min(p_years)}-{max(p_years)})...")
            cats = "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh"
            for y in p_years:
                reports = self._fetch_api(stock, f"{y}-01-01", f"{y+1}-06-30", cats)
                for ann in reports:
                    t = ann["announcementTitle"]
                    if any(x in t for x in ["摘要", "英文"]) or "PDF" not in ann.get("adjunctType", ""): continue
                    q = "Q4" if "年度" in t else ("Q2" if "半年" in t or "中期" in t else ("Q1" if "一季" in t else "Q3"))
                    rev = "_修订版" if any(x in t for x in ["修订", "更正"]) else ""
                    fname = f"{stock['code']}_{stock['name']}_{y}_{q}_报告{rev}.pdf"
                    self._download(ann, out_dir, fname)

        # ================= 阶段二：重要公告 =================
        if i_years:
            start_y = min(i_years)
            print(f"  📥 捕获重大事件 ({start_y}至今)...")
            events = self._fetch_api(stock, f"{start_y}-01-01", f"{datetime.datetime.now().year}-12-31", "")
            core = {
                "问询函": "监管", "关注函": "监管", "警示函": "监管", "立案": "监管",
                "业绩预告": "业绩", "业绩快报": "业绩", "分红": "分红", "利润分配": "分红",
                "股权激励": "激励", "员工持股": "激励", "增持": "筹码", "减持": "筹码",
                "计提": "风险", "减值": "风险", "诉讼": "风险", 
                "重大合同": "业务", "中标": "业务", "战略合作": "业务",
                "重组": "资本", "收购": "资本", "定增": "资本", "募集": "资本"
            }
            for ann in events:
                t = ann["announcementTitle"]
                hit = next((k for k in core if k in t), None)
                if hit and not any(x in t for x in ["摘要", "取消", "提示性", "补充"]):
                    pub = time.strftime("%Y%m%d", time.localtime(ann["announcementTime"]/1000))
                    clean_t = t.replace("/", "-").replace("\\", "-").replace(":", "：").replace("*", "")
                    fname = f"{pub}_{clean_t}_{core[hit]}.pdf"
                    self._download(ann, out_dir, fname)
                    
        return True, stock

def parse_years(year_arg):
    if not year_arg: return []
    if '-' in year_arg:
        s, e = map(int, year_arg.split('-'))
        return list(range(s, e + 1))
    return [int(y) for y in year_arg.split(',')]

def interactive_wizard():
    print("="*60)
    print(" 🚀 巨潮资讯 A股财报/公告 智能下载器")
    print("="*60)

    curr_year = datetime.datetime.now().year
    default_out = os.path.join(os.path.expanduser("~"), "Documents", "Reports")

    # 1. 获取股票代码
    keyword = ""
    while not keyword:
        keyword = input("\n👉 1. 请输入股票代码、简称 (或TXT批量文件路径): ").strip()

    # 2. 选择下载模式
    mode_map = {'1': 'P', '2': 'I', '3': 'B'}
    print("\n👉 2. 请选择下载模式:")
    print("   [1] 仅下载 定期财报")
    print("   [2] 仅下载 重要公告 (排雷/业务增量)")
    print("   [3] 两者全要")
    mode_choice = input("   请输入序号 [直接回车默认 3]: ").strip()
    dl_mode = mode_map.get(mode_choice, 'B')

    p_years = []
    i_years = []

    # 3. 询问定期报告年份
    if dl_mode in ['P', 'B']:
        default_p = f"{curr_year-5}-{curr_year}"
        p_in = input(f"\n👉 3a. 定期财报年份区间 (直接回车默认 {default_p}): ").strip()
        p_years = parse_years(p_in if p_in else default_p)

    # 4. 询问重要公告年份
    if dl_mode in ['I', 'B']:
        default_i = f"{curr_year-3}-{curr_year}"
        i_in = input(f"\n👉 3b. 重要公告年份区间 (直接回车默认 {default_i}): ").strip()
        i_years = parse_years(i_in if i_in else default_i)

    # 5. 存储路径
    out_dir = input(f"\n👉 4. 保存目录 (直接回车默认 {default_out}): ").strip()
    if not out_dir:
        out_dir = default_out

    print("\n" + "="*60)
    print("⏳ 参数配置完毕，开始执行下载任务...")
    print("="*60 + "\n")

    spider = CnInfoLocalSpider(out_dir)
    
    if keyword.lower().endswith('.txt') and os.path.exists(keyword):
        success_list, fail_list = [], []
        with open(keyword, 'r', encoding='utf-8') as f:
            for line in f:
                kw = line.strip()
                if not kw: continue
                print(f"\n▶️ 处理目标: {kw}")
                ok, res = spider.sync(kw, p_years, i_years)
                if ok: success_list.append(res)
                else: fail_list.append(kw)
        
        print("\n" + "█"*60)
        print(f"✅ 成功: {len(success_list)} 家 | ❌ 失败: {len(fail_list)} 家")
        print("█"*60)
    else:
        spider.sync(keyword, p_years, i_years)
        
    print("\n🎉 任务全部结束！文件已保存在:", out_dir)
    # 防止双击运行时窗口一闪而过退出
    input("\n按回车键退出程序...")

if __name__ == "__main__":
    # 如果用户还是习惯用命令行传参，也做了兼容，如果没参数就启动向导
    if len(sys.argv) > 1:
        print("⚠️ 检测到命令行参数，但本版本主推交互向导。")
        print("💡 请直接双击运行脚本，或不带参数执行 `python sync_reports.py`")
        sys.exit(0)
    
    interactive_wizard()