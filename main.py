import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_RUN = 3  # 每次執行單一來源最多發送篇數

# 1. 訂閱來源清單
FEEDS = [
    {
        "name": "The War Zone",
        "url": "https://www.twz.com/feed",
        "color": 0x1A365D
    },
    {
        "name": "USNI News (海軍學會)",
        "url": "https://news.usni.org/feed",
        "color": 0x003366
    },
    {
        "name": "Defense News",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
        "color": 0x2D6A4F
    }
]

# 2. 關鍵字過濾規則
INCLUDE_PATTERN = re.compile(
    r"(?i)\b(military|defense|pentagon|pla|missile|navy|air force|drills|sanctions|geopolitics|ukraine|russia|taiwan|carrier|drone|war|strait)\b"
)
EXCLUDE_PATTERN = re.compile(
    r"(?i)(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle)"
)

# 3. 繁體中文翻譯器
translator = GoogleTranslator(source='auto', target='zh-TW')

def translate_text(text):
    """翻譯為繁體中文，失敗時保留原文"""
    if not text:
        return ""
    try:
        # 限制送審長度防止超出 API 限制
        return translator.translate(text[:1500])
    except Exception as e:
        print(f"翻譯異常，改用原文推送: {e}")
        return text

def clean_text(html_text, max_len=220):
    """去除 RSS 摘要裡的 HTML 標籤並擷取指定字數"""
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
    orig_title = entry.get("title", "No Title")
    link = entry.get("link", "")
    orig_summary = clean_text(entry.get("summary", entry.get("description", "")))
    thumb_url = extract_thumbnail(entry)

    # 執行中文翻譯
    title_zh = translate_text(orig_title)
    summary_zh = translate_text(orig_summary)

    # 排版：卡片上方顯示中文摘要，下方以斜體附上英文原標題方便查證
    description_text = f"{summary_zh}\n\n*原標題：{orig_title}*"

    embed = {
        "author": {"name": feed_info["name"]},
        "title": title_zh[:256],
        "url": link,
        "description": description_text[:2000],
        "color": feed_info["color"],
        "footer": {"text": "即時防務情報 • 中文自動翻譯"}
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

            # 初次運行防炸頻
            if is_initial_run:
                new_ids.append(entry_id)
                continue

            # 關鍵字過濾
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
                    print(f"已翻譯並發送: {title}")
                    new_ids.append(entry_id)
                    sent_count += 1
                    time.sleep(2)  # 翻譯與發送間隔，防止頻率限制
            else:
                break

    if new_ids:
        history.extend(new_ids)
        save_history(history)
        print(f"更新完畢，本次共記錄 {len(new_ids)} 筆項目。")

if __name__ == "__main__":
    main()
