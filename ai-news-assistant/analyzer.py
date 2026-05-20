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

from config import DATA_DIR, TRENDING_THRESHOLD

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
