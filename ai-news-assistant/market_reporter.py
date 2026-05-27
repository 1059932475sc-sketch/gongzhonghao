"""
每日个股追踪日报 - 飞书推送
==========================
抓取指定个股的详细数据（价格、涨跌幅、成交量等），
自动检测最大波动和异常信号，
用 AI 生成行情解读，最后推送到飞书。
"""

import json
import logging
import statistics
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import (
    FEISHU_WEBHOOK_URL as _WEBHOOK_URL,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
)

logger = logging.getLogger(__name__)


# ============================================================
# 追踪标的配置
# ============================================================

STOCKS = [
    # (symbol, 中文名, 英文名)
    ("NVDA",  "英伟达",    "NVIDIA"),
    ("INTC",  "英特尔",    "Intel"),
    ("ORCL",  "甲骨文",    "Oracle"),
    ("NOK",   "诺基亚",    "Nokia"),
    ("MRVL",  "迈威尔科技",  "Marvell Technology"),
    ("QCOM",  "高通",      "Qualcomm"),
    ("AAOI",  "应用光电",   "Applied Optoelectronics"),
    ("SMCI",  "超威电脑",   "Super Micro Computer"),
    ("QQQM",  "纳指ETF",   "Invesco QQQM"),
    ("VOO",   "标普500ETF", "Vanguard S&P 500 ETF"),
    ("SOXQ",  "半导体ETF",  "Invesco PHLX Semiconductor ETF"),
]

# 基准指数（用于大盘环境判断）
BENCHMARKS = ["^GSPC", "^IXIC", "^VIX"]

# 回看天数（计算均量、异常检测用）
LOOKBACK_DAYS = 30


# ============================================================
# 数据获取与分析
# ============================================================

def _fetch_all() -> tuple[list[dict] | None, list[dict] | None]:
    """
    获取所有标的数据 + 基准指数数据。
    返回 (stocks_data, benchmarks_data)。
    """
    all_symbols = [s[0] for s in STOCKS] + BENCHMARKS
    try:
        raw = yf.download(all_symbols, period=f"{LOOKBACK_DAYS+5}d", progress=False)
    except Exception as e:
        logger.error(f"yfinance 批量下载失败: {e}")
        return None, None

    if not isinstance(raw.columns, pd.MultiIndex):
        logger.error("yfinance 返回数据结构异常")
        return None, None

    close = raw.get("Close")
    volume = raw.get("Volume")
    high = raw.get("High")
    low = raw.get("Low")
    open_p = raw.get("Open")

    if close is None or close.empty:
        logger.error("未获取到收盘价数据")
        return None, None

    today = datetime.now()
    market_is_open = _is_market_open(close)

    stocks_data = []
    for sym, cname, ename in STOCKS:
        try:
            item = _analyze_stock(sym, cname, ename, close, volume, high, low, open_p, market_is_open)
            if item:
                stocks_data.append(item)
        except Exception as e:
            logger.warning(f"分析 {sym}({cname}) 失败: {e}")

    benchmarks_data = []
    for sym in BENCHMARKS:
        try:
            bm = _analyze_benchmark(sym, close, market_is_open)
            if bm:
                benchmarks_data.append(bm)
        except Exception as e:
            logger.warning(f"分析基准 {sym} 失败: {e}")

    return stocks_data, benchmarks_data


def _is_market_open(close: pd.DataFrame) -> bool:
    """
    朴素判断：如果最近两个交易日的最新价包含今天的日期，
    且当前时间在美国交易时段内，视为盘中。
    但为了简单，我们只看最后数据点是否在"今天"。
    """
    last_date = close.index[-1]
    today = datetime.now().date()
    return last_date.date() == today


def _analyze_stock(
    sym: str, cname: str, ename: str,
    close: pd.DataFrame, volume: pd.DataFrame,
    high: pd.DataFrame, low: pd.DataFrame, open_p: pd.DataFrame,
    market_open: bool,
) -> dict | None:
    """分析单只股票，返回结构化数据"""
    if sym not in close.columns:
        return None

    prices = close[sym].dropna()
    if len(prices) < 2:
        return None

    # 最新价和前一交易日
    if market_open and len(prices) >= 3:
        # 盘中：用倒数第二个完整交易日作为"前一天"
        last_full = prices.iloc[-2]
        current = prices.iloc[-1]
        prev_close = last_full
    else:
        current = prices.iloc[-1]
        prev_close = prices.iloc[-2]

    change = float(current - prev_close)
    change_pct = (change / prev_close) * 100 if prev_close else 0

    # 当日成交量
    vol_series = volume[sym].dropna() if sym in volume.columns else pd.Series(dtype=float)
    current_vol = float(vol_series.iloc[-1]) if not vol_series.empty else 0

    # 日均成交量（过去20个完整交易日）
    if len(vol_series) >= 21:
        avg_vol = float(vol_series.iloc[-21:-1].mean())
    elif len(vol_series) > 1:
        avg_vol = float(vol_series.iloc[:-1].mean())
    else:
        avg_vol = current_vol or 1
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

    # 日收益率序列（用于异常检测）
    daily_returns = prices.pct_change().dropna()
    if len(daily_returns) >= 5:
        recent = daily_returns.iloc[-min(21, len(daily_returns)):]
        mean_ret = float(recent.mean())
        std_ret = float(recent.std()) or 0.001
        ret_zscore = (float(daily_returns.iloc[-1]) - mean_ret) / std_ret
    else:
        ret_zscore = 0

    # 当日最高/最低
    current_high = float(high[sym].iloc[-1]) if sym in high.columns and not high[sym].dropna().empty else current
    current_low = float(low[sym].iloc[-1]) if sym in low.columns and not low[sym].dropna().empty else current
    day_range_pct = (current_high - current_low) / prev_close * 100 if prev_close else 0

    # 跳空
    open_today = float(open_p[sym].iloc[-1]) if sym in open_p.columns and not open_p[sym].dropna().empty else current
    gap_pct = (open_today - prev_close) / prev_close * 100 if prev_close else 0

    return {
        "symbol": sym,
        "name_cn": cname,
        "name_en": ename,
        "price": round(float(current), 2),
        "prev_close": round(float(prev_close), 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": current_vol,
        "avg_volume": round(avg_vol, 0),
        "vol_ratio": round(vol_ratio, 2),
        "day_high": round(float(current_high), 2),
        "day_low": round(float(current_low), 2),
        "day_range_pct": round(day_range_pct, 2),
        "gap_pct": round(gap_pct, 2),
        "ret_zscore": round(ret_zscore, 2),
    }


def _analyze_benchmark(sym: str, close: pd.DataFrame, market_open: bool) -> dict | None:
    """分析基准指数"""
    if sym not in close.columns:
        return None
    prices = close[sym].dropna()
    if len(prices) < 2:
        return None

    if market_open and len(prices) >= 3:
        current = prices.iloc[-1]
        prev = prices.iloc[-2]
    else:
        current = prices.iloc[-1]
        prev = prices.iloc[-2]

    change_pct = (current - prev) / prev * 100
    return {
        "symbol": sym,
        "price": round(float(current), 2),
        "change_pct": round(float(change_pct), 2),
    }


# ============================================================
# 异常检测
# ============================================================

def _detect_anomalies(stocks: list[dict]) -> list[dict]:
    """
    检测异常信号：
    - 成交量异常（>2倍均值）
    - 涨跌幅异常（|z-score| > 2）
    - 跳空异常（|gap| > 1%）
    - 日内振幅异常（> 2倍均值... 简化：> 4% 且 > 平均）
    """
    anomalies = []

    # 计算整体波动均值（用于振幅比较）
    all_range = [s.get("day_range_pct", 0) for s in stocks if s.get("day_range_pct")]
    mean_range = statistics.mean(all_range) if all_range else 2

    for s in stocks:
        reasons = []

        # 成交量异常
        if s.get("vol_ratio", 1) > 2:
            reasons.append(f"成交量放量至均值的 {s['vol_ratio']:.1f} 倍")

        # 涨跌幅异常
        z = s.get("ret_zscore", 0)
        if abs(z) > 2:
            direction = "涨幅" if z > 0 else "跌幅"
            reasons.append(f"{direction}异常（z-score={z:.1f}）")

        # 跳空
        gap = s.get("gap_pct", 0)
        if abs(gap) > 1:
            reasons.append(f"跳空{'高开' if gap > 0 else '低开'} {abs(gap):.2f}%")

        # 日内振幅大
        dr = s.get("day_range_pct", 0)
        if dr > max(4, mean_range * 2):
            reasons.append(f"日内振幅 {dr:.1f}% 较大")

        if reasons:
            anomalies.append({
                "symbol": s["symbol"],
                "name_cn": s["name_cn"],
                "reasons": reasons,
                "severity": "high" if len(reasons) >= 2 else "medium",
            })

    return anomalies


# ============================================================
# AI 分析
# ============================================================

def _generate_ai_analysis(stocks: list[dict], anomalies: list[dict]) -> str:
    """用 LLM 生成行情解读"""
    if not LLM_API_KEY:
        return ""

    # 整理数据文本
    lines = ["【今日持仓表现】"]
    for s in stocks:
        arrow = "🟢" if s["change_pct"] > 0 else ("🔴" if s["change_pct"] < 0 else "⚪")
        lines.append(
            f"{arrow} {s['symbol']} {s['name_cn']}: "
            f"${s['price']}  ({s['change_pct']:+.2f}%)  "
            f"量比 {s['vol_ratio']:.1f}x  振幅 {s['day_range_pct']:.1f}%"
        )

    if anomalies:
        lines.append("\n【异常信号】")
        for a in anomalies:
            lines.append(f"⚠️ {a['symbol']} {a['name_cn']}: {'; '.join(a['reasons'])}")

    # 最大波动
    if stocks:
        sorted_abs = sorted(stocks, key=lambda x: abs(x["change_pct"]), reverse=True)
        top = sorted_abs[0]
        lines.append(f"\n【最大波动】{top['symbol']} {top['name_cn']}: {top['change_pct']:+.2f}%")
        if len(sorted_abs) > 1:
            lines.append(f"  次之: {sorted_abs[1]['symbol']} {sorted_abs[1]['name_cn']}: {sorted_abs[1]['change_pct']:+.2f}%")

    input_text = "\n".join(lines)

    prompt = f"""你是一位资深美股分析师，外号「布丁」。请根据以下今日持仓数据，写一段简短有力的市场解读。

要求：
1. **说人话**——像朋友在群里分享行情，不要投行报告腔
2. **有观点**——涨了的原因？跌了慌不慌？值不值得关注？
3. **挑重点**——先把最大波动的股票说清楚，再提异常信号，最后快速扫一遍整体
4. **给建议**——一句话说说明天应该关注什么
5. **控制在 300 字以内**
6. **用中文**

今日数据：
{input_text}"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1000,
            timeout=30,
        )
        text = resp.choices[0].message.content.strip()
        logger.info("✅ AI 行情解读生成成功")
        return text
    except Exception as e:
        logger.warning(f"AI 分析生成失败: {e}")
        return ""


# ============================================================
# 飞书卡片构建
# ============================================================

def _build_daily_card(
    stocks: list[dict],
    anomalies: list[dict],
    top_mover: dict | None,
    ai_text: str,
    bench_data: list[dict] | None,
) -> dict:
    """构建个股追踪日报卡片"""
    today = datetime.now().strftime("%Y-%m-%d")

    # 判断行情好坏
    up = sum(1 for s in stocks if s["change_pct"] > 0)
    dn = sum(1 for s in stocks if s["change_pct"] < 0)
    if up > dn * 1.5:
        theme = "green"
    elif dn > up * 1.5:
        theme = "red"
    else:
        theme = "blue"

    elements = []

    # ---- 🔥 最大波动 ----
    if top_mover:
        arrow = "🟢" if top_mover["change_pct"] > 0 else "🔴"
        mover_text = (
            f"**{arrow} {top_mover['symbol']} {top_mover['name_cn']}**  "
            f"{top_mover['change_pct']:+.2f}%  "
            f"${top_mover['price']}\n"
            f"量比 {top_mover['vol_ratio']:.1f}x  |  "
            f"振幅 {top_mover['day_range_pct']:.1f}%  |  "
            f"日内 ${top_mover['day_low']} ~ ${top_mover['day_high']}"
        )
        elements.append({"tag": "markdown", "content": f"**🔥 今日最大波动**\n{mover_text}"})
        elements.append({"tag": "hr"})

    # ---- ⚠️ 异常预警 ----
    if anomalies:
        anom_lines = ["**⚠️ 异常信号**"]
        for a in anomalies:
            sev = "🚨" if a["severity"] == "high" else "⚠️"
            anom_lines.append(f"{sev} **{a['symbol']} {a['name_cn']}**")
            for r in a["reasons"]:
                anom_lines.append(f"   · {r}")
        elements.append({"tag": "markdown", "content": "\n".join(anom_lines)})
        elements.append({"tag": "hr"})

    # ---- 📋 持仓一览 ----
    table_lines = ["**📋 持仓一览**"]
    table_lines.append(
        "标的        价格        涨跌        成交量            振幅"
    )
    for s in stocks:
        arrow = "🟢" if s["change_pct"] > 0 else ("🔴" if s["change_pct"] < 0 else "⚪")
        price_str = f"${s['price']:<7}"
        chg_str = f"{s['change_pct']:+6.2f}%"
        vol_str = _fmt_volume(s["volume"])
        range_str = f"{s['day_range_pct']:5.1f}%"
        table_lines.append(
            f"{arrow} {s['symbol']:<6} {price_str}  {chg_str}  {vol_str:>10}  {range_str}"
        )

    # 统计
    gains = [s for s in stocks if s["change_pct"] > 0]
    losses = [s for s in stocks if s["change_pct"] < 0]
    avg_chg = statistics.mean([s["change_pct"] for s in stocks]) if stocks else 0
    table_lines.append(
        f"\n📊 共 {len(stocks)} 只 | 涨 {len(gains)} 跌 {len(losses)} 平 "
        f"{len(stocks)-len(gains)-len(losses)} | 均值 {avg_chg:+.2f}%"
    )

    elements.append({"tag": "markdown", "content": "\n".join(table_lines)})

    # ---- 🤖 AI 行情解读 ----
    if ai_text:
        # 飞书卡片 markdown 超长会报错，分多条
        MAX_MD = 1800
        if len(ai_text) <= MAX_MD:
            elements.append({"tag": "hr"})
            elements.append({"tag": "markdown", "content": f"**🤖 布丁解读**\n\n{ai_text}"})
        else:
            # 先发第一段，剩余的通过文本消息发
            elements.append({"tag": "hr"})
            first_part = ai_text[:MAX_MD]
            last_break = first_part.rfind("\n")
            if last_break > 0:
                first_part = ai_text[:last_break]
                remaining = ai_text[last_break:]
            else:
                remaining = ""
            elements.append({"tag": "markdown", "content": f"**🤖 布丁解读**\n\n{first_part}"})
            if remaining.strip():
                _send_text(f"🤖 布丁解读（续）\n\n{remaining}")

    # ---- 底部 ----
    elements.append({"tag": "hr"})
    source_note = "📡 数据来源: Yahoo Finance | 均量计算周期: 20个交易日"
    if anomalies:
        source_note += " | 异常判定: 量比>2x / z-score>2 / 跳空>1% / 振幅异常"
    source_note += "\n🤖 AI 解读由 LLM 生成，仅供参考，不构成投资建议"
    elements.append({"tag": "note", "content": source_note})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 布丁持仓追踪 | {today}"},
            "template": theme,
        },
        "elements": elements,
    }


# ============================================================
# 工具函数
# ============================================================

def _fmt_volume(v: float) -> str:
    """格式化成交量"""
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    elif v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    elif v >= 1_000:
        return f"{v/1_000:.1f}K"
    else:
        return f"{v:.0f}"


# ============================================================
# 推送
# ============================================================

def _send_card(card: dict) -> bool:
    """发送消息卡片到飞书"""
    if not _WEBHOOK_URL:
        logger.warning("⚠️ FEISHU_WEBHOOK_URL 未配置")
        return False
    payload = {"msg_type": "interactive", "card": card}
    try:
        resp = requests.post(
            _WEBHOOK_URL, json=payload, timeout=15,
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
    if not _WEBHOOK_URL:
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(_WEBHOOK_URL, json=payload, timeout=15)
        return resp.json().get("StatusCode") == 0 or resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"飞书文本推送异常: {e}")
        return False


def send_daily_report() -> bool:
    """
    主入口：获取个股数据 → AI 分析 → 推送飞书
    """
    logger.info("📊 正在获取个股数据...")

    stocks, bench = _fetch_all()
    if not stocks:
        logger.warning("⚠️ 未获取到个股数据，跳过推送")
        return False

    # 找最大波动
    sorted_by_abs = sorted(stocks, key=lambda x: abs(x["change_pct"]), reverse=True)
    top_mover = sorted_by_abs[0] if sorted_by_abs else None

    # 异常检测
    anomalies = _detect_anomalies(stocks)

    # AI 分析
    logger.info("🤖 正在生成 AI 解读...")
    ai_text = _generate_ai_analysis(stocks, anomalies)

    # 构建卡片
    card = _build_daily_card(stocks, anomalies, top_mover, ai_text, bench)

    ok = _send_card(card)
    if ok:
        logger.info("✅ 持仓追踪日报已推送到飞书")
    else:
        logger.error("❌ 持仓追踪日报推送失败")

    return ok


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    send_daily_report()
