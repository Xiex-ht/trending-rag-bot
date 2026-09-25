# -*- coding: utf-8 -*-
"""
RAG 评测脚本：批量跑评测集，输出命中率基线
================================================
用法：
  1. 在 Dify 应用「访问API」创建 app- 密钥，填入下方 APP_KEY
  2. python eval_run.py                # 跑全部题目，生成 评测结果_日期.csv
  3. 打开结果 CSV，人工在"判定"列标 对/错（或用 --judge 自动关键词初判）

自动初判逻辑（--judge）：把标准答案拆成关键词，回答命中 >=60% 记为疑似正确，
最终仍需人工抽检——这就是简历里"LLM辅助判卷 + 人工复核"的雏形。
"""
import argparse
import csv
import os
import re
import sys
import time

import requests

BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost/v1")   # 本机 Dify
APP_KEY = os.environ.get("DIFY_APP_KEY", "app-通过环境变量 DIFY_APP_KEY 传入")
HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_CSV = os.path.join(HERE, "评测集.csv")
TIMEOUT = 120


def ask(session: requests.Session, q: str) -> str:
    r = session.post(
        f"{BASE_URL}/chat-messages",
        json={"inputs": {}, "query": q, "response_mode": "blocking", "user": "eval-bot"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return (r.json().get("answer") or "").strip()


def keyword_hit(expected: str, answer: str) -> float:
    """标准答案按标点切词，计算回答命中的比例。"""
    tokens = [t for t in re.split(r"[，。、；;,\s（）()]+", expected) if len(t) >= 2]
    if not tokens:
        return 0.0
    hit = sum(1 for t in tokens if t.lower() in answer.lower())
    return hit / len(tokens)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true", help="自动关键词初判")
    args = ap.parse_args()

    if "请填入" in APP_KEY:
        print("请先在脚本顶部填入 APP_KEY（app- 开头，来自 Dify 应用->访问API）")
        return 1

    with open(QUESTIONS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"载入 {len(rows)} 题，开始评测…")

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {APP_KEY}"})

    out_path = os.path.join(HERE, f"评测结果_{time.strftime('%Y%m%d-%H%M')}.csv")
    results = []
    for i, row in enumerate(rows, 1):
        q, expected = row["问题"], row["标准答案"]
        try:
            ans = ask(session, q)
        except Exception as exc:  # noqa: BLE001
            ans = f"[请求失败] {exc}"
        score = keyword_hit(expected, ans) if args.judge else ""
        verdict = ("疑似正确" if score and score >= 0.6 else "疑似错误") if score != "" else ""
        results.append({**row, "模型回答": ans,
                        "关键词命中率": f"{score:.0%}" if score != "" else "",
                        "判定": verdict, "人工复核": ""})
        flag = f" [{verdict}]" if verdict else ""
        print(f"  {i:02d}/{len(rows)} {q[:28]}…{flag}")
        time.sleep(1)

    fields = list(results[0].keys())
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)

    if args.judge:
        ok = sum(1 for r in results if r["判定"] == "疑似正确")
        print(f"\n自动初判：疑似正确 {ok}/{len(results)}（{ok/len(results):.0%}）")
        print("请打开结果 CSV 人工复核『判定』列后，把最终数字记为基线。")
    print(f"结果已写入：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
