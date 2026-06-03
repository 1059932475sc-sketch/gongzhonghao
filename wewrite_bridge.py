"""
把当前项目生成的 Markdown 文章交给 wewrite 做公众号排版。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
WEWRITE_TOOLKIT = REPO_ROOT / "wewrite" / "toolkit"
WEWRITE_THEMES = WEWRITE_TOOLKIT / "themes"
WEWRITE_VENV_LIB = REPO_ROOT / "wewrite" / ".venv" / "lib"


def render_markdown_with_wewrite(article_path: str, theme_name: str | None = None) -> dict | None:
    """把 Markdown 文章渲染成 wewrite 主题 HTML，返回产物信息。"""
    if not WEWRITE_TOOLKIT.exists():
        return None

    theme_name = theme_name or os.getenv("WEWRITE_THEME", "professional-clean")

    if str(WEWRITE_TOOLKIT) not in sys.path:
        sys.path.insert(0, str(WEWRITE_TOOLKIT))
    if WEWRITE_VENV_LIB.exists():
        for site_packages in WEWRITE_VENV_LIB.glob("python*/site-packages"):
            if str(site_packages) not in sys.path:
                sys.path.insert(0, str(site_packages))

    try:
        from converter import WeChatConverter, preview_html
        from theme import load_theme
    except ModuleNotFoundError:
        return None

    path = Path(article_path)
    theme = load_theme(theme_name, themes_dir=str(WEWRITE_THEMES))
    converter = WeChatConverter(theme=theme)
    result = converter.convert_file(str(path))

    body_path = path.with_suffix(f".{theme_name}.body.html")
    preview_path = path.with_suffix(f".{theme_name}.preview.html")

    body_path.write_text(result.html, encoding="utf-8")
    preview_path.write_text(preview_html(result.html, theme), encoding="utf-8")

    return {
        "theme": theme_name,
        "title": result.title,
        "digest": result.digest,
        "body_html_path": str(body_path),
        "preview_html_path": str(preview_path),
    }
