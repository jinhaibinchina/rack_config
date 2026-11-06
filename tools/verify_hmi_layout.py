"""PopPick HMI 7 页版式回归：750×1000 固定画布下必须 1:1 装得下、且不许叠控件。

    .venv/Scripts/python.exe tools/verify_hmi_layout.py
    .venv/Scripts/python.exe tools/verify_hmi_layout.py --shot build/hmi_layout

断言项（离屏，不连 PLC）：

1. 页面尺寸 = 750×1000，内容区（去掉 52px 页头）= 750×948；
2. ``ScrollBody`` 内容最小尺寸 ≤ 设计尺寸（**装得下**，不需要缩放/滚动）；
3. 视图 transform 恰好 1.0（0.995 之类会让整页发虚）；
4. 任何容器里**直接子控件两两不重叠**——这条是给 ``ElidedLabel`` 那类"长度
   不参与最小宽度"的控件兜底的：策略写错时布局会把同一行的控件全排到同一个
   x 上，肉眼只看到「速 64.000」，几何上就是两个控件叠在一起；
5. 页头的端点 / 统计标签宽度 > 0（曾经被 ``QSizePolicy.Ignored`` 压成 0 宽，
   页头上那两块信息直接消失）。

退出码 0 = 全过；1 = 有断言失败（失败项会逐条打印）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from App_PopPick.hmi.pages import make_page_specs  # noqa: E402
from App_PopPick.hmi.tag_catalog import TagCatalog  # noqa: E402
from App_PopPick.hmi.widgets import (  # noqa: E402
    BODY_SIZE, HEADER_HEIGHT, PAGE_SIZE, PageHeader,
)

_FONT_FILES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


def make_app() -> QApplication:
    app = QApplication([sys.argv[0]])
    if not QFontDatabase.families():
        for path in _FONT_FILES:
            if Path(path).is_file():
                QFontDatabase.addApplicationFont(path)
    return app


def _direct_children(widget: QWidget) -> list[QWidget]:
    return [c for c in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
            if c.isVisible()]


def find_overlaps(root: QWidget) -> list[str]:
    """返回所有「同一容器内直接子控件互相重叠」的描述。

    只看直接子控件：``QDoubleSpinBox`` 内部的 ``QLineEdit`` 之类本来就在父框里
    面，不属于叠版。
    """
    problems: list[str] = []
    containers = [root, *root.findChildren(QWidget)]
    for parent in containers:
        if parent.layout() is None:
            continue
        kids = _direct_children(parent)
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                a, b = kids[i], kids[j]
                hit = a.geometry().intersected(b.geometry())
                if hit.width() > 1 and hit.height() > 1:
                    problems.append(
                        f"{type(parent).__name__}({parent.objectName() or '-'}) 里 "
                        f"{type(a).__name__} {a.geometry().getRect()} 与 "
                        f"{type(b).__name__} {b.geometry().getRect()} 重叠 "
                        f"{hit.width()}x{hit.height()}"
                    )
    return problems


def check_header(page) -> list[str]:
    header = page.findChild(PageHeader)
    if header is None:
        return ["找不到 PageHeader"]
    problems = []
    if header.height() != HEADER_HEIGHT:
        problems.append(f"页头高度 {header.height()} != {HEADER_HEIGHT}")
    endpoint = header.findChild(QLabel, "hmiEndpoint")
    # 端点是 ElidedLabel("")，没有 objectName；按文本特征找：非标题/非时钟的标签
    candidates = [lab for lab in header.findChildren(QLabel)
                  if lab.objectName() not in ("hmiTitle", "hmiSubtitle", "hmiValue")]
    if not candidates:
        problems.append("页头找不到端点/统计标签")
        return problems
    widths = [lab.width() for lab in candidates]
    if not any(w > 0 for w in widths):
        problems.append(f"页头端点/统计标签宽度全为 0：{widths}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shot", help="可选：把每页截图写到这个目录")
    args = parser.parse_args()

    app = make_app()
    outdir = Path(args.shot) if args.shot else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    catalog = TagCatalog()
    failures: list[str] = []
    d = BODY_SIZE
    print(f"画布 {PAGE_SIZE.width()}x{PAGE_SIZE.height()}｜页头 {HEADER_HEIGHT}px｜"
          f"内容区 {d.width()}x{d.height()}")
    print(f"{'页面':<11}{'内容最小尺寸':>14}{'溢出':>14}{'缩放':>8}  结果")

    for spec in make_page_specs():
        page = spec.factory(catalog)
        page.resize(PAGE_SIZE)
        page.set_connection(False, "离线演示数据（未连接 PLC）")
        page.seed_demo()
        page.show()
        for _ in range(6):
            app.processEvents()

        need = page.body.content_minimum()
        over = page.body.overflow()
        scale = page.body.transform().m11()
        problems: list[str] = []

        if page.size() != PAGE_SIZE:
            problems.append(f"页面尺寸 {page.size().toTuple()} != {PAGE_SIZE.toTuple()}")
        if need.width() > d.width() + 0.5 or need.height() > d.height() + 0.5:
            problems.append(
                f"内容最小尺寸 {need.width():.0f}x{need.height():.0f} 超出 "
                f"{d.width()}x{d.height()}（溢出 {over.width():.0f}x{over.height():.0f}）"
            )
        if abs(scale - 1.0) > 1e-6:
            problems.append(f"视图缩放 {scale:.4f} != 1.0（整页会发虚）")
        if page.body.verticalScrollBar().isVisible():
            problems.append("内容区出现竖向滚动条")
        problems.extend(check_header(page))
        problems.extend(find_overlaps(page.body.content))

        if outdir:
            page.grab().save(str(outdir / f"{page.PAGE_ID}.png"))

        state = "OK" if not problems else f"FAIL ×{len(problems)}"
        print(f"{page.PAGE_ID:<11}{need.width():>7.0f}x{need.height():<6.0f}"
              f"{over.width():>7.0f}x{over.height():<6.0f}{scale:>8.3f}  {state}")
        for item in problems:
            failures.append(f"[{page.PAGE_ID}] {item}")
        page.shutdown()

    print()
    if failures:
        print(f"失败 {len(failures)} 项：")
        for line in failures:
            print("  -", line)
        return 1
    print("全部通过：7 页在 750×1000 下 1:1 装得下，无重叠、无滚动条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
