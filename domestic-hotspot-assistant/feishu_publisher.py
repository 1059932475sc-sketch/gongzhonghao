"""
国内热点文章推送到飞书，附带 wewrite 排版产物路径。
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

from config import FEISHU_WEBHOOK_URL

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wewrite_bridge import render_markdown_with_wewrite


logger = logging.getLogger(__name__)


def _send_text(text: str) -> bool:
    if not FEISHU_WEBHOOK_URL:
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=15)
        data = resp.json()
        return data.get("StatusCode") == 0 or data.get("code") == 0
    except Exception as e:
        logger.error("飞书消息发送失败: %s", e)
        return False


def _to_feishu_readable_text(markdown_text: str) -> str:
    text = markdown_text
    text = re.sub(r"^#\s+", "", text, flags=re.M)
    text = re.sub(r"^##\s+", "\n", text, flags=re.M)
    text = text.replace("**", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_news_notification(report: dict) -> bool:
    if not FEISHU_WEBHOOK_URL:
        logger.warning("⚠️ FEISHU_WEBHOOK_URL 未配置，跳过飞书推送")
        return False

    articles = report.get("articles", [])
    today = datetime.now().strftime("%Y-%m-%d")
    summary_lines = [
        f"【国内热点公众号推送】{today}",
        "",
        f"今日抓取：{report.get('fetched', 0)} 条热点",
        f"今日正文：{len(articles)} 篇，下面会直接发送全文",
        "",
        "选题：",
    ]

    for idx, article in enumerate(articles, 1):
        summary_lines.extend([
            f"{idx}. {article.get('title', '')}",
            f"来源：{article.get('source', '未知')}｜原始标题：{article.get('source_title', '')}",
            f"合规说明：{article.get('compliance', '')}",
            "",
        ])

    if not _send_text("\n".join(summary_lines)):
        return False

    all_ok = True
    for article in articles:
        path = article.get("path", "")
        if not path:
            continue
        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            logger.error("读取文章失败 %s: %s", path, e)
            all_ok = False
            continue

        themed = render_markdown_with_wewrite(path)
        theme_line = ""
        if themed:
            theme_line = (
                f"排版主题：{themed['theme']}\n"
                f"预览文件：{themed['preview_html_path']}\n"
                f"发布文件：{themed['body_html_path']}\n\n"
            )

        readable = _to_feishu_readable_text(content)
        header = (
            "【今日可发公众号正文】\n"
            f"账号：国内热点\n"
            f"标题：{article.get('title', '')}\n\n"
            f"{theme_line}"
            "正文如下，直接在飞书里复制即可：\n\n"
        )
        footer = "\n\n---\n操作：热点文保持克制口吻，发布前补一句你自己的观察。"
        body = f"{header}{readable}{footer}"

        max_len = 2600
        if len(body) <= max_len:
            if not _send_text(body):
                all_ok = False
        else:
            chunk_size = 2300
            chunks = [readable[i:i + chunk_size] for i in range(0, len(readable), chunk_size)]
            for idx, chunk in enumerate(chunks, 1):
                if idx == 1:
                    msg = f"{header}（第 {idx}/{len(chunks)} 段）\n\n{chunk}"
                elif idx == len(chunks):
                    msg = f"【续】{article.get('title', '')}（第 {idx}/{len(chunks)} 段）\n\n{chunk}{footer}"
                else:
                    msg = f"【续】{article.get('title', '')}（第 {idx}/{len(chunks)} 段）\n\n{chunk}"
                if not _send_text(msg):
                    all_ok = False

    return all_ok
