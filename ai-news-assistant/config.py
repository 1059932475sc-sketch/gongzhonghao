"""
AI 资讯情报官 - 配置文件
========================
所有配置集中管理，修改这里即可调整整个系统的行为
"""

import os
from pathlib import Path

# 尝试加载 .env 文件
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        # 手动解析 .env
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    print(f"[config] 已加载 .env 文件: {_env_path}")
else:
    print("[config] 未找到 .env 文件，使用系统环境变量")

# ============================================================
# 项目路径
# ============================================================
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"

for d in [OUTPUT_DIR, DATA_DIR, CACHE_DIR]:
    d.mkdir(exist_ok=True)

# ============================================================
# RSS 数据源（每天抓取）
# ============================================================
RSS_SOURCES = [
    {
        "name": "Hugging Face Papers",
        "url": "https://huggingface.co/papers",
        "type": "webpage",  # HuggingFace papers 没有 RSS，抓取页面
        "selector": "article a",
    },
    {
        "name": "GitHub Trending",
        "url": "https://github.com/trending?since=daily",
        "type": "webpage",
        "selector": "h2.h3 a",
    },
    {
        "name": "arXiv cs.AI Recent",
        "url": "https://arxiv.org/list/cs.AI/recent",
        "type": "webpage",
    },
    {
        "name": "Product Hunt AI",
        "url": "https://www.producthunt.com/topics/artificial-intelligence",
        "type": "webpage",
    },
]

# 额外 RSS 备选（标准 RSS feed）
RSS_FEEDS = [
    {
        "name": "Google AI Blog",
        "url": "https://blog.research.google/feeds/posts/default?alt=rss",
        "type": "rss",
    },
    {
        "name": "MIT Tech Review AI",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "type": "rss",
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "type": "rss",
    },
    {
        "name": "ArsTechnica AI",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "type": "rss",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://feeds.feedburner.com/venturebeat/SZYF",
        "type": "rss",
    },
]

# ============================================================
# 筛选策略
# ============================================================
MAX_ITEMS_PER_SOURCE = 20      # 每个源最多取多少条
TRENDING_THRESHOLD = 3         # 几个来源同时提到 → 触发深度选题
KEYWORD_BLACKLIST = [           # 排除的营销关键词
    "限时优惠", "点击购买", "注册送", "免费领取",
    "割韭菜", "暴富", "月入过万", "被动收入",
    "限时特价", "立即下单",
]

# ============================================================
# LLM 配置（用于文章生成）
# ============================================================
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# 如果使用 DeepSeek / 国内模型，修改这里即可
# LLM_BASE_URL = "https://api.deepseek.com/v1"
# LLM_MODEL = "deepseek-chat"

# ============================================================
# 微信公众号配置（可选）
# ============================================================
# 如需自动发布到公众号，填写以下信息：
# 1. 前往 https://mp.weixin.qq.com 获取 AppID 和 AppSecret
# 2. 注意：发布 API 需要认证（付费）服务号
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")

# ============================================================
# 飞书推送配置（推荐，替代微信公众号）
# ============================================================
# 在飞书群中添加自定义机器人 Webhook 即可，无需任何认证
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

# ============================================================
# 文章风格设置
# ============================================================
WRITER_STYLE = "资深公众号科技博主「布丁」"
TONE = "像朋友聊天一样讲AI，说人话、有态度、不装逼"
TARGET_AUDIENCE = "中文科技爱好者、AI 从业者、产品经理"
ARTICLE_LENGTH = "1500-2000 字"
