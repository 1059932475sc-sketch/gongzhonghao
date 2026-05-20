"""
AI 资讯情报官 - 飞书推送模块
============================
通过 Webhook 机器人发送消息到飞书会话
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests

from config import FEISHU_WEBHOOK_URL

logger = logging.getLogger(__name__)

# 生成的文章会提交到 GitHub，这里构造可访问的 Raw URL
GITHUB_REPO = "1059932475sc-sketch/gongzhonghao"
GITHUB_BRANCH = "main"
ARTICLE_DIR = "ai-news-assistant/output"
GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{ARTICLE_DIR}"


def _article_url(article_path: str) -> str:
    """从本地路径提取文件名，构造 GitHub 可访问 URL"""
    filename = Path(article_path).name
    return f"{GITHUB_RAW_BASE}/{filename}"


def _send_card(card: dict) -> bool:
    """发送消息卡片到飞书"""
    payload = {"msg_type": "interactive", "card": card}
    try:
        resp = requests.post(
            FEISHU_WEBHOOK_URL, json=payload, timeout=15,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if data.get("StatusCode") == 0 or data.get("code") == 0:
            return True
        logger.error(f"❌ 飞书推送失败: {data}")
        return False
    except Exception as e:
        logger.error(f"❌ 飞书推送异常: {e}")
        return False


def _send_text(text: str) -> bool:
    """发送纯文本消息到飞书"""
    if not FEISHU_WEBHOOK_URL:
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=15)
        return resp.json().get("StatusCode") == 0 or resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"飞书文本消息发送失败: {e}")
        return False


def send_news_notification(items: list[dict], articles: list[dict]) -> bool:
    """
    发送今日 AI 资讯简报到飞书

    分两部分发送：
    1. 消息卡片 —— 资讯概览（标题、数量、热点速览）
    2. 文章正文 —— 每篇生成的文章全文，可直接阅读复制
    """
    if not FEISHU_WEBHOOK_URL:
        logger.warning("⚠️ FEISHU_WEBHOOK_URL 未配置，跳过飞书推送")
        return False

    all_ok = True

    # ---- 第一部分：消息卡片（概览） ----
    card = _build_empty_card() if not items else _build_news_card(items, articles)
    if _send_card(card):
        logger.info("✅ 资讯概览卡片已发送")
    else:
        all_ok = False

    # ---- 第二部分：文章全文 ----
    for art in articles:
        path = art.get("path", "")
        if not path:
            continue

        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"⚠️ 读取文章失败 {path}: {e}")
            continue

        # 提取标题（第一行 # 开头的）
        lines = content.split("\n")
        title_line = ""
        for line in lines:
            if line.startswith("# "):
                title_line = line.strip("# ").strip()
                break
        title = title_line or art["topic"]

        # 飞书 webhook 文本消息有长度限制，单条控制在 3000 字以内
        # 文章过长则分多条发送，每条加页码
        MAX_LEN = 2800
        if len(content) <= MAX_LEN:
            msg = f"📄 {title}\n\n---\n\n{content}\n\n---\n🤖 AI 资讯情报官"
            if _send_text(msg):
                logger.info(f"✅ 文章已发送: {title}")
            else:
                all_ok = False
        else:
            # 分条发送
            total_parts = (len(content) + MAX_LEN - 1) // MAX_LEN
            for i in range(total_parts):
                start = i * MAX_LEN
                end = start + MAX_LEN
                chunk = content[start:end]
                if i == 0:
                    msg = f"📄 {title} (1/{total_parts})\n\n---\n\n{chunk}"
                else:
                    msg = f"📄 {title} ({i+1}/{total_parts})\n\n{chunk}"
                if _send_text(msg):
                    logger.info(f"✅ 文章片段已发送: {title} ({i+1}/{total_parts})")
                else:
                    all_ok = False

    if all_ok:
        logger.info("✅ 飞书推送全部完成!")
    return all_ok


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
        elements.append({"tag": "hr"})

    # 生成的文章
    if articles:
        elements.append({
            "tag": "markdown",
            "content": "**📄 已生成文章（下方会逐篇发送全文）**",
        })
        for art in articles:
            art_type_label = "深度分析" if art['type'] == 'deep_dive' else "每日简报"
            elements.append({
                "tag": "markdown",
                "content": f"📄 **[{art_type_label}] {art['topic']}**",
            })

    # 底部
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "content": f"👇 每篇文章的全文会作为单独消息发送，可直接阅读复制",
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
            {"tag": "hr"},
            {
                "tag": "note",
                "content": "🤖 AI 资讯情报官 · 自动运行",
            },
        ],
    }
