"""
国内社会热点公众号主流程：每天一篇，直接进草稿箱，不推飞书。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from analyzer import select_topics
from analyzer import compliance_check
from config import ARTICLE_COUNT, DATA_DIR, OUTPUT_DIR
from feishu_publisher import send_news_notification
from generator import generate_article, save_article
from publisher import WeChatPublisher
from scraper import fetch_all


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run(enable_publish: bool = True, enable_feishu: bool = False) -> dict:
    items = fetch_all()
    selected = select_topics(items, 12)
    report = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fetched": len(items),
        "articles": [],
        "publish_status": "未尝试发布",
        "feishu_ok": False,
    }
    published_count = 0
    for sel in selected:
        title, article = generate_article(sel, published_count + 1)
        ok_compliance, risks = compliance_check(title, article)
        if not ok_compliance:
            logger.error("❌ 发布前合规拦截：%s risks=%s", title, risks)
            continue
        published_count += 1
        path = save_article(title, article, published_count)
        ok, msg = (False, "未推送公众号草稿箱")
        if enable_publish:
            publisher = WeChatPublisher()
            ok, msg = publisher.create_draft(title, article)
        report["articles"].append({
            "title": title,
            "source_title": sel["item"]["title"],
            "source": sel["item"]["source"],
            "path": path,
            "draft_ok": ok,
            "draft_message": msg,
            "compliance": "已过滤政治/高风险词，按生活观察口径生成",
        })
        logger.info("%s %s", "✅" if ok else "❌", msg)
        if published_count >= ARTICLE_COUNT:
            break
    if enable_publish:
        report["publish_status"] = "草稿箱已尝试创建"
    else:
        report["publish_status"] = "未推送公众号草稿箱"
    if enable_feishu:
        report["feishu_ok"] = send_news_notification(report)
        report["publish_status"] = "飞书推送成功" if report["feishu_ok"] else "飞书推送失败"
    report_path = DATA_DIR / f"report_{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import sys

    enable_publish = "--publish" in sys.argv
    enable_feishu = "--feishu" in sys.argv
    result = run(enable_publish=enable_publish, enable_feishu=enable_feishu)
    print(json.dumps(result, ensure_ascii=False, indent=2))
