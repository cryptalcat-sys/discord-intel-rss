import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_RUN = 3  # 每次執行單一來源最多發送篇數（防止洗版）

# 1. 訂閱來源清單（名稱、RSS 網址、自訂卡片顏色色碼）
FEEDS = [
    {
        "name": "The War Zone",
        "url": "https://www.twz.com/feed",
        "color": 0x1A365D  # 深海軍藍
    },
    {
        "name": "USNI News (海軍學會)",
        "url": "https://news.usni.org/feed",
        "color": 0x003366
    },
    {
        "name": "Defense News",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
        "color": 0x2D6A4F  # 防務綠
    }
]

# 2. 正則表達式過濾器
INCLUDE_PATTERN = re.compile(
    r"(?i)\b(military|defense|pentagon|pla|missile|navy|air force|drills|sanctions|geopolitics|ukraine|russia|taiwan|carrier|drone|war|strait)\b"
)
EXCLUDE_PATTERN = re.compile(
    r"(?i)(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle)"
)

def clean_text(html_text, max_len=200):
    """去除 RSS 摘要裡的 HTML 標籤並限制字數"""
    if not html_text:
        return ""
    text = BeautifulSoup(html_text, "html.parser").get_text()
    text = " ".join(text.split())
    return (text[:max_len] + "...") if len(text) > max_len else text

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    # 只保留最近 300 筆文章 ID，避免檔案無限膨脹
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-300:], f, ensure_ascii=False, indent=2)

def extract_thumbnail(entry):
    """提取文章縮圖"""
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    if "enclosures" in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href")
    return None

def send_to_discord(entry, feed_info):
    title = entry.get("title", "No Title")
    link = entry.get("link", "")
    summary = clean_text(entry.get("summary", entry.get("description", "")))
    thumb_url = extract_thumbnail(entry)

    embed = {
        "author": {"name": feed_info["name"]},
        "title": title[:256],
        "url": link,
        "description": summary,
        "color": feed_info["color"],
        "footer": {"text": "即時防務情報 • 自動過濾驗證"}
    }
    if thumb_url:
        embed["thumbnail"] = {"url": thumb_url}

    payload = {
        "username": "全球情報觀測站",
        "embeds": [embed]
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    return resp.status_code in [200, 204]

def main():
    if not WEBHOOK_URL:
        print("未設定 DISCORD_WEBHOOK_URL，程式終止。")
        return

    history = load_history()
    is_initial_run = len(history) == 0
    new_ids = []

    for feed_info in FEEDS:
        print(f"正在檢查: {feed_info['name']}")
        parsed = feedparser.parse(feed_info["url"])
        sent_count = 0

        for entry in parsed.entries:
            entry_id = entry.get("id", entry.get("link", ""))
            if not entry_id or entry_id in history or entry_id in new_ids:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            content_to_check = f"{title} {summary}"

            # 初次運行防炸頻機制：把現存新聞直接標為已讀，不實際推播
            if is_initial_run:
                new_ids.append(entry_id)
                continue

            # 關鍵字過濾：排除黑名單、比對白名單
            if EXCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            if not INCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            # 發送 Webhook
            if sent_count < MAX_POSTS_PER_RUN:
                success = send_to_discord(entry, feed_info)
                if success:
                    print(f"已發送: {title}")
                    new_ids.append(entry_id)
                    sent_count += 1
                    time.sleep(1)  # 防 Discord API 限流
            else:
                break

    if new_ids:
        history.extend(new_ids)
        save_history(history)
        print(f"更新完畢，本次共記錄 {len(new_ids)} 筆項目。")

if __name__ == "__main__":
    main()
