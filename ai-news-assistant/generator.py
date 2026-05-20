"""
AI 资讯情报官 - AI 文章生成模块
===============================
使用大模型自动生成公众号文章
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    OUTPUT_DIR, WRITER_STYLE, TONE, TARGET_AUDIENCE, ARTICLE_LENGTH,
)

logger = logging.getLogger(__name__)

# ============================================================
# 提示词模板
# ============================================================

DAILY_BRIEF_PROMPT = """你是一位{writer_style}。

## 你的任务
根据以下今日 AI 资讯素材，写一篇约 {length} 的**公众号风格文章**。

## 什么是"公众号风格"？（非常重要，必须遵守）
这不是传统的新闻报道，而是像你个人公众号上发的一篇文章。要让人感觉：
1. **开头抓人**——用一句反常识的话、一个故事、或者一个扎心问题开头，让读者忍不住往下看
2. **说人话**——不要学术腔，不要机器翻译感。用大白话把AI技术讲清楚
3. **有态度**——不是冷冰冰的"据报道"，而是"我觉得"、"说实话"、"我直接说结论"
4. **短段落**——每段不超过3-4行，读起来轻松
5. **金句**——中间插一两句有记忆点的句子（加粗）
6. **节奏感**——多用短句、反问句，像跟朋友聊天
7. **不完美感**——不要太工整，有点口语化、有点个人风格，才像真人写的

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 不要只是罗列新闻，要讲背后的意义和趋势
- 要有作者自己的评论和见解
- 专业术语保留英文并附中文释义
- 结尾不要"综上所述"，要丢一个思考题或一个犀利的观点让读者回味

## 今日素材
{items}

## 文章格式要求
用以下格式输出：

# 标题（要"标题党"但别太离谱，让人想点进来）

## 📌 今日速览（3-5条一句话总结）

## 🔥 正文（按重要性排列，每个小标题要吊胃口）

## 💡 布丁说（作者自己的观点和吐槽）

## 📚 延伸阅读"""


DEEP_DIVE_PROMPT = """你是一位{writer_style}。

## 触发条件
今天有多个权威来源同时报道了 **{topic}**，说明这是一个重要趋势，值得写一篇深度分析。

## 你的任务
基于以下素材，写一篇约 {length} 的**公众号深度分析文章**。不是百科词条、不是论文综述，而是像你公众号上发的爆款深度文。

## 什么是"公众号深度文"？（非常重要）
1. **开头定生死**——必须在前3句话抓住读者。可以用一个故事、一组反常识数据、或者一个灵魂拷问
2. **说人话的技术解读**——再复杂的技术，也要用大白话讲。比如不要写"基于Transformer架构的多模态模型"，而要写"这个模型能同时看懂文字、图片和声音，就像给AI装了五感"
3. **有观点的分析**——"这件事意味着什么"比"这件事是什么"重要一万倍
4. **有信息量**——读者看完要觉得"值了"，有可以转发给朋友的东西
5. **有记忆点**——中间放1-2个金句（加粗），让人看完能记住
6. **短段落、多换行**——手机上读起来不累
7. **结尾有力量**——不是"总之"式结尾，而是丢一个犀利的判断、或者一个开放问题

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 不要只讲是什么，要讲为什么重要、对谁有影响、接下来会怎样
- 要有作者的态度（"我说句不好听的"、"坦白讲"、"我直接说结论"）
- 口语化但不过度，读起来像是朋友在跟你分享

## 相关素材
{items}

## 文章格式要求

# 标题（爆款标题，让人想点进来）

## 🎯 核心观点（一句说清楚，这篇文章在讲什么）

## 🔥 正文

### 1. 先说说（用吸引人的方式引出话题）
### 2. 到底怎么回事（把事情讲清楚）
### 3. 为什么这事很重要（深度分析、行业影响）
### 4. 接下来会怎样（趋势判断）

## 💡 布丁说（作者的犀利点评）

## 📚 参考来源"""


def _build_items_text(items: list[dict]) -> str:
    """将新闻条目格式化为 LLM 可读的文本"""
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"[{i}] 标题: {item['title']}")
        lines.append(f"    摘要: {item['summary'][:300]}")
        lines.append(f"    来源: {item.get('source_name', '未知')}")
        lines.append(f"    链接: {item['url']}")
        lines.append("")
    return "\n".join(lines)


def _call_llm(prompt: str) -> str:
    """调用 LLM 生成文章内容"""
    if not LLM_API_KEY:
        logger.error("❌ LLM_API_KEY 未设置！请在环境变量或 config.py 中配置")
        return _fallback_no_api(prompt)

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一位中文科技公众号博主「布丁」。你用大白话讲AI，有态度有观点，文章读起来像朋友聊天，读者都说你写得通俗易懂又有深度。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=4000,
        )

        return resp.choices[0].message.content

    except Exception as e:
        logger.error(f"❌ LLM 调用失败: {e}")
        return _fallback_no_api(prompt)


def _fallback_no_api(prompt: str) -> str:
    """当 API 不可用时的降级方案：生成结构化模板"""
    logger.warning("⚠️ 使用降级方案：生成结构化文章模板")
    return """# ⚠️ 今日 AI 资讯简报（API 未配置）

## 📌 今日快讯

本文由 AI 资讯情报官自动生成。
请配置 LLM_API_KEY 以启用 AI 撰写功能。

## 如何配置

1. 设置环境变量：export OPENAI_API_KEY="你的 key"
2. 或在 config.py 中直接填写 LLM_API_KEY

支持 OpenAI、DeepSeek 等任意兼容 API。
"""


def generate_daily_brief(items: list[dict]) -> str:
    """生成每日 AI 资讯简报"""
    logger.info("📝 生成每日 AI 资讯简报...")

    items_text = _build_items_text(items)

    prompt = DAILY_BRIEF_PROMPT.format(
        writer_style=WRITER_STYLE,
        tone=TONE,
        length=ARTICLE_LENGTH,
        audience=TARGET_AUDIENCE,
        items=items_text,
    )

    content = _call_llm(prompt)
    return content


def generate_deep_dive(trend: dict) -> str:
    """生成深度选题文章"""
    topic = trend["topic"]
    logger.info(f"📝 生成深度文章: {topic}")

    items_text = _build_items_text(trend["articles"])

    prompt = DEEP_DIVE_PROMPT.format(
        writer_style=WRITER_STYLE,
        tone=TONE,
        topic=topic,
        length=ARTICLE_LENGTH,
        audience=TARGET_AUDIENCE,
        items=items_text,
    )

    content = _call_llm(prompt)
    return content


def save_article(content: str, topic: str, article_type: str = "daily") -> str:
    """保存生成的文章到 output 目录"""
    today = datetime.now().strftime("%Y%m%d")
    safe_topic = "".join(c for c in topic if c.isalnum() or c in " _-")[:30]
    filename = f"{today}_{article_type}_{safe_topic}.md"
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info(f"💾 文章已保存: {path}")
    return str(path)
