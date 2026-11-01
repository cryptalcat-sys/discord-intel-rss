import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

# Webhook 雙軌路由
WEBHOOK_MILITARY = os.environ.get("DISCORD_WEBHOOK_URL")
WEBHOOK_POLITICS = os.environ.get("DISCORD_WEBHOOK_POLITICS") or os.environ.get("DISCORD_WEBHOOK_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_RUN = 3

# 1. 訂閱來源清單（以 channel 標註分類分流）
FEEDS = [
    # --- 戰略與軍聞 ---
    {
        "name": "The War Zone",
        "url": "https://www.twz.com/feed",
        "channel": "military",
        "color": 0x1A365D
    },
    {
        "name": "USNI News (海軍學會)",
        "url": "https://news.usni.org/feed",
        "channel": "military",
        "color": 0x003366
    },
    {
        "name": "Defense News",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
        "channel": "military",
        "color": 0x2D6A4F
    },
    # --- 政局觀測所 ---
    {
        "name": "The Diplomat (外交政局)",
        "url": "https://thediplomat.com/category/diplomacy/feed/",
        "channel": "politics",
        "color": 0x8E24AA
    },
    {
        "name": "SCMP (中國外交與大國博弈)",
        "url": "https://www.scmp.com/rss/91/feed",
        "channel": "politics",
        "color": 0xD84315
    },
    {
        "name": "BBC News (國際外交)",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "channel": "politics",
        "color": 0x455A64
    }
]

# 2. 關鍵字過濾規範
MILITARY_INCLUDE = re.compile(
    r"(?i)\b("
    r"coast guard|ccg|pcg|cga|maritime militia|water cannon|ramming|"
    r"gr[ae]y[- ]zone|adiz|median line|incursion|standoff|blockade|"
    r"second thomas|sabina shoal|scarborough|taiwan strait|south china sea|"
    r"first island chain|pla|plan|plaf|missile|carrier|drone|taiwan|ukraine"
    r")\b"
)

POLITICS_INCLUDE = re.compile(
    r"(?i)\b("
    r"sanction|embargo|summit|bilateral|diplomat|treaty|sovereignty|"
    r"election|parliament|congress|white house|beijing|kremlin|"
    r"g7|brics|nato|un security council|quad|aukus|asean|"
    r"trade war|tariff|semiconductor|taiwan relations act|geopolit"
    r")\b"
)

EXCLUDE_PATTERN = re.compile(
    r"(?i)(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle|entertainment|sports)"
)

def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

def clean_url(raw_url):
    """防呆過濾：從字串擷取純淨標準的 http/https 網址"""
    if not raw_url:
        return ""
    match = re.search(r"https?://[^\s\]\)\"\'<>]+", str(raw_url).strip())
    return match.group(0) if match else raw_url.strip()

def analyze_with_groq(orig_title, orig_summary, channel_type):
    """呼叫 Groq API (qwen/qwen3.8-27b) 根據頻道屬性產出專屬情報摘要"""
    if not GROQ_API_KEY:
        print("❌ 未偵測到 GROQ_API_KEY！")
        return None

    model_name = "qwen/qwen3.8-27b"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    if channel_type == "politics":
        system_prompt = """你是一名專精國際關係與地緣政治的資深情報分析官。
請分析該政經外交情報，嚴格以繁體中文輸出符合以下結構的 JSON 物件：
{
  "title_zh": "精準且具宏觀政治洞察的繁體中文標題",
  "region": "標註受影響之核心地緣區域或國際陣營（如：美中博弈前線、印太同盟、歐盟體系、台海周邊、中東政局等）",
  "actors": "標註核心博弈實體（格式：主體 A vs 主體 B，例如：華府 vs 北京、歐盟執委會 vs 俄羅斯、執政黨 vs 在野陣營）",
  "points": [
    "第一點：核心外交決策、法案制裁或政局事件事實",
    "第二點：雙方外交攻防、政策意圖或國家利益折衝",
    "第三點：對區域地緣政治平衡、國際秩序或經貿供應鏈的長期衝擊"
  ]
}"""
    else:
        system_prompt = """你是一名專精印太地緣防務軍事的情報分析官。
請分析防務情報，嚴格以繁體中文輸出符合以下結構的 JSON 物件：
{
  "title_zh": "精準且符合軍事術語的繁體中文標題",
  "region": "標註衝突所屬海空域（如：台海中線、南海仁愛暗沙、巴士海峽、烏克蘭前線等）",
  "actors": "標註主要對峙實體（格式：主體 A vs 主體 B，如：中國海警 vs 菲律賓海巡）",
  "points": [
    "第一點：核心事件與載具/武器裝備行動細節",
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
        "temperature": 0.2,
        "max_tokens": 500
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            raw_text = resp.json()["choices"][0]["message"]["content"].strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)
            return json.loads(raw_text.strip())
        else:
            print(f"❌ Groq API 錯誤: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"❌ Groq 分析異常: {e}")

    return None

def send_to_discord(entry, feed_info):
    channel_type = feed_info.get("channel", "military")
    webhook_target = WEBHOOK_POLITICS if channel_type == "politics" else WEBHOOK_MILITARY

    if not webhook_target:
        print(f"❌ 未設定 [{channel_type}] 對應的 Webhook，略過發送。")
        return False

    orig_title = entry.get("title", "No Title")
    link = clean_url(entry.get("link", ""))
    orig_summary = clean_html(entry.get("summary", entry.get("description", "")))

    intel_data = analyze_with_groq(orig_title, orig_summary, channel_type)

    if intel_data and isinstance(intel_data, dict):
        title = str(intel_data.get("title_zh") or orig_title).strip()
        region_label = "🌐 戰略地緣陣營" if channel_type == "politics" else "📍 戰略海空域"
        actors_label = "⚖️ 核心博弈實體" if channel_type == "politics" else "⚔️ 涉事實體"
        
        region_str = str(intel_data.get("region") or "全球 / 區域政局").strip()
        actors_str = str(intel_data.get("actors") or "未特定實體").strip()

        raw_points = intel_data.get("points", [])
        formatted_points = []
        if isinstance(raw_points, list):
            for p in raw_points:
                cleaned = str(p).strip().lstrip("🔹🔷-*• ")
                if cleaned:
                    formatted_points.append(f"🔷 {cleaned}")

        points_text = "\n".join(formatted_points) if formatted_points else f"🔷 {orig_summary[:200]}..."

        description = (
            f"{region_label}：`{region_str}`\n"
            f"{actors_label}：`{actors_str}`\n\n"
            f"{points_text}\n\n"
            f"🔗 **原文連結**：{link}\n\n"
            f"*原標題：{orig_title}*"
        )
    else:
        title = orig_title
        description = (
            f"{orig_summary[:250]}...\n\n"
            f"🔗 **原文連結**：{link}\n\n"
            f"*原標題：{orig_title}*"
        )

    bot_name = "國際政局觀測所" if channel_type == "politics" else "戰略防務快報"
    footer_text = "即時政局情報 • AI 地緣外交研判 (Groq)" if channel_type == "politics" else "即時防務情報 • AI 灰色地帶觀測 (Groq)"

    embed = {
        "title": title[:256],
        "url": link,
        "description": description[:2000],
        "color": int(feed_info.get("color", 0x1A365D)),
        "footer": {"text": footer_text}
    }

    payload = {
        "username": bot_name,
        "embeds": [embed]
    }

    try:
        resp = requests.post(webhook_target, json=payload, timeout=10)
        print(f"📩 [{channel_type}] Discord 推播回應: HTTP {resp.status_code}")
        return resp.status_code in [200, 204]
    except Exception as e:
        print(f"❌ Discord 發送異常: {e}")
        return False

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
    history = load_history()
    is_initial_run = len(history) == 0
    new_ids = []

    for feed_info in FEEDS:
        channel_type = feed_info.get("channel", "military")
        print(f"正在檢查 [{channel_type}]: {feed_info['name']}")
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

            # 依頻道套用對應的篩選正則
            matcher = POLITICS_INCLUDE if channel_type == "politics" else MILITARY_INCLUDE
            if not matcher.search(content_to_check):
                new_ids.append(entry_id)
                continue

            if sent_count < MAX_POSTS_PER_RUN:
                success = send_to_discord(entry, feed_info)
                if success:
                    print(f"已發送 AI 情報: {title}")
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
    main()
