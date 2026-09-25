# -*- coding: utf-8 -*-
"""
Dify 知识库自动同步脚本（配合爬虫每周一自动运行）
====================================================
策略：对账式同步
  1. 列出 Dify 知识库中的现有文档
  2. 与本地 agent\\github-trending\\*.md 比对文件名
  3. 新增的 -> 上传（create-by-file）
     同名已存在 -> 删除旧文档后重新上传（保证内容是本周最新）
     本地已没有的（上周在榜、本周跌出的项目）-> 从知识库删除
  4. 结果写入同一份 run.log

使用前提：
  - 在 Dify 右上角头像 -> 设置 -> API 密钥 创建 Space API Key（dataset- 开头）
  - 知识库 ID：打开知识库页面，浏览器地址栏 /datasets/<这串> 即为 ID
  - 把上面两项填入同目录 config_dify_kb.json

单独运行：python dify_kb_sync.py
"""
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config_dify_kb.json")
RETRY = 3
TIMEOUT = 60


def log(msg: str) -> None:
    print(f"[kb-sync] {msg}")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        log(f"ERROR: 未找到配置文件 {CONFIG_PATH}")
        log("请先复制 config_dify_kb.json 模板并填入 dataset_api_key / dataset_id")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    need = {"base_url", "dataset_api_key", "dataset_id", "docs_dir"}
    missing = need - set(cfg)
    if missing:
        log(f"ERROR: 配置缺少字段 {missing}")
        sys.exit(1)
    if "请填入" in cfg["dataset_api_key"] or "请填入" in cfg["dataset_id"]:
        log("ERROR: 配置里还是占位符，请先填入真实的 API Key 和知识库 ID")
        sys.exit(1)
    return cfg


def api(cfg: dict, method: str, path: str, **kw) -> requests.Response | None:
    url = f"{cfg['base_url'].rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {cfg['dataset_api_key']}"}
    for attempt in range(1, RETRY + 1):
        try:
            r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
            if r.status_code in (200, 201, 204):
                return r
            log(f"HTTP {r.status_code} {method} {path}: {r.text[:200]} (第{attempt}次)")
        except Exception as exc:  # noqa: BLE001
            log(f"请求异常 {type(exc).__name__}: {exc} (第{attempt}次)")
        time.sleep(2 * attempt)
    return None


def list_remote_docs(cfg: dict) -> dict[str, str]:
    """返回 {文档名: document_id}，自动翻页。"""
    docs: dict[str, str] = {}
    page = 1
    while True:
        r = api(cfg, "GET", f"/datasets/{cfg['dataset_id']}/documents",
                params={"page": page, "limit": 100})
        if r is None:
            break
        data = r.json().get("data", [])
        for d in data:
            docs[d.get("name", "")] = d["id"]
        if not r.json().get("has_more"):
            break
        page += 1
    return docs


def upload_doc(cfg: dict, path: str) -> bool:
    fname = os.path.basename(path)
    body = {
        "indexing_technique": "high_quality",
        "process_rule": {"mode": "automatic"},
        "doc_form": "text_model",
    }
    with open(path, "rb") as fh:
        r = api(cfg, "POST", f"/datasets/{cfg['dataset_id']}/document/create-by-file",
                data={"data": json.dumps(body)},
                files={"file": (fname, fh, "text/markdown")})
    return r is not None


def delete_docs(cfg: dict, ids: list[str]) -> bool:
    """Dify 删除文档接口为单文档 DELETE /datasets/{id}/documents/{doc_id}，逐个删。"""
    all_ok = True
    for doc_id in ids:
        r = api(cfg, "DELETE", f"/datasets/{cfg['dataset_id']}/documents/{doc_id}")
        if r is None:
            log(f"  删除失败 document_id={doc_id}")
            all_ok = False
        else:
            log(f"  已删除 document_id={doc_id}")
        time.sleep(0.3)
    return all_ok


def main() -> int:
    cfg = load_config()
    docs_dir = cfg["docs_dir"]
    if not os.path.isdir(docs_dir):
        log(f"ERROR: 文档目录不存在 {docs_dir}")
        return 1

    local = {f"{os.path.splitext(n)[0]}.md": os.path.join(docs_dir, n)
             for n in os.listdir(docs_dir) if n.endswith(".md")}
    log(f"本地文档 {len(local)} 篇，开始对账…")

    remote = list_remote_docs(cfg)
    log(f"知识库现有文档 {len(remote)} 篇")

    # 1) 先删：同名旧文档（将重传） + 本地已消失的过时文档
    stale_ids = [remote[n] for n in remote if n in local]
    gone_ids = [remote[n] for n in remote if n not in local]
    if stale_ids or gone_ids:
        log(f"删除 {len(stale_ids)} 篇同名旧文档、{len(gone_ids)} 篇过时文档")
        if not delete_docs(cfg, stale_ids + gone_ids):
            log("ERROR: 删除失败，中止本轮同步（避免重复入库）")
            return 2
        time.sleep(1)

    # 2. 再传：本地全部（含刷新）
    ok = fail = 0
    for name, path in sorted(local.items()):
        if upload_doc(cfg, path):
            log(f"  上传成功 {name}")
            ok += 1
        else:
            log(f"  上传失败 {name}")
            fail += 1
        time.sleep(0.5)

    log(f"同步完成：成功 {ok}，失败 {fail}，清理过时 {len(gone_ids)}")
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
