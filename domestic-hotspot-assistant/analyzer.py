"""
社会热点合规筛选和选题评分。
"""

from __future__ import annotations

import json
from datetime import datetime

from config import BLOCK_KEYWORDS, DATA_DIR


GOOD_KEYWORDS = [
    "年轻人", "普通人", "上班", "工作", "工资", "消费", "价格", "房租", "外卖",
    "餐饮", "旅游", "电影", "综艺", "手机", "平台", "网友", "生活", "健康",
    "睡眠", "情绪", "社交", "家庭", "教育", "孩子", "大学生", "毕业", "求职",
    "通勤", "高铁", "地铁", "城市", "服务", "商家", "顾客",
    "老人", "父母", "奶奶", "爷爷", "养老", "退休", "医保", "医院", "存款",
    "小区", "物业", "房子", "买菜", "做饭", "水果", "超市", "菜市场", "西瓜",
    "端午", "龙舟", "汉服", "传统", "家用", "充电", "华为", "小米",
]

PREFERRED_KEYWORDS = ["消费", "价格", "健康", "睡眠", "职场", "工作", "教育", "学生", "校园", "旅游", "生活"]
MATURE_AUDIENCE_KEYWORDS = [
    "老人", "父母", "奶奶", "爷爷", "养老", "退休", "医保", "医院", "健康",
    "存款", "房子", "小区", "物业", "菜", "做饭", "水果", "超市", "西瓜",
    "端午", "龙舟", "传统", "家庭", "孩子", "孙子", "华为", "小米", "家用",
]


def compliance_check(title: str, summary: str = "") -> tuple[bool, list[str]]:
    text = f"{title} {summary}"
    hits = [k for k in BLOCK_KEYWORDS if k in text]
    return not hits, hits


def score_item(item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    good = sum(2 for k in GOOD_KEYWORDS if k in text)
    preferred = sum(5 for k in PREFERRED_KEYWORDS if k in text)
    mature = sum(4 for k in MATURE_AUDIENCE_KEYWORDS if k in text)
    length_bonus = 2 if 8 <= len(item.get("title", "")) <= 28 else 0
    source_bonus = {"微博热搜": 3, "百度热榜": 2, "知乎热榜": 2, "头条热榜": 2, "抖音热榜": 2}.get(item.get("source"), 1)
    ok, risks = compliance_check(item.get("title", ""), item.get("summary", ""))
    risk_penalty = 100 if not ok else 0
    return {
        "score": preferred + good + mature + length_bonus + source_bonus - risk_penalty,
        "risks": risks,
        "reason": "生活/消费/职场/文娱类安全热点" if ok else f"命中风险词: {','.join(risks)}",
    }


def select_topics(items: list[dict], count: int = 2) -> list[dict]:
    candidates = []
    for item in items:
        s = score_item(item)
        if s["score"] <= 0 or s["risks"]:
            continue
        candidates.append({"item": item, "analysis": s})
    candidates.sort(key=lambda x: x["analysis"]["score"], reverse=True)
    selected = candidates[:count]
    path = DATA_DIR / f"selected_{datetime.now().strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected
