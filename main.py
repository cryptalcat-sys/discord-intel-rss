import os
import re
import json
import time
import socket
import requests
import feedparser
from bs4 import BeautifulSoup

# 設定全域網路底層逾時為 15 秒，嚴禁無限期等待卡死
socket.setdefaulttimeout(15)

# ==================== 1. 環境變數與核心設定 ====================
WEBHOOK_MILITARY = os.environ.get("DISCORD_WEBHOOK_URL")
WEBHOOK_POLITICS = os.environ.get("DISCORD_WEBHOOK_POLITICS") or os.environ.get("DISCORD_WEBHOOK_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_CHANNEL = 2  # 每個頻道每次執行最多推播 2 則
MAX_ARTICLE_AGE_HOURS = 48  # 只接受 48 小時內發布的新文章（封殺陳年舊聞）
# ==================== 2. 訂閱來源清單 (18 組新聞、智庫與影音) ====================
FEEDS = [
    # ==================== 🛡️ 戰略與軍聞頻道 (印太核心 70% + 全球防務 30%) ====================
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
        "name": "Breaking Defense (全域防務科技)",
        "url": "https://breakingdefense.com/feed/",
        "channel": "military",
        "color": 0x0B3C5D
    },
    {
        "name": "RUSI (英國皇家三軍防務研究所)",
        "url": "https://www.rusi.org/rss/all",
        "channel": "military",
        "color": 0x8B0000
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
    # --- YouTube 專題影音 ---
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

    # ==================== 🏛️ 政局觀測所 (印太核心 + 全球戰略視野) ====================
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
        "name": "Atlantic Council (大西洋理事會)",
        "url": "https://www.atlanticcouncil.org/feed/",
        "channel": "politics",
        "color": 0x2A4D69
    },
    {
        "name": "ECFR (歐洲對外關係委員會)",
        "url": "https://ecfr.eu/feed/",
        "channel": "politics",
        "color": 0x0055A5
    },
    {
        "name": "Carnegie Endowment (卡內基國際和平)",
        "url": "https://carnegieendowment.org/rss/solr",
        "channel": "politics",
        "color": 0x4A6984
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
    # --- YouTube 智庫與國際戰略影音 ---
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
    # ---------------- 1. 印太第一島鏈與灰色地帶衝突 (70% 核心) ----------------
    r"taiwan strait|south china sea|east china sea|first island chain|"
    r"bashi channel|miyako strait|luzon strait|tsushima strait|"
    r"coast guard|ccg|pcg|cga|maritime militia|militia vessel|water cannon|ramming|"
    r"gr[ae]y[- ]zone|adiz|air defense identification zone|median line|incursion|"
    r"standoff|blockade|joint patrol|encirclement|swarming|harassment|"
    r"second thomas|sabina shoal|scarborough|spratly|paracel|mischief reef|"
    r"fiery cross|subi reef|ren'?ai|xianbin|huangyan|senkaku|diaoyu|"
    r"kinmen|matsu|pratas|taiping island|"
    r"eastern theater command|southern theater command|indo[- ]pacific command|"
    r"joint sword|han kuang|balikatan|rimpac|live[- ]fire|drills|war game|"
    # ---------------- 2. 常規海空載具與現代作戰編隊 ----------------
    r"navy|naval|plan|fleet|destroyer|frigate|corvette|cutter|"
    r"carrier|aircraft carrier|amphibious|landing ship|marines|"
    r"submarine|\bssn\b|\bssbn\b|anti[- ]submarine|\basw\b|torpedo|sonar|"
    r"air force|plaf|fighter jet|bomber|stealth aircraft|"
    r"f[- ]35|f[- ]16|j[- ]20|j[- ]35|b[- ]21|h[- ]6k|su[- ]57|"
    # ---------------- 3. 全球實戰經驗：無人戰術、電戰與防空反導 (30% 全球) ----------------
    r"drone|\buav\b|\busv\b|\buuv\b|unmanned|loitering munition|\bfpv\b|"
    r"counter[- ]drone|\bc[- ]uas\b|electronic warfare|radar jamming|spectrum|"
    r"missile|ballistic missile|cruise missile|hypersonic|\bhgv\b|"
    r"air defense|patriot|nasams|thaad|aegis|himars|harpoon|tomahawk|sm[- ]6|pac[- ]3|"
    r"cjadc2|command and control|multi[- ]domain|space force|counter[- ]space|"
    # ---------------- 4. 全球戰略咽喉與兵力牽制熱點 (30% 全球) ----------------
    r"red sea|bab el[- ]mandeb|strait of hormuz|persian gulf|black sea|baltic sea|"
    r"giuk gap|suwalki gap|arctic defense|"
    r"houthi|pentagon|nato|nuclear triad|deterrence"
    r")\b"
)

POLITICS_INCLUDE = re.compile(
    r"(?i)\b("
    # ---------------- 1. 核心大選、政權更替與民意板塊 (在地政治核心) ----------------
    r"general election|presidential election|midterm election|snap election|"
    r"primary election|referendum|ballot|voter turnout|exit poll|"
    r"coalition government|ruling party|opposition party|majority government|"
    r"hung parliament|vote of no confidence|dissolve parliament|dissolution|"
    r"cabinet reshuffle|ouster|impeachment|lame duck|transition of power|"
    r"inauguration|political crisis|constitutional crisis|democratic backsliding|"
    r"authoritarian|polarization|populism|nationalist|civil unrest|coup d'?etat|"
    # ---------------- 2. 各國核心政權首腦、內閣與國會決策機構 ----------------
    r"prime minister|chancellor|president[- ]elect|premiership|parliamentary|"
    r"congress|senate|house of representatives|capitol hill|white house|"
    r"diet\b|bundestag|national assembly|european parliament|knesset|"
    r"politburo|standing committee|national people's congress|\bnpc\b|cppcc|"
    r"state council|national security council|\bnsc\b|ministry of foreign affairs|"
    # ---------------- 3. 台海法案、同盟承諾與防務政策 ----------------
    r"taiwan relations act|taiwan policy act|taipei act|taiwan assurance act|"
    r"six assurances|ndaa|national defense authorization act|"
    r"foreign military financing|\bfmf\b|presidential drawdown authority|\bpda\b|"
    r"arms sale|cross[- ]strait|status quo|one china policy|"
    # ---------------- 4. 半導體科技戰、先進封裝與供應鏈自主 ----------------
    r"chips act|semiconductor|advanced chip|ai chip|export control|entity list|"
    r"lithography|extreme ultraviolet|\beuv\b|advanced packaging|"
    r"tsmc|asml|smic|outbound investment|technology transfer|"
    r"decoupling|de[- ]risking|friend[- ]shoring|supply chain resilience|"
    r"clean network|telecom ban|rare earth|critical minerals|"
    # ---------------- 5. 跨國同盟機制與多邊體系 ----------------
    r"quad|aukus|g7|brics|nato|un security council|asean|ap4|"
    r"beijing|kremlin|washington|tokyo|seoul|manila|canberra|brussels|"
    # ---------------- 6. 全球戰略連動：跨大西洋、中俄朝軸心與地緣經貿 ----------------
    r"transatlantic|eu[- ]china|european union|european commission|"
    r"russia[- ]china|sino[- ]russian|north korea[- ]russia|axis of resistance|"
    r"red sea|bab el[- ]mandeb|strait of hormuz|suez canal|malacca strait|"
    r"sanction|secondary sanction|embargo|summit|bilateral|diplomat|treaty|sovereignty|"
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

def is_entry_fresh(entry, max_hours=48):
    """檢查 RSS 條目的發布時間是否在指定小時數內"""
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed_time:
        # 若來源未提供時間標籤，預設允許通過，避免漏抓
        return True
    
    try:
        entry_timestamp = time.mktime(parsed_time)
        age_in_seconds = time.time() - entry_timestamp
        # 若發布時間距今超過 max_hours 小時，判定為過期舊文
        return age_in_seconds <= (max_hours * 3600)
    except Exception:
        return True
        
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
  "topic_key": "歸納本事件核心主體與事件動作（4-8字，如：美中晶片管制、G7涉台聲明、菲律賓南海仲裁、東協緬甸危機失能）",
  "title_zh": "【必須翻譯為繁體中文】請將原標題完整翻譯並提煉為具宏觀政治洞察的繁體中文標題，嚴格禁止保留英文原標題",
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
  "title_zh": "【必須翻譯為繁體中文】請將原標題完整翻譯並提煉為具軍事術語的繁體中文標題，嚴格禁止保留英文原標題",
  "region": "標註衝突所屬海空域",
  "actors": "標註主要對峙實體（格式：主體 A vs 主體 B）",
  "points": [
    "第一點：核心事件與載具/武器裝備行動細節",
    "第二點：戰術意圖、官方敘事或灰色地帶施壓手法",
    "第三點：對第一島鏈防務、戰略航道或地緣平衡的影響"
  ]
}"""

    user_content = f"新聞標題：{orig_title}\n新聞內容：{orig_summary[:800]}"
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

    # 多鍵值相容：防止模型返回 "title" 或 "chinese_title"
    raw_title_zh = (
        intel_data.get("title_zh")
        or intel_data.get("title")
        or intel_data.get("chinese_title")
        or intel_data.get("title_tw")
    )

    # 檢查標題是否真的包含中文字元
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", str(raw_title_zh or "")))

    topic_key = str(intel_data.get("topic_key", "")).strip()

    if raw_title_zh and has_chinese:
        title = str(raw_title_zh).strip()
    elif topic_key:
        # 若模型偷懶給了英文標題，直接借用已提煉好的中文 topic_key 組裝
        title = f"【情報研判】{topic_key}"
    else:
        title = orig_title.strip()
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

    max_article_age = globals().get("MAX_ARTICLE_AGE_HOURS", 48)

    for feed_info in FEEDS:
        channel_type = feed_info.get("channel", "military")

        # 雙頻道皆達到上限時提前終止巡邏
        if all(count >= MAX_POSTS_PER_CHANNEL for count in channel_counts.values()):
            print("🏁 雙頻道皆已達本次推播上限 (各 2 則)，結束本輪巡邏。")
            break

        # 單一頻道若已達上限則跳過該頻道的後續來源
        if channel_counts[channel_type] >= MAX_POSTS_PER_CHANNEL:
            continue

        print(f"🔍 正在檢查 [{channel_type}]: {feed_info['name']}")

        target_feed_url = resolve_feed_url(feed_info["url"])

        # 🛡️ 防卡死與防 403 雙層防線
        parsed = None
        try:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*"
            }
            r = requests.get(target_feed_url, headers=req_headers, timeout=12)
            if r.status_code == 200:
                parsed = feedparser.parse(r.content)
            elif r.status_code == 403:
                # 若遭反爬蟲擋下，退回由 feedparser 內建網路模組重試
                print(f"⚠️ 來源回應 403，改由 feedparser 原生解析: {feed_info['name']}")
                parsed = feedparser.parse(target_feed_url)
            else:
                print(f"⚠️ 來源回應 HTTP {r.status_code}，跳過: {feed_info['name']}")
                continue
        except Exception as e:
            print(f"⚠️ 抓取來源逾時或連線失敗 ({feed_info['name']}): {e}，跳過。")
            continue

        if not parsed or not parsed.entries:
            continue

        for entry in parsed.entries:
            if channel_counts[channel_type] >= MAX_POSTS_PER_CHANNEL:
                break

            entry_id = entry.get("id", entry.get("link", ""))
            if not entry_id or entry_id in existing_ids or entry_id in new_ids:
                continue

            # 🛑 時效守門員：只抓 48 小時內新文章，封殺數月前的陳年舊聞
            if "is_entry_fresh" in globals() and not is_entry_fresh(entry, max_hours=max_article_age):
                new_ids.append(entry_id)
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            content_to_check = f"{title} {summary}"

            # 首次運行建立基準線，只記錄不推播，防止海量歷史洗版
            if is_initial_run:
                new_ids.append(entry_id)
                continue

            # 排除廣告、娛樂與民用航空等無關雜訊
            if EXCLUDE_PATTERN.search(content_to_check):
                new_ids.append(entry_id)
                continue

            # 命中關鍵字匹配 (70/30 架構 + 在地政治動態)
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

            # 跨來源事件語意去重檢查（24 小時事件記憶池）
            combined_events = recent_events + new_events
            if is_duplicate_event(topic_key, combined_events):
                print(f"⏩ 命中同事件冷卻池：[{topic_key}] 近 24 小時內已推播過相關報導，略過此來源。")
                new_ids.append(entry_id)  # 標記已讀，避免後續重複比對
                continue

            # 正式推播至 Discord
            success = send_to_discord(entry, feed_info, intel_data)
            if success:
                print(f"✅ [{channel_type}] 已發送 ({channel_counts[channel_type] + 1}/{MAX_POSTS_PER_CHANNEL}): {title}")
                new_ids.append(entry_id)
                if topic_key:
                    new_events.append({"key": topic_key, "timestamp": time.time()})
                channel_counts[channel_type] += 1
                time.sleep(8)
            else:
                print(f"❌ [{channel_type}] 推播失敗，不記錄於歷史。")

    # 寫入歷史資料庫與事件指紋池
    if new_ids:
        history["ids"] = list(existing_ids.union(new_ids))
        history["events"] = recent_events + new_events
        save_history(history)
        print(f"💾 歷史更新完畢，本次共記錄 {len(new_ids)} 筆項目，新增 {len(new_events)} 個獨立事件指紋。")

    print(f"📊 本輪推播統計：軍聞 {channel_counts['military']}/{MAX_POSTS_PER_CHANNEL} 則 | 政局 {channel_counts['politics']}/{MAX_POSTS_PER_CHANNEL} 則。")

if __name__ == "__main__":
    main()
