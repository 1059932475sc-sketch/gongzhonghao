"""
生成 1000 字左右的合规公众号文字草稿。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import ARTICLE_TARGET_CHARS, OUTPUT_DIR, STYLE_RULES


def make_safe_title(topic: str) -> str:
    cleaned = re.sub(r"[#【】\[\]！!？?]", "", topic).strip()
    cleaned = cleaned.replace("逆袭上岸", "上岸").replace("逆袭", "上岸")
    if "毕业生" in cleaned or "三清" in cleaned or "招聘" in cleaned:
        return "大厂重金抢人背后，普通人的机会变了"
    if "考研" in cleaned or "北大" in cleaned or "上岸" in cleaned:
        return "专科生上岸北大，真正值得普通人看的不是励志"
    if "白开水" in cleaned or "48元" in cleaned or "餐厅" in cleaned:
        return "一杯白开水卖48元，为什么大家都不只是嫌贵"
    if "瘦腿" in cleaned or "膝关节" in cleaned or "爬楼梯" in cleaned:
        return "为了变瘦去爬楼梯，很多人忽略了这个代价"
    if "向日葵" in cleaned or "楼顶" in cleaned or "校园" in cleaned:
        return "学校楼顶种满向日葵，为什么很多人看完会羡慕"
    if "安全带" in cleaned or "节目组" in cleaned:
        return "安全带都能P图，观众为什么越来越较真"
    if "黑黄金" in cleaned or "10吨卡车" in cleaned:
        return "一根材料拉动10吨车，普通人该关心吗"
    if "消费" in cleaned or "价格" in cleaned:
        return "这届消费者不爱忍了，背后是一个新变化"
    if len(cleaned) > 16:
        cleaned = cleaned[:16]
    return f"{cleaned}背后，普通人该看懂什么"


def generate_article(selection: dict, index: int) -> tuple[str, str]:
    item = selection["item"]
    title = make_safe_title(item["title"])
    source = item.get("source", "公开热榜")
    summary = "这个话题今天出现在公开热榜上，引发不少普通网友讨论。"

    article = f"""# {title}

## 先说结论

今天这个话题能上热榜，不是因为它本身多复杂，而是它戳中了很多人的共同感受。

对普通人来说，热点最有价值的地方，不是跟着吵，而是看清楚：生活里哪些规则变了，哪些机会变少了，哪些坑以后要提前避开。

这篇只做生活观察，不扩散未经证实的信息，也不审判任何具体个人。

## 这件事为什么会被关注

今天的热点是：{item['title']}。

来自{source}的信息摘要是：{summary[:180]}。

它能被大家讨论，通常是因为踩中了一个很普通的感受：很多人都在意生活成本、工作压力、消费体验、平台规则、家庭关系，或者城市里的日常便利。

换句话说，热点表面是新闻，背后往往是普通人的真实情绪。

## 普通人可以从中看到什么

第一，看消费变化。

如果一个话题和价格、服务、排队、体验有关，它提醒我们的不是“谁对谁错”，而是以后做选择时要多看规则、评价和售后。普通人最怕的不是花钱，而是花了钱还不省心。

第二，看平台规则。

现在很多生活都和平台有关：外卖、打车、旅游、购物、短视频、招聘。一个热点能火，往往说明某条规则影响了很多人。下次遇到类似情况，先保存证据、看清条款，再沟通处理。

第三，看情绪出口。

有些话题本质上是在说压力。大家表面讨论一件小事，背后可能是上班累、收入焦虑、家庭沟通难、时间不够用。看懂这一层，就不会轻易被标题带着跑。

## 这类热点不要怎么写

不要用夸张、刺激、诱导站队的标题。

不要把个案写成定论。

不要引导对立，也不要把评论区里的情绪当事实。

公众号最怕的不是文章不够热，而是为了追热度，把账号带进风险里。

## 更稳的看法

我更建议把这类热点当成一个提醒：以后遇到类似场景，普通人要学会多留一步。

消费前，多看规则。

沟通时，保留记录。

遇到争议，先核实来源。

看到情绪很重的内容，先慢半拍，不急着转发。

## 布丁说

社会热点每天都有，但真正能长期做的公众号，不应该靠刺激情绪活着。

更稳的方式，是把热点翻译成普通人能用的生活经验：怎么少踩坑，怎么做判断，怎么保护自己的时间、钱和注意力。

今天这件事，最值得记住的不是热闹本身，而是它提醒我们：普通人的生活细节，正在变成越来越重要的信息差。
"""
    return title, article


def save_article(title: str, content: str, index: int) -> str:
    today = datetime.now().strftime("%Y%m%d")
    safe = re.sub(r"[^\w\u4e00-\u9fff-]", "", title)[:24]
    path = OUTPUT_DIR / f"{today}_{index:02d}_{safe}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
