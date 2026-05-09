#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os, datetime, time, random, re, httpx

class CnInfoLocalSpider:
    def __init__(self, base_storage_dir):
        self.base_dir = base_storage_dir
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Connection": "close",
            "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastPage=index",
            "Host": "static.cninfo.com.cn"
        }
        self.search_url = "http://www.cninfo.com.cn/new/information/topSearch/query"
        self.query_url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        self.download_base = "http://static.cninfo.com.cn/"

    def resolve_stock(self, keyword):
        h = self.headers.copy()
        h["Host"] = "www.cninfo.com.cn"
        try:
            with httpx.Client(headers=h, timeout=10.0) as client:
                resp = client.post(self.search_url, data={"keyWord": keyword, "maxNum": 10}).json()
                for item in resp:
                    if item.get("code") == keyword or item.get("zwjc") == keyword:
                        return {"code": item["code"], "name": item["zwjc"], "orgId": item["orgId"], "market": "hke" if item.get("category") == "HKH" else "szse"}
                if resp:
                    return {"code": resp[0]["code"], "name": resp[0]["zwjc"], "orgId": resp[0]["orgId"], "market": "hke" if resp[0].get("category") == "HKH" else "szse"}
        except Exception as e: return {}
        return {}

    def _fetch_api(self, stock_info, start_date, end_date, category):
        """修复翻页假死的核心逻辑"""
        h = self.headers.copy()
        h["Host"] = "www.cninfo.com.cn"
        payload = {
            "pageNum": 1, "pageSize": 30, "column": stock_info["market"], "tabName": "fulltext",
            "stock": f"{stock_info['code']},{stock_info['orgId']}",
            "category": category, "seDate": f"{start_date}~{end_date}", "isHLtitle": False,
        }
        results = []
        # 翻页超时控制得严格一点 (10秒)，一旦API假死立刻切断
        with httpx.Client(headers=h, timeout=httpx.Timeout(10.0, read=15.0)) as client:
            has_more = True
            max_pages = 20 # 强行限制最大翻页数，防止死循环
            while has_more and payload["pageNum"] <= max_pages:
                try:
                    resp = client.post(self.query_url, data=payload)
                    if resp.status_code != 200: break
                    data = resp.json()
                    has_more = data.get("hasMore", False)
                    if data.get("announcements"): 
                        results.extend(data["announcements"])
                    payload["pageNum"] += 1
                    time.sleep(0.5) # 翻页停顿，防止触发封锁
                except Exception as e:
                    print(f"  ⚠️ 检索列表遇到网络波动，已拿到 {len(results)} 条记录，直接进入下载...")
                    break
        return results

    def _parse_report_info(self, title):
        year_match = re.search(r'(20\d{2})', title)
        report_year = int(year_match.group(1)) if year_match else None
        q_type = None
        if "一季" in title or "第一季" in title: q_type = "Q1"
        elif any(x in title for x in ["半年", "中期"]): q_type = "Q2"
        elif "三季" in title or "第三季" in title: q_type = "Q3"
        elif "年度" in title or "年报" in title: q_type = "Q4"
        return report_year, q_type, any(x in title for x in ["修订", "更正", "更新"])

    def _download(self, ann, out_dir, filename):
        filepath = os.path.join(out_dir, filename)
        if os.path.exists(filepath): return
        
        dl_headers = self.headers.copy()
        dl_headers["Host"] = "static.cninfo.com.cn"
        
        for attempt in range(3):
            try:
                with httpx.Client(headers=dl_headers, timeout=httpx.Timeout(15.0, read=300.0)) as client:
                    print(f"  ⬇️ 正在同步: {filename} (尝试 {attempt+1})")
                    with client.stream("GET", self.download_base + ann["adjunctUrl"]) as resp:
                        if resp.status_code == 200:
                            with open(filepath, "wb") as f:
                                for chunk in resp.iter_bytes(): f.write(chunk)
                            print(f"  ✅ 成功")
                            time.sleep(random.uniform(1.0, 2.0))
                            return
                        else:
                            time.sleep(3)
            except Exception as e:
                time.sleep(3)
        print(f"  ‼️ 放弃: {filename}")

    def sync(self, keyword, p_years, i_years):
        stock = self.resolve_stock(keyword)
        if not stock: return False, keyword
        print(f"\n📊 目标: {stock['code']} ({stock['name']})")
        out_dir = os.path.join(self.base_dir, f"{stock['code']}_{stock['name']}")
        os.makedirs(out_dir, exist_ok=True)
        curr_y = datetime.datetime.now().year

        if p_years:
            print(f"  📥 财报检索 (范围: {min(p_years)}-{max(p_years)})...")
            cats = "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh"
            all_reports = self._fetch_api(stock, f"{min(p_years)}-01-01", f"{curr_y+1}-06-30", cats)
            for ann in all_reports:
                t = ann["announcementTitle"]
                if any(x in t for x in ["摘要", "英文"]) or "PDF" not in ann.get("adjunctType", ""): continue
                rep_y, q_type, is_revised = self._parse_report_info(t)
                if not q_type or not rep_y or rep_y not in p_years: continue
                if rep_y <= curr_y - 3 and q_type != "Q4": continue
                rev = "_修订版" if is_revised else ""
                fname = f"{stock['code']}_{stock['name']}_{rep_y}_{q_type}_报告{rev}.pdf"
                self._download(ann, out_dir, fname)

        if i_years:
            start_y = min(i_years)
            print(f"  📥 公告捕获 ({start_y}至今)...")
            events = self._fetch_api(stock, f"{start_y}-01-01", f"{curr_y}-12-31", "")
            core = {"问询函":"监管","关注函":"监管","警示函":"监管","立案":"监管","业绩预告":"业绩","业绩快报":"业绩","股权激励":"激励","重大合同":"业务","重组":"资本","计提":"风险"}
            for ann in events:
                t = ann["announcementTitle"]
                hit = next((k for k in core if k in t), None)
                if hit and not any(x in t for x in ["摘要", "取消", "补充"]):
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
    print("="*60 + "\n 🚀 巨潮资讯 A股同步器 (稳健防假死版)\n" + "="*60)
    curr_y = datetime.datetime.now().year
    default_out = os.path.join(os.path.expanduser("~"), "Documents", "Reports")
    keyword = input("\n👉 1. 请输入代码/简称 (或TXT路径): ").strip()
    if not keyword: return
    mode_map = {'1': 'P', '2': 'I', '3': 'B'}
    dl_mode = mode_map.get(input("\n👉 2. 模式: [1]仅财报 [2]仅公告 [3]全要 (默认3): ").strip(), 'B')
    p_years = parse_years(input(f"👉 3a. 财报年份 (默认{curr_y-5}-{curr_y}): ").strip() or f"{curr_y-5}-{curr_y}") if dl_mode in ['P','B'] else []
    i_years = parse_years(input(f"👉 3b. 公告年份 (默认{curr_y-3}-{curr_y}): ").strip() or f"{curr_y-3}-{curr_y}") if dl_mode in ['I','B'] else []
    out_dir = input(f"👉 4. 保存目录 (默认{default_out}): ").strip() or default_out
    
    spider = CnInfoLocalSpider(out_dir)
    if keyword.lower().endswith('.txt') and os.path.exists(keyword):
        with open(keyword, 'r', encoding='utf-8') as f:
            for line in f: 
                if line.strip(): spider.sync(line.strip(), p_years, i_years)
    else: spider.sync(keyword, p_years, i_years)
    input("\n🎉 任务结束！按回车退出...")

if __name__ == "__main__":
    interactive_wizard()