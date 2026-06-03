"""
AI 资讯情报官 - AI 文章生成模块
===============================
使用大模型自动生成公众号文章
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    OUTPUT_DIR, WRITER_STYLE, TONE, TARGET_AUDIENCE, ARTICLE_LENGTH,
)

logger = logging.getLogger(__name__)
_LLM_STATUS = {
    "mode": "ok",
    "fallback_count": 0,
    "errors": [],
}


def reset_llm_status():
    _LLM_STATUS["mode"] = "ok"
    _LLM_STATUS["fallback_count"] = 0
    _LLM_STATUS["errors"] = []


def get_llm_status() -> dict:
    return {
        "mode": _LLM_STATUS["mode"],
        "fallback_count": _LLM_STATUS["fallback_count"],
        "errors": list(_LLM_STATUS["errors"]),
    }


def _mark_llm_fallback(error: str):
    _LLM_STATUS["mode"] = "fallback"
    _LLM_STATUS["fallback_count"] += 1
    if error and error not in _LLM_STATUS["errors"]:
        _LLM_STATUS["errors"].append(error)

# ============================================================
# 提示词模板
# ============================================================

DAILY_BRIEF_PROMPT = """你是一位{writer_style}。

## 你的任务
根据以下今日 AI 资讯素材，写一篇约 {length} 的**公众号风格文章**。

## 什么是"公众号风格"？（非常重要，必须遵守）
这不是传统的新闻报道，而是像你个人公众号上发的一篇文章。要让人感觉：
1. **开头抓人**——用一句反常识的话、一个故事、或者一个扎心问题开头，让读者忍不住往下看
2. **说人话**——不要学术腔，不要机器翻译感。用大白话把AI技术讲清楚
3. **有态度**——不是冷冰冰的"据报道"，而是"我觉得"、"说实话"、"我直接说结论"
4. **短段落**——每段不超过3-4行，读起来轻松
5. **金句**——中间插一两句有记忆点的句子（加粗）
6. **节奏感**——多用短句、反问句，像跟朋友聊天
7. **不完美感**——不要太工整，有点口语化、有点个人风格，才像真人写的

## 📱 公众号排版规范（非常重要，严格控制）
1. **段与段之间必须空一行**，一篇正文至少空出 8-12 个空行
2. **每段不超过 4 行**，手机上读起来不累
3. **核心观点必须加粗**（用 ** **），让扫读时一眼抓到重点
4. **不可使用代码块、表格、超长段落**——这些在公众号上很难看
5. **标题层级严格**：# 标题 → 文章主标题，## → 一级小标题，### → 二级小标题
6. **小标题使用 emoji + 文字组合**，视觉效果更好（如 "🔥 正文"）
7. **链接只放文末"参考来源"部分**，正文中不要嵌入长链接
8. **全文 1500-2000 字**，太长读者看不完

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 不要只是罗列新闻，要讲背后的意义和趋势
- 要有作者自己的评论和见解
- 专业术语保留英文并附中文释义
- 结尾不要"综上所述"，要丢一个思考题或一个犀利的观点让读者回味

## 今日素材
{items}

## 文章格式要求
用以下格式输出，严格遵守排版规范：

# 标题（14-18字，吸引人但不夸张）

## 📌 今日速览（3-5条一句话加粗总结）

（空一行）
**核心速览条目1**
（空一行）
**核心速览条目2**
（空一行）

## 🔥 正文（按重要性排列，用小标题 + 空行分段）

## 💡 布丁说（作者自己的犀利观点，用**加粗**强调金句）

## 📚 延伸阅读（相关链接，可选）"""


DEEP_DIVE_PROMPT = """你是一位{writer_style}。

## 触发条件
今天有多个权威来源同时报道了 **{topic}**，说明这是一个重要趋势，值得写一篇深度分析。

## 你的任务
基于以下素材，写一篇约 {length} 的**公众号深度分析文章**。不是百科词条、不是论文综述，而是像你公众号上发的爆款深度文。

## 什么是"公众号深度文"？（非常重要）
1. **开头定生死**——必须在前3句话抓住读者。可以用一个故事、一组反常识数据、或者一个灵魂拷问
2. **说人话的技术解读**——再复杂的技术，也要用大白话讲。比如不要写"基于Transformer架构的多模态模型"，而要写"这个模型能同时看懂文字、图片和声音，就像给AI装了五感"
3. **有观点的分析**——"这件事意味着什么"比"这件事是什么"重要一万倍
4. **有信息量**——读者看完要觉得"值了"，有可以转发给朋友的东西
5. **有记忆点**——中间放1-2个金句（加粗），让人看完能记住
6. **短段落、多换行**——手机上读起来不累
7. **结尾有力量**——不是"总之"式结尾，而是丢一个犀利的判断、或者一个开放问题

## 📱 公众号排版规范（非常重要，严格控制）
1. **段与段之间必须空一行**，整篇文章至少空出 10-15 个空行
2. **每段不超过 4 行**，手机上读着不累
3. **所有核心观点、金句、关键数据必须加粗**
4. **不可使用代码块、表格、超长段落**
5. **小标题用 emoji + 文字组合**（如 "🎯 核心观点"、"🔥 正文"）
6. **链接只放文末"参考来源"部分**

## 写作要求
- 目标读者：{audience}
- 语气风格：{tone}
- 不要只讲是什么，要讲为什么重要、对谁有影响、接下来会怎样
- 要有作者的态度（"我说句不好听的"、"坦白讲"、"我直接说结论"）
- 口语化但不过度，读起来像是朋友在跟你分享

## 相关素材
{items}

## 文章格式要求
严格遵守以下排版结构，每个标题之间用空行分隔：

# 标题（14-18字，爆款标题，让人想点进来）

## 🎯 核心观点（一句加粗说清楚，这篇文章在讲什么）

（空一行）
**一句话核心观点**
（空一行）

## 🔥 正文

### 1. 先说说（用吸引人的方式引出话题）
（段落之间空行）

### 2. 到底怎么回事（把事情讲清楚）
（段落之间空行）

### 3. 为什么这事很重要（深度分析、行业影响）
（段落之间空行）

### 4. 接下来会怎样（趋势判断）
（段落之间空行）

## 💡 布丁说（作者的犀利点评，**加粗**金句）

## 📚 参考来源"""


PUBLIC_ACCOUNT_PROMPT = """你是一位{writer_style}，现在要为公众号「{account_name}」写一篇今天可发布的文章。

## 账号定位
{positioning}

## 目标读者
{account_audience}

## 变现方向
{monetization}

## 今日选题
标题素材：{source_title}
摘要素材：{source_summary}
来源：{source_name}
链接：{source_url}

## 运营判断
流量分：{traffic_score}
收益分：{money_score}
匹配分：{fit_score}
风险分：{risk_score}
推荐理由：{reasons}

## 写作目标
这不是新闻搬运，而是公众号运营稿。你要把一个 AI 热点，翻译成普通人愿意点、愿意看完、愿意收藏转发的文章。

文章必须满足：
1. 开头 3 句话必须抓人，直接点出普通人的利益或焦虑。
2. 不写硬核论文综述，不堆英文术语。
3. 多写「具体场景」：职场、办公、副业、短视频、电商、学习、老板经营。
4. 必须有「能带来收益的行动建议」，但不能承诺暴富、稳赚、躺赚。
5. 必须设计一个自然的关注/私域钩子，例如“我后面会整理工具清单/模板/避坑表”。
6. 每段不超过 4 行，段落之间空一行。
7. 金句、核心判断、行动建议用 **加粗**。
8. 不要使用表格、代码块、复杂列表。

## 文章结构
# 标题（15-24字，面向普通人，有点击欲但不夸张）

## 先说结论
用 2-3 段说清楚这件事和普通人有什么关系。

## 为什么这个题今天值得看
解释热点背后的变化，但要说人话。

## 普通人可以怎么用
给 3-5 个具体场景和做法。

## 哪些坑不要踩
提醒风险，建立信任。

## 布丁说
给出明确观点、下一步行动建议和自然关注钩子。

## 参考来源
只放来源名和链接，不要在正文中插长链接。
"""


def _build_items_text(items: list[dict]) -> str:
    """将新闻条目格式化为 LLM 可读的文本"""
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"[{i}] 标题: {item['title']}")
        lines.append(f"    摘要: {item['summary'][:300]}")
        lines.append(f"    来源: {item.get('source_name', '未知')}")
        lines.append(f"    链接: {item['url']}")
        lines.append("")
    return "\n".join(lines)


def _call_llm(prompt: str) -> str:
    """调用 LLM 生成文章内容"""
    if not LLM_API_KEY:
        logger.error("❌ LLM_API_KEY 未设置！请在环境变量或 config.py 中配置")
        _mark_llm_fallback("LLM_API_KEY 未设置")
        return _fallback_no_api(prompt)

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一位中文科技公众号博主「布丁」。你用大白话讲AI，有态度有观点，文章读起来像朋友聊天，读者都说你写得通俗易懂又有深度。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=4000,
        )

        return resp.choices[0].message.content

    except Exception as e:
        logger.error(f"❌ LLM 调用失败: {e}")
        _mark_llm_fallback(str(e))
        return _fallback_no_api(prompt)


def _fallback_no_api(prompt: str) -> str:
    """当 API 不可用时的降级方案：生成结构化模板"""
    logger.warning("⚠️ 使用降级方案：生成结构化文章模板")
    return """# ⚠️ 今日 AI 资讯简报（API 未配置）

## 📌 今日快讯

本文由 AI 资讯情报官自动生成。
请配置 LLM_API_KEY 以启用 AI 撰写功能。

## 如何配置

1. 设置环境变量：export OPENAI_API_KEY="你的 key"
2. 或在 config.py 中直接填写 LLM_API_KEY

支持 OpenAI、DeepSeek 等任意兼容 API。
"""


def generate_daily_brief(items: list[dict]) -> str:
    """生成每日 AI 资讯简报"""
    logger.info("📝 生成每日 AI 资讯简报...")

    items_text = _build_items_text(items)

    prompt = DAILY_BRIEF_PROMPT.format(
        writer_style=WRITER_STYLE,
        tone=TONE,
        length=ARTICLE_LENGTH,
        audience=TARGET_AUDIENCE,
        items=items_text,
    )

    content = _call_llm(prompt)
    return content


def generate_deep_dive(trend: dict) -> str:
    """生成深度选题文章"""
    topic = trend["topic"]
    logger.info(f"📝 生成深度文章: {topic}")

    items_text = _build_items_text(trend["articles"])

    prompt = DEEP_DIVE_PROMPT.format(
        writer_style=WRITER_STYLE,
        tone=TONE,
        topic=topic,
        length=ARTICLE_LENGTH,
        audience=TARGET_AUDIENCE,
        items=items_text,
    )

    content = _call_llm(prompt)
    return content


def generate_public_account_article(selection: dict) -> str:
    """根据运营选题，为指定公众号生成一篇可发布文章。"""
    profile = selection["account"]
    item = selection["item"]
    score = selection["score"]
    logger.info(f"📝 生成公众号文章: {profile['account_name']} / {item.get('title', '')[:40]}")

    prompt = PUBLIC_ACCOUNT_PROMPT.format(
        writer_style=WRITER_STYLE,
        account_name=profile["account_name"],
        positioning=profile["positioning"],
        account_audience=profile["audience"],
        monetization=profile["monetization"],
        source_title=item.get("title", ""),
        source_summary=item.get("summary", ""),
        source_name=item.get("source_name", "未知"),
        source_url=item.get("url", ""),
        traffic_score=score["traffic_score"],
        money_score=score["money_score"],
        fit_score=score["fit_score"],
        risk_score=score["risk_score"],
        reasons="；".join(score["reasons"]),
    )

    content = _call_llm(prompt)
    if content.startswith("# ⚠️ 今日 AI 资讯简报"):
        return _fallback_public_account_article(selection)
    return content


def _fallback_public_account_article(selection: dict) -> str:
    """LLM 不可用时，仍按选题生成一篇可编辑的公众号草稿。"""
    profile = selection["account"]
    item = selection["item"]
    score = selection["score"]
    title = item.get("title", "今天这个 AI 变化，普通人也该看一眼")
    source = item.get("source_name", "公开来源")
    url = item.get("url", "")
    summary = item.get("summary", "").strip() or "这条信息缺少摘要，建议发布前补充 1-2 个实际案例。"

    if profile.get("article_type") == "money":
        main_title = "普通人做AI副业，先别急着交钱"
        use_cases = [
            "短视频账号可以先用 AI 做选题、脚本和标题测试，而不是一上来买课。",
            "电商和本地商家可以用 AI 批量生成商品文案、活动海报文案和客服话术。",
            "会写作、剪辑、做图的人，可以把 AI 当成提速工具，接更小、更快、更稳定的单。",
        ]
        action = "先选一个你已经会的技能，再用 AI 把交付速度提高一倍。"
    else:
        main_title = "这个AI工具火了，普通人别只看热闹"
        use_cases = [
            "职场人可以把它拆成“找资料、写初稿、改表达、做清单”四步来用。",
            "学生和新手可以用它做学习提纲、面试准备和资料整理。",
            "小老板可以用它先处理重复文案，再把省下来的时间放到成交和服务上。",
        ]
        action = "不要追每一个新工具，先把一个高频场景跑通。"

    use_case_text = "\n\n".join(f"**{i}. {case}**" for i, case in enumerate(use_cases, 1))
    reasons = "；".join(score.get("reasons", []))

    return f"""# {main_title}

## 先说结论

今天这条消息值得看，不是因为它又多了一个新概念，而是因为它提醒我们：**AI 的机会正在从“看新闻”变成“改工作流”。**

素材里提到的重点是：{title}

如果你是普通人，不需要先研究技术细节。你要先问一句：**这件事能不能帮我省时间、接单、涨粉，或者少踩一个坑？**

## 为什么这个题今天值得看

来自 {source} 的信息显示，AI 工具和应用还在快速更新。

原始摘要是：

{summary[:500]}

这类内容以前更像工程师看的新闻，但现在已经开始影响普通人的工作方式。谁能把复杂工具拆成简单动作，谁就更容易吃到第一波红利。

## 普通人可以怎么用

{use_case_text}

**真正有效的 AI 用法，不是“让 AI 替你发财”，而是让 AI 替你省掉重复劳动。**

## 哪些坑不要踩

第一，不要看到“赚钱”“自动化”“爆款”就立刻付费。

第二，不要把 AI 生成的内容原封不动发出去。公众号、短视频、电商文案都需要你加上真实经验，否则很容易像模板。

第三，不要同时追十几个工具。工具越多，越容易忙了一天，什么结果都没有。

## 布丁说

我的建议很简单：**先找一个你每天都会重复做的动作，再让 AI 介入。**

比如写标题、整理资料、改文案、生成脚本、做客户回复。

{action}

我后面会继续整理适合普通人的 AI 工具清单和副业避坑表。你不用追所有热点，跟着能落地的看就够了。

## 参考来源

- {source}: {url}

---

运营备注：总分 {score['total_score']}｜流量 {score['traffic_score']}｜收益 {score['money_score']}｜风险 {score['risk_score']}｜理由：{reasons}
"""


def save_article(content: str, topic: str, article_type: str = "daily") -> str:
    """保存生成的文章到 output 目录"""
    today = datetime.now().strftime("%Y%m%d")
    safe_topic = "".join(c for c in topic if c.isalnum() or c in " _-")[:30]
    filename = f"{today}_{article_type}_{safe_topic}.md"
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info(f"💾 文章已保存: {path}")
    return str(path)
