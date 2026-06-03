"""
国内社会热点公众号 - 配置
"""

import os
from pathlib import Path


BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"

for d in [OUTPUT_DIR, DATA_DIR]:
    d.mkdir(exist_ok=True)


_env_path = BASE_DIR / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")


ARTICLE_COUNT = 1
ARTICLE_TARGET_CHARS = 1000


SAFE_CATEGORIES = [
    "消费", "职场", "教育", "生活", "健康", "文娱", "科技", "城市服务",
    "交通出行", "餐饮", "旅游", "社交平台", "普通人生活",
]


BLOCK_KEYWORDS = [
    # 政治/时政/国际/军事
    "习近平", "中央", "国务院", "人大", "政协", "外交部", "国防部", "中方", "代表", "停火", "止战", "形势", "省委", "市委",
    "书记", "市长", "省长", "部长", "政策", "反腐", "落马", "台海", "台湾", "香港",
    "澳门", "美国", "日本", "韩国", "俄罗斯", "乌克兰", "以色列", "巴勒斯坦",
    "战争", "军演", "导弹", "军方", "间谍", "制裁", "大使馆",
    "海外", "外国", "中国人", "国家", "民族", "爱国", "移民",
    "官方", "公务员", "网警", "警方", "公安", "法院", "检察院", "宣判", "获刑",
    "被查", "通报", "救灾", "村支书", "干部", "公职",
    "当地", "回应", "教师", "质量差",
    # 高风险社会新闻
    "命案", "凶杀", "杀人", "尸体", "自杀", "跳楼", "坠楼", "强奸", "猥亵",
    "拐卖", "毒品", "赌博", "诈骗", "传销", "邪教", "黑社会", "枪", "爆炸",
    "死亡", "遇难", "伤亡", "坍塌", "火灾", "地震", "洪水", "台风",
    # 账号风险
    "谣言", "网传", "内幕", "曝光", "实锤", "抵制", "维权", "举报", "上访",
    "未成年人隐私", "人肉", "偷拍视频", "馆长",
    "宣布", "队长", "国乒", "男队", "女队",
]


STYLE_RULES = """
只写普通人可安全讨论的社会生活热点。
不写政治、时政、军事、国际冲突、敏感案件、灾难伤亡、未成年人隐私。
文章只做生活观察、消费提醒、职场启发、情绪共鸣和实用建议。
不要煽动对立，不要审判个人，不要使用“震惊、全网炸了、不看后悔”等夸张标题。
"""
