"""
AI 资讯情报官 - 飞书推送模块
============================
通过 Webhook 机器人发送消息到飞书会话
"""

import json
import logging
from datetime import datetime

import requests

from config import FEISHU_WEBHOOK_URL

logger = logging.getLogger(__name__)


def send_news_notification(items: list[dict], articles: list[dict]) -> bool:
    """
    发送今日 AI 资讯简报到飞书

    参数:
        items: 抓取到的原始资讯列表
        articles: 生成的文章列表

    返回:
        bool: 是否发送成功
    """
    if not FEISHU_WEBHOOK_URL:
        logger.warning("⚠️ FEISHU_WEBHOOK_URL 未配置，跳过飞书推送")
        return False

    if not items:
        # 今日无内容时发送提示
        card = _build_empty_card()
    else:
        card = _build_news_card(items, articles)

    payload = {
        "msg_type": "interactive",
        "card": card,
    }

    try:
        resp = requests.post(
            FEISHU_WEBHOOK_URL,
            json=payload,
            timeout=15,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if data.get("StatusCode") == 0 or data.get("code") == 0:
            logger.info("✅ 飞书推送成功!")
            return True
        else:
            logger.error(f"❌ 飞书推送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"❌ 飞书推送异常: {e}")
        return False


def send_text_message(text: str) -> bool:
    """发送纯文本消息到飞书"""
    if not FEISHU_WEBHOOK_URL:
        return False

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }

    try:
        resp = requests.post(
            FEISHU_WEBHOOK_URL,
            json=payload,
            timeout=15,
        )
        return resp.json().get("StatusCode") == 0 or resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"飞书文本消息发送失败: {e}")
        return False


def _build_news_card(items: list[dict], articles: list[dict]) -> dict:
    """构建飞书消息卡片（图文并茂的资讯简报）"""
    today = datetime.now().strftime("%Y-%m-%d")
    source_names = list({it.get("source_name", "未知") for it in items})
    sources_text = " | ".join(source_names[:6])

    # 精选资讯（最多展示 10 条）
    top_items = items[:10]

    # 构建标题和摘要
    elements = [
        {
            "tag": "markdown",
            "content": f"**📡 今日抓取:** {len(items)} 条资讯\n"
                       f"**📝 生成文章:** {len(articles)} 篇\n"
                       f"**🌐 信息来源:** {sources_text}",
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": "**🔥 热门资讯速览**",
        },
    ]

    for i, item in enumerate(top_items, 1):
        title = item["title"][:60]
        source = item.get("source_name", "未知")
        summary = item["summary"][:100] + ("..." if len(item["summary"]) > 100 else "")
        url = item.get("url", "")

        if url:
            elements.append({
                "tag": "markdown",
                "content": f"{i}. **{title}** ({source})\n"
                           f"   {summary}\n"
                           f"   [🔗 查看原文]({url})",
            })
        else:
            elements.append({
                "tag": "markdown",
                "content": f"{i}. **{title}** ({source})\n   {summary}",
            })
        elements.append({"tag": "divider"})

    # 生成的文章
    if articles:
        elements.append({
            "tag": "markdown",
            "content": "**📄 已生成文章**",
        })
        for art in articles:
            elements.append({
                "tag": "markdown",
                "content": f"- [{art['type']}] {art['topic']}",
            })

    # 底部按钮
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "content": f"🤖 AI 资讯情报官 · 自动生成于 {today}",
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📰 AI 资讯简报 | {today}",
            },
            "template": "blue",
        },
        "elements": elements,
    }

    return card


def _build_empty_card() -> dict:
    """今日无资讯时的占位卡片"""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📰 AI 资讯简报 | {today}",
            },
            "template": "yellow",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": "今日无新增资讯内容。\n\n可能原因：\n- 各信息源暂未更新\n- 所有内容均为重复内容已去重\n- 网络请求异常\n\n明天会继续为您抓取。",
            },
            {
                "tag": "hr",
            },
            {
                "tag": "note",
                "content": "🤖 AI 资讯情报官 · 自动运行",
            },
        ],
    }
