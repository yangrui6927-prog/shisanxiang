#!/usr/bin/env python3
"""
中国移动招标信息抓取与飞书推送系统
- 对标题进行多组关键字筛选
- 获取点击后新窗口的详情页URL
- 支持CSV动态配置关键字分组和Webhook
"""

import os
import json
import csv
import requests
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from collections import defaultdict
from playwright.sync_api import sync_playwright

# 缓存文件路径（从环境变量读取，默认当前目录）
CACHE_FILE = os.getenv("PUSHED_BIDS_CACHE", "pushed_bids.json")


class FeishuAPI:
    """飞书Webhook推送"""
    
    def send_webhook(self, webhook_url, message):
        """发送Webhook消息"""
        headers = {"Content-Type": "application/json"}
        data = {"msg_type": "text", "content": {"text": message}}
        try:
            resp = requests.post(webhook_url, headers=headers, json=data, timeout=30)
            success = resp.status_code == 200
            if not success:
                print(f"  Webhook发送失败: HTTP {resp.status_code}")
            return success
        except Exception as e:
            print(f"  Webhook发送异常: {e}")
            return False


class BiddingScraper:
    """招标信息抓取器"""
    
    URLS = {
        "招标采购公告": "https://b2b.10086.cn/#/biddingProcurementBulletin",
        "采购服务": "https://b2b.10086.cn/#/procurementServices",
    }
    
    # 公告类型映射
    BID_TYPE_MAP = {
        "CANDIDATE_PUBLICITY": "中标候选人公示",
        "WIN_BID": "中标公告",
        "WIN_BID_PUBLICITY": "中标结果公示",
        "BIDDING": "招标公告",
        "BIDDING_PROCUREMENT": "招标采购公告",
        "PROCUREMENT": "直接采购公告",
        "SINGLE_SOURCE": "单一来源公示",
        "PREQUALIFICATION": "资格预审公告",
        "CORRECTION": "更正公告",
        "TERMINATION": "终止公告",
        "SUSPENSION": "暂停公告",
        "CLARIFICATION": "澄清公告",
        # 采购服务页面类型
        "OPINION_SOLICITATION": "采购意见征求公告",
        "RECRUITMENT": "招募甄选合作公告",
        "VENDOR_CHECK_START": "信息核查公告",
        "SELECT_RESULT": "招募甄选合作结果公告",
    }
    
    def __init__(self):
        self.browser = None
        self.page = None
        self.playwright = None
        
    def init_browser(self):
        """初始化浏览器"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = self.context.new_page()
        
    def fetch_page(self, url, category="招标采购公告"):
        """抓取单个页面，同时获取详情URL"""
        try:
            print(f"正在抓取: {category}")
            self.page.goto(url, wait_until="networkidle", timeout=90000)
            self.page.wait_for_timeout(10000)  # 等待表格加载
            
            rows = self.page.query_selector_all("table tbody tr")
            print(f"  找到 {len(rows)} 行数据")
            
            bids = []
            for i, row in enumerate(rows):
                bid = self._parse_row(row, category)
                if bid:
                    # 立即获取详情URL
                    print(f"  [{i+1}/{len(rows)}] 获取详情: {bid['title'][:30]}...")
                    detail_url = self._get_detail_url_from_row(row)
                    bid["url"] = detail_url
                    if detail_url:
                        bid["type"] = self._parse_bid_type_from_url(detail_url)
                    bids.append(bid)
                    
            return bids
        except Exception as e:
            print(f"  抓取失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _get_detail_url_from_row(self, row):
        """从行元素获取详情URL"""
        try:
            cells = row.query_selector_all("td")
            if len(cells) < 3:
                return ""
            
            title_cell = cells[2]
            
            # 尝试多种可能的选择器找可点击元素
            clickable = None
            for selector in ["a", "span", "div", "button"]:
                clickable = title_cell.query_selector(selector)
                if clickable:
                    break
            
            if not clickable:
                clickable = title_cell
            
            # 等待新窗口弹出
            with self.page.expect_popup(timeout=15000) as popup_info:
                clickable.click()
            
            popup = popup_info.value
            popup.wait_for_load_state("networkidle", timeout=15000)
            detail_url = popup.url
            popup.close()
            
            if "noticeDetail" in detail_url:
                return detail_url
            else:
                return ""
                
        except Exception as e:
            print(f"    ✗ 获取失败: {e}")
            return ""
    
    def get_detail_url_for_bid(self, bid, row_element=None):
        """点击标题，在新窗口获取详情URL（备用方法）"""
        try:
            title = bid.get("title", "")
            print(f"  获取详情: {title[:40]}...")
            
            # 如果传入了row_element，直接使用；否则在页面中查找
            target_row = row_element
            if not target_row:
                # 在页面中找到对应标题的行（使用包含匹配，更宽松）
                rows = self.page.query_selector_all("table tbody tr")
                for row in rows:
                    cells = row.query_selector_all("td")
                    if len(cells) >= 4:
                        row_title = cells[2].inner_text().strip()
                        # 使用包含匹配，处理可能的空白字符差异
                        if title in row_title or row_title in title:
                            target_row = row
                            break
            
            if not target_row:
                print(f"    ✗ 未找到对应行")
                return ""
            
            # 找到标题单元格中的可点击元素（尝试多种选择器）
            cells = target_row.query_selector_all("td")
            title_cell = cells[2]
            
            # 尝试多种可能的选择器
            clickable = None
            for selector in ["span", "a", "div", "button"]:
                clickable = title_cell.query_selector(selector)
                if clickable:
                    break
            
            if not clickable:
                # 如果没有找到特定元素，尝试直接点击单元格
                clickable = title_cell
            
            # 等待新窗口弹出
            with self.page.expect_popup(timeout=15000) as popup_info:
                clickable.click()
            
            popup = popup_info.value
            popup.wait_for_load_state("networkidle", timeout=15000)
            detail_url = popup.url
            popup.close()
            
            if "noticeDetail" in detail_url:
                print(f"    ✓ 成功: {detail_url[:60]}...")
                return detail_url
            else:
                print(f"    ✗ URL无效: {detail_url[:60]}")
                return ""
                
        except Exception as e:
            print(f"    ✗ 失败: {e}")
            return ""

    def _parse_bid_type_from_url(self, url):
        """从URL解析公告类型"""
        if "publishType=" in url:
            try:
                publish_type = url.split("publishType=")[1].split("&")[0]
                return self.BID_TYPE_MAP.get(publish_type, "招标公告")
            except:
                pass
        return "招标公告"

    def _parse_row(self, row, category):
        """解析单行数据"""
        try:
            cells = row.query_selector_all("td")
            if len(cells) < 4:
                return None
            
            province = cells[0].inner_text().strip()
            bid_type = cells[1].inner_text().strip()
            title = cells[2].inner_text().strip()
            date_str = cells[3].inner_text().strip()
            
            return {
                "type": bid_type,
                "title": title,
                "date": date_str,
                "province": province,
                "url": "",
                "category": category,
            }
        except Exception as e:
            return None
    
    def get_detail_url_for_bid(self, bid, row_element=None):
        """点击标题，在新窗口获取详情URL"""
        try:
            title = bid.get("title", "")
            print(f"  获取详情: {title[:40]}...")
            
            # 如果传入了row_element，直接使用；否则在页面中查找
            target_row = row_element
            if not target_row:
                # 在页面中找到对应标题的行（使用包含匹配，更宽松）
                rows = self.page.query_selector_all("table tbody tr")
                for row in rows:
                    cells = row.query_selector_all("td")
                    if len(cells) >= 4:
                        row_title = cells[2].inner_text().strip()
                        # 使用包含匹配，处理可能的空白字符差异
                        if title in row_title or row_title in title:
                            target_row = row
                            break
            
            if not target_row:
                print(f"    ✗ 未找到对应行")
                return ""
            
            # 找到标题单元格中的可点击元素（尝试多种选择器）
            cells = target_row.query_selector_all("td")
            title_cell = cells[2]
            
            # 尝试多种可能的选择器
            clickable = None
            for selector in ["span", "a", "div", "button"]:
                clickable = title_cell.query_selector(selector)
                if clickable:
                    break
            
            if not clickable:
                # 如果没有找到特定元素，尝试直接点击单元格
                clickable = title_cell
            
            # 等待新窗口弹出
            with self.page.expect_popup(timeout=15000) as popup_info:
                clickable.click()
            
            popup = popup_info.value
            popup.wait_for_load_state("networkidle", timeout=15000)
            detail_url = popup.url
            popup.close()
            
            if "noticeDetail" in detail_url:
                print(f"    ✓ 成功: {detail_url[:60]}...")
                return detail_url
            else:
                print(f"    ✗ URL无效: {detail_url[:60]}")
                return ""
                
        except Exception as e:
            print(f"    ✗ 失败: {e}")
            return ""
    
    def _parse_bid_type_from_url(self, url):
        """从URL解析公告类型"""
        if "publishType=" in url:
            try:
                publish_type = url.split("publishType=")[1].split("&")[0]
                return self.BID_TYPE_MAP.get(publish_type, "招标公告")
            except:
                pass
        return "招标公告"
    
    def close(self):
        """关闭浏览器"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()


class BiddingNotifier:
    """招标通知主控制器"""
    
    def __init__(self):
        # 从环境变量读取配置
        self.fetch_hours = int(os.getenv("FETCH_HOURS", "25"))
        self.csv_file = os.getenv("LOCAL_CSV_FILE", "招标订阅表.csv")

        self.scraper = BiddingScraper()
        self.feishu = FeishuAPI()
        self.keyword_groups = []  # 从CSV加载的分组配置
        
    def load_keyword_groups(self):
        """从CSV加载关键字分组配置"""
        groups = []
        try:
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 解析关键词
                    keywords_str = row.get('关注关键词', '')
                    keywords = [k.strip() for k in keywords_str.split('|') if k.strip()]
                    
                    if keywords and row.get('Webhook', '').strip():
                        groups.append({
                            'name': row.get('销售姓名', f'分组{len(groups)+1}'),
                            'keywords': keywords,
                            'webhook': row.get('Webhook', '').strip()
                        })
            
            print(f"已加载 {len(groups)} 个关键字分组:")
            for i, group in enumerate(groups):
                print(f"  [{i+1}] {group['name']}: {len(group['keywords'])}个关键字")
            print()
            return groups
        except FileNotFoundError:
            print(f"警告: 未找到配置文件 {self.csv_file}")
            return []
        except Exception as e:
            print(f"读取配置文件失败: {e}")
            return []
    
    def load_pushed(self):
        """加载已推送记录，从缓存文件读取"""
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def save_pushed(self, urls):
        """保存已推送记录到缓存文件，最多100条"""
        import os as os_module
        cache_dir = os_module.path.dirname(CACHE_FILE)
        if cache_dir:  # 如果路径包含目录部分
            os_module.makedirs(cache_dir, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(urls)[-100:], f, ensure_ascii=False)
    
    def match_keyword_groups(self, bid):
        """匹配关键字分组，返回匹配的所有组索引"""
        title = bid.get('title', '')
        matched_groups = []
        
        for i, group in enumerate(self.keyword_groups):
            for keyword in group["keywords"]:
                if keyword in title:
                    matched_groups.append(i)
                    break  # 匹配到该组任一关键字即可
        
        return matched_groups
    
    def is_recent(self, bid):
        """检查是否在时间范围内"""
        try:
            bid_date = date_parser.parse(bid.get('date', ''))
            cutoff = datetime.now() - timedelta(hours=self.fetch_hours)
            return bid_date > cutoff
        except:
            return True
    
    def format_message(self, bids):
        """格式化推送消息"""
        # 按类型统计
        type_counts = defaultdict(int)
        for bid in bids:
            t = bid.get("type", "其他")
            type_counts[t] += 1
        
        summary = " | ".join([f"{t}{c}条" for t, c in type_counts.items()])
        message = f"您好，此次一共检索{len(bids)}条新消息（{summary}）～\n\n"
        
        # 按类型分组显示
        for bid_type in type_counts.keys():
            type_bids = [b for b in bids if b.get("type") == bid_type]
            for i, bid in enumerate(type_bids, 1):
                message += f"【{bid_type}{i}】\n"
                message += f"发布单位：{bid.get('province', '未知')}\n"
                message += f"发布时间：{bid.get('date', '未知')}\n"
                message += f"《{bid.get('title', '无标题')}》\n"
                url = bid.get('url', '')
                if url:
                    message += f"链接：{url}\n\n"
                else:
                    message += f"链接：https://b2b.10086.cn/#/biddingProcurementBulletin\n\n"
        
        return message
    
    def run(self):
        """主运行逻辑"""
        print("=" * 60)
        print("中国移动招标信息监控启动")
        print("=" * 60)
        
        # 加载关键字分组配置
        self.keyword_groups = self.load_keyword_groups()
        if not self.keyword_groups:
            print("没有配置关键字分组，退出")
            return
        
        # 初始化浏览器
        self.scraper.init_browser()
        
        # 加载已推送记录
        pushed = self.load_pushed()
        print(f"已有 {len(pushed)} 条推送记录")
        print(f"抓取时间范围: 最近{self.fetch_hours}小时\n")
        
        # 抓取所有招标
        all_bids = []
        for category, url in BiddingScraper.URLS.items():
            bids = self.scraper.fetch_page(url, category)
            all_bids.extend(bids)
            print(f"  抓取到 {len(bids)} 条\n")
        
        # 筛选: 未推送 + 时间范围内 + 匹配关键字分组
        matched_bids = []
        for bid in all_bids:
            # 使用URL作为唯一标识（如果还没有URL，先用标题）
            bid_id = bid.get("url") or bid.get("title", "")
            if bid_id in pushed:
                continue
            if not self.is_recent(bid):
                continue
            
            # 匹配关键字分组
            matched_groups = self.match_keyword_groups(bid)
            if matched_groups:
                bid["matched_groups"] = matched_groups
                matched_bids.append(bid)
        
        print(f"总计: {len(all_bids)} 条, 匹配: {len(matched_bids)} 条\n")
        
        # 为匹配项获取详情URL（如果抓取时未获取到）
        need_fetch_url = [b for b in matched_bids if not b.get("url")]
        if need_fetch_url:
            print(f"\n正在为 {len(need_fetch_url)} 条招标补获取详情URL...")
            for bid in need_fetch_url:
                detail_url = self.scraper.get_detail_url_for_bid(bid)
                bid["url"] = detail_url
                if detail_url:
                    bid["type"] = self.scraper._parse_bid_type_from_url(detail_url)
        else:
            print(f"\n所有招标详情URL已获取")
            for bid in matched_bids:
                url_short = bid.get('url', '')[:60] + "..." if bid.get('url') else "无"
                print(f"  ✓ {bid.get('title', '')[:40]}... | {url_short}")
        
        self.scraper.close()
        
        if not matched_bids:
            print("没有新的匹配招标信息")
            return
        
        # 按Webhook分组（一个招标可能推送到多个群）
        webhook_groups = defaultdict(list)
        for bid in matched_bids:
            for group_idx in bid.get("matched_groups", []):
                webhook = self.keyword_groups[group_idx]["webhook"]
                webhook_groups[webhook].append(bid)
        
        # 逐组推送
        print(f"\n开始推送，共 {len(webhook_groups)} 个目标群...")
        all_pushed_urls = []

        for webhook, bids in webhook_groups.items():
            # 去重（一个招标可能在同一个webhook中出现多次）
            unique_bids = []
            seen_titles = set()
            for bid in bids:
                title = bid.get("title", "")
                if title not in seen_titles:
                    seen_titles.add(title)
                    unique_bids.append(bid)

            print(f"\n推送到群 ({webhook[-20:]}):")
            for bid in unique_bids:
                print(f"  - {bid.get('title', '')[:40]}...")

            message = self.format_message(unique_bids)
            success = self.feishu.send_webhook(webhook, message)
            print(f"推送结果: {'成功' if success else '失败'}")

            if success:
                for bid in unique_bids:
                    url = bid.get("url") or bid.get("title", "")
                    if url not in all_pushed_urls:
                        all_pushed_urls.append(url)

        # 保存已推送记录：先移除已存在的（保持最新在末尾），再添加新的，最后截取100条
        for url in all_pushed_urls:
            if url in pushed:
                pushed.remove(url)  # 移除旧的
            pushed.append(url)      # 添加到末尾（最新）

        # 只保留最新的100条
        if len(pushed) > 100:
            pushed = pushed[-100:]

        self.save_pushed(pushed)
        
        print(f"\n完成! 本次推送 {len(all_pushed_urls)} 条新记录")
        print("=" * 60)


if __name__ == "__main__":
    notifier = BiddingNotifier()
    notifier.run()
