"""
微信公众号草稿箱发布：纯文字，无视觉封面。
"""

from __future__ import annotations

import json
import logging
import re
from html import escape
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from config import OUTPUT_DIR, WECHAT_APPID, WECHAT_APPSECRET


logger = logging.getLogger(__name__)
WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


def truncate_utf8(text: str, max_bytes: int) -> str:
    out = ""
    used = 0
    for ch in text:
        size = len(ch.encode("utf-8"))
        if used + size > max_bytes:
            break
        out += ch
        used += size
    return out.strip()


def compact_title(title: str) -> str:
    if "重金抢人" in title or "机会变了" in title:
        return "普通人的机会变了"
    if "上岸北大" in title or "不是励志" in title:
        return "别只把它当励志"
    if "48元" in title or "嫌贵" in title:
        return "大家不只是嫌贵"
    if "变瘦" in title or "代价" in title:
        return "变瘦也有代价"
    if "向日葵" in title or "羡慕" in title:
        return "这所学校让人羡慕"
    if "不信镜头" in title:
        return "普通人不信镜头了"
    if "较真" in title:
        return "观众越来越较真"
    if "10吨车" in title or "材料" in title:
        return "新材料离你多远"
    if "消费者" in title:
        return "消费者不爱忍了"
    return truncate_utf8(title, 30)


class WeChatPublisher:
    def __init__(self):
        self.appid = WECHAT_APPID
        self.appsecret = WECHAT_APPSECRET
        self._token: Optional[str] = None

    def get_access_token(self) -> Optional[str]:
        if self._token:
            return self._token
        data = requests.get(
            f"{WECHAT_API_BASE}/token",
            params={"grant_type": "client_credential", "appid": self.appid, "secret": self.appsecret},
            timeout=10,
        ).json()
        if "access_token" not in data:
            logger.error(f"获取 token 失败: {data}")
            return None
        self._token = data["access_token"]
        return self._token

    def upload_placeholder_cover(self) -> Optional[str]:
        token = self.get_access_token()
        if not token:
            return None
        cover = OUTPUT_DIR / "wechat_placeholder_cover.jpg"
        Image.new("RGB", (900, 500), "#ffffff").save(cover, "JPEG", quality=92)
        with cover.open("rb") as f:
            data = requests.post(
                f"{WECHAT_API_BASE}/material/add_material",
                params={"access_token": token, "type": "image"},
                files={"media": (cover.name, f, "image/jpeg")},
                timeout=20,
            ).json()
        if "media_id" not in data:
            logger.error(f"上传占位封面失败: {data}")
            return None
        return data["media_id"]

    def markdown_to_html(self, markdown: str) -> str:
        html = []
        for line in markdown.splitlines():
            s = line.strip()
            if not s or s in {"---", "***"}:
                continue
            if s.startswith("# "):
                html.append(f"<h2>{escape(s[2:])}</h2>")
            elif s.startswith("## "):
                html.append(f"<h3>{escape(s[3:])}</h3>")
            elif re.match(r"^\d+\.\s", s):
                html.append(f"<p>{escape(s)}</p>")
            elif s.startswith("- "):
                html.append(f"<p>• {escape(s[2:])}</p>")
            else:
                html.append(f"<p>{escape(s)}</p>")
        return "\n".join(html)

    def create_draft(self, title: str, markdown: str) -> tuple[bool, str]:
        token = self.get_access_token()
        thumb = self.upload_placeholder_cover()
        if not token or not thumb:
            return False, "token 或占位封面不可用"
        api_title = compact_title(title)
        payload = {
            "articles": [{
                "title": truncate_utf8(api_title, 30),
                "author": "布丁",
                "digest": "社会热点，普通人怎么看。",
                "content": self.markdown_to_html(markdown),
                "content_source_url": "",
                "thumb_media_id": thumb,
                "show_cover_pic": 0,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
            }]
        }
        data = requests.post(
            f"{WECHAT_API_BASE}/draft/add",
            params={"access_token": token},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=20,
        ).json()
        if "media_id" in data or data.get("errcode") == 0:
            return True, f"草稿已创建：{api_title}（media_id: {data.get('media_id')}）"
        return False, f"草稿创建失败：{data}"
