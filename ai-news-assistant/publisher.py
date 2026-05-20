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

    def get_access_token(self) -> Optional[str]:
        """获取微信 access_token"""
        if not self.appid or not self.appsecret:
            logger.warning("⚠️ WECHAT_APPID 或 WECHAT_APPSECRET 未配置")
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
                logger.info("✅ 微信 access_token 获取成功")
                return self._access_token
            else:
                logger.error(f"❌ 获取 token 失败: {data}")
                return None
        except Exception as e:
            logger.error(f"❌ 请求微信 API 异常: {e}")
            return None

    def create_draft(self, title: str, content: str) -> Optional[str]:
        """创建公众号草稿（所有账号都支持此 API）"""
        token = self.get_access_token()
        if not token:
            logger.warning("⚠️ 无法获取 token，跳过发布到公众号")
            return None

        # 格式化文章正文
        body_html = self._convert_to_wechat_format(content)

        draft_data = {
            "articles": [
                {
                    "title": title,
                    "content": body_html,
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                }
            ]
        }

        url = f"{WECHAT_API_BASE}/draft/create"
        try:
            resp = requests.post(
                url,
                params={"access_token": token},
                json=draft_data,
                timeout=15,
            )
            data = resp.json()
            if data.get("errcode") == 0:
                media_id = data.get("media_id")
                logger.info(f"✅ 草稿创建成功！media_id: {media_id}")
                return media_id
            else:
                logger.error(f"❌ 创建草稿失败: {data}")
                return None
        except Exception as e:
            logger.error(f"❌ 创建草稿异常: {e}")
            return None

    def _convert_to_wechat_format(self, markdown_text: str) -> str:
        """将 Markdown 转换为微信 HTML 格式"""
        import re

        lines = markdown_text.split("\n")
        html_parts = []
        in_list = False
        list_type = None

        for line in lines:
            stripped = line.strip()

            # 标题
            if stripped.startswith("# "):
                html_parts.append(f"<h2>{stripped[2:]}</h2>")
            elif stripped.startswith("## "):
                html_parts.append(f"<h3>{stripped[3:]}</h3>")
            elif stripped.startswith("### "):
                html_parts.append(f"<h4>{stripped[4:]}</h4>")
            # 粗体
            elif stripped.startswith("**") and stripped.endswith("**"):
                html_parts.append(f"<p><strong>{stripped[2:-2]}</strong></p>")
            # 无序列表
            elif stripped.startswith("- ") or stripped.startswith("* ") and not stripped.startswith("**"):
                content = stripped[2:]
                html_parts.append(f"<p>• {content}</p>")
            # 有序列表
            elif re.match(r"^\d+\.\s", stripped):
                content = re.sub(r"^\d+\.\s", "", stripped)
                html_parts.append(f"<p>{stripped}</p>")
            # 空行
            elif not stripped:
                if in_list:
                    in_list = False
            # 普通段落
            else:
                html_parts.append(f"<p>{stripped}</p>")

        return "\n".join(html_parts)


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
