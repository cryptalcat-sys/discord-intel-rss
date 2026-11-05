import os
import re
import json
import time
import socket
import random
import requests
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone

# 設定全域網路底層逾時為 15 秒，嚴禁無限期等待卡死
socket.setdefaulttimeout(15)

# ==================== 1. 環境變數與核心設定 ====================
WEBHOOK_MILITARY = os.environ.get("DISCORD_WEBHOOK_URL")
WEBHOOK_POLITICS = os.environ.get("DISCORD_WEBHOOK_POLITICS") or os.environ.get("DISCORD_WEBHOOK_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
MAX_POSTS_PER_CHANNEL = 2  # 每個頻道每次執行最多推播 2 則
MAX_ARTICLE_AGE_HOURS = 48  # 只接受 48 小時內發布的新文章（封殺陳年舊聞）

# ==================== 2. 訂閱來源清單 (24 組新聞、智庫與影音) ====================
FEEDS = [
    # ==================== 🛡️ 戰略與軍聞頻道 (印太核心 70% + 全球防務 30%) ====================
    # ─── 台灣在地核心情咨（防務第一線） ───
    {
        "name": "中央社 兩岸透視 (防務)",
        "url": "https://feeds.feedburner.com/rsscna/mainland",
        "channel": "military",
        "color": 0x0284C7
    },
    {
        "name": "報呱 PourQuoi (安全防務)",
        "url": "https://pourquoi.tw/feed/",
        "channel": "military",
        "color": 0x4F46E5
    },
    # ─── 歐美權威防務刊物與智庫 ───
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
        "name": "IISS 國際戰略研究所",
        "url": "https://www.iiss.org/en/rss-feeds/analysis/",
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
    # ─── YouTube 防務專題影音 ───
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
    # ─── 台灣在地核心情咨（政經與戰略線） ───
    {
        "name": "中央社 兩岸透視 (政局)",
        "url": "https://feeds.feedburner.com/rsscna/mainland",
        "channel": "politics",
        "color": 0x0284C7
    },
    {
        "name": "中央社 科技產業",
        "url": "https://feeds.feedburner.com/rsscna/technology",
        "channel": "politics",
        "color": 0x059669
    },
    {
        "name": "報導者 The Reporter",
        "url": "https://www.twreporter.org/a/rss2.xml",
        "channel": "politics",
        "color": 0xD97706
    },
    {
        "name": "報呱 PourQuoi (國際戰略)",
        "url": "https://pourquoi.tw/feed/",
        "channel": "politics",
        "color": 0x4F46E5
    },
    # ─── 地緣經貿與科技戰線（台灣供應鏈與全球經濟安全） ───
    {
        "name": "PIIE 彼得森國際經濟研究所",
        "url": "https://www.piie.com/rss/update.xml",
        "channel": "politics",
        "color": 0x0A2540
    },
    {
        "name": "Bruegel 布魯塞爾全球經濟研究所",
        "url": "https://www.bruegel.org/rss.xml",
        "channel": "politics",
        "color": 0x1E40AF
    },
    {
        "name": "MERICS 柏林墨卡托中國研究中心",
        "url": "https://merics.org/en/rss.xml",
        "channel": "politics",
        "color": 0xC2410C
    },
    # ─── 國際頂級外交與地緣戰略智庫 ───
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
    # ─── YouTube 智庫與國際戰略影音 ───
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

# ==================== 3. 關鍵字過濾規範 (中英雙軌無死角架構) ====================
MILITARY_INCLUDE = re.compile(
    r"(?i)(?:"
    r"\b("
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
    r"navy|naval|plan|fleet|destroyer|frigate|corvette|cutter|"
    r"carrier|aircraft carrier|amphibious|landing ship|marines|"
    r"submarine|\bssn\b|\bssbn\b|anti[- ]submarine|\basw\b|torpedo|sonar|"
    r"air force|plaf|fighter jet|bomber|stealth aircraft|"
    r"f[- ]35|f[- ]16|j[- ]20|j[- ]35|b[- ]21|h[- ]6k|su[- ]57|"
    r"drone|\buav\b|\busv\b|\buuv\b|unmanned|loitering munition|\bfpv\b|"
    r"counter[- ]drone|\bc[- ]uas\b|electronic warfare|radar jamming|spectrum|"
    r"missile|ballistic missile|cruise missile|hypersonic|\bhgv\b|"
    r"air defense|patriot|nasams|thaad|aegis|himars|harpoon|tomahawk|sm[- ]6|pac[- ]3|"
    r"cjadc2|command and control|multi[- ]domain|space force|counter[- ]space|"
    r"red sea|bab el[- ]mandeb|strait of hormuz|persian gulf|black sea|baltic sea|"
    r"giuk gap|suwalki gap|arctic defense|"
    r"houthi|pentagon|nato|nuclear triad|deterrence"
    r")\b"
    r"|"
    r"(?:"
    r"台海|台灣海峽|南海|東海|第一島鏈|巴士海峽|宮古海峽|海巡|海警|海上民兵|水砲|"
    r"灰色地帶|防空識別區|海峽中線|越線|封鎖|聯合巡航|圍島|仁愛暗沙|仙賓暗沙|黃岩島|"
    r"南沙|西沙|釣魚台|金門|馬祖|東沙|太平島|東部戰區|南部戰區|印太司令部|"
    r"聯合利劍|漢光|肩並肩|環太軍演|實彈|軍演|兵推|海軍|艦隊|驅逐艦|巡防艦|巡邏艦|"
    r"航母|航空母艦|兩棲|登陸艦|陸戰隊|潛艦|核潛艦|反潛|魚雷|聲納|空軍|戰機|轟炸機|"
    r"匿蹤|無人機|無人艇|巡飛彈|反無人機|電子戰|電戰|干擾|頻譜|飛彈|彈道飛彈|巡弋飛彈|"
    r"極音速|防空|愛國者|薩德|神盾|海馬斯|魚叉|戰斧|太空軍|紅海|波斯灣|黑海|胡塞|五角大廈|"
    r"北約|核威懾|嚇阻"
    r")"
    r")"
)

POLITICS_INCLUDE = re.compile(
    r"(?i)(?:"
    r"\b("
    r"general election|presidential election|midterm election|snap election|"
    r"primary election|referendum|ballot|voter turnout|exit poll|"
    r"coalition government|ruling party|opposition party|majority government|"
    r"hung parliament|vote of no confidence|dissolve parliament|dissolution|"
    r"cabinet reshuffle|ouster|impeachment|lame duck|transition of power|"
    r"inauguration|political crisis|constitutional crisis|democratic backsliding|"
    r"authoritarian|polarization|populism|nationalist|civil unrest|coup d'?etat|"
    r"prime minister|chancellor|president[- ]elect|premiership|parliamentary|"
    r"congress|senate|house of representatives|capitol hill|white house|"
    r"diet\b|bundestag|national assembly|european parliament|knesset|"
    r"politburo|standing committee|national people's congress|\bnpc\b|cppcc|"
    r"state council|national security council|\bnsc\b|ministry of foreign affairs|"
    r"taiwan relations act|taiwan policy act|taipei act|taiwan assurance act|"
    r"six assurances|ndaa|national defense authorization act|"
    r"foreign military financing|\bfmf\b|presidential drawdown authority|\bpda\b|"
    r"arms sale|cross[- ]strait|status quo|one china policy|"
    r"chips act|semiconductor|advanced chip|ai chip|export control|entity list|"
    r"lithography|extreme ultraviolet|\beuv\b|advanced packaging|cowos|high bandwidth memory|\bhbm\b|"
    r"silicon photonics|sub[- ]3nm|[23]nm|wafer fab|foundry|fabless|"
    r"tsmc|asml|smic|nvidia|qualcomm|mediatek|foxconn|tokyo electron|applied materials|"
    r"outbound investment|technology transfer|sovereign ai|ai cluster|gpu restriction|gpu ban|"
    r"decoupling|de[- ]risking|friend[- ]shoring|supply chain resilience|"
    r"clean network|telecom ban|"
    r"section 301|section 232|anti[- ]dumping|countervailing dut(?:y|ies)|"
    r"universal tariff|baseline tariff|reciprocal tariff|tariff hike|tariff escalation|trade barrier|"
    r"industrial overcapacity|market distortion|export subsid(?:y|ies)|"
    r"us[- ]taiwan 21st century trade|indo[- ]pacific economic framework|\bipef\b|cptpp|rcep|"
    r"cfius|fdi screening|inbound investment screening|anti[- ]coercion instrument|\baci\b|"
    r"economic security promotion act|china\+1|taiwan\+1|near[- ]shoring|re[- ]shoring|"
    r"critical raw materials|minerals security partnership|\bmsp\b|"
    r"gallium|germanium|antimony|graphite|lithium|cobalt|rare earth magnet|"
    r"submarine cable|undersea cable|subsea cable|port security|choke point|export ban|"
    r"bureau of industry and security|\bbis\b|unverified list|military end user|\bmeu\b|"
    r"specially designated nationals|\bsdn list\b|secondary sanction|financial sanction|"
    r"asset freeze|de[- ]dollarization|petrodollar|mbridge|cross[- ]border payment|swift ban|"
    r"cbam|carbon border adjustment|energy security|strategic petroleum reserve|\bspr\b|"
    r"quad|aukus|g7|brics|nato|un security council|asean|ap4|"
    r"beijing|kremlin|washington|tokyo|seoul|manila|canberra|brussels|taipei|"
    r"transatlantic|eu[- ]china|european union|european commission|"
    r"russia[- ]china|sino[- ]russian|north korea[- ]russia|axis of resistance|"
    r"red sea|bab el[- ]mandeb|strait of hormuz|suez canal|malacca strait|"
    r"sanction|embargo|summit|bilateral|diplomat|treaty|sovereignty|"
    r"trade war|tariff|economic coercion|weaponized interdependence|"
    r"geopolit"
    r")\b"
    r"|"
    r"(?:"
    r"兩岸|台海|中共|國台辦|陸委會|統戰|灰色地帶|軍演|共機|共艦|海警|"
    r"圍台|第一島鏈|九二共識|一中原則|主權|領土|雙邊會談|國安會|立法院|"
    r"行政院|外交部|國防部|總統大選|內閣改組|不信任案|政權更迭|地緣政治|"
    r"半導體|晶片|台積電|聯電|日月光|聯發科|鴻海|晶圓代工|先進製程|先進封裝|"
    r"矽光子|高頻寬記憶體|晶片法案|實體清單|出口管制|技術禁令|對外投資審查|"
    r"去風險|脫鉤|友岸外包|近岸外包|供應鏈韌性|產業產能過剩|主權AI|"
    r"關稅|301條款|232條款|反傾銷|反補貼|貿易戰|經濟脅迫|經濟安保|反脅迫工具|"
    r"台美21世紀貿易倡議|外資審查|投審會|關鍵礦產|稀土|鎵|鍺|銻|石墨|鋰|鈷|"
    r"海底電纜|海纜安全|港口資安|商務部產業安全局|長臂管轄|金融制裁|資產凍結|"
    r"去美元化|碳邊境調整機制"
    r")"
    r")"
)

EXCLUDE_PATTERN = re.compile(
    r"(?i)\b(sponsored|advertisement|webinar|deals|review:|podcast|lifestyle|"
    r"entertainment|sports|box office|smartphone|gaming laptop|geforce|rtx|"
    r"civil aviation|commercial airline|boeing 737|airbus a320|flight delay|"
    r"video game|gameplay|war thunder|call of duty)\b|"
    r"(?:贊助|廣告|線上研討會|優惠|生活風格|娛樂|體育|票房|智慧型手機|電競筆電|民航|商業航班|航班延誤|電玩|遊戲畫面)"
)

# ==================== 4. 輔助函式與網址解析 ====================
def clean_html(html_text):
    if not html_text:
        return ""
    return " ".join(BeautifulSoup(html_text, "html.parser").get_text().split())

def clean_url(raw_url):
    """提取乾淨網址，移除 query string (如 ?utm_source) 與尾端斜線，避免網址浮動造成重複"""
    if not raw_url:
        return ""
    match = re.search(r"https?://[^\s\]\)\"\'<>]+", str(raw_url).strip())
    url = match.group(0) if match else raw_url.strip()
    try:
        parsed = urlparse(url)
        # 移除 query 與 fragment，保留乾淨的 scheme + netloc + path
        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return cleaned.rstrip("/")
    except Exception:
        return url.rstrip("/")

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
        return True
    try:
        entry_timestamp = time.mktime(parsed_time)
        age_in_seconds = time.time() - entry_timestamp
        return age_in_seconds <= (max_hours * 3600)
    except Exception:
        return True

# ==================== 5. Gemini + Groq 跨平台混合智能分析 (動態引擎標記) ====================
def analyze_with_ai(orig_title, orig_summary, channel_type):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    if not gemini_key and not groq_key:
        print("❌ 未偵測到 GEMINI_API_KEY 或 GROQ_API_KEY！")
        return None

    if channel_type == "politics":
        system_prompt = """你是一名專精國際關係與地緣政治的資深情報分析官。
請分析該政經外交情報，嚴格以繁體中文輸出符合以下結構的 JSON 物件：
{
  "topic_key": "歸納本事件核心主體與事件動作（4-8字，如：美中晶片管制、G7涉台聲明、菲律賓南海仲裁、日本自民黨選舉）",
  "title_zh": "【必須翻譯為繁體中文】請將原標題完整翻譯並提煉為具宏觀政治洞察的繁體中文標題，嚴格禁止保留英文原標題",
  "region": "標註受影響之核心地緣區域或國際陣營（如：第一島鏈、歐盟體系、台海周邊、美中博弈前線）",
  "actors": "標註核心博弈實體（格式：主體 A vs 主體 B）",
  "points": [
    "第一點：核心外交決策、法案制裁、政權更迭或政局事件事實",
    "第二點：雙方外交攻防、政策意圖或國家利益折衝",
    "第三點：對區域地緣政治平衡、國際秩序或經貿供應鏈的長期衝擊"
  ]
}"""
    else:
        system_prompt = """你是一名專精印太地緣防務軍事的情報分析官。
請分析防務情報，嚴格以繁體中文輸出符合以下結構的 JSON 物件：
{
  "topic_key": "歸納本事件核心載具/行動與地點（4-8字，如：美艦穿越台海、仁愛暗沙海警衝突、漢光無人機兵推、紅海無人機防空）",
  "title_zh": "【必須翻譯為繁體中文】請將原標題完整翻譯並提煉為具軍事術語的繁體中文標題，嚴格禁止保留英文原標題",
  "region": "標註衝突所屬海空域（如：台海中線、南海仁愛暗沙、巴士海峽、紅海航道、黑海前線）",
  "actors": "標註主要對峙實體（格式：主體 A vs 主體 B）",
  "points": [
    "第一點：核心事件與載具/武器裝備行動細節",
    "第二點：戰術意圖、官方敘事或灰色地帶施壓手法",
    "第三點：對第一島鏈防務、戰略航道或地緣平衡的影響"
  ]
}"""

    user_content = f"新聞標題：{orig_title}\n新聞內容：{orig_summary[:800]}"

    pipeline = [
        {
            "name": "Gemini-3.5-Flash-Lite (極速首選主力)",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key": gemini_key,
            "model": "gemini-3.5-flash-lite",
            "timeout": 20,
            "engine_tag": "Gemini-Lite"
        },
        {
            "name": "Gemini-3.8-Flash (Google 旗艦備援)",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key": gemini_key,
            "model": "gemini-3.8-flash",
            "timeout": 35,
            "engine_tag": "Gemini-Flash"
        },
        {
            "name": "Groq-Qwen-3.8-27B (跨雲有效托底)",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": groq_key,
            "model": "qwen/qwen3.8-27b",
            "timeout": 20,
            "engine_tag": "Groq"
        }
    ]

    for node in pipeline:
        if not node["key"]:
            continue

        headers = {
            "Authorization": f"Bearer {node['key']}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": node["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 500
        }

        try:
            resp = requests.post(node["url"], headers=headers, json=payload, timeout=node["timeout"])
            
            if resp.status_code == 200:
                raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                    raw_text = re.sub(r"\n?```$", "", raw_text)
                
                parsed_data = json.loads(raw_text.strip())
                parsed_data["engine"] = node.get("engine_tag", "AI")
                return parsed_data

            elif resp.status_code in [429, 503, 404]:
                print(f"⚠️ [{node['name']}] 回應 HTTP {resp.status_code}，自動切換至下一備援引擎...")
                time.sleep(2)
                continue
            else:
                print(f"⚠️ [{node['name']}] 回應異常 HTTP {resp.status_code}，切換備援...")
                continue

        except requests.exceptions.Timeout:
            print(f"⏳ [{node['name']}] 回應逾時，自動切換至下一備援引擎...")
            continue
        except Exception as e:
            print(f"⚠️ [{node['name']}] 連線異常: {e}，切換備援...")
            continue

    print("❌ 所有 AI 推理引擎 (Gemini & Groq) 皆無法回應，本則跳過。")
    return None

analyze_with_groq = analyze_with_ai
analyze_with_gemini = analyze_with_ai

# ==================== 6. 跨媒體語意去重與歷史管理 (時間戳字典化) ====================
def load_history():
    """讀取歷史紀錄，自動將舊版 list 格式升級為 timestamp dict"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # 舊版純 list 相容處理
                    return {"ids": {fp: time.time() for fp in data}, "events": []}
                if isinstance(data.get("ids"), list):
                    # 舊版 ids: list 相容處理
                    data["ids"] = {fp: time.time() for fp in data["ids"]}
                elif not isinstance(data.get("ids"), dict):
                    data["ids"] = {}
                if not isinstance(data.get("events"), list):
                    data["events"] = []
                return data
        except Exception:
            return {"ids": {}, "events": []}
    return {"ids": {}, "events": []}

def save_history(history_data):
    """保存歷史紀錄：按時間戳精確淘汰超過 72 小時的指紋與事件，絕不隨機斬斷"""
    current_time = time.time()
    cutoff_time = current_time - (72 * 3600)  # 保留 72 小時 (3 天)

    # 1. 清理超過 72 小時的事件
    history_data["events"] = [
        ev for ev in history_data.get("events", [])
        if ev.get("timestamp", 0) >= cutoff_time
    ]

    # 2. 清理超過 72 小時的文章指紋
    raw_ids = history_data.get("ids", {})
    if isinstance(raw_ids, dict):
        history_data["ids"] = {
            fp: ts for fp, ts in raw_ids.items()
            if isinstance(ts, (int, float)) and ts >= cutoff_time
        }
    elif isinstance(raw_ids, list):
        history_data["ids"] = {fp: current_time for fp in raw_ids}

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

def is_duplicate_event(topic_key, recent_events):
    """比對新事件與過去 24 小時內推播事件的字元重疊度"""
    if not topic_key:
        return False
    current_time = time.time()
    candidate_chars = set(topic_key)

    for ev in recent_events:
        if current_time - ev.get("timestamp", 0) > 86400:
            continue
        past_key = ev.get("key", "")
        past_chars = set(past_key)

        overlap = len(candidate_chars & past_chars)
        min_len = min(len(candidate_chars), len(past_chars))
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

    orig_title = clean_html(entry.get("title", "No Title"))
    link = clean_url(entry.get("link", ""))
    orig_summary = clean_html(entry.get("summary", entry.get("description", "")))

    raw_title_zh = (
        intel_data.get("title_zh")
        or intel_data.get("title")
        or intel_data.get("chinese_title")
        or intel_data.get("title_tw")
    )

    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", str(raw_title_zh or "")))
    topic_key = str(intel_data.get("topic_key", "")).strip()

    if raw_title_zh and has_chinese:
        title = str(raw_title_zh).strip()
    elif topic_key:
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
    engine_name = intel_data.get("engine", "AI")

    if channel_type == "politics":
        footer_text = f"即時政局情報 • AI 地緣外交研判 ({engine_name})"
    else:
        footer_text = f"即時防務情報 • AI 灰色地帶觀測 ({engine_name})"

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

# ==================== 8. 主排程迴圈 (隨機均勻輪詢 + 時間戳防重複) ====================
def main():
    history = load_history()
    existing_ids = history.get("ids", {})  # 格式: {fingerprint: timestamp}
    recent_events = history.get("events", [])

    is_initial_run = len(existing_ids) == 0
    new_ids = {}  # 本次新增指紋: {fingerprint: timestamp}
    new_events = []

    channel_counts = {
        "military": 0,
        "politics": 0
    }

    max_article_age = globals().get("MAX_ARTICLE_AGE_HOURS", 48)

    # 🎲 每次隨機洗牌來源順序，打破優先權壟斷
    shuffled_feeds = list(FEEDS)
    random.shuffle(shuffled_feeds)

    for feed_info in shuffled_feeds:
        channel_type = feed_info.get("channel", "military")

        # 雙頻道皆達到上限時提前退出
        if all(count >= MAX_POSTS_PER_CHANNEL for count in channel_counts.values()):
            print("🏁 雙頻道皆已達本次推播上限 (各 2 則)，結束本輪巡邏。")
            break

        # 單一頻道已達上限時跳過該頻道的來源
        if channel_counts[channel_type] >= MAX_POSTS_PER_CHANNEL:
            continue

        print(f"🔍 正在檢查 [{channel_type}]: {feed_info['name']}")

        target_feed_url = resolve_feed_url(feed_info["url"])

        parsed = None
        try:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*"
            }
            r = requests.get(target_feed_url, headers=req_headers, timeout=12)
            if r.status_code == 200:
                parsed = feedparser.parse(r.content)
            elif r.status_code in [403, 404]:
                print(f"⚠️ 來源回應 {r.status_code}，改由 feedparser 原生解析: {feed_info['name']}")
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

            # 🛡️ 三重防重複指紋鎖：正規化網址、原始 GUID、原始新聞標題指紋
            clean_link = clean_url(entry.get("link", ""))
            raw_id = str(entry.get("id", "")).strip()
            raw_title = clean_html(entry.get("title", "")).strip()
            title_fingerprint = f"title:{raw_title}" if raw_title else ""

            entry_fingerprints = [fp for fp in [clean_link, raw_id, title_fingerprint] if fp]
            if not entry_fingerprints:
                continue

            # 🔒 只要三者任一曾在 72 小時內記錄過，絕對封殺略過
            if any(fp in existing_ids or fp in new_ids for fp in entry_fingerprints):
                continue

            now = time.time()

            # 🛑 時效守門員：超過指定時效的舊文章直接略過並永久標記已讀
            if not is_entry_fresh(entry, max_hours=max_article_age):
                for fp in entry_fingerprints:
                    new_ids[fp] = now
                continue

            title = raw_title
            summary = entry.get("summary", entry.get("description", ""))
            content_to_check = f"{title} {summary}"

            # 首次運行只建立歷史基準線，不推播
            if is_initial_run:
                for fp in entry_fingerprints:
                    new_ids[fp] = now
                continue

            # 排除廣告或娛樂雜訊
            if EXCLUDE_PATTERN.search(content_to_check):
                for fp in entry_fingerprints:
                    new_ids[fp] = now
                continue

            # 命中關鍵字匹配
            matcher = POLITICS_INCLUDE if channel_type == "politics" else MILITARY_INCLUDE
            if not matcher.search(content_to_check):
                # ⚠️ 不將未命中關鍵字寫入 new_ids，避免同來源（如中央社兩岸）跨頻道被誤殺
                continue

            # 呼叫跨雲 AI 管線進行分析與提煉
            intel_data = analyze_with_ai(title, summary, channel_type)
            if not intel_data or not isinstance(intel_data, dict):
                print(f"⏩ 跳過推播：[{title[:25]}...] AI 分析未就緒，留待下輪處理。")
                continue

            topic_key = str(intel_data.get("topic_key", "")).strip()

            # 跨來源 24 小時語意冷卻池檢查
            combined_events = recent_events + new_events
            if is_duplicate_event(topic_key, combined_events):
                print(f"⏩ 命中同事件冷卻池：[{topic_key}] 近 24 小時內已推播過相關報導，略過此來源。")
                for fp in entry_fingerprints:
                    new_ids[fp] = now
                continue

            # 正式發送 Discord 推播
            success = send_to_discord(entry, feed_info, intel_data)
            if success:
                print(f"✅ [{channel_type}] 已發送 ({channel_counts[channel_type] + 1}/{MAX_POSTS_PER_CHANNEL}): {title}")
                for fp in entry_fingerprints:
                    new_ids[fp] = now
                if topic_key:
                    new_events.append({"key": topic_key, "timestamp": time.time()})
                channel_counts[channel_type] += 1
                time.sleep(8)
            else:
                print(f"❌ [{channel_type}] 推播失敗，不記錄於歷史。")

    # 寫入歷史資料庫與事件指紋池
    if new_ids:
        # 合併字典並自動按 72 小時淘汰過期項目
        existing_ids.update(new_ids)
        history["ids"] = existing_ids
        history["events"] = recent_events + new_events
        save_history(history)
        print(f"💾 歷史更新完畢，本次共記錄 {len(new_ids)} 筆指紋，現存總指紋數：{len(history['ids'])} 筆。")

    print(f"📊 本輪推播統計：軍聞 {channel_counts['military']}/{MAX_POSTS_PER_CHANNEL} 則 | 政局 {channel_counts['politics']}/{MAX_POSTS_PER_CHANNEL} 則。")

if __name__ == "__main__":
    main()
