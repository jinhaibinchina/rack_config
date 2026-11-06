"""PopPick HMI 7 页的独立预览 / 截图 / 场景挂载自检。

不连 PLC、不进设计器，就能检查版式、点位解析和场景挂载：

    # 打开一个带 7 个页签的预览窗口（模拟数据）
    .venv/Scripts/python.exe tools/preview_hmi_pages.py

    # 连真实 PLC（端点取自 globalvars_tags.json，可用 --endpoint 覆盖）
    .venv/Scripts/python.exe tools/preview_hmi_pages.py --live

    # 离屏截图：每页一张 PNG，顺带导出点位报告 JSON
    .venv/Scripts/python.exe tools/preview_hmi_pages.py --shot out/hmi --report out/hmi/report.json

    # 场景挂载自检：加载 page_10.json，切 Run，把 7 页挂到卡片上（模拟数据）
    .venv/Scripts/python.exe tools/preview_hmi_pages.py --attach

``--attach`` 走真实的 ``QuadTreeScene`` / ``SceneSerializer`` /
``EmbeddedWidgetLayer``，能验证「控件工厂被承载层调用」这条链路；
它只读场景 JSON，不会启动 DesignWindow，因此不会回写 page_*.json。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 import PySide6 之前决定平台插件
if any(flag in sys.argv for flag in ("--shot", "--report", "--verify", "--attach", "--offscreen")):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget  # noqa: E402

from App_PopPick.hmi.binding import PAGE_PIXEL_SIZE, HmiClient  # noqa: E402
from App_PopPick.hmi.pages import make_page_specs  # noqa: E402
from App_PopPick.hmi.tag_catalog import TagCatalog  # noqa: E402

#: Windows 的 offscreen 平台不加载系统字体（QFontDatabase.families() 为空），
#: 中文全是方块。预览/截图时手动挂几份常见字体，让截图能反映真机效果。
_FONT_FILES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def make_app() -> QApplication:
    app = QApplication([sys.argv[0]])
    if QFontDatabase.families():
        return app
    for path in _FONT_FILES:
        if Path(path).is_file():
            QFontDatabase.addApplicationFont(path)
    return app


def build_report(catalog: TagCatalog, pages) -> dict:
    per_page = []
    all_keys = set()
    all_pending = set()
    for page in pages:
        all_keys.update(page.keys())
        all_pending.update(page.pending_report())
        per_page.append({
            "page_id": page.PAGE_ID,
            "title": page.TITLE,
            "display_points": len(page.refs),
            "subscribed_keys": len(page.keys()),
            "pending": page.pending_report(),
        })
    return {
        "catalog": catalog.stats(),
        "pages": per_page,
        "subscribed_keys_total": len(all_keys),
        "pending_points": sorted(all_pending),
        "pending_count": len(all_pending),
    }


def make_pages(catalog: TagCatalog) -> list:
    return [spec.factory(catalog) for spec in make_page_specs()]


def run_window(args) -> int:
    app = make_app()
    catalog = TagCatalog()
    pages = make_pages(catalog)
    window = QMainWindow()
    window.setWindowTitle("PopPick HMI 页面预览（模拟数据）" if not args.live
                          else f"PopPick HMI 页面预览（{catalog.endpoint}）")
    window.resize(1440, 940)
    tabs = QTabWidget()
    for page in pages:
        tabs.addTab(page, page.TITLE)
    window.setCentralWidget(tabs)

    client = None
    if args.live:
        client = HmiClient(catalog, endpoint=args.endpoint,
                           user=args.user, password=args.password)
        keys = sorted({k for page in pages for k in page.keys()})
        client.tag_changed.connect(
            lambda key, value: [page.on_tag(key, value) for page in pages if key in page._sinks]
        )
        client.connection_changed.connect(
            lambda ok: [page.set_connection(ok, client.endpoint) for page in pages]
        )
        client.message.connect(
            lambda text, level: [page.on_client_message(text, level) for page in pages]
        )
        for page in pages:
            page.write_requested.connect(client.write)
        client.start(keys)
    else:
        for page in pages:
            page.set_connection(False, "离线演示数据（未连接 PLC）")
            page.seed_demo()

    # 预览窗口没有 HmiPagesHost 统一驱动时钟，这里给每页各起一条（预览不追求
    # 帧率，7 页各 1s 也无所谓；主程序里绝不能这么干，见 profile_hmi.py）
    for page in pages:
        page.header.start_clock()

    print(f"页面 {len(pages)} 个，订阅点 {len({k for p in pages for k in p.keys()})} 个")
    window.show()
    code = app.exec()
    if client is not None:
        client.stop()
    for page in pages:
        page.shutdown()
    return code


def run_shots(args) -> int:
    app = make_app()
    catalog = TagCatalog()
    pages = make_pages(catalog)
    outdir = Path(args.shot) if args.shot else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        page.resize(args.width, args.height)
        page.set_connection(False, "离线演示数据（未连接 PLC）")
        page.seed_demo()
        # 预览窗口单独跑，页头时钟要自己驱动（主程序里由 HmiPagesHost 统一给
        # 槽位页一条定时器，避免 7 页各自每秒重画一次）
        page.header.start_clock()
        page.show()
        app.processEvents()
        if args.measure:
            view = page.body.viewport()
            need = page.body.content.minimumSizeHint()
            scale = page.body.transform().m11()
            corner = page.body.mapFromScene(page.body.sceneRect().bottomRight())
            lay = page.body.vbox.minimumSize()
            print(
                f"{page.PAGE_ID:<11} viewport={view.width()}x{view.height()} "
                f"design={page.body._design.width():.0f}x{page.body._design.height():.0f} "
                f"layout_min={lay.width()}x{lay.height()} "
                f"scale={scale:.3f} 右下角视口坐标=({corner.x():.0f},{corner.y():.0f}) "
                f"竖滚动条={page.body.verticalScrollBar().isVisible()}"
            )
        if outdir:
            path = outdir / f"{page.PAGE_ID}.png"
            page.grab().save(str(path))
            print(f"截图: {path}")
    report = build_report(catalog, pages)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告: {path}")
    print(json.dumps({
        "pages": len(pages),
        "subscribed_keys": report["subscribed_keys_total"],
        "pending_points": report["pending_count"],
    }, ensure_ascii=False))
    for page in pages:
        page.shutdown()
    return 0


def run_attach(args) -> int:
    """真实场景挂载自检：只加载 JSON，不启动设计器。"""
    from Designer.Core.my_common import SceneMode  # noqa: E402
    from Designer.Core.myQuadTreeScene import (  # noqa: E402
        QuadTreeScene, SceneManager, SceneSerializer,
    )
    from App_PopPick.hmi import attach_hmi_pages  # noqa: E402
    from App_PopPick.page_deck import PageDeck, find_page_cards  # noqa: E402

    app = make_app()
    scene_path = Path(args.scene)
    if not scene_path.is_absolute():
        scene_path = ROOT / scene_path
    if not scene_path.is_file():
        raise SystemExit(f"场景文件不存在: {scene_path}")

    window = QMainWindow()
    window.resize(1280, 820)
    scene = QuadTreeScene(parent=window)
    manager = SceneManager(scene, parent=window)
    scene.set_scene_manager(manager)
    scene.update_callback = None
    window.setCentralWidget(scene)
    scene.delete_all_elements()
    SceneSerializer.deserialize_scene(scene, str(scene_path), mode=SceneMode.Design)
    scene.set_scene_mode(SceneMode.Run)
    window.show()
    app.processEvents()

    cards = find_page_cards(manager.m_sorted_items)
    print(f"场景: {scene_path.name}｜widget 卡片 {len(cards)} 张: "
          f"{', '.join(c.get_name() for c in cards)}")
    deck = PageDeck(scene, cards, parent=window)
    print(f"PageDeck 槽位: {deck.slot_card().get_name()}｜堆叠 {len(deck.stack_cards())} 张")

    page_size = PAGE_PIXEL_SIZE
    if args.page_size:
        width, _, height = args.page_size.lower().partition("x")
        page_size = (int(width), int(height))
    host = attach_hmi_pages(manager, parent=window, demo=True, page_size=page_size)
    # 和真实窗口一致：只把最前面两页设为活跃，report 才反映现场刷新范围
    host.set_active_cards((deck.slot_card().get_name(),
                           deck.stack_cards()[0].get_name()))
    scene.refresh_embedded_widgets()
    app.processEvents()
    print(host.report())
    created = {pid: len(pl) for pid, pl in host._pages.items()}
    print("承载层实际创建的页面实例:", created)
    print(f"已挂载: {sum(1 for v in created.values() if v)}/{len(make_page_specs())} 页")

    # 卡片尺寸自检：挂载后每张卡的"控件像素尺寸"都该等于目标尺寸，
    # 说明 fit_widget_size 的换算和承载层几何是同一口径（AGV 90° 不含糊）。
    target = host.page_pixel_size
    size_bad = []
    for card in cards:
        px = card.widget_pixel_size()
        scene_size = card.getSize()
        print(f"  {card.get_name():<6} 场景 {scene_size.width():.0f}×{scene_size.height():.0f}"
              f"  控件 {px.width():.0f}×{px.height():.0f}"
              f"  中心 ({card.get_scene_center_pos().x():.0f},"
              f"{card.get_scene_center_pos().y():.0f}) @ {card.get_angle():.1f}°")
        if target is not None and (abs(px.width() - target.width()) > 1.0
                                   or abs(px.height() - target.height()) > 1.0):
            size_bad.append(card.get_name())
    if size_bad:
        print(f"卡片尺寸未对齐目标 {target.width()}×{target.height()}: {size_bad}")
    ok = not host._missing and all(created.values()) and not size_bad
    host.shutdown()
    if not args.keep_open:
        return 0 if ok else 1
    return app.exec()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="连真实 PLC（默认离线模拟）")
    ap.add_argument("--endpoint", default="", help="覆盖 JSON 里的 OPC UA 端点")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--shot", metavar="DIR", help="离屏把每页存成 PNG 后退出")
    ap.add_argument("--width", type=int, default=1400, help="截图宽度（默认 1400）")
    ap.add_argument("--height", type=int, default=900, help="截图高度（默认 900）")
    ap.add_argument("--report", metavar="FILE", help="导出点位报告 JSON")
    ap.add_argument("--verify", action="store_true", help="只做解析自检，不截图不开窗")
    ap.add_argument("--measure", action="store_true",
                    help="按 --width/--height 量各页内容是否超出视口（不做截图也能用）")
    ap.add_argument("--offscreen", action="store_true", help="强制 offscreen 平台")
    ap.add_argument("--attach", action="store_true", help="场景挂载自检")
    ap.add_argument("--scene", default="Designer/Core/data.json/datas/design/pages/page_10.json")
    ap.add_argument("--page-size", default="",
                    help="--attach 时卡片目标像素尺寸，如 1000x750（默认取 PAGE_PIXEL_SIZE）")
    ap.add_argument("--keep-open", action="store_true", help="--attach 时保持窗口")
    args = ap.parse_args()

    if args.attach:
        return run_attach(args)
    if args.verify:
        app = make_app()
        catalog = TagCatalog()
        pages = make_pages(catalog)
        report = build_report(catalog, pages)
        for item in report["pages"]:
            print(f"{item['page_id']:<11} 显示点={item['display_points']:<4} "
                  f"订阅 key={item['subscribed_keys']:<4} 待接入={len(item['pending'])}")
        print(f"合计订阅 key={report['subscribed_keys_total']}，"
              f"待接入点={report['pending_count']}")
        if args.report:
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"报告: {path}")
        for page in pages:
            page.shutdown()
        return 0
    if args.shot or args.report or args.measure:
        return run_shots(args)
    return run_window(args)


if __name__ == "__main__":
    raise SystemExit(main())
