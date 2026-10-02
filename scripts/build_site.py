#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/build_site.py - 把看板构建为可独立部署的静态站点 (dist-site/)

设计要点：
  1. 单一数据源：直接读取 web/templates/dashboard.html 与 web/static/*，
     绝不复制粘贴源码，避免"两份前端"漂移。
  2. 无后端依赖：产出的站点显式启用 demo-data.js，不向 API 发送请求，
     可直接部署到 Cloudflare Pages 等静态托管。
  3. 幂等：只覆盖带构建标记的专属产物，绝不递归删除输出目录。
  4. 只用标准库；退出码 0 = 成功，非 0 = 失败。

用法：
    python scripts/build_site.py                 # 输出到默认 dist-site/
    python scripts/build_site.py --out custom/   # 自定义输出目录
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from typing import Dict, List
from pathlib import Path

logger = logging.getLogger("build_site")

# ─── 路径常量 ─────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
TEMPLATE_SRC = os.path.join(WEB_DIR, "templates", "dashboard.html")
STATIC_SRC = os.path.join(WEB_DIR, "static")

# 站点级静态文件（源 → 输出根目录相对路径）
SITE_FILES = {
    "_headers": os.path.join(WEB_DIR, "_headers"),
    "robots.txt": os.path.join(WEB_DIR, "robots.txt"),
    "404.html": os.path.join(WEB_DIR, "404.html"),
}

# 需要打包到 dist-site/static/ 的前端资源
STATIC_FILES = ["style.css", "app.js", "demo-data.js"]

DEFAULT_OUT = os.path.join(PROJECT_ROOT, "dist-site")
BUILD_MARKER = ".soulcompanion-build.json"
BUILD_KIND = "soulcompanion-static-demo-v1"

# 去除任何潜在 Jinja 模板语法的正则
_JINJA_VAR = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_JINJA_TAG = re.compile(r"\{%.*?%\}", re.DOTALL)


# ─── 基础 IO ──────────────────────────────────────────────────────────
def _read_text(path: str) -> str:
    """以 UTF-8 读取文本文件。"""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_text(path: str, text: str) -> None:
    """以 UTF-8 写入文本，统一换行符，自动创建父目录。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ─── 核心转换 ─────────────────────────────────────────────────────────
def transform_dashboard(html: str) -> str:
    """
    把 Jinja 模板型 dashboard.html 转换为纯静态 index.html。

    - 去除所有 ``{{ ... }}`` / ``{% ... %}``（当前模板本就没有，做防御性清理）；
    - 保留 ``/static/...`` 绝对路径（静态站同样以 /static/ 提供服务）。

    Raises:
        ValueError: 若清理后仍残留 Jinja 语法。
    """
    cleaned = _JINJA_VAR.sub("", html)
    cleaned = _JINJA_TAG.sub("", cleaned)
    if "{{" in cleaned or "{%" in cleaned:
        raise ValueError("index.html 清理后仍残留 Jinja 语法（{{ / {%）")
    # 仅处理仓库自有模板属性；这不是用于处理外部 HTML 的 sanitizer。
    def demo_body(match: re.Match) -> str:
        attributes = re.sub(r'\sdata-mode\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)',
                            '', match.group(1), flags=re.IGNORECASE)
        attributes = re.sub(r'\sdata-demo-only\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)',
                            '', attributes, flags=re.IGNORECASE)
        return f'<body{attributes} data-mode="demo" data-demo-only="true">'

    return re.sub(r'<body\b([^>]*)>', demo_body, cleaned, count=1, flags=re.IGNORECASE)


def _validate_output(out_dir: str, project_root: str) -> Path:
    """Require a dedicated output and prevent source/linked-path overwrites."""
    output = Path(os.path.abspath(out_dir))
    project = Path(project_root).resolve()
    for path in (output, *output.parents):
        if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
            raise ValueError("输出目录不能使用符号链接或 junction")
    output = output.resolve()
    if output == project or output in project.parents:
        raise ValueError("输出目录不能是项目根目录或其父目录")
    for source_name in ("web", "emotion", "modules", "hardware", "core", "reports",
                        "scripts", "tests", "docs", "utils", ".git", ".agents", ".codex"):
        source = project / source_name
        if output == source or source in output.parents:
            raise ValueError("输出目录不能位于源码或项目配置目录中")
    if output.exists() and not output.is_dir():
        raise ValueError("输出目录指向现有文件")
    marker = output / BUILD_MARKER
    if output.is_dir() and any(output.iterdir()):
        if not marker.is_file() or marker.is_symlink():
            raise ValueError("现有非空输出目录缺少专属构建标记，请选择新的空目录")
        try:
            metadata = json.loads(_read_text(str(marker)))
        except (ValueError, OSError) as exc:
            raise ValueError("输出目录的构建标记无效") from exc
        if not isinstance(metadata, dict) or metadata != {
            "kind": BUILD_KIND, "path": str(output),
        }:
            raise ValueError("输出目录的构建标记不匹配")
    # 已授权的构建目录内也不能沿着 asset symlink 覆盖其他位置。
    for name in ["static", "index.html", "_headers", "robots.txt", "404.html", BUILD_MARKER]:
        path = output / name
        if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
            raise ValueError("输出产物不能使用符号链接或 junction")
    for name in STATIC_FILES:
        if (output / "static" / name).is_symlink():
            raise ValueError("输出静态资源不能使用符号链接")
    return output


def build(out_dir: str = DEFAULT_OUT, project_root: str = PROJECT_ROOT) -> Dict:
    """
    执行一次完整构建。

    Args:
        out_dir: 新的空目录，或带本工具专属标记的构建目录。
        project_root: 项目根目录（便于测试注入）。

    Returns:
        dict: 包含 out_dir / index_path / static_files / site_files 的构建报告。

    Raises:
        FileNotFoundError: 必需的源文件缺失。
        ValueError: 产出校验失败。
    """
    web_dir = os.path.join(project_root, "web")
    template_src = os.path.join(web_dir, "templates", "dashboard.html")
    static_src = os.path.join(web_dir, "static")
    site_files = {
        "_headers": os.path.join(web_dir, "_headers"),
        "robots.txt": os.path.join(web_dir, "robots.txt"),
        "404.html": os.path.join(web_dir, "404.html"),
    }

    # ── 1. 校验源文件 ──
    required = [template_src] + [os.path.join(static_src, f) for f in STATIC_FILES]
    required += list(site_files.values())
    missing = [p for p in required if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError("缺少源文件:\n  - " + "\n  - ".join(missing))

    # ── 2. 验证输出边界。只写本工具产物，保留其余文件 ──
    out_dir = str(_validate_output(out_dir, project_root))
    index_html = transform_dashboard(_read_text(template_src))
    if 'data-mode="demo"' not in index_html:
        raise ValueError("构建失败：模板缺少可设置显式演示模式的 body")
    os.makedirs(out_dir, exist_ok=True)
    static_out = os.path.join(out_dir, "static")
    os.makedirs(static_out, exist_ok=True)

    # ── 3. index.html <- dashboard.html ──
    index_path = os.path.join(out_dir, "index.html")
    _write_text(index_path, index_html)
    logger.info("生成 index.html (%d 字节)", len(index_html.encode("utf-8")))

    # ── 4. 前端静态资源 ──
    written_static: List[str] = []
    for name in STATIC_FILES:
        shutil.copyfile(os.path.join(static_src, name), os.path.join(static_out, name))
        written_static.append(name)
        logger.info("复制 static/%s", name)

    # ── 5. 站点级文件（_headers / robots.txt / 404.html）──
    written_site: List[str] = []
    for out_name, src in site_files.items():
        shutil.copyfile(src, os.path.join(out_dir, out_name))
        written_site.append(out_name)
        logger.info("复制 %s", out_name)

    # ── 6. 产出校验 ──
    if not os.path.isfile(index_path):
        raise ValueError("构建失败：dist-site/index.html 不存在")
    produced = _read_text(index_path)
    if "{{" in produced or "{%" in produced:
        raise ValueError("构建失败：index.html 残留 Jinja 语法")
    _write_text(os.path.join(out_dir, BUILD_MARKER),
                json.dumps({"kind": BUILD_KIND, "path": out_dir}, ensure_ascii=False) + "\n")

    return {
        "out_dir": os.path.abspath(out_dir),
        "index_path": os.path.abspath(index_path),
        "index_bytes": os.path.getsize(index_path),
        "static_files": written_static,
        "site_files": written_site,
    }


def main(argv: List[str] | None = None) -> int:
    """命令行入口。返回进程退出码。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="构建 SoulCompanion 看板静态站点")
    parser.add_argument("--out", default=DEFAULT_OUT, help="输出目录 (默认: dist-site/)")
    parser.add_argument("--project-root", default=PROJECT_ROOT, help="项目根目录")
    args = parser.parse_args(argv)

    logger.info("开始构建静态站点 → %s", args.out)
    try:
        report = build(out_dir=args.out, project_root=args.project_root)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层需捕获并给出退出码
        logger.error("构建失败: %s", exc)
        return 1

    logger.info("=" * 56)
    logger.info("✅ 构建成功")
    logger.info("  输出目录 : %s", report["out_dir"])
    logger.info("  入口文件 : index.html (%d 字节)", report["index_bytes"])
    logger.info("  静态资源 : %s", ", ".join(report["static_files"]))
    logger.info("  站点文件 : %s", ", ".join(report["site_files"]))
    logger.info("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
