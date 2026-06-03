"""
AI 资讯情报官 - 微信公众号发布模块
===================================
支持两种发布方式：
1. 自动 API 发布（需要认证服务号）
2. 生成 Markdown 文件手动发布（推荐）
"""

import json
import logging
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional
from html import escape

import requests

from config import OUTPUT_DIR, WECHAT_APPID, WECHAT_APPSECRET

logger = logging.getLogger(__name__)

# ============================================================
# WeChat API 常量
# ============================================================
WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


class WeChatPublisher:
    """微信公众号发布器"""

    def __init__(self):
        self.appid = WECHAT_APPID
        self.appsecret = WECHAT_APPSECRET
        self._access_token = None
        self.last_error = ""

    def _set_error(self, message: str) -> None:
        self.last_error = message
        logger.error(f"❌ {message}")

    def _format_wechat_error(self, data: dict) -> str:
        errcode = data.get("errcode")
        errmsg = data.get("errmsg", "")
        if errcode == 40164:
            return f"微信接口被 IP 白名单拦截（40164）: {errmsg}"
        return f"微信接口错误（{errcode}）: {errmsg or data}"

    def get_access_token(self) -> Optional[str]:
        """获取微信 access_token"""
        if not self.appid or not self.appsecret:
            self.last_error = "WECHAT_APPID 或 WECHAT_APPSECRET 未配置"
            logger.warning(f"⚠️ {self.last_error}")
            return None

        url = f"{WECHAT_API_BASE}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.appid,
            "secret": self.appsecret,
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if "access_token" in data:
                self._access_token = data["access_token"]
                self.last_error = ""
                logger.info("✅ 微信 access_token 获取成功")
                return self._access_token
            else:
                self._set_error(f"获取 access_token 失败，{self._format_wechat_error(data)}")
                return None
        except Exception as e:
            self._set_error(f"请求微信 token API 异常: {e}")
            return None

    def create_draft(self, title: str, content: str) -> Optional[str]:
        """创建公众号草稿（所有账号都支持此 API）"""
        token = self.get_access_token()
        if not token:
            logger.warning("⚠️ 无法获取 token，跳过发布到公众号")
            return None

        title = _truncate_utf8(title, 30)

        # 格式化文章正文
        body_html = self._convert_to_wechat_format(content)
        thumb_media_id = self._get_default_thumb_media_id(title)
        if not thumb_media_id:
            if not self.last_error:
                self._set_error("无法上传默认封面，跳过创建草稿")
            logger.warning("⚠️ 无法上传默认封面，跳过创建草稿")
            return None

        draft_data = {
            "articles": [
                {
                    "title": title,
                    "author": "布丁",
                    "digest": self._build_digest(content),
                    "content": body_html,
                    "content_source_url": "",
                    "thumb_media_id": thumb_media_id,
                    "show_cover_pic": 0,
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                }
            ]
        }

        url = f"{WECHAT_API_BASE}/draft/add"
        try:
            resp = requests.post(
                url,
                params={"access_token": token},
                data=json.dumps(draft_data, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=15,
            )
            data = resp.json()
            if data.get("errcode") == 0 or "media_id" in data:
                media_id = data.get("media_id")
                self.last_error = ""
                logger.info(f"✅ 草稿创建成功！media_id: {media_id}")
                return media_id
            else:
                self._set_error(f"创建草稿失败，{self._format_wechat_error(data)}")
                return None
        except Exception as e:
            self._set_error(f"创建草稿请求异常: {e}")
            return None

    def _convert_to_wechat_format(self, markdown_text: str) -> str:
        """将 Markdown 转换为微信 HTML 格式"""
        import re

        lines = markdown_text.split("\n")
        html_parts = []
        in_code = False
        skip_rest = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("运营备注："):
                skip_rest = True
            if skip_rest:
                continue

            if stripped.startswith("```"):
                in_code = not in_code
                continue

            if in_code:
                if stripped:
                    html_parts.append(f"<p>{escape(stripped)}</p>")
                continue

            # 标题
            if stripped.startswith("# "):
                html_parts.append(f"<h2>{escape(stripped[2:])}</h2>")
            elif stripped.startswith("## "):
                html_parts.append(f"<h3>{escape(stripped[3:])}</h3>")
            elif stripped.startswith("### "):
                html_parts.append(f"<h4>{escape(stripped[4:])}</h4>")
            # 粗体
            elif stripped.startswith("**") and stripped.endswith("**"):
                html_parts.append(f"<p><strong>{escape(stripped[2:-2])}</strong></p>")
            # 无序列表
            elif stripped.startswith("- ") or stripped.startswith("* ") and not stripped.startswith("**"):
                content = stripped[2:]
                html_parts.append(f"<p>• {escape(content)}</p>")
            # 有序列表
            elif re.match(r"^\d+\.\s", stripped):
                html_parts.append(f"<p>{escape(stripped)}</p>")
            # 空行
            elif not stripped:
                continue
            elif stripped in {"---", "———", "***"}:
                continue
            elif re.match(r"^-\s+[^:：]+:\s*https?://", stripped):
                continue
            # 普通段落
            else:
                line_html = escape(stripped)
                line_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line_html)
                html_parts.append(f"<p>{line_html}</p>")

        return "\n".join(html_parts)

    def _build_digest(self, markdown_text: str) -> str:
        """生成公众号分享摘要。"""
        return "AI信息差，普通人也能用。"

    def _get_default_thumb_media_id(self, title: str) -> Optional[str]:
        """上传技术占位封面，返回永久素材 media_id。

        微信草稿接口要求 thumb_media_id，但用户不想要 AI 封面；
        因此使用 1x1 白图占位，并设置 show_cover_pic=0，不在正文显示。
        """
        token = self._access_token or self.get_access_token()
        if not token:
            return None

        cover_path = OUTPUT_DIR / "wechat_placeholder_cover.jpg"
        self._generate_placeholder_cover(cover_path)

        url = f"{WECHAT_API_BASE}/material/add_material"
        try:
            with cover_path.open("rb") as f:
                resp = requests.post(
                    url,
                    params={"access_token": token, "type": "image"},
                    files={"media": (cover_path.name, f, "image/jpeg")},
                    timeout=20,
                )
            data = resp.json()
            if "media_id" in data:
                self.last_error = ""
                return data["media_id"]
            self._set_error(f"上传封面失败，{self._format_wechat_error(data)}")
            return None
        except Exception as e:
            self._set_error(f"上传封面请求异常: {e}")
            return None

    def _generate_placeholder_cover(self, path: Path):
        """生成纯白占位图，不作为视觉封面使用。"""
        from PIL import Image

        img = Image.new("RGB", (900, 500), "#ffffff")
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "JPEG", quality=92)


# ============================================================
# 手动发布模式（推荐给电脑小白）
# ============================================================

def open_wechat_editor():
    """在浏览器中打开公众号编辑器"""
    url = "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit"
    webbrowser.open(url)
    logger.info("🌐 已打开公众号编辑器")


def generate_publish_guide(article_path: str):
    """生成发布指南"""
    guide = f"""
# 📤 发布指南：手动发布到公众号

## 步骤

1. **打开文章文件**
   📄 `{article_path}`

2. **复制内容**
   - 用任何文本编辑器打开上述文件
   - 全选 (Cmd+A) → 复制 (Cmd+C)

3. **打开公众号编辑器**
   - 访问 https://mp.weixin.qq.com/
   - 登录你的公众号
   - 点击"新建群发"或"新建图文"

4. **粘贴并调整格式**
   - 粘贴内容 (Cmd+V)
   - 调整图片位置
   - 检查链接是否正常
   - 添加封面图

5. **预览和发布**
   - 先预览确认排版没问题
   - 点击"群发"

> 💡 每天只能群发一次，建议确认无误再发
"""
    guide_path = OUTPUT_DIR / "发布指南.md"
    guide_path.write_text(guide, encoding="utf-8")
    logger.info(f"📋 发布指南已生成: {guide_path}")
    return str(guide_path)


def auto_publish(title: str, content: str, article_path: Optional[str] = None) -> bool:
    """
    自动发布流程：
    1. 如果有配置微信 API → 自动创建草稿
    2. 否则 → 生成发布指南
    """
    publisher = WeChatPublisher()

    if WECHAT_APPID and WECHAT_APPSECRET:
        media_id = publisher.create_draft(title, content)
        if media_id:
            logger.info("✅ 草稿已创建，请到公众号后台发布")
            return True
        else:
            logger.warning("⚠️ API 发布失败，切换到手动模式")

    # 手动模式
    if article_path:
        guide_path = generate_publish_guide(article_path)
        logger.info(f"📋 手动发布指南: {guide_path}")
        # 尝试打开公众号编辑器
        try:
            open_wechat_editor()
        except Exception:
            pass

    return False


def extract_markdown_title(content: str, fallback: str) -> str:
    """从 Markdown 第一行标题提取草稿标题。"""
    for line in content.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return _compact_wechat_title(title or fallback)
    return _compact_wechat_title(fallback)


def _compact_wechat_title(title: str) -> str:
    """生成适合微信草稿接口的短标题，避免截断成半句话。"""
    text = title.lower()
    if "副业" in title or "赚钱" in title or "money" in text:
        return "AI副业观察"
    if "工具" in title or "tool" in text or "github" in text:
        return "AI工具避坑"
    if "办公" in title or "效率" in title:
        return "AI办公提效"
    return "AI信息差"


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """按 UTF-8 字节截断，避免微信标题超限。"""
    out = ""
    used = 0
    for ch in text:
        size = len(ch.encode("utf-8"))
        if used + size > max_bytes:
            break
        out += ch
        used += size
    return out.rstrip()


def create_wechat_draft_from_file(article_path: str, fallback_title: str) -> tuple[bool, str]:
    """为任意文章文件创建公众号草稿，返回 (成功, 结果信息)。"""
    try:
        content = Path(article_path).read_text(encoding="utf-8")
    except Exception as e:
        return False, f"读取文章失败: {e}"

    title = extract_markdown_title(content, fallback_title)
    publisher = WeChatPublisher()
    media_id = publisher.create_draft(title, content)
    if media_id:
        return True, f"草稿已创建：{title}（media_id: {media_id}）"
    detail = publisher.last_error or "未知错误"
    return False, f"草稿创建失败：{title}；{detail}"
