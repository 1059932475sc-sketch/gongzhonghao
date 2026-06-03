"""
AI 资讯情报官 - 热点分析模块
=============================
跨源检测哪些 AI 技术/工具被多个来源同时讨论
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher

from config import (
    DATA_DIR, TRENDING_THRESHOLD, PUBLIC_ACCOUNT_PROFILES,
    TRAFFIC_KEYWORDS, MONEY_KEYWORDS, RISK_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ============================================================
# 核心 AI/技术关键词（用于识别和归类）
# ============================================================
AI_KEYWORDS = [
    # 大模型
    "GPT", "Claude", "Gemini", "Llama", "Mistral", "Qwen", "DeepSeek",
    "LLaMA", "Yi-", "MoE", "transformer", "diffusion", "multimodal",
    # 框架
    "PyTorch", "TensorFlow", "LangChain", "LLaMAIndex", "Hugging Face",
    "AutoGPT", "Agent", "RAG", "Fine-tuning", "LoRA", "QLoRA",
    # 应用
    "Copilot", "Cursor", "v0", "Codex", "Sora", "Runway", "Midjourney",
    "Stable Diffusion", "DALL-E", "Suno", "ElevenLabs",
    # 概念
    "AGI", "ASI", "open source", "alignment", "safety",
    "reasoning", "chain-of-thought", "function calling",
    "computer use", "vision", "speech", "voice",
    # 中文翻译
    "大模型", "人工智能", "机器学习", "深度学习", "神经网络",
    "自然语言处理", "计算机视觉", "智能体", "多模态",
    "推理", "对齐", "开源", "微调",
]

# 来源权重（同一个话题在不同来源出现，权重更高）
SOURCE_WEIGHTS = {
    "Hugging Face Papers": 2.0,   # 学术界
    "arXiv cs.AI Recent": 2.0,    # 顶会论文
    "GitHub Trending": 1.5,       # 开源社区
    "Product Hunt AI": 1.2,       # 产品侧
    "OpenAI Blog": 1.8,           # 官方
    "Google AI Blog": 1.8,       # 官方
    "Anthropic Blog": 1.8,       # 官方
}


def extract_topics(text: str) -> list[str]:
    """从文本中提取 AI 相关关键词"""
    found = []
    lower_text = text.lower()
    for kw in AI_KEYWORDS:
        if kw.lower() in lower_text:
            found.append(kw)
    return found


def title_similarity(t1: str, t2: str) -> float:
    """计算两个标题的相似度"""
    return SequenceMatcher(None, t1.lower(), t2.lower()).ratio()


def detect_trends(items: list[dict], threshold: int = None) -> list[dict]:
    """
    核心：跨源检测趋势热点

    返回：
        [
            {
                "topic": "话题名称",
                "keywords": [...],
                "mentions": 提及次数,
                "weighted_score": 加权分数,
                "articles": [关联文章列表],
                "sources": [来源名称列表],
                "is_deep_dive": True/False (是否触发深度选题)
            },
            ...
        ]
    """
    if threshold is None:
        threshold = TRENDING_THRESHOLD

    logger.info("🔍 开始热点分析...")

    if not items:
        return []

    # 第一步：建立关键词 → 文章映射
    keyword_items = {}
    for item in items:
        text = f"{item['title']} {item['summary']}"
        topics = extract_topics(text)
        for topic in topics:
            if topic not in keyword_items:
                keyword_items[topic] = []
            keyword_items[topic].append(item)

    # 第二步：合并相似话题
    trends = []
    processed_topics = set()

    for topic, articles in sorted(keyword_items.items(),
                                   key=lambda x: len(x[1]), reverse=True):
        if topic in processed_topics:
            continue

        # 找到相似话题合并
        related_topics = {topic}
        for other_topic in keyword_items:
            if other_topic not in processed_topics and other_topic != topic:
                if SequenceMatcher(None, topic.lower(), other_topic.lower()).ratio() > 0.6:
                    related_topics.add(other_topic)

        # 合并这些话题下的文章（去重）
        merged_articles = []
        seen_urls = set()
        for rt in related_topics:
            for art in keyword_items[rt]:
                if art["url"] not in seen_urls:
                    seen_urls.add(art["url"])
                    merged_articles.append(art)

        # 统计来源分布
        source_counts = Counter(a["source_name"] for a in merged_articles)
        unique_sources = list(source_counts.keys())
        mention_count = len(merged_articles)

        # 计算加权分数
        weighted_score = 0
        for s in unique_sources:
            count = source_counts[s]
            weight = SOURCE_WEIGHTS.get(s, 1.0)
            weighted_score += count * weight

        # 判断是否触发深度选题
        is_deep_dive = (
            len(unique_sources) >= 2 and mention_count >= threshold
        )

        trend = {
            "topic": topic,
            "related_keywords": list(related_topics - {topic}),
            "mentions": mention_count,
            "unique_sources": len(unique_sources),
            "weighted_score": round(weighted_score, 1),
            "sources": unique_sources,
            "articles": merged_articles,
            "is_deep_dive": is_deep_dive,
        }
        trends.append(trend)

        for rt in related_topics:
            processed_topics.add(rt)

    # 按加权分数降序排列
    trends.sort(key=lambda x: x["weighted_score"], reverse=True)

    # 记录日志
    deep_dives = [t for t in trends if t["is_deep_dive"]]
    if deep_dives:
        logger.info(f"🔥 触发深度选题 {len(deep_dives)} 个:")
        for t in deep_dives:
            logger.info(f"   [{t['topic']}] {t['mentions']}次提及, "
                       f"{t['unique_sources']}个来源, 得分{t['weighted_score']}")
    else:
        logger.info("📊 未触发深度选题，继续日常简报模式")

    # 保存分析结果
    _save_trends(trends)

    return trends


def _save_trends(trends: list[dict]):
    """保存热点分析结果到文件"""
    today = datetime.now().strftime("%Y-%m-%d")
    path = DATA_DIR / f"trends_{today}.json"
    summary = []
    for t in trends:
        summary.append({
            "topic": t["topic"],
            "mentions": t["mentions"],
            "sources": t["sources"],
            "score": t["weighted_score"],
            "is_deep_dive": t["is_deep_dive"],
            "articles": [
                {"title": a["title"][:80], "source": a["source_name"], "url": a["url"]}
                for a in t["articles"]
            ],
        })
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"💾 趋势报告已保存: {path}")


def _keyword_score(text: str, keywords: list[str], weight: float = 1.0) -> float:
    """按关键词命中计算简单运营分。"""
    lower_text = text.lower()
    score = 0.0
    for kw in keywords:
        if kw.lower() in lower_text:
            score += weight
    return score


def score_item_for_account(item: dict, profile: dict) -> dict:
    """为单条资讯计算公众号运营价值。"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    profile_keywords = profile.get("preferred_angles", [])

    if profile.get("article_type") == "money":
        traffic_weight = 1.5
        money_weight = 4.0
    else:
        traffic_weight = 2.5
        money_weight = 1.0

    traffic_score = _keyword_score(text, TRAFFIC_KEYWORDS, traffic_weight)
    money_score = _keyword_score(text, MONEY_KEYWORDS, money_weight)
    fit_score = _keyword_score(text, profile_keywords, 3.0)
    risk_score = _keyword_score(text, RISK_KEYWORDS, 4.0)

    source_name = item.get("source_name", "")
    source_bonus = 1.5 if any(x in source_name for x in ["AIbase", "量子位", "机器之心", "36氪"]) else 0.5
    tech_bonus = 1.0 if any(x in text for x in ["AI", "人工智能", "大模型", "智能体", "Agent"]) else 0.0

    total_score = traffic_score + money_score + fit_score + source_bonus + tech_bonus - risk_score

    reasons = []
    if traffic_score:
        reasons.append("有大众搜索/点击关键词")
    if money_score:
        reasons.append("具备变现关联")
    if fit_score:
        reasons.append(f"贴合「{profile['account_name']}」定位")
    if source_bonus > 1:
        reasons.append("来自中文大众资讯源")
    if risk_score:
        reasons.append("存在夸张或违规风险，写作需降火")

    return {
        "traffic_score": round(traffic_score, 1),
        "money_score": round(money_score, 1),
        "fit_score": round(fit_score, 1),
        "risk_score": round(risk_score, 1),
        "total_score": round(total_score, 1),
        "reasons": reasons or ["常规 AI 热点，可作为备选"],
    }


def select_public_account_topics(items: list[dict], trends: list[dict] = None) -> list[dict]:
    """
    为配置中的公众号档案选择选题。

    目标不是找最硬核技术新闻，而是找「大众愿意点、能收藏转发、后续能变现」的题。
    """
    scored_by_account = []

    for profile in PUBLIC_ACCOUNT_PROFILES:
        candidates = []
        for item in items:
            score = score_item_for_account(item, profile)
            candidates.append({
                "account": profile,
                "item": item,
                "score": score,
            })

        candidates.sort(key=lambda x: x["score"]["total_score"], reverse=True)
        scored_by_account.append(candidates[:12])

    selections = _best_non_overlapping_assignment(scored_by_account)

    _save_public_account_selections(selections)
    return selections


def _best_non_overlapping_assignment(scored_by_account: list[list[dict]]) -> list[dict]:
    """为多个账号做不重复选题分配，最大化总运营分。"""
    if not scored_by_account:
        return []

    best_combo = []
    best_score = float("-inf")

    def walk(account_idx: int, current: list[dict], used_urls: set[str], total: float):
        nonlocal best_combo, best_score
        if account_idx >= len(scored_by_account):
            if total > best_score:
                best_score = total
                best_combo = list(current)
            return

        for candidate in scored_by_account[account_idx]:
            url = candidate["item"].get("url", "")
            if url in used_urls:
                continue
            current.append(candidate)
            used_urls.add(url)
            walk(
                account_idx + 1,
                current,
                used_urls,
                total + candidate["score"]["total_score"],
            )
            used_urls.remove(url)
            current.pop()

    walk(0, [], set(), 0.0)
    return best_combo


def _save_public_account_selections(selections: list[dict]):
    """保存公众号选题决策，方便复盘。"""
    today = datetime.now().strftime("%Y-%m-%d")
    path = DATA_DIR / f"account_selections_{today}.json"
    data = []
    for sel in selections:
        item = sel["item"]
        profile = sel["account"]
        data.append({
            "account_name": profile["account_name"],
            "title": item.get("title", ""),
            "source": item.get("source_name", ""),
            "url": item.get("url", ""),
            "score": sel["score"],
        })
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"💾 公众号选题已保存: {path}")
