"""
AI 资讯情报官 - 主控协调模块
=============================
编排完整的自动化流程：
抓取 → 分析 → 生成 → 发布
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import DATA_DIR
from scraper import fetch_all
from analyzer import detect_trends
from generator import generate_daily_brief, generate_deep_dive, save_article
from publisher import auto_publish, generate_publish_guide
from feishu_publisher import send_news_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_pipeline(enable_publish: bool = False, enable_feishu: bool = False) -> dict:
    """
    执行完整情报流水线

    参数:
        enable_publish: 是否尝试发布到公众号（默认只生成文件）

    返回:
        dict: 执行结果报告
    """
    start_time = datetime.now()
    report = {
        "运行时间": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "抓取数量": 0,
        "热点数量": 0,
        "深度选题": [],
        "生成文章": [],
        "发布状态": "未发布",
    }

    logger.info("=" * 50)
    logger.info("🤖 AI 资讯情报官 开始今日作业")
    logger.info("=" * 50)

    # ============================================================
    # 第一步：抓取
    # ============================================================
    logger.info("\n📡 === 第一步：资讯抓取 ===")
    items = fetch_all()
    report["抓取数量"] = len(items)

    if not items:
        logger.warning("⚠️ 今日无新内容，跳过后续步骤")
        return report

    # 保存原始抓取结果
    today = datetime.now().strftime("%Y-%m-%d")
    raw_path = DATA_DIR / f"raw_{today}.json"
    raw_data = [
        {
            "title": it["title"],
            "url": it["url"],
            "summary": it["summary"][:200],
            "source": it.get("source_name", "未知"),
        }
        for it in items
    ]
    raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"💾 原始数据已保存: {raw_path}")

    # ============================================================
    # 第二步：热点分析
    # ============================================================
    logger.info("\n🔍 === 第二步：热点分析 ===")
    trends = detect_trends(items)
    report["热点数量"] = len(trends)

    # 检查是否触发深度选题
    deep_dives = [t for t in trends if t["is_deep_dive"]]
    report["深度选题"] = [t["topic"] for t in deep_dives]

    # ============================================================
    # 第三步：文章生成
    # ============================================================
    logger.info("\n📝 === 第三步：文章生成 ===")

    articles_generated = []

    if deep_dives:
        # 触发深度选题 → 生成深度文章
        for trend in deep_dives[:2]:  # 最多写 2 篇深度
            logger.info(f"\n🔥 撰写深度文章: {trend['topic']}")
            content = generate_deep_dive(trend)
            topic = trend["topic"]
            path = save_article(content, topic, "deep_dive")
            articles_generated.append({
                "type": "deep_dive",
                "topic": topic,
                "path": path,
            })

    # 天天发日报
    logger.info("\n📰 生成每日资讯简报")
    daily_content = generate_daily_brief(items)
    daily_path = save_article(daily_content, "AI资讯简报", "daily")
    articles_generated.append({
        "type": "daily",
        "topic": "AI资讯简报",
        "path": daily_path,
    })

    report["生成文章"] = articles_generated

    # ============================================================
    # 第四步：发布
    # ============================================================
    if enable_publish and articles_generated:
        logger.info("\n📤 === 第四步：发布 ===")
        for article in articles_generated:
            if article["type"] == "daily":
                title = f"AI 资讯简报 | {today}"
                content = Path(article["path"]).read_text(encoding="utf-8")
                success = auto_publish(title, content, article["path"])
                report["发布状态"] = "已尝试发布" if success else "发布失败"
    elif enable_feishu:
        # 飞书推送模式
        logger.info("\n📤 === 飞书推送 ===")
        feishu_ok = send_news_notification(items, articles_generated)
        report["发布状态"] = "飞书推送成功" if feishu_ok else "飞书推送失败"
    else:
        # 生成发布指南
        for article in articles_generated:
            generate_publish_guide(article["path"])
        report["发布状态"] = "文件已生成，请手动发布"

    # ============================================================
    # 完成
    # ============================================================
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("\n" + "=" * 50)
    logger.info(f"✅ 今日作业完成！耗时 {elapsed:.1f} 秒")
    logger.info("=" * 50)

    # 保存执行报告
    report_path = DATA_DIR / f"report_{today}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"📋 执行报告已保存: {report_path}")

    return report


def print_report(report: dict):
    """友好地打印执行报告"""
    print("\n" + "=" * 50)
    print("📊 AI 资讯情报官 - 作业报告")
    print("=" * 50)
    print(f"⏱  运行时间: {report['运行时间']}")
    print(f"📡 抓取资讯: {report['抓取数量']} 条")
    print(f"🔍 热点话题: {report['热点数量']} 个")

    if report["深度选题"]:
        print(f"🔥 深度选题:")
        for t in report["深度选题"]:
            print(f"   - {t}")
    else:
        print(f"📊 深度选题: 无")

    print(f"\n📝 生成文章:")
    for a in report["生成文章"]:
        print(f"   - [{a['type']}] {a['topic']}")
        print(f"     📄 {a['path']}")

    print(f"\n📤 发布状态: {report['发布状态']}")
    print("=" * 50)
    print("💡 提示: 直接运行 python main.py --feishu 推送到飞书")
    print("=" * 50)


if __name__ == "__main__":
    import sys

    enable_publish = "--publish" in sys.argv
    enable_feishu = "--feishu" in sys.argv
    report = run_pipeline(enable_publish=enable_publish, enable_feishu=enable_feishu)
    print_report(report)
