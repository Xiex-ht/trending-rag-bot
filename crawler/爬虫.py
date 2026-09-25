# -*- coding: utf-8 -*-
"""
GitHub 周榜热门项目爬虫
====================================
功能：
  1. 抓取 GitHub Trending 本周最热门的前 10 个项目
  2. 解析项目基本信息（名称、链接、语言、Star 总数、本周新增 Star、官方简介、Topics）
  3. 顺带抓取每个仓库 README 的摘要（前 N 字，清洗掉图片/徽章/代码块）
  4. 每个项目输出一个 Markdown 文件 + 一份榜单汇总，UTF-8 编码，
     可直接导入 Dify 知识库使用

输出目录：桌面 agent/github-trending/
用法：
  python 爬虫.py                 # 默认：本周 Top10
  python 爬虫.py --daily        # 改为今日榜
  python 爬虫.py --top 20       # 改数量
  python 爬虫.py --readme-chars 800   # 调整 README 摘要长度
  python 爬虫.py --proxy http://127.0.0.1:7890  # 需要代理时再启用
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ------------------------- 配置区 -------------------------
TRENDING_URL = "https://github.com/trending"
RAW_URL = "https://raw.githubusercontent.com"  # README 原文通道
DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Desktop", "agent", "github-trending")
DEFAULT_TOP_N = 10
DEFAULT_README_CHARS = 500
REQUEST_TIMEOUT = 30
RETRY = 3
DELAY_BETWEEN = 1.0  # 每次请求间隔，友好一点

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# --------------------------------------------------------


def make_session(proxy: str = "") -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
        print(f"[i] 已启用代理：{proxy}")
    return s


def fetch(session: requests.Session, url: str, *, mode: str = "text") -> str | None:
    """带重试的 GET。mode: text | json | bytes"""
    for attempt in range(1, RETRY + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                if mode == "json":
                    return r.json()
                r.encoding = "utf-8"
                return r.text
            print(f"[!] HTTP {r.status_code} {url} (第 {attempt} 次)")
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 请求异常 {type(exc).__name__}: {exc} (第 {attempt} 次)")
        time.sleep(1.5 * attempt)
    return None


def clean_readme(raw: str, limit: int) -> str:
    """把 README 压成一段干净的中文可读摘要。"""
    if not raw:
        return ""
    text = raw
    # 去 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)
    # 去图片、徽章
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", lambda m: m.group(0).split("[")[-1].rstrip("]"), text)
    # 去代码块与行内代码
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    # 去标题井号、引用、列表符号、水平线
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-=*_]{3,}\s*$", "", text, flags=re.M)
    # 合并空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    # 掐头：跳过纯 badge / 免责声明行，找第一段有效文字
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        if len(para) >= 60 and not para.lower().startswith(("license", "build status")):
            text = para
            break
    if len(text) > limit:
        text = text[:limit].rstrip() + "……（完整内容见仓库 README）"
    return text


def fetch_readme(session: requests.Session, full_name: str, default_branch: str) -> tuple[str, str]:
    """返回 (摘要, 实际来源分支)。README 文件名与分支都可能有多种组合。"""
    names = ["README.md", "readme.md", "README.rst", "README", "README.MD", "readme.MD", "docs/README.md"]
    branches = [default_branch, "main", "master"] if default_branch else ["main", "master"]
    for br in branches:
        for nm in names:
            url = f"{RAW_URL}/{full_name}/{br}/{nm}"
            raw = fetch(session, url, mode="text")
            if raw:
                return clean_readme(raw, args_readme_chars), br
            time.sleep(0.3)
    return "", ""


def parse_trending(html: str, top_n: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for art in soup.select("article.Box-row")[:top_n]:
        # 仓库全名 owner/repo
        a = art.select_one("h2 a")
        if not a:
            continue
        href = (a.get("href") or "").strip("/")
        parts = href.split("/")
        if len(parts) != 2:
            continue
        owner, repo = parts
        full_name = f"{owner}/{repo}"

        # 官方简介
        desc_tag = art.select_one("p")
        desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""

        # 语言
        lang_tag = art.select_one("[itemprop='programmingLanguage']")
        language = lang_tag.get_text(strip=True) if lang_tag else "未标注"

        # Star / Fork 总数
        star_tag = art.select_one("a[href$='/stargazers']")
        stars = star_tag.get_text(strip=True).replace(",", "") if star_tag else "N/A"
        fork_tag = art.select_one("a[href$='/forks']")
        forks = fork_tag.get_text(strip=True).replace(",", "") if fork_tag else "N/A"

        # 本周（今日）新增 star
        today_tag = art.select_one("span.d-inline-block.float-sm-right")
        this_week = today_tag.get_text(" ", strip=True) if today_tag else "N/A"

        # Topics（趋势页没有，从仓库主页补，失败则留空）
        items.append(
            {
                "rank": len(items) + 1,
                "full_name": full_name,
                "owner": owner,
                "repo": repo,
                "url": f"https://github.com/{full_name}",
                "description": desc or "（该项目未填写简介）",
                "language": language,
                "stars": stars,
                "forks": forks,
                "this_week": this_week,
                "topics": [],
                "default_branch": "HEAD",
                "readme": "",
            }
        )
    return items


def enrich_from_api(session: requests.Session, item: dict) -> None:
    """用 GitHub REST 元数据补 topics 与默认分支（比抓 HTML 稳）。"""
    meta = fetch(session, f"https://api.github.com/repos/{item['full_name']}", mode="json")
    if isinstance(meta, dict):
        item["topics"] = meta.get("topics") or []
        item["default_branch"] = meta.get("default_branch") or "HEAD"
        if not item["description"]:
            item["description"] = meta.get("description") or "（该项目未填写简介）"
    time.sleep(0.5)


def to_markdown(item: dict, period: str) -> str:
    topics = "、".join(f"`{t}`" for t in item["topics"][:12]) if item["topics"] else "（无）"
    readme = item["readme"] or "（未能获取 README，建议访问仓库主页查看）"
    rank_sentence = (
        f"**排名信息**：{item['full_name']} 在{period} GitHub 热门项目榜（Trending）中排名第 "
        f"{item['rank']} 名；本周榜单第 {item['rank']} 名即该仓库，其 Star 总数为 {item['stars']}。"
    )
    return f"""# {item['full_name']}

> GitHub {period}热门项目榜 · 第 {item['rank']} 名
> 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{rank_sentence}

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 仓库名称 | {item['repo']} |
| 所有者 | {item['owner']} |
| 仓库地址 | {item['url']} |
| 主要语言 | {item['language']} |
| Star 总数 | {item['stars']} |
| Fork 总数 | {item['forks']} |
| {period}新增 Star | {item['this_week']} |
| 主题标签 | {topics} |

## 项目简介

{item['description']}

## README 摘要

{readme}
"""


def build_summary(items: list[dict], period: str) -> str:
    rows = "\n".join(
        f"| {it['rank']} | [{it['full_name']}]({it['url']}) | {it['language']} | "
        f"{it['stars']} | {it['this_week']} | {it['description'][:50]} |"
        for it in items
    )
    # 自然语言排名速查：把表格行转成完整语义句（修复表格切块边界召不回问题）
    rank_lines = "\n".join(
        f"- {period} GitHub 热门项目榜第 {it['rank']} 名是 **{it['full_name']}**"
        f"（{it['language']}，Star 总数 {it['stars']}，{period}新增 {it['this_week']}）。"
        for it in items
    )
    top_new = max(items, key=lambda x: int(str(x["this_week"]).split()[0].replace(",", "") or 0))
    top_star = max(items, key=lambda x: int(str(x["stars"]).replace(",", "") or 0))
    return f"""# GitHub {period}热门项目 Top {len(items)} 榜单汇总

> 数据来源：GitHub Trending（https://github.com/trending?since={SINCE}）
> 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

本文件为榜单总览，各项目详情见同目录下对应的独立 Markdown 文件。

## 排名速查（自然语言版）

{rank_lines}

- 本周新增 Star 最多的项目是 **{top_new['full_name']}**（{top_new['this_week']}）。
- 榜单中 Star 总数最多的项目是 **{top_star['full_name']}**（Star 总数 {top_star['stars']}）。

## 榜单明细表

| 排名 | 项目 | 语言 | Star 总数 | {period}新增 | 简介 |
| --- | --- | --- | --- | --- | --- |
{rows}

## 榜单特征小结

- **语言分布**：{_lang_dist(items)}
- **平均 Star**：约 {int(_avg_stars(items) or 0):,}
- 完整详情请查阅目录内 01~{len(items):02d} 各独立文件。
"""


def _lang_dist(items: list[dict]) -> str:
    count: dict[str, int] = {}
    for it in items:
        count[it["language"]] = count.get(it["language"], 0) + 1
    return "、".join(f"{k} {v} 个" for k, v in sorted(count.items(), key=lambda x: -x[1]))


def _avg_stars(items: list[dict]) -> float | None:
    nums = [int(it["stars"]) for it in items if str(it["stars"]).isdigit()]
    return sum(nums) / len(nums) if nums else None


def sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def main() -> int:
    global args_readme_chars, SINCE
    ap = argparse.ArgumentParser(description="GitHub Trending 周榜爬虫")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="抓取项目数量，默认 10")
    ap.add_argument("--daily", action="store_true", help="抓今日榜（默认本周）")
    ap.add_argument("--readme-chars", type=int, default=DEFAULT_README_CHARS, help="README 摘要字数")
    ap.add_argument("--out", default=DEFAULT_OUTPUT, help="输出目录")
    ap.add_argument("--proxy", default="", help="HTTP 代理，如 http://127.0.0.1:7890")
    a = ap.parse_args()

    args_readme_chars = a.readme_chars
    SINCE = "daily" if a.daily else "weekly"
    period = "今日" if a.daily else "本周"

    out_dir = a.out
    os.makedirs(out_dir, exist_ok=True)
    session = make_session(a.proxy)

    print(f"[1/4] 抓取 GitHub Trending（{period}榜，取前 {a.top}）…")
    html = fetch(session, f"{TRENDING_URL}?since={SINCE}&spoken_language_code=")
    if not html:
        print("[x] 趋势页抓取失败：网络不可达或被限流。可尝试 --proxy 指定代理后重跑。")
        return 1

    items = parse_trending(html, a.top)
    if not items:
        print("[x] 页面结构可能已变更，未能解析出任何项目（选择器 article.Box-row 失效）。")
        return 2
    print(f"    解析到 {len(items)} 个项目")

    print("[2/4] 补充 topics / 默认分支元数据…")
    for it in items:
        enrich_from_api(session, it)

    print("[3/4] 抓取各仓库 README 摘要…")
    for it in items:
        it["readme"], used_br = fetch_readme(session, it["full_name"], it["default_branch"])
        state = "OK" if it["readme"] else "缺失"
        print(f"    {it['rank']:>2}. {it['full_name']:<38} README {state} {f'({used_br})' if used_br else ''}")
        time.sleep(DELAY_BETWEEN)

    print(f"[4/4] 写入文件 -> {out_dir}")
    written = []
    for it in items:
        fname = f"{it['rank']:02d}-{sanitize(it['repo'])}.md"
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(to_markdown(it, period))
        written.append(fname)
    summary_path = os.path.join(out_dir, "00-榜单汇总.md")
    with open(summary_path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(build_summary(items, period))

    print(f"\n[完成] 共 {len(written)} 个项目文件 + 1 个汇总文件")
    for f in written:
        print(f"  - {f}")
    print("  - 00-榜单汇总.md")
    print(f"\n下一步：把该目录下的 .md 文件上传到 Dify 知识库（分段方式建议选「按 Markdown 标题分段」）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
