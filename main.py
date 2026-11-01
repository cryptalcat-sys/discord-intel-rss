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
MAX_POSTS_PER_RUN = 2  # 每次每個來源最多抓 2 篇，平滑分散 API 請求

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
    # 灰色地帶、海警與海上民兵
    r"coast guard|ccg|pcg|cga|maritime militia|militia vessel|water cannon|ramming|"
    r"gr[ae]y[- ]zone|adiz|air defense identification zone|median line|incursion|"
    r"standoff|blockade|joint patrol|encirclement|swarming|harassment|"
    r"combat readiness patrol|encircle|airspace violation|"
    # 戰略節點與爭端島礁
    r"taiwan strait|south china sea|east china sea|first island chain|"
    r"bashi channel|miyako strait|luzon strait|tsushima strait|"
    r"second thomas|sabina shoal|scarborough|spratly|paracel|mischief reef|"
    r"fiery cross|subi reef|ren'?ai|xianbin|huangyan|senkaku|diaoyu|"
    r"kinmen|matsu|pratas|taiping island|"
    # 水下與海軍
    r"navy|naval|plan|fleet|destroyer|frigate|corvette|cutter|"
    r"carrier|aircraft carrier|amphibious|landing ship|"
    r"submarine|\bssn\b|\bssbn\b|anti[- ]submarine|\basw\b|torpedo|sonar|"
    # 空權與飛彈
    r"air force|plaf|fighter jet|bomber|stealth aircraft|"
    r"f[- ]35|f[- ]16|j[- ]20|j[- ]35|b[- ]21|h[- ]6k|"
    r"missile|ballistic missile|cruise missile|hypersonic|"
    r"air defense|patriot missile|nasams|thaad|aegis|himars|harpoon|"
    r"rocket force|plarf|strategic rocket|"
    # 無人化、電戰與演訓
    r"drone|\buav\b|\busv\b|\buuv\b|unmanned|loitering munition|"
    r"counter[- ]drone|\bc[- ]uas\b|electronic warfare|radar jamming|"
    r"eastern theater command|southern theater command|indo[- ]pacific command|\bpentagon\b|"
    r"joint sword|han kuang|balikatan|rimpac|live[- ]fire|drills|war game|"
    r"taiwan|ukraine|russia"
    r")\b"
)

POLITICS_INCLUDE = re.compile(
    r"(?i)\b("
    # 台海法案、同盟與防務政策
    r"taiwan relations act|taiwan policy act|taipei act|taiwan assurance act|"
    r"six assurances|ndaa|national defense authorization act|"
    r"foreign military financing|\bfmf\b|presidential drawdown authority|\bpda\b|"
    r"arms sale|cross[- ]strait|status quo|one china policy|"
    # 科技戰、地緣半導體與供應鏈
    r"chips act|semiconductor|advanced chip|ai chip|export control|entity list|"
    r"lithography|extreme ultraviolet|\beuv\b|advanced packaging|"
    r"tsmc|asml|smic|outbound investment|technology transfer|"
    r"decoupling|de[- ]risking|friend[- ]shoring|supply chain resilience|"
    r"clean network|telecom ban|"
    # 外交大國博弈與同盟
    r"sanction|embargo|summit|bilateral|diplomat|treaty|sovereignty|"
    r"election|parliament|congress|white house|state department|"
    r"beijing|kremlin|politburo|national security council|"
    r"g7|brics|nato|un security council|quad|aukus|asean|"
    # 貿易戰與經濟脅迫
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

# ==================== 4. 輔助函式 ====================
def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

def clean_url(raw_url):
    """防呆過濾：擷取標準純淨 URL，防止特殊括號阻斷 Discord 點擊"""
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

# ==================== 5. Groq AI 智慧情報分析 ====================
def analyze_with_groq(orig_title, orig_summary, channel_type):
    """呼叫 Groq API (qwen/qwen3.8-27b) 生成專屬結構化繁中情報，附帶 429 限速重試"""
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
        system_prompt = """你是一名專精國際關係與地緣政治的資深情報
