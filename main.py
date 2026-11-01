import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_RUN = 3

FEEDS = [
    # --- 北美即時軍武 ---
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
    # --- 亞太 / 第一島鏈防務 ---
    {
        "name": "The Diplomat (亞太防務)",
        "url": "https://thediplomat.com/category/asia-defense/feed/",
        "color": 0xB71C1C  # 磚紅
    },
    {
        "name": "SCMP (中國與軍事)",
        "url": "https://www.scmp.com/rss/4/feed",
        "color": 0xF57F17  # 琥珀橙
    },
    {
        "name": "Lowy (澳洲洛伊智庫)",
        "url": "https://www.lowyinstitute.org/the-interpreter/rss.xml",
        "color": 0x4A148C  # 深紫
    },
    {
        "name": "Focus Taiwan (台灣國防要聞)",
        "url": "https://focustaiwan.tw/rss/politics.aspx",
        "color": 0x00695C  # 墨綠
    }
]

INCLUDE_PATTERN = re.compile(
    r"(?i)\b(military|defense|pentagon|pla|missile|navy|air force|drills|sanctions|geopolitics|ukraine|russia|taiwan|carrier|drone|war|strait)\b"
)
EXCLUDE_PATTERN = re.compile(
    r"(?i)(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle)"
)

def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

def analyze_with_gemini(orig_title, orig_summary):
    """呼叫 Gemini 進行防務情報 3 點式摘要"""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
你是一名專精地緣政治與國防軍事的情報分析官。請閱讀以下防務新聞，產出繁體中文情報摘要。
請嚴格輸出符合以下結構的 JSON 格式（不要包含額外文字或 markdown 標籤）：
{{
  "title_zh": "精準且符合軍事術語的繁體中文標題",
  "points": [
    "第一點：核心事件與裝備/作戰/採購細節",
    "第二點：背後戰略意圖、軍工背景或官方立場",
    "第三點：對區域安全、第一島鏈或地緣格局的影響研判"
  ]
}}

新聞標題：{orig_title}
新聞內容：{orig_summary[:1500]}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json"
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)
        else:
            print(f"Gemini API 回傳錯誤: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Gemini 分析異常: {e}")
    return None

def extract_thumbnail(entry):
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
    orig_summary = clean_html(entry.get("summary", entry.get("description", "")))
    thumb_url = extract_thumbnail(entry)

    # 執行 AI 情報重點萃取
    intel_data = analyze_with_gemini(orig_title, orig_summary)

    if intel_data and "title_zh" in intel_data and "points" in intel_data:
        title = intel_data["title_zh"]
        points_text = "\n".join([f"🔹 {p}" for p in intel_data["points"]])
        description = f"{points_text}\n\n*原標題：{orig_title}*"
    else:
        # 降級處理：若 AI 失敗則直接使用原生英文截斷
        title = orig_title
        description = orig_summary[:250] + "..."

    embed = {
        "author": {"name": feed_info["name"]},
        "title": title[:256],
        "url": link,
        "description": description[:2000],
        "color": feed_info["color"],
        "footer": {"text": "即時防務情報 • AI 三點式戰略摘要"}
    }
    if thumb_url:
        embed["thumbnail"] = {"url": thumb_url}

    payload = {
        "username": "全球情報觀測站",
        "embeds": [embed]
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    return resp.status_code in [200, 204]

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

            if is_initial_run:
                new_ids.append(entry_id)
                continue

            if EXCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            if not INCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            if sent_count < MAX_POSTS_PER_RUN:
                success = send_to_discord(entry, feed_info)
                if success:
                    print(f"已發送 AI 情報簡報: {title}")
                    new_ids.append(entry_id)
                    sent_count += 1
                    time.sleep(3)  # 間隔 3 秒，避免觸發 LLM API 與 Discord 速率限制
            else:
                break

    if new_ids:
        history.extend(new_ids)
        save_history(history)
        print(f"更新完畢，本次共記錄 {len(new_ids)} 筆項目。")

if __name__ == "__main__":
    main()
