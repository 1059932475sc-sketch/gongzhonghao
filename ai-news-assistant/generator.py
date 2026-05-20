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

DAILY_BRIEF_PROMPT = """你是一位{writer_style}，正在为{tone}的中文科技读者撰写今日 AI 资讯简报。

## 你的任务
根据以下今日 AI 资讯素材，撰写一篇约 {length} 的微信公众号文章。

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 开篇要有吸引力（hook），让人想读下去
- 每段小标题要抓人眼球
- 内容要深度：不要只是罗列新闻，要讲背后的意义和趋势
- 适当加入你自己的评论和见解
- 结尾要有总结和展望
- 全文用中文，专业术语保留英文并附括号中文释义

## 今日素材
{items}

## 文章格式要求
请用以下格式输出（方便后续直接发布到公众号）：

# 标题（这里写一个吸引人的标题）

## 📌 今日看点（3-5条一句话总结）

## 🔥 正文（按重要性排列）

## 💡 我的观点

## 📚 延伸阅读
"""


DEEP_DIVE_PROMPT = """你是一位{writer_style}，正在为{tone}的中文科技读者撰写一篇深度分析文章。

## 触发条件
今天有多个权威来源同时报道了 **{topic}**，说明这是一个重要趋势，值得深入分析。

## 你的任务
基于以下素材，写一篇约 {length} 的深度分析文章。

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 开篇：一个有力的 hook（数据、故事或反常识的观点）
- 背景：这个技术/工具是什么？为什么在此时爆发？
- 深度分析：技术原理（通俗解释）、行业影响、竞争格局
- 案例：具体的应用场景或产品
- 未来展望：接下来会发生什么？
- 结尾：点题升华
- 全文用中文，专业术语保留英文并附中文释义

## 相关素材
{items}

## 文章格式要求
请用以下格式输出：

# 标题（这里写一个吸引人的深度标题）

## 🎯 核心观点（一句话总结）

## 🔥 正文

### 1. 发生了什么？
### 2. 为什么重要？
### 3. 深入解读
### 4. 影响与启示

## 💡 写在最后

## 📚 参考来源
"""


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
                {"role": "system", "content": "你是一位资深科技媒体主编，擅长撰写高质量的中文科技分析文章。"},
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
