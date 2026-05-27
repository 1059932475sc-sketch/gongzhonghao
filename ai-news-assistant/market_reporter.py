"""
布丁量化日报 - 专业版
=====================
量化全栈分析管线，每日自动运行推送到飞书。

功能概览：
  [数据层]  个股行情、期货/指数期货、盘前数据、VIX
  [技术面]  RSI · MACD · SMA(20/50/200) · 布林带
  [扫描器]  突破检测 · 超买超卖 · 量价背离 · 波动率扩张
  [异常]    期货异动 · 跳空检测 · z-score偏离 · 量比异常
  [AI]     LLM 综合行情解读 · 个股深度分析 · 风险评估
  [记忆]    JSON 持久化 · 历史判断追踪 · 准确率统计
"""

import json
import logging
import os
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import (
    FEISHU_WEBHOOK_URL as _WEBHOOK_URL,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
)

logger = logging.getLogger(__name__)

# ========================================================================
#  配置
# ========================================================================

STOCKS = [
    ("NVDA",  "英伟达",       "NVIDIA"),
    ("INTC",  "英特尔",       "Intel"),
    ("ORCL",  "甲骨文",       "Oracle"),
    ("NOK",   "诺基亚",       "Nokia"),
    ("MRVL",  "迈威尔科技",    "Marvell Technology"),
    ("QCOM",  "高通",         "Qualcomm"),
    ("AAOI",  "应用光电",     "Applied Optoelectronics"),
    ("SMCI",  "超威电脑",     "Super Micro Computer"),
    ("QQQM",  "纳指ETF",      "Invesco QQQM"),
    ("VOO",   "标普500ETF",   "Vanguard S&P 500 ETF"),
    ("SOXQ",  "半导体ETF",    "Invesco PHLX Semiconductor ETF"),
]

# 指数期货（23h交易，盘前信号参考）
FUTURES = [
    ("ES=F",   "S&P 500 E-mini 期货"),
    ("NQ=F",   "Nasdaq 100 E-mini 期货"),
]

# 基准指数
BENCHMARKS = ["^GSPC", "^IXIC", "^VIX", "^TNX"]

DAYS_HISTORY = 60  # 获取历史天数（计算指标用）
LOOKBACK = 30      # 异常检测回看天数
MEMO_FILE = Path(__file__).parent / "data" / "analysis_memory.json"


# ========================================================================
#  工具函数
# ========================================================================

def _fmt_volume(v: float) -> str:
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    elif v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    elif v >= 1_000:
        return f"{v/1_000:.2f}K"
    else:
        return f"{v:.0f}"


def _fmt_price(val: float) -> str:
    if val >= 10000:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:,.2f}"
    else:
        return f"{val:.4f}"


def _fmt_chg(chg_pct: float) -> str:
    sign = "+" if chg_pct > 0 else ""
    return f"{sign}{chg_pct:.2f}%"


def _arrow(chg: float) -> str:
    return "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")


# ========================================================================
#  技术指标计算
# ========================================================================

def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def calc_macd(series: pd.Series) -> dict:
    ema12 = series.ewm(span=12).mean()
    ema26 = series.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal
    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "crossover": "golden" if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0
                     else ("death" if histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0
                     else ("positive" if histogram.iloc[-1] > 0 else "negative")),
    }


def calc_bollinger(series: pd.Series, period: int = 20) -> dict:
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    last = series.iloc[-1]
    band_pct = (last - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1] + 1e-10) * 100
    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(sma.iloc[-1]),
        "lower": float(lower.iloc[-1]),
        "bandwidth_pct": float((upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1] * 100),
        "position": "above" if last > upper.iloc[-1]
                    else ("below" if last < lower.iloc[-1] else "inside"),
        "band_pct": round(float(band_pct), 1),
    }


def calc_sma(series: pd.Series, period: int) -> float:
    sma = series.rolling(window=period).mean()
    return float(sma.iloc[-1]) if not sma.empty else 0.0


# ========================================================================
#  数据获取
# ========================================================================

def fetch_all() -> dict | None:
    """
    主数据获取函数。
    返回: { stocks: [...], futures: [...], benchmarks: [...] }
    """
    all_symbols = [s[0] for s in STOCKS] + [f[0] for f in FUTURES] + BENCHMARKS
    try:
        raw = yf.download(all_symbols, period=f"{DAYS_HISTORY+10}d", progress=False)
    except Exception as e:
        logger.error(f"yfinance 批量下载失败: {e}")
        return None

    if not isinstance(raw.columns, pd.MultiIndex):
        logger.error("yfinance 数据格式异常")
        return None

    close = raw.get("Close")
    volume = raw.get("Volume")
    high = raw.get("High")
    low = raw.get("Low")
    open_p = raw.get("Open")

    if close is None or close.empty:
        return None

    today_market_day = close.index[-1].date() == datetime.now().date()

    # ---- 个股 ----
    stocks = []
    for sym, cn, en in STOCKS:
        try:
            s = _analyze_one_stock(sym, cn, en, close, volume, high, low, open_p, today_market_day)
            if s:
                stocks.append(s)
        except Exception as e:
            logger.warning(f"分析 {sym} 跳过: {e}")

    # ---- 期货 ----
    futures_data = []
    for sym, name in FUTURES:
        try:
            f = _analyze_futures(sym, name, close, volume, today_market_day)
            if f:
                futures_data.append(f)
        except Exception as e:
            logger.warning(f"期货 {sym} 跳过: {e}")

    # ---- 基准 ----
    benches = {}
    for sym in BENCHMARKS:
        try:
            if sym not in close.columns:
                continue
            prices = close[sym].dropna()
            if len(prices) < 2:
                continue
            curr = float(prices.iloc[-1])
            prev = float(prices.iloc[-2])
            chg = (curr - prev) / prev * 100
            benches[sym] = {"price": round(curr, 2), "change_pct": round(chg, 2)}
        except Exception:
            pass

    return {
        "stocks": stocks,
        "futures": futures_data,
        "benchmarks": benches,
        "is_today_market_day": today_market_day,
    }


def _analyze_one_stock(sym, cn, en, close, volume, high, low, open_p, market_open):
    """单只个股全维度分析"""
    COL = close[sym].dropna()
    VOL = volume[sym].dropna() if sym in volume.columns else pd.Series(dtype=float)
    HI = high[sym].dropna() if sym in high.columns else COL
    LO = low[sym].dropna() if sym in low.columns else COL
    OP = open_p[sym].dropna() if sym in open_p.columns else COL

    if len(COL) < 10:
        return None

    # 价格
    if market_open and len(COL) >= 3:
        curr = float(COL.iloc[-1])
        prev = float(COL.iloc[-2])
    else:
        curr = float(COL.iloc[-1])
        prev = float(COL.iloc[-2])
    chg = curr - prev
    chg_pct = chg / prev * 100

    # 成交量
    curr_vol = float(VOL.iloc[-1]) if not VOL.empty else 0
    if len(VOL) >= 21:
        avg_vol = float(VOL.iloc[-21:-1].mean())
    elif len(VOL) > 1:
        avg_vol = float(VOL.iloc[:-1].mean())
    else:
        avg_vol = curr_vol or 1
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1

    # 技术指标
    rsi = calc_rsi(COL)
    macd = calc_macd(COL)
    sma20 = calc_sma(COL, 20)
    sma50 = calc_sma(COL, 50) if len(COL) >= 50 else None
    sma200 = calc_sma(COL, 200) if len(COL) >= 200 else None
    bb = calc_bollinger(COL)

    # 均线位置
    above_sma20 = curr > sma20 if sma20 > 0 else None
    above_sma50 = curr > sma50 if sma50 else None
    above_sma200 = curr > sma200 if sma200 else None

    # 日波动
    dhi = float(HI.iloc[-1]) if not HI.empty else curr
    dlo = float(LO.iloc[-1]) if not LO.empty else curr
    day_range_pct = (dhi - dlo) / prev * 100

    # 跳空
    open_t = float(OP.iloc[-1]) if not OP.empty else curr
    gap_pct = (open_t - prev) / prev * 100

    # z-score
    returns = COL.pct_change().dropna()
    if len(returns) >= 10:
        recent = returns.iloc[-min(21, len(returns)):]
        mu = float(recent.mean())
        sigma = float(recent.std()) or 0.001
        ret_z = (float(returns.iloc[-1]) - mu) / sigma
    else:
        ret_z = 0

    # 量与价的关系（量价背离检测）
    vol_series = VOL
    price_series = COL
    if len(vol_series) >= 10 and len(price_series) >= 10:
        price_trend = price_series.iloc[-5:].mean() - price_series.iloc[-10:-5].mean()
        vol_trend = vol_series.iloc[-5:].mean() - vol_series.iloc[-10:-5].mean()
        divergence = "bullish" if price_trend < 0 and vol_trend > 0 \
                     else ("bearish" if price_trend > 0 and vol_trend > 0 and chg_pct < 0
                     else None)
    else:
        divergence = None

    # 异常评分
    anomaly_score = 0
    anomaly_reasons = []
    if vol_ratio > 2:
        anomaly_score += 2
        anomaly_reasons.append(f"量比 {vol_ratio:.1f}x")
    if abs(ret_z) > 2:
        anomaly_score += 2
        anomaly_reasons.append(f"涨跌z-score={ret_z:.1f}")
    if abs(gap_pct) > 1:
        anomaly_score += 1
        anomaly_reasons.append(f"跳空{abs(gap_pct):.1f}%")
    if day_range_pct > 5:
        anomaly_score += 1
        anomaly_reasons.append(f"振幅{day_range_pct:.1f}%")
    if divergence:
        anomaly_score += 1
        anomaly_reasons.append("量价背离")

    return {
        "symbol": sym, "name_cn": cn, "name_en": en,
        "price": round(curr, 2), "prev_close": round(prev, 2),
        "change": round(chg, 2), "change_pct": round(chg_pct, 2),
        "volume": curr_vol, "avg_volume": round(avg_vol, 0), "vol_ratio": round(vol_ratio, 2),
        "day_high": round(dhi, 2), "day_low": round(dlo, 2),
        "day_range_pct": round(day_range_pct, 2),
        "gap_pct": round(gap_pct, 2), "ret_zscore": round(ret_z, 2),
        "rsi": round(rsi, 1),
        "macd_crossover": macd["crossover"],
        "macd_histogram": round(macd["histogram"], 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2) if sma50 else None,
        "above_sma20": above_sma20,
        "above_sma50": above_sma50,
        "bb_position": bb["position"],
        "bb_bandwidth": bb["bandwidth_pct"],
        "bb_band_pct": bb["band_pct"],
        "divergence": divergence,
        "anomaly_score": anomaly_score,
        "anomaly_reasons": anomaly_reasons,
    }


def _analyze_futures(sym, name, close, volume, market_open):
    """分析期货数据"""
    if sym not in close.columns:
        return None
    prices = close[sym].dropna()
    if len(prices) < 2:
        return None
    if market_open and len(prices) >= 3:
        curr = float(prices.iloc[-1])
        prev = float(prices.iloc[-2])
    else:
        curr = float(prices.iloc[-1])
        prev = float(prices.iloc[-2])

    chg_pct = (curr - prev) / prev * 100

    # 期货成交量
    vol = float(volume[sym].iloc[-1]) if sym in volume.columns and not volume[sym].dropna().empty else 0

    return {
        "symbol": sym, "name": name,
        "price": round(curr, 2), "change_pct": round(chg_pct, 2),
        "volume": vol,
    }


# ========================================================================
#  机会扫描器
# ========================================================================

class OpportunityScanner:
    """模仿 QuantDinger 的 opportunity scanner"""

    @staticmethod
    def detect_breakout(s: dict) -> str | None:
        """突破信号：价格站上布林带上轨 + 放量"""
        if s.get("bb_position") == "above" and s.get("vol_ratio", 1) > 1.3:
            return f"放量突破布林带上轨"
        if s.get("above_sma20") is True and s.get("change_pct", 0) > 2:
            return f"放量上穿20日均线" if s.get("vol_ratio", 1) > 1.5 else None
        return None

    @staticmethod
    def detect_support_bounce(s: dict) -> str | None:
        """支撑反弹：触及布林带下轨后反弹"""
        if s.get("bb_position") == "below" and s.get("change_pct", 0) > 0:
            return "触及布林带下轨反弹"
        return None

    @staticmethod
    def detect_oversold_overbought(s: dict) -> str | None:
        """超买超卖"""
        rsi = s.get("rsi", 50)
        if rsi > 70:
            return f"RSI={rsi} **超买**"
        if rsi < 30:
            return f"RSI={rsi} **超卖**"
        return None

    @staticmethod
    def detect_macd_signal(s: dict) -> str | None:
        """MACD 金叉/死叉"""
        co = s.get("macd_crossover", "")
        if co == "golden":
            return "MACD **金叉**"
        if co == "death":
            return "MACD **死叉** ⚠️"
        return None

    @staticmethod
    def scan_all(s: dict) -> list[str]:
        signals = []
        for method in [
            OpportunityScanner.detect_breakout,
            OpportunityScanner.detect_oversold_overbought,
            OpportunityScanner.detect_macd_signal,
            OpportunityScanner.detect_support_bounce,
        ]:
            sig = method(s)
            if sig:
                signals.append(sig)
        return signals


# ========================================================================
#  分析记忆系统
# ========================================================================

class AnalysisMemory:
    """
    模仿 QuantDinger 的 analysis_memory.py。
    用本地 JSON 文件持久化，记录每日分析结论，后续可追踪准确率。
    """

    def __init__(self):
        self._cache = None

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        if MEMO_FILE.exists():
            try:
                self._cache = json.loads(MEMO_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}
        else:
            self._cache = {}
        return self._cache

    def _save(self, data: dict):
        MEMO_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._cache = data

    def record_today(self, date_str: str, stocks: list[dict], analysis_summary: str):
        """记录今天的分析"""
        memo = self._load()
        memo[date_str] = {
            "timestamp": time.time(),
            "recorded_at": datetime.now().isoformat(),
            "stocks": {
                s["symbol"]: {
                    "price": s["price"],
                    "change_pct": s["change_pct"],
                    "rsi": s.get("rsi"),
                    "macd": s.get("macd_crossover"),
                    "anomaly_score": s.get("anomaly_score", 0),
                    "anomaly_reasons": s.get("anomaly_reasons", []),
                    "signals": OpportunityScanner.scan_all(s),
                }
                for s in stocks
            },
            "analysis": analysis_summary[:500],
        }
        self._save(memo)
        logger.info(f"💾 分析记录已保存: {date_str}")

    def get_accuracy_report(self) -> str:
        """生成历史判断准确率报告（暂无实际涨跌验证，只展示最近N天记录）"""
        memo = self._load()
        dates = sorted(memo.keys(), reverse=True)[:30]
        if not dates:
            return "暂无历史记录"

        lines = [f"📊 最近 {len(dates)} 天记录摘要"]
        for d in dates:
            entry = memo[d]
            stocks_entry = entry.get("stocks", {})
            anomaly_count = sum(
                1 for s in stocks_entry.values() if s.get("anomaly_score", 0) >= 2
            )
            signal_count = sum(
                len(s.get("signals", [])) for s in stocks_entry.values()
            )
            lines.append(f"  {d} | {len(stocks_entry)} 只 | 异常 {anomaly_count} | 信号 {signal_count}")
        return "\n".join(lines)


# ========================================================================
#  AI 深度分析
# ========================================================================

def _call_llm(prompt: str) -> str:
    """调用 LLM"""
    if not LLM_API_KEY:
        return ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=2000,
            timeout=45,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"LLM 调用失败: {e}")
        return ""


def generate_ai_analysis(data: dict, futures_data: list[dict], anomalies: list[dict]) -> str:
    """
    多段式 AI 分析，涵盖：
    1. 大盘/期货环境
    2. 最大波动 & 异动解读
    3. 技术面全景
    4. 机会提示
    5. 风险预警
    """
    stocks = data.get("stocks", [])
    benches = data.get("benchmarks", {})

    # ---- 构建数据摘要 ----
    lines = ["【大盘环境】"]
    for sym, label in [("^GSPC", "S&P 500"), ("^IXIC", "纳斯达克"), ("^VIX", "VIX")]:
        b = benches.get(sym)
        if b:
            lines.append(f"  {label}: {b['price']}  ({b['change_pct']:+.2f}%)")

    if futures_data:
        lines.append("\n【期货盘前信号】")
        for f in futures_data:
            lines.append(f"  {f['symbol']} {f['name']}: {_fmt_chg(f['change_pct'])}")

    lines.append(f"\n【{len(stocks)} 只持仓扫描】")
    for s in stocks:
        sigs = OpportunityScanner.scan_all(s)
        sig_str = f" | {'; '.join(sigs)}" if sigs else ""
        lines.append(
            f"  {_arrow(s['change_pct'])} {s['symbol']} {s['name_cn']}: "
            f"{s['change_pct']:+.2f}%  RSI={s['rsi']}  量比={s['vol_ratio']:.1f}x{sig_str}"
        )

    if anomalies:
        lines.append("\n【异常信号汇总】")
        for a in anomalies:
            lines.append(f"  🚨 {a['symbol']} {a['name_cn']}: {'; '.join(a['anomaly_reasons'])}")

    # ---- 期货异常 ----
    if futures_data and stocks:
        fut_avg = statistics.mean([f["change_pct"] for f in futures_data]) if futures_data else 0
        stock_avg = statistics.mean([s["change_pct"] for s in stocks]) if stocks else 0
        if abs(fut_avg - stock_avg) > 0.5:
            lines.append(
                f"\n【期货/现货背离】"
                f"期货均涨跌 {fut_avg:+.2f}% vs 持仓均涨跌 {stock_avg:+.2f}%，存在背离"
            )

    input_text = "\n".join(lines)

    prompt = f"""你是布丁，一个资深的华尔街分析师，也懂散户关心什么。
请根据以下今日仓位数据，写一份【完整的市场解读】，用中文、说人话。

结构要求：
1️⃣ **盘前/期货怎么看**（期货指向多还是空，今天大环境如何）
2️⃣ **今天最大动静**（涨最多的和最惨的，为什么，技术面怎么看）
3️⃣ **值得注意的信号**（异常、金叉死叉、超买超卖，哪个值得关注）
4️⃣ **机会 & 风险**（哪个有突破迹象、哪个要小心）
5️⃣ **一句话总结**（今天整体行不行）

语气：像布丁在群里发消息，有观点、有态度、不啰嗦。300-500 字。
不要列所有股票数据，挑重点说。

今日数据：
{input_text}"""

    text = _call_llm(prompt)
    return text


def generate_futures_analysis(futures_data: list[dict], benches: dict) -> str:
    """期货专项分析"""
    lines = ["【期货市场监测】"]
    for f in futures_data:
        arrow = "🟢" if f["change_pct"] > 0 else "🔴"
        lines.append(f"  {arrow} {f['name']}: {f['change_pct']:+.2f}%  最新价 {f['price']}")

    vix = benches.get("^VIX", {})
    if vix:
        v = vix["price"]
        if v < 15:
            lines.append(f"\nVIX={v} 低波动环境，市场情绪稳定")
        elif v < 25:
            lines.append(f"\nVIX={v} 中等波动，正常市场状态")
        else:
            lines.append(f"\n⚠️ VIX={v} 高波动！注意风险")

    tnx = benches.get("^TNX", {})
    if tnx:
        lines.append(f"10Y 美债收益率: {tnx['price']}% ({tnx['change_pct']:+.2f}%)")

    if futures_data:
        avg_fut = statistics.mean([f["change_pct"] for f in futures_data])
        direction = "偏多 📈" if avg_fut > 0.3 else ("偏空 📉" if avg_fut < -0.3 else "中性 ➖")
        lines.append(f"\n📌 综合判断: 期货指向 **{direction}**")

    return "\n".join(lines)


# ========================================================================
#  飞书卡片
# ========================================================================

def _send_card(card: dict) -> bool:
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
    if not _WEBHOOK_URL:
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(_WEBHOOK_URL, json=payload, timeout=15)
        return resp.json().get("StatusCode") == 0 or resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"飞书文本推送异常: {e}")
        return False


def _build_card(all_data: dict, anomalies: list,
                scanner_signals: dict, futures_analysis: str,
                ai_text: str, memo_report: str) -> dict | None:
    """构建完整日报卡片"""
    stocks = all_data.get("stocks", [])
    futures_data = all_data.get("futures", [])
    benches = all_data.get("benchmarks", {})
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not stocks:
        return None

    # 主题色
    up = sum(1 for s in stocks if s["change_pct"] > 0)
    dn = sum(1 for s in stocks if s["change_pct"] < 0)
    theme = "green" if up > dn * 1.5 else ("red" if dn > up * 1.5 else "blue")

    elements = []

    # ====== 1. 期货/盘前信号 ======
    fut_lines = ["**📡 期货 / 盘前信号**"]
    for f in futures_data:
        fut_lines.append(f"  {_arrow(f['change_pct'])} {f['name']}:  {_fmt_chg(f['change_pct'])}")
    v = benches.get("^VIX", {})
    if v:
        fut_lines.append(f"  😨 VIX: {v['price']}  ({v['change_pct']:+.2f}%)")
    if len(fut_lines) > 1:
        elements.append({"tag": "markdown", "content": "\n".join(fut_lines)})
        elements.append({"tag": "hr"})

    # ====== 2. 最大波动 & 异动 ======
    top_mover = max(stocks, key=lambda s: abs(s["change_pct"])) if stocks else None

    if top_mover:
        top_lines = [f"**🔥 最大波动: {_arrow(top_mover['change_pct'])} {top_mover['symbol']} {top_mover['name_cn']}**"]
        top_lines.append(f"  {top_mover['change_pct']:+.2f}%  ${top_mover['price']}")
        top_lines.append(f"  RSI={top_mover['rsi']}  量比={top_mover['vol_ratio']:.1f}x  振幅={top_mover['day_range_pct']:.1f}%")

        sigs = scanner_signals.get(top_mover["symbol"], [])
        if sigs:
            top_lines.append(f"  信号: {'; '.join(sigs)}")

        elements.append({"tag": "markdown", "content": "\n".join(top_lines)})

    # 异常清单
    if anomalies:
        anom_lines = ["\n**⚠️ 异常检测**"]
        for a in anomalies[:5]:  # 最多5条
            severity = "🚨" if a["anomaly_score"] >= 3 else "⚠️"
            anom_lines.append(
                f"{severity} **{a['symbol']} {a['name_cn']}** "
                f"(score={a['anomaly_score']})"
            )
            for r in a["anomaly_reasons"]:
                anom_lines.append(f"  · {r}")
            sigs = scanner_signals.get(a["symbol"], [])
            if sigs:
                anom_lines.append(f"  信号: {'; '.join(sigs)}")
        elements.append({"tag": "markdown", "content": "\n".join(anom_lines)})

    elements.append({"tag": "hr"})

    # ====== 3. 全持仓技术扫描表 ======
    table = ["**📋 技术扫描**"]
    table.append(
        "标的       价格        涨跌        RSI    MACD    量比   布林带"
    )
    for s in stocks:
        macd_icon = {"golden": "🟢金叉", "death": "🔴死叉",
                     "positive": "🟢", "negative": "🔴"}.get(s.get("macd_crossover", ""), "➖")
        bb_pos = {"above": "上轨↑", "below": "下轨↓", "inside": "中轨"}.get(s.get("bb_position", ""), "")
        table.append(
            f"{_arrow(s['change_pct'])} {s['symbol']:<6}"
            f" ${s['price']:<7}"
            f" {s['change_pct']:+6.2f}%"
            f" {s['rsi']:>5.1f}"
            f" {macd_icon:>6}"
            f" {s['vol_ratio']:>4.1f}x"
            f" {bb_pos:>6}"
        )

    # 统计行
    avg_rsi = statistics.mean([s["rsi"] for s in stocks]) if stocks else 0
    avg_chg = statistics.mean([s["change_pct"] for s in stocks]) if stocks else 0
    golden = sum(1 for s in stocks if s.get("macd_crossover") == "golden")
    death = sum(1 for s in stocks if s.get("macd_crossover") == "death")
    table.append(
        f"\n📊 共 {len(stocks)} 只 | 涨 {up} 跌 {dn}"
        f" | 均涨跌 {avg_chg:+.2f}% | 均RSI {avg_rsi:.1f}"
        f" | 金叉 {golden} 死叉 {death}"
    )
    elements.append({"tag": "markdown", "content": "\n".join(table)})

    # ====== 4. AI 综合解读 ======
    if ai_text:
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"**🤖 布丁解读**\n\n{ai_text[:1800]}"})

    # ====== 5. 底部 ======
    elements.append({"tag": "hr"})
    note_parts = [
        "📡 数据: Yahoo Finance",
        "技术: RSI(14)/MACD/SMA(20,50,200)/BB(20,2)",
        "期货: ES/F, NQ/F",
    ]
    if anomalies:
        note_parts.append(f"异常: {len(anomalies)} 项")
    elements.append({"tag": "note", "content": " | ".join(note_parts)})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 布丁量化日报 | {today_str}"},
            "template": theme,
        },
        "elements": elements,
    }


# ========================================================================
#  主入口
# ========================================================================

def send_daily_report() -> bool:
    """
    完整管线：（1）获取数据 → （2）技术分析 → （3）机会扫描
    → （4）异常检测 → （5）AI分析 → （6）记忆存储 → （7）飞书推送
    """
    logger.info("=" * 50)
    logger.info("📊 布丁量化日报 开始运行")
    logger.info("=" * 50)

    # （1）获取数据
    logger.info("📡 获取市场数据...")
    data = fetch_all()
    if not data or not data.get("stocks"):
        logger.warning("⚠️ 数据获取失败，跳过")
        return False

    stocks = data["stocks"]
    futures_data = data.get("futures", [])
    benches = data.get("benchmarks", {})

    # （2）技术指标在 fetch 阶段已经计算

    # （3）机会扫描
    logger.info("🔍 扫描交易信号...")
    scanner_signals = {}
    for s in stocks:
        sigs = OpportunityScanner.scan_all(s)
        if sigs:
            scanner_signals[s["symbol"]] = sigs

    # （4）异常检测
    logger.info("⚠️ 检测异常...")
    anomalies = [s for s in stocks if s.get("anomaly_score", 0) >= 2]
    anomalies.sort(key=lambda x: x["anomaly_score"], reverse=True)

    # （5）AI 分析
    logger.info("🤖 生成 AI 分析...")
    futures_text = generate_futures_analysis(futures_data, benches)
    ai_text = generate_ai_analysis(data, futures_data, anomalies)

    # （6）记忆存储
    try:
        memo = AnalysisMemory()
        memo.record_today(datetime.now().strftime("%Y-%m-%d"), stocks, ai_text[:500])
        memo_report = memo.get_accuracy_report()
    except Exception as e:
        logger.warning(f"记忆存储失败: {e}")
        memo_report = ""

    # （7）构建卡片并推送
    card = _build_card(data, anomalies, scanner_signals, futures_text, ai_text, memo_report)
    if not card:
        logger.warning("⚠️ 卡片构建失败")
        return False

    ok = _send_card(card)
    if ok:
        logger.info("✅ 量化日报已推送到飞书")

        # 如果AI分析超过卡片限制，用文本消息发剩余的
        if ai_text and len(ai_text) > 1800:
            remaining = ai_text[1800:]
            # 找自然断点
            br = remaining.rfind("\n\n") if len(remaining) > 200 else -1
            if br > 0:
                _send_text(f"🤖 布丁解读（续）\n\n{remaining}")

        # 期货分析单独发
        if futures_text:
            _send_text(f"📡 期货监测\n\n{futures_text}")
    else:
        logger.error("❌ 量化日报推送失败")

    return ok


# ========================================================================
#  命令行入口
# ========================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    send_daily_report()
