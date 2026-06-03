"""
AI 资讯情报官 - RSS/网页抓取模块
=================================
自动抓取各大 AI 新闻源的最新内容
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import RSS_SOURCES, RSS_FEEDS, MAX_ITEMS_PER_SOURCE, CACHE_DIR, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 请求头，模拟真实浏览器
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_REQUEST_ERRORS: dict[str, str] = {}
_FETCH_STATS: list[dict] = []
_SESSION = requests.Session()
_SESSION.mount(
    "http://",
    HTTPAdapter(
        max_retries=Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    ),
)
_SESSION.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    ),
)


def _reset_fetch_diagnostics():
    _REQUEST_ERRORS.clear()
    _FETCH_STATS.clear()


def _record_fetch_stat(name: str, url: str, count: int, error: str = ""):
    _FETCH_STATS.append({
        "name": name,
        "url": url,
        "count": count,
        "ok": not error,
        "error": error,
    })


def get_fetch_stats() -> list[dict]:
    return list(_FETCH_STATS)


def fetch_url(url: str, timeout: int = 30) -> Optional[str]:
    """安全地获取 URL 内容"""
    try:
        resp = _SESSION.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        # 自动检测编码
        resp.encoding = resp.apparent_encoding or "utf-8"
        _REQUEST_ERRORS.pop(url, None)
        return resp.text
    except requests.RequestException as e:
        _REQUEST_ERRORS[url] = str(e)
        logger.warning(f"请求失败 [{url}]: {e}")
        return None


def parse_feed(url: str) -> list[dict]:
    """解析标准 RSS/Atom Feed，返回文章列表"""
    html = fetch_url(url)
    if not html:
        return []

    feed = feedparser.parse(html)
    items = []

    for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")

        # 提取摘要
        summary = ""
        if hasattr(entry, "summary"):
            summary = BeautifulSoup(entry.summary, "html.parser").get_text(separator=" ", strip=True)
        elif hasattr(entry, "description"):
            summary = BeautifulSoup(entry.description, "html.parser").get_text(separator=" ", strip=True)

        # 提取发布日期
        pub_date = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        items.append({
            "title": title,
            "url": link,
            "summary": summary[:500],  # 截断过长摘要
            "source": url,
            "published": pub_date,
        })

    return items


def parse_huggingface_papers(url: str) -> list[dict]:
    """通过 API 抓取 Hugging Face Daily Papers"""
    api_url = "https://huggingface.co/api/daily_papers"

    try:
        resp = _SESSION.get(api_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        papers = resp.json()
        _REQUEST_ERRORS.pop(url, None)
    except Exception as e:
        _REQUEST_ERRORS[url] = str(e)
        logger.warning(f"HuggingFace API 请求失败: {e}")
        return []

    items = []
    for paper in papers[:MAX_ITEMS_PER_SOURCE]:
        title = paper.get("title", "").strip()
        paper_id = paper.get("paper_id", paper.get("id", ""))
        summary = paper.get("summary", "") or ""
        url_path = paper.get("url", f"https://huggingface.co/papers/{paper_id}")

        # 提取作者
        authors = paper.get("authors", [])
        if isinstance(authors, list):
            author_text = ", ".join(
                a.get("name", str(a)) if isinstance(a, dict) else str(a)
                for a in authors[:5]
            )
        else:
            author_text = str(authors)

        full_summary = f"作者: {author_text}\n\n{summary}" if author_text else summary

        items.append({
            "title": title,
            "url": url_path,
            "summary": full_summary[:500],
            "source": url,
            "published": datetime.now(timezone.utc),
        })

    return items


def parse_github_trending(url: str) -> list[dict]:
    """抓取 GitHub Trending 页面"""
    html = fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    for article in soup.select("article.Box-row")[:MAX_ITEMS_PER_SOURCE]:
        title_el = article.select_one("h2 a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True).replace("\n", "").replace(" ", "")
        link = "https://github.com" + title_el.get("href", "")

        # 项目描述
        desc_el = article.select_one("p")
        summary = desc_el.get_text(strip=True) if desc_el else ""

        # 星标数 / 今日星标
        stars = ""
        star_el = article.select_one(".d-inline-block.float-sm-right")
        if star_el:
            stars = star_el.get_text(strip=True)

        items.append({
            "title": f"[GitHub] {title} ⭐{stars}",
            "url": link,
            "summary": summary[:500],
            "source": url,
            "published": datetime.now(timezone.utc),
        })

    return items


def parse_arxiv_list(url: str) -> list[dict]:
    """抓取 arXiv cs.AI 最新论文列表"""
    html = fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    for dt, dd in zip(soup.select("dt")[:MAX_ITEMS_PER_SOURCE * 2],
                       soup.select("dd")[:MAX_ITEMS_PER_SOURCE * 2]):
        title_el = dd.select_one(".list-title.mathjax")
        if not title_el:
            continue

        title = title_el.get_text(strip=True).replace("Title:", "").strip()

        # 论文链接
        link_el = dt.select_one("a")
        link = ""
        if link_el:
            link = "https://arxiv.org" + link_el.get("href", "")

        # 摘要
        abstract_el = dd.select_one("p.mathjax")
        summary = abstract_el.get_text(strip=True) if abstract_el else ""

        # 作者
        authors_el = dd.select_one(".list-authors")
        authors = authors_el.get_text(strip=True).replace("Authors:", "").strip() if authors_el else ""

        items.append({
            "title": f"[arXiv] {title}",
            "url": link,
            "summary": f"作者: {authors[:200]}\n{summary[:500]}",
            "source": url,
            "published": datetime.now(timezone.utc),
        })

    return items


def parse_producthunt(url: str) -> list[dict]:
    """抓取 Product Hunt AI 产品列表"""
    html = fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Product Hunt 是 JS 渲染的，这里做基础抓取
    for item in soup.select('[class*="post"], [class*="item_"]')[:MAX_ITEMS_PER_SOURCE]:
        title_el = item.select_one("a[class*='title'], h2 a, h3 a")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")
        if link and not link.startswith("http"):
            link = "https://www.producthunt.com" + link

        desc_el = item.select_one('[class*="description"], p, [class*="tagline"]')
        summary = desc_el.get_text(strip=True) if desc_el else ""

        items.append({
            "title": f"[ProductHunt] {title}",
            "url": link,
            "summary": summary[:500],
            "source": url,
            "published": datetime.now(timezone.utc),
        })

    return items


def parse_generic_news_page(url: str, selector: str = "a") -> list[dict]:
    """抓取中文资讯站列表页，提取可读性较高的新闻链接。"""
    html = fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_links = set()

    for link_el in soup.select(selector)[:MAX_ITEMS_PER_SOURCE * 8]:
        title = link_el.get_text(" ", strip=True)
        href = link_el.get("href", "")
        if not title or not href:
            continue
        if len(title) < 8 or len(title) > 90:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        if not href.startswith("http"):
            href = requests.compat.urljoin(url, href)
        if href in seen_links:
            continue

        parent_text = link_el.parent.get_text(" ", strip=True) if link_el.parent else ""
        summary = parent_text.replace(title, "").strip()
        summary = re.sub(r"\s+", " ", summary)[:500]

        seen_links.add(href)
        items.append({
            "title": title,
            "url": href,
            "summary": summary,
            "source": url,
            "published": datetime.now(timezone.utc),
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break

    return items


def _is_recent(item: dict, hours: int = 48) -> bool:
    """判断条目是否在指定小时内发布"""
    if item.get("published"):
        now = datetime.now(timezone.utc)
        delta = now - item["published"]
        return delta.total_seconds() <= hours * 3600
    return True  # 没日期信息的默认保留


def _is_advertising(item: dict) -> bool:
    """检查是否营销软文"""
    text = f"{item['title']} {item['summary']}".lower()
    ad_keywords = [
        "sponsored", "ad", "promoted", "partner",
        "限时优惠", "点击购买", "注册送", "免费领取",
        "割韭菜", "暴富", "月入过万", "被动收入",
        "限时特价", "立即下单", "买一送一",
        "通讯会员", "加入会员", "购买会员", "立即订阅", "限时订阅",
    ]
    return any(kw in text for kw in ad_keywords)


def generate_item_id(item: dict) -> str:
    """为条目生成唯一 ID（去重用）"""
    raw = f"{item['title']}{item['url']}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_seen_ids() -> set:
    """加载已处理过的条目 ID"""
    path = DATA_DIR / "seen_ids.json"
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_seen_ids(ids: set):
    """保存已处理过的条目 ID"""
    path = DATA_DIR / "seen_ids.json"
    path.write_text(json.dumps(list(ids)))


def fetch_all() -> list[dict]:
    """执行全量抓取，返回所有去重后的有效条目"""
    logger.info("🚀 开始全量抓取...")
    _reset_fetch_diagnostics()

    all_items = []
    parsers = {
        "huggingface.co/papers": parse_huggingface_papers,
        "github.com/trending": parse_github_trending,
        "arxiv.org/list": parse_arxiv_list,
        "producthunt.com": parse_producthunt,
    }

    # 抓取主要 RSS 源
    for source in RSS_SOURCES:
        name = source["name"]
        url = source["url"]
        logger.info(f"📡 抓取: {name}")
        items = []

        for key, parser in parsers.items():
            if key in url:
                items = parser(url)
                break
        else:
            if source.get("type") == "webpage":
                items = parse_generic_news_page(url, source.get("selector", "a"))
            else:
                items = parse_feed(url)

        for item in items:
            item["source_name"] = name
        all_items.extend(items)
        _record_fetch_stat(name, url, len(items), _REQUEST_ERRORS.get(url, ""))
        logger.info(f"   → 获取 {len(items)} 条")

    # 抓取额外 RSS Feed
    for feed in RSS_FEEDS:
        name = feed["name"]
        url = feed["url"]
        logger.info(f"📡 抓取: {name}")
        items = parse_feed(url)
        for item in items:
            item["source_name"] = name
        all_items.extend(items)
        _record_fetch_stat(name, url, len(items), _REQUEST_ERRORS.get(url, ""))
        logger.info(f"   → 获取 {len(items)} 条")

    # 去重 & 过滤
    seen_ids = load_seen_ids()
    new_seen = set(seen_ids)

    filtered = []
    for item in all_items:
        item_id = generate_item_id(item)
        if item_id in new_seen:
            continue
        if not _is_recent(item):
            continue
        if _is_advertising(item):
            continue
        new_seen.add(item_id)
        item["id"] = item_id
        filtered.append(item)

    save_seen_ids(new_seen)
    logger.info(f"✅ 抓取完成: 原始 {len(all_items)} 条 → 去重过滤后 {len(filtered)} 条")

    return filtered


if __name__ == "__main__":
    items = fetch_all()
    for item in items[:10]:
        print(f"\n--- {item['source_name']} ---")
        print(f"标题: {item['title'][:80]}")
        print(f"摘要: {item['summary'][:150]}")
        print(f"链接: {item['url']}")
