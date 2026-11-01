import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_RUN = 3

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
        "name": "The Diplomat (亞太防務)",
        "url": "https://thediplomat.com/category/asia-defense/feed/",
        "color": 0xB71C1C
    },
    {
        "name": "SCMP (中國與軍事)",
        "url": "https://www.scmp.com/rss/4/feed",
        "color": 0xF57F17
    },
    {
        "name": "Defense News",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
        "color": 0x2D6A4F
    }
]

# 2. 灰色地帶、海警與防務關鍵字過濾
INCLUDE_PATTERN = re.compile(
    r"(?i)\b("
    r"coast guard|ccg|pcg|cga|maritime militia|militia vessel|water cannon|ramming|"
    r"gr[ae]y[- ]zone|adiz|air defense identification zone|median line|incursion|"
    r"standoff|blockade|joint patrol|encirclement|swarming|harassment|"
    r"second thomas|sabina shoal|scarborough|spratly|paracel|mischief reef|"
    r"fiery cross|subi reef|ren'?ai|xianbin|huangyan|"
    r"taiwan strait|south china sea|east china sea|bashi channel|luzon strait|"
    r"first island chain|senkaku|diaoyu|"
    r"pla|plan|plaf|military|defense|pentagon|missile|navy|air force|drills|"
    r"carrier|drone|taiwan|ukraine|russia"
    r")\b"
)

EXCLUDE_PATTERN = re.compile(
    r"(?i)(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle)"
)

def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

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

def analyze_with_groq(orig_title, orig_summary):
    """呼叫 Groq API (鎖定 qwen/qwen3.8-27b) 產出結構化繁體中文三點式情報摘要"""
    if not GROQ_API_KEY:
        print("未偵測到 GROQ_API_KEY！請檢查 GitHub Secrets。")
        return None

    # 明確指定帳號內可用的 Qwen 模型
    model_name = "qwen/qwen3.8-27b"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = """你是一名專精印太地緣政治與防務軍事的情報分析官。
請分析防務情報，嚴格以繁體中文輸出符合以下結構的 JSON 物件（不要包含任何額外說明）：
{
  "title_zh": "精準且符合軍事術語的繁體中文標題",
  "region": "標註衝突或事件所屬海域/戰略空域（如：台海海峽中線、南海仁愛暗沙、巴士海峽、東海釣魚台、烏克蘭前線、紅海、印太地區等）",
  "actors": "標註主要對峙或涉事主體（格式為：主體 A vs 主體 B，例如：中國海警 vs 菲律賓海巡、共軍軍機 vs 國軍防空、美軍第7艦隊 vs 中國海軍、美軍 vs 胡塞武裝）",
  "points": [
    "第一點：核心事件與載具/武器/裝備行動細節",
    "第二點：戰術意圖、官方敘事或灰色地帶施壓手法",
    "第三點：對第一島鏈防務、戰略航道或地緣平衡的影響"
  ]
}"""

    user_content = f"新聞標題：{orig_title}\n新聞內容：{orig_summary[:1500]}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    try:
        print(f"正在呼叫 Groq [{model_name}] 進行情報分析...")
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"].strip()
            
            # 防呆去除 markdown 標籤
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)
                
            return json.loads(raw_text.strip())
        else:
            print(f"Groq API 回傳錯誤: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Groq 分析異常: {e}")

    return None

def send_to_discord(entry, feed_info):
    orig_title = entry.get("title", "No Title")
    link = entry.get("link", "")
    orig_summary = clean_html(entry.get("summary", entry.get("description", "")))
    thumb_url = extract_thumbnail(entry)

    intel_data = analyze_with_groq(orig_title, orig_summary)

    fields = []
    if intel_data and "title_zh" in intel_data and "points" in intel_data:
        title = intel_data["title_zh"]
        points_text = "\n".join([f"🔹 {p}" for p in intel_data["points"]])
        description = f"{points_text}\n\n*原標題：{orig_title}*"
        
        region = intel_data.get("region", "全球 / 未特定海域")
        actors = intel_data.get("actors", "未特定實體")
        fields = [
            {"name": "📍 戰略海空域", "value": f"`{region}`", "inline": True},
            {"name": "⚔️ 涉事實體", "value": f"`{actors}`", "inline": True}
        ]
    else:
        title = orig_title
        description = orig_summary[:250] + "..."

    embed = {
        "author": {"name": feed_info["name"]},
        "title": title[:256],
        "url": link,
        "description": description[:2000],
        "color": feed_info["color"],
        "footer": {"text": "即時防務情報 • AI 灰色地帶觀測 (Groq)"}
    }
    
    if fields:
        embed["fields"] = fields

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
                    time.sleep(1)
            else:
                break

    if new_ids:
        history.extend(new_ids)
        save_history(history)
        print(f"更新完畢，本次共記錄 {len(new_ids)} 筆項目。")

if __name__ == "__main__":
    # 單筆強制測試
    test_entry = {
        "id": "test-force-groq-qwen-01",
        "title": "China Coast Guard and PLA Navy Conduct Joint Blockade Drills Near Taiwan Strait",
        "link": "[https://www.defense.gov](https://www.defense.gov)",
        "summary": "Chinese military vessels and coast guard cutters conducted joint encirclement drills around Taiwan, deploying water cannons and simulated missile strikes across the median line to test gray-zone escalation."
    }
    test_feed = {
        "name": "測試情報源 (Groq Qwen)",
        "color": 0xFF0000
    }
    print("=== 開始強制測試發送 (Groq Qwen) ===")
    send_to_discord(test_entry, test_feed)
    print("=== 強制測試結束 ===")
