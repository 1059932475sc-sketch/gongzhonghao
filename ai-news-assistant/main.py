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

from config import DATA_DIR, WECHAT_APPID, WECHAT_APPSECRET
from scraper import fetch_all, get_fetch_stats
from analyzer import detect_trends, select_public_account_topics
from generator import (
    generate_daily_brief, generate_deep_dive, generate_public_account_article,
    save_article, get_llm_status, reset_llm_status,
)
from publisher import auto_publish, create_wechat_draft_from_file, generate_publish_guide
from feishu_publisher import send_news_notification, send_pipeline_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _save_report(today: str, report: dict) -> Path:
    report_path = DATA_DIR / f"report_{today}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"📋 执行报告已保存: {report_path}")
    return report_path


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
        "公众号选题": [],
        "生成文章": [],
        "草稿箱": [],
        "抓取详情": [],
        "错误摘要": [],
        "模型状态": {},
        "发布状态": "未发布",
    }
    today = datetime.now().strftime("%Y-%m-%d")
    reset_llm_status()

    logger.info("=" * 50)
    logger.info("🤖 AI 资讯情报官 开始今日作业")
    logger.info("=" * 50)

    # ============================================================
    # 第一步：抓取
    # ============================================================
    logger.info("\n📡 === 第一步：资讯抓取 ===")
    items = fetch_all()
    report["抓取数量"] = len(items)
    report["抓取详情"] = get_fetch_stats()
    report["错误摘要"] = [
        f"{detail['name']}: {detail['error']}"
        for detail in report["抓取详情"]
        if detail.get("error")
    ]

    if not items:
        logger.warning("⚠️ 今日无新内容，跳过后续步骤")
        report["发布状态"] = "抓取为空，已跳过后续步骤"
        _save_report(today, report)
        if enable_feishu:
            alert_lines = [
                f"运行时间：{report['运行时间']}",
                f"抓取数量：{report['抓取数量']} 条",
                "状态：今天没有生成文章，后续步骤未执行。",
            ]
            if report["错误摘要"]:
                alert_lines.extend(["", "抓取错误："] + report["错误摘要"][:8])
            send_pipeline_status("【AI信息差自动化告警】今日抓取为空", alert_lines)
        return report

    # 保存原始抓取结果
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

    account_selections = select_public_account_topics(items, trends)
    report["公众号选题"] = [
        {
            "account": sel["account"]["account_name"],
            "title": sel["item"].get("title", ""),
            "score": sel["score"],
        }
        for sel in account_selections
    ]

    # ============================================================
    # 第三步：文章生成
    # ============================================================
    logger.info("\n📝 === 第三步：文章生成 ===")

    articles_generated = []

    if account_selections:
        # 双公众号运营模式：每天两个号各生成 1 篇
        for selection in account_selections:
            profile = selection["account"]
            item = selection["item"]
            logger.info(f"\n🔥 为「{profile['account_name']}」撰写文章: {item.get('title', '')}")
            content = generate_public_account_article(selection)
            topic = f"{profile['account_name']}_{item.get('title', '今日选题')}"
            path = save_article(content, topic, profile["article_type"])
            articles_generated.append({
                "type": profile["article_type"],
                "account": profile["account_name"],
                "topic": topic,
                "path": path,
                "selection": {
                    "title": item.get("title", ""),
                    "source": item.get("source_name", ""),
                    "url": item.get("url", ""),
                    "score": selection["score"],
                },
            })
    else:
        # 兜底：抓取到内容但选题评分不足时，仍生成一篇旧版简报，避免当天断档
        logger.info("\n📰 未选出公众号题，生成每日资讯简报兜底")
        daily_content = generate_daily_brief(items)
        daily_path = save_article(daily_content, "AI资讯简报", "daily")
        articles_generated.append({
            "type": "daily",
            "account": "兜底简报",
            "topic": "AI资讯简报",
            "path": daily_path,
        })

    report["生成文章"] = articles_generated
    report["模型状态"] = get_llm_status()

    # ============================================================
    # 第四步：公众号草稿箱
    # ============================================================
    draft_results = []
    if WECHAT_APPID and WECHAT_APPSECRET and articles_generated:
        logger.info("\n📬 === 公众号草稿箱 ===")
        for article in articles_generated:
            ok, message = create_wechat_draft_from_file(
                article["path"],
                article.get("topic", "AI信息差公众号文章"),
            )
            draft_results.append({
                "account": article.get("account", article.get("type", "公众号")),
                "path": article["path"],
                "ok": ok,
                "message": message,
            })
            if ok:
                logger.info(f"✅ {message}")
            else:
                logger.error(f"❌ {message}")
    report["草稿箱"] = draft_results

    # ============================================================
    # 第五步：飞书/手动发布提示
    # ============================================================
    if enable_publish and articles_generated and not draft_results:
        logger.info("\n📤 === 第五步：发布 ===")
        for article in articles_generated:
            if article["type"] == "daily":
                title = f"AI 资讯简报 | {today}"
                content = Path(article["path"]).read_text(encoding="utf-8")
                success = auto_publish(title, content, article["path"])
                report["发布状态"] = "已尝试发布" if success else "发布失败"
    if enable_feishu:
        # 飞书推送模式
        logger.info("\n📤 === 飞书推送 ===")
        feishu_ok = send_news_notification(items, articles_generated, account_selections, draft_results)
        draft_ok = bool(draft_results) and all(d["ok"] for d in draft_results)
        llm_fallback = report["模型状态"].get("mode") == "fallback"
        if feishu_ok and draft_ok and not llm_fallback:
            report["发布状态"] = "飞书推送成功，草稿箱创建成功"
        elif feishu_ok and draft_ok:
            report["发布状态"] = "飞书推送成功，草稿箱创建成功，但模型已降级"
        elif feishu_ok:
            report["发布状态"] = "飞书推送成功，草稿箱未全部成功"
        else:
            report["发布状态"] = "飞书推送失败"
    elif not enable_publish:
        # 生成发布指南
        for article in articles_generated:
            generate_publish_guide(article["path"])
        report["发布状态"] = "文件已生成，请手动发布" if not draft_results else "草稿箱已尝试创建"

    # ============================================================
    # 完成
    # ============================================================
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("\n" + "=" * 50)
    logger.info(f"✅ 今日作业完成！耗时 {elapsed:.1f} 秒")
    logger.info("=" * 50)

    # 保存执行报告
    _save_report(today, report)

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

    if report.get("公众号选题"):
        print(f"\n🎯 今日公众号选题:")
        for s in report["公众号选题"]:
            print(f"   - [{s['account']}] {s['title'][:60]}")
            print(f"     分数: {s['score']['total_score']} | 流量 {s['score']['traffic_score']} | 收益 {s['score']['money_score']}")

    print(f"\n📝 生成文章:")
    for a in report["生成文章"]:
        print(f"   - [{a.get('account', a['type'])}] {a['topic']}")
        print(f"     📄 {a['path']}")

    if report.get("草稿箱"):
        print(f"\n📬 草稿箱:")
        for d in report["草稿箱"]:
            status = "成功" if d["ok"] else "失败"
            print(f"   - [{status}] {d['account']}: {d['message']}")

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
