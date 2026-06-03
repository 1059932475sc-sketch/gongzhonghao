"""
抓取国内公开热点榜单，并做第一层安全过滤。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape

import requests
from bs4 import BeautifulSoup

from config import BLOCK_KEYWORDS, DATA_DIR


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def blocked(text: str) -> bool:
    return any(k in text for k in BLOCK_KEYWORDS)


def looks_mojibake(text: str) -> bool:
    """过滤 UTF-8 被错解成 Latin-1 后的乱码。"""
    return any(token in text for token in ["æ", "å", "ç", "è", "é", "ï¼", "ã"])


def normalize_title(title: str) -> str:
    title = unescape(title)
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^[#【\[]+", "", title)
    title = re.sub(r"[】\]#]+$", "", title)
    return title


def fetch_baidu_top() -> list[dict]:
    url = "https://top.baidu.com/board?tab=realtime"
    try:
        html = requests.get(url, headers=HEADERS, timeout=15).text
    except Exception as e:
        logger.warning(f"百度热榜抓取失败: {e}")
        return []

    items = []
    # 页面里常有 title/contentUrl/desc 的 JSON 片段。
    for m in re.finditer(r'"word":"(.*?)".*?"desc":"(.*?)"', html):
        title = normalize_title(m.group(1))
        summary = normalize_title(m.group(2))
        if title and not looks_mojibake(title + summary) and not blocked(title + summary):
            items.append({"title": title, "summary": summary, "source": "百度热榜", "url": url})
    return dedupe(items)


def fetch_weibo_hot() -> list[dict]:
    url = "https://weibo.com/ajax/side/hotSearch"
    try:
        data = requests.get(url, headers=HEADERS, timeout=15).json()
    except Exception as e:
        logger.warning(f"微博热搜抓取失败: {e}")
        return []

    items = []
    for row in data.get("data", {}).get("realtime", [])[:50]:
        title = normalize_title(row.get("word", ""))
        summary = normalize_title(row.get("note", ""))
        if title and not looks_mojibake(title + summary) and not blocked(title + summary):
            items.append({
                "title": title,
                "summary": summary,
                "source": "微博热搜",
                "url": f"https://s.weibo.com/weibo?q={title}",
            })
    return dedupe(items)


def fetch_zhihu_hot() -> list[dict]:
    url = "https://www.zhihu.com/billboard"
    try:
        html = requests.get(url, headers=HEADERS, timeout=15).text
    except Exception as e:
        logger.warning(f"知乎热榜抓取失败: {e}")
        return []

    items = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.get_text("", strip=True)
        if "initialState" not in text and "hotList" not in text:
            continue
        for m in re.finditer(r'"titleArea":\{"text":"(.*?)"\}.*?"excerptArea":\{"text":"(.*?)"', text):
            title = normalize_title(m.group(1))
            summary = normalize_title(m.group(2))
            if title and not looks_mojibake(title + summary) and not blocked(title + summary):
                items.append({"title": title, "summary": summary, "source": "知乎热榜", "url": url})
    return dedupe(items)


def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        key = item["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def fetch_all() -> list[dict]:
    all_items = []
    for fetcher in [fetch_weibo_hot, fetch_baidu_top, fetch_zhihu_hot]:
        all_items.extend(fetcher())
    all_items = dedupe(all_items)
    path = DATA_DIR / f"raw_{datetime.now().strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch_all()[:20]:
        print(item["source"], item["title"])
