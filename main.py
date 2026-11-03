import os
import re
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

# ==================== 1. 環境變數與核心設定 ====================
WEBHOOK_MILITARY = os.environ.get("DISCORD_WEBHOOK_URL")
WEBHOOK_POLITICS = os.environ.get("DISCORD_WEBHOOK_POLITICS") or os.environ.get("DISCORD_WEBHOOK_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_CHANNEL = 2  # 每個頻道每次執行最多推播 2 則

# ==================== 2. 訂閱來源清單 (18 組新聞、智庫與影音) ====================
FEEDS = [
    # -------------------- 🛡️ 戰略與軍聞頻道 --------------------
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
    {
        "name": "Naval News (全球海事防務)",
        "url": "https://www.navalnews.com/feed/",
        "channel": "military",
        "color": 0x0F4C81
    },
    {
        "name": "The Diplomat (亞太防務)",
        "url": "https://thediplomat.com/category/asia-defense/feed/",
        "channel": "military",
        "color": 0x900C3F
    },
    {
        "name": "Perun (防務戰略與後勤)",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCC3ehuUksTyQ7bbjGntmx3Q",
        "channel": "military",
        "color": 0xD32F2F
    },
    {
        "name": "Task & Purpose (軍事戰術動態)",
        "url": "https://www.youtube.com/@Taskandpurpose",
        "channel": "military",
        "color": 0x1976D2
    },
    {
        "name": "Defense Updates (尖端裝備速報)",
        "url": "https://www.youtube.com/@DefenseUpdates",
        "channel": "military",
        "color": 0x388E3C
    },
    {
        "name": "公視有話好說 (國防院/時事深度座談)",
        "url": "https://www.youtube.com/@ptstalk",
        "channel": "military",
        "color": 0x00897B
    },

    # -------------------- 🏛️ 政局觀測所 --------------------
    {
        "name": "Foreign Affairs (外交事務)",
        "url": "https://www.foreignaffairs.com/rss.xml",
        "channel": "politics",
        "color": 0x1A237E
    },
    {
        "name": "CSIS 戰略與國際研究中心",
        "url": "https://www.csis.org/rss.xml",
        "channel": "politics",
        "color": 0x002B49
    },
    {
        "name": "Jamestown China Brief (中共戰略簡報)",
        "url": "https://jamestown.org/feed/",
        "channel": "politics",
        "color": 0xB71C1C
    },
    {
        "name": "War on the Rocks (戰略評估)",
        "url": "https://warontherocks.com/feed/",
        "channel": "politics",
        "color": 0x37474F
    },
    {
        "name": "Lowy Interpreter (洛伊印太觀測)",
        "url": "https://www.lowyinstitute.org/the-interpreter/rss.xml",
        "channel": "politics",
        "color": 0xFF6F00
    },
    {
        "name": "East Asia Forum (東亞論壇)",
        "url": "https://eastasiaforum.org/feed/",
        "channel": "politics",
        "color": 0x00695C
    },
    {
        "name": "The Diplomat (外交政局)",
        "url": "https://thediplomat.com/category/diplomacy/feed/",
        "channel": "politics",
        "color": 0x8E24AA
    },
    {
        "name": "CSIS 官方戰略影音",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCr5jq6MC_VCe1c5ciIZtk_w",
        "channel": "politics",
        "color": 0x002B49
    },
    {
        "name": "TaiwanPlus News (台灣國際防務專題)",
        "url": "https://www.youtube.com/@TaiwanPlusNews",
        "channel": "politics",
        "color": 0x7B1FA2
    }
]

# ==================== 3. 關鍵字過濾規範 ====================
MILITARY_INCLUDE = re.compile(
    r"(?i)\b("
    r"coast guard|ccg|pcg|cga|maritime militia|militia vessel|water cannon|ramming|"
    r"gr[ae]y[- ]zone|adiz|air defense identification zone|median line|incursion|"
    r"standoff|blockade|joint patrol|encirclement|swarming|harassment|"
    r"combat readiness patrol|encircle|airspace violation|"
    r"taiwan strait|south china sea|east china sea|first island chain|"
    r"bashi channel|miyako strait|luzon strait|tsushima strait|"
    r"second thomas|sabina shoal|scarborough|spratly|paracel|mischief reef|"
    r"fiery cross|subi reef|ren'?ai|xianbin|huangyan|senkaku|diaoyu|"
    r"kinmen|matsu|pratas|taiping island|"
    r"navy|naval|plan|fleet|destroyer|frigate|corvette|cutter|"
    r"carrier|aircraft carrier|amphibious|landing ship|"
    r"submarine|\bssn\b|\bssbn\b|anti[- ]submarine|\basw\b|torpedo|sonar|"
    r"air force|plaf|fighter jet|bomber|stealth aircraft|"
    r"f[- ]35|f[- ]16|j[- ]20|j[- ]35|b[- ]21|h[- ]6k|"
    r"missile|ballistic missile|cruise missile|hypersonic|"
    r"air defense|patriot missile|nasams|thaad|aegis|himars|harpoon|"
    r"rocket force|plarf|strategic rocket|"
    r"drone|\buav\b|\busv\b|\buuv\b|unmanned|loitering munition|"
    r"counter[- ]drone|\bc[- ]uas\b|electronic warfare|radar jamming|"
    r"eastern theater command|southern theater command|indo[- ]pacific command|\bpentagon\b|"
    r"joint sword|han kuang|balikatan|rimpac|live[- ]fire|drills|war game|"
    r"taiwan|ukraine|russia"
    r")\b"
)

POLITICS_INCLUDE = re.compile(
    r"(?i)\b("
    r"taiwan relations act|taiwan policy act|taipei act|taiwan assurance act|"
    r"six assurances|ndaa|national defense authorization act|"
    r"foreign military financing|\bfmf\b|presidential drawdown authority|\bpda\b|"
    r"arms sale|cross[- ]strait|status quo|one china policy|"
    r"chips act|semiconductor|advanced chip|ai chip|export control|entity list|"
    r"lithography|extreme ultraviolet|\beuv\b|advanced packaging|"
    r"tsmc|asml|smic|outbound investment|technology transfer|"
    r"decoupling|de[- ]risking|friend[- ]shoring|supply chain resilience|"
    r"clean network|telecom ban|"
    r"sanction|embargo|summit|bilateral|diplomat|treaty|sovereignty|"
    r"election|parliament|congress|white house|state department|"
    r"beijing|kremlin|politburo|national security council|"
    r"g7|brics|nato|un security council|quad|aukus|asean|"
    r"trade war|tariff|economic coercion|weaponized interdependence|"
    r"geopolit"
    r")\b"
)

EXCLUDE_PATTERN = re.compile(
    r"(?i)\b(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle|"
    r"entertainment|sports|box office|smartphone|gaming laptop|geforce|rtx|"
    r"civil aviation|commercial airline|boeing 737|airbus a320|flight delay|"
    r"video game|gameplay|war thunder|call of duty)\b"
)

# ==================== 4. 輔助函式與網址解析 ====================
def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

def clean_url(raw_url):
    if not raw_url:
        return ""
    match = re.search(r"https?://[^\s\]\)\"\'<>]+", str(raw_url).strip())
    return match.group(0) if match else raw_url.strip()

def resolve_feed_url(url):
    """若為 YouTube 頻道首頁/handle 網址，自動抓取 channel_id 並轉化為標準 RSS 網址"""
    if "youtube.com" in url and "videos.xml" not in url:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, headers=headers, timeout=10)
            m = re.search(r'["\']channelId["\']:\s*["\'](UC[\w-]+)["\']', r.text) or \
                re.search(r'itemprop="channelId"\s+content="(UC[\w-]+)"', r.text) or \
                re.search(r'/channel/(UC[\w-]+)', r.text)
            if m:
                channel_id = m.group(1)
                print(f"🎬 成功解析 YouTube 頻道 ID [{channel_id}]: {url}")
                return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        except Exception as e:
            print(f"⚠️ 解析 YouTube 網址失敗 ({url}): {e}")
    return url

# ==================== 5. Groq AI 智慧情報分析 (加入核心指紋 topic_key) ====================
def analyze_with_groq(orig_title, orig_summary, channel_type):
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
  "topic_key": "歸納本事件核心主體與事件動作（4-8字，如：美中晶片管制、G7涉台聲明、菲律賓南海仲裁、歐盟對俄制裁）",
  "title_zh": "精準且具宏觀政治洞察的繁體中文標題",
  "region": "標註受影響之核心地緣區域或國際陣營",
  "actors": "標註核心博弈實體（格式：主體 A vs 主體 B）",
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
  "topic_key": "歸納本事件核心載具/行動與地點（4-8字，如：美艦穿越台海、仁愛暗沙海警衝突、漢光無人機兵推、F-16升級採購）",
  "title_zh": "精準且符合軍事術語的繁體中文標題",
  "region": "標註衝突所屬海空域",
  "actors": "標註主要對峙實體（格式：主體 A vs 主體 B）",
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

    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code == 200:
                raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                    raw_text = re.sub(r"\n?```$", "", raw_text)
                return json.loads(raw_text.strip())
            elif resp.status_code == 429:
                print(f"⚠️ 觸發 Groq 限速 (429)，冷卻 15 秒後重試...")
                time.sleep(15)
            else:
                print(f"❌ Groq API 錯誤: {resp.status_code} - {resp.text}")
                break
        except Exception as e:
            print(f"❌ Groq 分析異常: {e}")
            break

    return None

# ==================== 6. 跨媒體語意去重與歷史管理 ====================
def load_history():
    """讀取歷史紀錄，自動相容舊版 list 與新版 dict 結構"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {"ids": data, "events": []}
                return data
        except Exception:
            return {"ids": [], "events": []}
    return {"ids": [], "events": []}

def save_history(history_data):
    """保存歷史紀錄，事件冷卻池僅保留 48 小時以內的事件"""
    current_time = time.time()
    history_data["events"] = [
        ev for ev in history_data.get("events", [])
        if current_time - ev.get("timestamp", 0) < 172800
    ]
    history_data["ids"] = history_data.get("ids", [])[-500:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

def is_duplicate_event(topic_key, recent_events):
    """比對新事件與過去 24 小時內推播事件的字元重疊度"""
    if not topic_key:
        return False
    current_time = time.time()
    candidate_chars = set(topic_key)

    for ev in recent_events:
        # 只比對 24 小時 (86400 秒) 內的事件
        if current_time - ev.get("timestamp", 0) > 86400:
            continue
        past_key = ev.get("key", "")
        past_chars = set(past_key)

        overlap = len(candidate_chars & past_chars)
        min_len = min(len(candidate_chars), len(past_chars))
        # 若核心關鍵字重疊超過 65%，判定為同一事件
        if min_len > 0 and (overlap / min_len) >= 0.65:
            return True
    return False

# ==================== 7. Discord 推播發送 ====================
def send_to_discord(entry, feed_info, intel_data):
    channel_type = feed_info.get("channel", "military")
    webhook_target = WEBHOOK_POLITICS if channel_type == "politics" else WEBHOOK_MILITARY

    if not webhook_target:
        print(f"❌ 未設定 [{channel_type}] 對應的 Webhook，略過發送。")
        return False

    orig_title = entry.get("title", "No Title")
    link = clean_url(entry.get("link", ""))
    orig_summary = clean_html(entry.get("summary", entry.get("description", "")))

    title = str(intel_data.get("title_zh") or orig_title).strip()
    region_label = "🌐 戰略地緣陣營" if channel_type == "politics" else "📍 戰略海空域"
    actors_label = "⚖️ 核心博弈實體" if channel_type == "politics" else "⚔️ 涉事實體"

    region_str = str(intel_data.get("region") or "全球 / 區域動態").strip()
    actors_str = str(intel_data.get("actors") or "未特定實體").strip()

    raw_points = intel_data.get("points", [])
    formatted_points = []
    if isinstance(raw_points, list):
        for p in raw_points:
            cleaned = str(p).strip().lstrip("🔹🔷-*• ")
            if cleaned:
                formatted_points.append(f"🔷 {cleaned}")
    elif isinstance(raw_points, str):
        for line in raw_points.split("\n"):
            cleaned = line.strip().lstrip("🔹🔷-*• ")
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

# ==================== 8. 主排程迴圈 ====================
def main():
    history = load_history()
    existing_ids = set(history.get("ids", []))
    recent_events = history.get("events", [])
    
    is_initial_run = len(existing_ids) == 0
    new_ids = []
    new_events = []

    # 記錄各頻道本次執行的推播總數
    channel_counts = {
        "military": 0,
        "politics": 0
    }

    for feed_info in FEEDS:
        channel_type = feed_info.get("channel", "military")

        # 雙頻道皆達到上限時提前退出
        if all(count >= MAX_POSTS_PER_CHANNEL for count in channel_counts.values()):
            print("🏁 雙頻道皆已達本次推播上限 (各 2 則)，結束本輪巡邏。")
            break

        # 單一頻道已達上限時跳過該頻道的來源
        if channel_counts[channel_type] >= MAX_POSTS_PER_CHANNEL:
            continue

        print(f"正在檢查 [{channel_type}]: {feed_info['name']}")

        target_feed_url = resolve_feed_url(feed_info["url"])
        parsed = feedparser.parse(target_feed_url)

        for entry in parsed.entries:
            if channel_counts[channel_type] >= MAX_POSTS_PER_CHANNEL:
                break

            entry_id = entry.get("id", entry.get("link", ""))
            if not entry_id or entry_id in existing_ids or entry_id in new_ids:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            content_to_check = f"{title} {summary}"

            # 首次運行只記錄不推播，防歷史海量洗版
            if is_initial_run:
                new_ids.append(entry_id)
                continue

            # 排除廣告或娛樂雜訊
            if EXCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            # 命中關鍵字匹配
            matcher = POLITICS_INCLUDE if channel_type == "politics" else MILITARY_INCLUDE
            if not matcher.search(content_to_check):
                new_ids.append(entry_id)
                continue

            # 呼叫 Groq 進行智慧分析與主題指紋提取
            intel_data = analyze_with_groq(title, summary, channel_type)
            if not intel_data or not isinstance(intel_data, dict):
                print(f"⏩ 跳過推播：[{title[:25]}...] AI 分析未就緒，留待下輪處理。")
                continue

            topic_key = str(intel_data.get("topic_key", "")).strip()

            # 跨來源事件語意去重檢查（24 小時記憶池）
            combined_events = recent_events + new_events
            if is_duplicate_event(topic_key, combined_events):
                print(f"⏩ 命中同事件冷卻池：[{topic_key}] 近 24 小時內已推播過相關報導，略過此來源。")
                new_ids.append(entry_id)  # 標記為已讀，防止下次重複讀取
                continue

            # 正式發送推播
            success = send_to_discord(entry, feed_info, intel_data)
            if success:
                print(f"✅ [{channel_type}] 已發送 ({channel_counts[channel_type] + 1}/{MAX_POSTS_PER_CHANNEL}): {title}")
                new_ids.append(entry_id)
                if topic_key:
                    new_events.append({"key": topic_key, "timestamp": time.time()})
                channel_counts[channel_type] += 1
                time.sleep(8)
            else:
                print("推播未完成，不寫入歷史紀錄。")

    if new_ids:
        history["ids"] = list(existing_ids.union(new_ids))
        history["events"] = recent_events + new_events
        save_history(history)
        print(f"歷史更新完畢，本次共記錄 {len(new_ids)} 筆項目，新增 {len(new_events)} 個獨立事件指紋。")

    print(f"📊 本輪推播統計：軍聞 {channel_counts['military']}/{MAX_POSTS_PER_CHANNEL} 則 | 政局 {channel_counts['politics']}/{MAX_POSTS_PER_CHANNEL} 則。")

if __name__ == "__main__":
    main()
