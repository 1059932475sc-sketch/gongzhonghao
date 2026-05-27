"""
每日市场简报 - 飞书推送
======================
抓取全球主要市场数据（同 QuantDinger 数据源），通过飞书机器人推送
每日自动运行，无需任何手动操作
"""

import logging
from datetime import datetime

import requests
import yfinance as yf

from config import FEISHU_WEBHOOK_URL as _WEBHOOK_URL

logger = logging.getLogger(__name__)


# ============================================================
# 市场指标配置
# ============================================================
# 可以随意增删，脚本会自动处理
INDICES = [
    {"symbol": "^GSPC",  "name": "S&P 500",     "region": "🇺🇸 美股"},
    {"symbol": "^IXIC",  "name": "纳斯达克",     "region": "🇺🇸 美股"},
    {"symbol": "^DJI",   "name": "道琼斯",       "region": "🇺🇸 美股"},
    {"symbol": "^HSI",   "name": "恒生指数",     "region": "🇭🇰 港股"},
    {"symbol": "000001.SS", "name": "上证指数",  "region": "🇨🇳 A股"},
    {"symbol": "399001.SZ", "name": "深证成指",  "region": "🇨🇳 A股"},
]

CRYPTO = [
    {"symbol": "BTC-USD",  "name": "比特币",   "emoji": "₿"},
    {"symbol": "ETH-USD",  "name": "以太坊",   "emoji": "⟠"},
    {"symbol": "SOL-USD",  "name": "Solana",   "emoji": "◎"},
]

MACRO = [
    {"symbol": "^VIX", "name": "VIX 恐慌指数"},
    {"symbol": "^TNX", "name": "10Y 美债收益率"},
]

# 所有标的列表
ALL_SYMBOLS = [i["symbol"] for i in INDICES] + \
              [c["symbol"] for c in CRYPTO] + \
              [m["symbol"] for m in MACRO]


# ============================================================
# 数据获取
# ============================================================

def _fetch_prices() -> dict:
    """批量获取所有市场价格数据"""
    try:
        data = yf.download(ALL_SYMBOLS, period="5d", progress=False)
    except Exception as e:
        logger.warning(f"yfinance 批量获取失败: {e}")
        # 逐个尝试
        return _fetch_prices_fallback()

    import pandas as pd
    if not isinstance(data.columns, pd.MultiIndex):
        # 只有单一标的的情况
        return {}

    close = data["Close"]
    results = {}
    for sym in ALL_SYMBOLS:
        try:
            if sym not in close.columns:
                continue
            series = close[sym].dropna()
            if len(series) < 2:
                continue
            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            chg_pct = (last - prev) / prev * 100
            results[sym] = {
                "price": last,
                "prev_close": prev,
                "change_pct": round(chg_pct, 2),
            }
        except Exception as e:
            logger.debug(f"处理 {sym} 失败: {e}")
    return results


def _fetch_prices_fallback() -> dict:
    """逐个获取，批量失败时的降级方案"""
    results = {}
    for sym in ALL_SYMBOLS:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg_pct = (last - prev) / prev * 100
            results[sym] = {
                "price": last,
                "prev_close": prev,
                "change_pct": round(chg_pct, 100),
            }
        except Exception as e:
            logger.debug(f"逐个获取 {sym} 失败: {e}")
    return results


def _fetch_fear_greed() -> dict | None:
    """获取恐惧与贪婪指数"""
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/?limit=1&format=json",
            timeout=10,
        )
        data = resp.json()
        item = data["data"][0]
        return {
            "value": int(item["value"]),
            "classification": item["value_classification"],
        }
    except Exception as e:
        logger.warning(f"恐惧贪婪指数获取失败: {e}")
        return None


def _classification_to_emoji(cls: str) -> str:
    """恐惧贪婪分类 → emoji"""
    mapping = {
        "Extreme Fear": "😱",
        "Fear": "😰",
        "Neutral": "😐",
        "Greed": "😊",
        "Extreme Greed": "🚀",
    }
    return mapping.get(cls, "📊")


# ============================================================
# 飞书卡片构建
# ============================================================

def _build_market_card(prices: dict, fear_greed: dict | None) -> dict | None:
    """构建市场简报飞书消息卡片"""
    if not prices:
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    elements = []

    # ---- 判断整体市场情绪，决定卡片主题色 ----
    changes = []
    for sym, p in prices.items():
        if "change_pct" in p and p["change_pct"] is not None:
            changes.append(p["change_pct"])

    up_count = sum(1 for c in changes if c > 0)
    down_count = sum(1 for c in changes if c < 0)

    if not changes:
        header_template = "blue"
    elif up_count >= down_count * 2:
        header_template = "green"
    elif down_count >= up_count * 2:
        header_template = "red"
    else:
        header_template = "blue"

    # ---- 指数板块 ----
    elements.append({"tag": "markdown", "content": "**📈 全球指数**"})

    for region in ["🇺🇸 美股", "🇭🇰 港股", "🇨🇳 A股"]:
        region_indices = [i for i in INDICES if i["region"] == region]
        region_data = [(i, prices.get(i["symbol"])) for i in region_indices]
        region_data = [(i, p) for i, p in region_data if p]

        if not region_data:
            continue

        lines = [region]
        for idx, p in region_data:
            val = p["price"]
            chg = p["change_pct"]
            arrow = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
            val_str = _fmt_price(val)
            lines.append(f"  {arrow} **{idx['name']}**    {val_str}    {_fmt_chg(chg)}")

        elements.append({"tag": "markdown", "content": "\n".join(lines)})

    elements.append({"tag": "hr"})

    # ---- 加密货币 ----
    crypto_lines = ["**₿ 加密货币**"]
    crypto_hit = False
    for c in CRYPTO:
        p = prices.get(c["symbol"])
        if not p:
            continue
        crypto_hit = True
        val = p["price"]
        chg = p["change_pct"]
        arrow = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
        val_str = f"${val:,.2f}"
        crypto_lines.append(f"  {arrow} **{c['name']}**    {val_str}    {_fmt_chg(chg)}")

    if crypto_hit:
        elements.append({"tag": "markdown", "content": "\n".join(crypto_lines)})
        elements.append({"tag": "hr"})

    # ---- 市场情绪 ----
    macro_lines = ["**📊 市场情绪**"]

    if fear_greed:
        emoji = _classification_to_emoji(fear_greed["classification"])
        macro_lines.append(
            f"  {emoji} 恐惧与贪婪指数: **{fear_greed['value']}** ({fear_greed['classification']})"
        )

    for m in MACRO:
        p = prices.get(m["symbol"])
        if not p:
            continue
        val = p["price"]
        chg = p.get("change_pct")
        if m["symbol"] == "^TNX":
            macro_lines.append(f"  📈 {m['name']}: **{val:.2f}%**")
        elif m["symbol"] == "^VIX":
            macro_lines.append(f"  😨 {m['name']}: **{val:.1f}**    {_fmt_chg(chg) if chg is not None else ''}")
        else:
            macro_lines.append(f"  {m['name']}: **{val:.2f}**")

    elements.append({"tag": "markdown", "content": "\n".join(macro_lines)})

    # ---- 底部 ----
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "content": "📡 数据来源: Yahoo Finance · alternative.me | 🤖 自动生成 · 仅供参考",
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 每日市场简报 | {today}"},
            "template": header_template,
        },
        "elements": elements,
    }
    return card


def _fmt_price(val: float) -> str:
    """智能格式化价格"""
    if val >= 10000:
        return f"{val:,.2f}"
    elif val >= 100:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:.2f}"
    else:
        return f"{val:.4f}"


def _fmt_chg(chg_pct: float) -> str:
    """格式化涨跌幅"""
    sign = "+" if chg_pct > 0 else ""
    return f"{sign}{chg_pct:.2f}%"


# ============================================================
# 发送
# ============================================================

def _send_card(card: dict) -> bool:
    """发送消息卡片到飞书"""
    if not _WEBHOOK_URL:
        logger.warning("⚠️ FEISHU_WEBHOOK_URL 未配置，跳过推送")
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


def send_market_report() -> bool:
    """
    主入口：获取市场数据 → 推送飞书
    可直接被外部调用，也可 standalone 运行
    """
    logger.info("📊 正在获取市场数据...")

    prices = _fetch_prices()
    if not prices:
        logger.warning("⚠️ 未获取到任何市场数据，跳过推送")
        return False

    fear_greed = _fetch_fear_greed()

    card = _build_market_card(prices, fear_greed)
    if not card:
        logger.warning("⚠️ 卡片构建失败，跳过推送")
        return False

    ok = _send_card(card)
    if ok:
        logger.info("✅ 市场简报已推送到飞书")
    else:
        logger.error("❌ 市场简报推送失败")
    return ok


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    send_market_report()
