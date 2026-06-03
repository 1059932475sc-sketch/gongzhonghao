"""
AI 资讯情报官 - 飞书推送模块
============================
通过 Webhook 机器人发送消息到飞书会话
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
import sys

import requests

from config import FEISHU_WEBHOOK_URL

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wewrite_bridge import render_markdown_with_wewrite

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


def send_pipeline_status(title: str, lines: list[str]) -> bool:
    """发送流程状态文本，适合失败告警或空结果提示。"""
    body = "\n".join([title, ""] + [line for line in lines if line])
    return _send_text(body)


def _to_feishu_readable_text(markdown_text: str) -> str:
    """把公众号 Markdown 草稿转成飞书里更容易直接阅读/复制的纯文本。"""
    text = markdown_text
    text = re.sub(r"^#\s+", "", text, flags=re.M)
    text = re.sub(r"^##\s+", "\n", text, flags=re.M)
    text = re.sub(r"^###\s+", "\n", text, flags=re.M)
    text = text.replace("```text\n", "").replace("```", "")
    text = text.replace("**", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_news_notification(
    items: list[dict],
    articles: list[dict],
    selections: list[dict] = None,
    draft_results: list[dict] = None,
) -> bool:
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

    # ---- 第一部分：纯文本运营摘要 ----
    # 飞书互动卡片容易限频；用户更需要直接在飞书读到内容，所以默认发纯文本。
    summary = _build_text_summary(items, articles, selections or [], draft_results or [])
    if _send_text(summary):
        logger.info("✅ 运营摘要已发送")
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

        readable = _to_feishu_readable_text(content)
        account = art.get("account", "公众号")
        themed = render_markdown_with_wewrite(path)
        theme_line = ""
        if themed:
            theme_line = (
                f"排版主题：{themed['theme']}\n"
                f"预览文件：{themed['preview_html_path']}\n"
                f"发布文件：{themed['body_html_path']}\n\n"
            )

        # 飞书 webhook 文本消息有长度限制，单条控制在 3000 字以内。
        # 这里直接发送可读正文，不要求用户打开本地 Markdown 文件。
        MAX_LEN = 2600
        header = (
            f"【今日可发公众号正文】\n"
            f"账号：{account}\n"
            f"标题：{title}\n\n"
            f"{theme_line}"
            f"正文如下，直接在飞书里复制即可：\n\n"
        )
        footer = "\n\n---\n操作：复制上面正文 → 粘贴到公众号编辑器 → 发布前加一句你自己的真实判断。"

        if len(header) + len(readable) + len(footer) <= MAX_LEN:
            msg = f"{header}{readable}{footer}"
            if _send_text(msg):
                logger.info(f"✅ 文章已发送: {title}")
            else:
                all_ok = False
        else:
            total_parts = (len(readable) + MAX_LEN - 1) // MAX_LEN
            for i in range(total_parts):
                start = i * MAX_LEN
                end = start + MAX_LEN
                chunk = readable[start:end]
                if i == 0:
                    msg = f"{header}（第 {i+1}/{total_parts} 段）\n\n{chunk}"
                elif i == total_parts - 1:
                    msg = f"【续】{title}（第 {i+1}/{total_parts} 段）\n\n{chunk}{footer}"
                else:
                    msg = f"【续】{title}（第 {i+1}/{total_parts} 段）\n\n{chunk}"
                if _send_text(msg):
                    logger.info(f"✅ 文章片段已发送: {title} ({i+1}/{total_parts})")
                else:
                    all_ok = False

    if all_ok:
        logger.info("✅ 飞书推送全部完成!")
    return all_ok


def _build_text_summary(
    items: list[dict],
    articles: list[dict],
    selections: list[dict],
    draft_results: list[dict],
) -> str:
    """构建飞书纯文本运营摘要，不依赖互动卡片。"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"【AI信息差公众号推送】{today}",
        "",
        f"今日抓取：{len(items)} 条候选资讯",
        f"今日正文：{len(articles)} 篇，下面会直接发送全文",
        "",
        "今日选题：",
    ]

    if selections:
        for idx, sel in enumerate(selections, 1):
            account = sel["account"]
            item = sel["item"]
            score = sel["score"]
            reasons = "；".join(score.get("reasons", []))
            lines.extend([
                f"{idx}. {account['account_name']}",
                f"选题：{item.get('title', '')}",
                f"来源：{item.get('source_name', '未知')}",
                f"分数：总分 {score['total_score']}｜流量 {score['traffic_score']}｜收益 {score['money_score']}｜风险 {score['risk_score']}",
                f"理由：{reasons}",
                "",
            ])
    else:
        lines.append("今天没有筛出高分选题，会使用兜底简报。")

    lines.extend([
        "草稿箱结果：",
    ])

    if draft_results:
        for d in draft_results:
            status = "成功" if d.get("ok") else "失败"
            lines.append(f"- {status}：{d.get('account', '公众号')}｜{d.get('message', '')}")
    else:
        lines.append("- 未尝试创建草稿箱，可能未配置公众号 AppID/AppSecret。")

    lines.extend([
        "",
        "操作：如果草稿箱成功，去公众号后台草稿箱检查即可；飞书后面仍会发两篇正文，方便你手机上直接看。",
        "发布前建议加一句你自己的判断或体验，让文章更像真人账号。",
    ])
    return "\n".join(lines)


def _build_news_card(items: list[dict], articles: list[dict], selections: list[dict] = None) -> dict:
    """构建飞书消息卡片：双公众号运营看板 + 今日文章清单。"""
    today = datetime.now().strftime("%Y-%m-%d")
    source_names = list({it.get("source_name", "未知") for it in items})
    sources_text = " | ".join(source_names[:6])
    selections = selections or []

    elements = [
        {
            "tag": "markdown",
            "content": f"**📡 今日抓取:** {len(items)} 条候选资讯\n"
                       f"**📝 今日发稿:** {len(articles)} 篇（两个公众号各 1 篇）\n"
                       f"**🌐 信息来源:** {sources_text}",
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": "**🎯 今日运营选题**",
        },
    ]

    if selections:
        for sel in selections:
            account = sel["account"]
            item = sel["item"]
            score = sel["score"]
            title = item.get("title", "")[:70]
            source = item.get("source_name", "未知")
            url = item.get("url", "")
            reasons = "；".join(score.get("reasons", []))
            elements.append({
                "tag": "markdown",
                "content": f"**{account['account_name']}**\n"
                           f"选题：[{title}]({url})\n"
                           f"来源：{source}\n"
                           f"总分：**{score['total_score']}**｜流量 {score['traffic_score']}｜收益 {score['money_score']}｜风险 {score['risk_score']}\n"
                           f"理由：{reasons}",
            })
            elements.append({"tag": "hr"})
    else:
        top_items = items[:5]
        for i, item in enumerate(top_items, 1):
            title = item["title"][:60]
            source = item.get("source_name", "未知")
            summary = item["summary"][:100] + ("..." if len(item["summary"]) > 100 else "")
            url = item.get("url", "")
            elements.append({
                "tag": "markdown",
                "content": f"{i}. **{title}** ({source})\n{summary}\n[🔗 查看原文]({url})",
            })
        elements.append({"tag": "hr"})

    # 生成的文章
    if articles:
        elements.append({
            "tag": "markdown",
            "content": "**📄 下方会直接发送两篇正文，不需要打开本地 Markdown 文件**",
        })
        for art in articles:
            account = art.get("account", "公众号")
            elements.append({
                "tag": "markdown",
                "content": f"📄 **[{account}] {art['topic']}**",
            })

    # 底部
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "content": f"👇 工作流：先看运营选题 → 再复制下方两篇全文 → 两个公众号各发一篇 → 次日按阅读/在看/关注复盘",
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🧭 双公众号运营看板 | {today}",
            },
            "template": "green",
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
