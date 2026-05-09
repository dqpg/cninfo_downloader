#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNinfo-Local-Sync V2
功能: 动态解析股票，支持自定义年份、下载类型及保存目录。
致谢: 本项目受 jarodise/CNinfo2Notebookllm 启发并在其基础上修改重构。
"""

import sys
import os
import datetime
import time
import random
import re
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
            print(f"解析股票失败: {e}")
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

    def sync(self, keyword, years, dl_type):
        stock = self.resolve_stock(keyword)
        if not stock: return False, keyword
        print(f"📊 目标: {stock['code']} ({stock['name']})")
        out_dir = os.path.join(self.base_dir, f"{stock['code']}_{stock['name']}")
        os.makedirs(out_dir, exist_ok=True)

        # 阶段一：定期报告
        if dl_type in ['P', 'B']:
            print(f"  📥 提取定期财报 ({years})...")
            cats = "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh"
            for y in years:
                reports = self._fetch_api(stock, f"{y}-01-01", f"{y+1}-06-30", cats)
                for ann in reports:
                    t = ann["announcementTitle"]
                    if any(x in t for x in ["摘要", "英文"]) or "PDF" not in ann.get("adjunctType", ""): continue
                    q = "Q4" if "年度" in t else ("Q2" if "半年" in t or "中期" in t else ("Q1" if "一季" in t else "Q3"))
                    rev = "_修订版" if any(x in t for x in ["修订", "更正"]) else ""
                    fname = f"{stock['code']}_{stock['name']}_{y}_{q}_报告{rev}.pdf"
                    self._download(ann, out_dir, fname)

        # 阶段二：重要公告
        if dl_type in ['I', 'B']:
            start_y = min(years) if years else datetime.datetime.now().year - 3
            print(f"  📥 捕获重大事件 ({start_y}至今)...")
            events = self._fetch_api(stock, f"{start_y}-01-01", f"{datetime.datetime.now().year}-12-31", "")
            core = {"问询函": "监管", "关注函": "监管", "业绩预告": "业绩", "股权激励": "激励", "重大合同": "业务", "定增": "资本"}
            for ann in events:
                t = ann["announcementTitle"]
                hit = next((k for k in core if k in t), None)
                if hit and not any(x in t for x in ["摘要", "取消"]):
                    pub = time.strftime("%Y%m%d", time.localtime(ann["announcementTime"]/1000))
                    fname = f"{pub}_{t}_{core[hit]}.pdf"
                    self._download(ann, out_dir, fname)
        return True, stock

def parse_years(year_arg):
    if '-' in year_arg:
        s, e = map(int, year_arg.split('-'))
        return list(range(s, e + 1))
    return [int(y) for y in year_arg.split(',')]

if __name__ == "__main__":
    default_doc = os.path.join(os.path.expanduser("~"), "Documents", "Reports")
    parser = argparse.ArgumentParser(description="巨潮资讯本地同步工具 V2")
    parser.add_argument("keyword", help="股票代码、简称或TXT文件路径")
    parser.add_argument("--years", default=f"{datetime.datetime.now().year-3}-{datetime.datetime.now().year}", help="年份: 2021-2025 或 2022,2024")
    parser.add_argument("--type", choices=['P', 'I', 'B'], default='B', help="P:定期, I:重要, B:两者")
    parser.add_argument("--out", default=default_doc, help="保存目录")
    args = parser.parse_args()

    spider = CnInfoLocalSpider(args.out)
    target_years = parse_years(args.years)
    
    if args.keyword.lower().endswith('.txt'):
        with open(args.keyword, 'r', encoding='utf-8') as f:
            for line in f: spider.sync(line.strip(), target_years, args.type)
    else:
        spider.sync(args.keyword, target_years, args.type)