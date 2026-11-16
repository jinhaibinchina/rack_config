"""运行态「分组说明页」的目录与渲染。

背景
----
运行模式下，点选画布上的一个分组，属性面板右侧要显示这个分组的若干说明页
（"某某工位逻辑说明"这类纯文字页）。页数、页标题、正文都随产线/工艺而变，
属于**业务数据**，不该写死在框架代码里。

本模块只提供三件事，不含任何业务名词：

- :class:`StationPage`：一页说明的描述（页 ID、导航标题、分组标题、正文行）；
- :class:`StationCatalog`：从 JSON 读入「组名特征 → 若干页」的映射并做匹配；
- :func:`build_station_page`：把一页描述渲染成只读文本框。

配置文件结构
------------
::

    {
      "version": 1,
      "groups": [
        {
          "match": ["组名里出现这个片段就算命中", "可以写多条"],
          "pages": [
            {
              "page_id": "page_key",          必填，交给 add_page 的键
              "title": "导航里显示的名字",      必填
              "group_title": "正文框的标题",    省略时用 title
              "count": 4,                     可选，配合 {n} 展开成多页
              "lines": ["第一行", "第二行"]     或 "用换行分隔的一整段"
            }
          ]
        }
      ]
    }

``count`` 大于 1 时，``page_id`` / ``title`` / ``group_title`` 里的 ``{n}`` 会
被替换成 1..count。这样"多个工位共用同一段说明"只写一条，不用把正文抄
四遍。缺 ``{n}`` 时退化成单页（避免生成同名页）。

匹配语义
--------
``match`` 里的片段按 **子串** 判断（与原实现 ``"片段" in 组名`` 一致），
``groups`` 的顺序就是优先级：取**第一个**命中的组，与原来那条 if/elif 链等价。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Sequence

from PySide6.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout, QWidget

#: 页 ID / 标题里的序号占位符，配合 ``count`` 使用。
INDEX_TOKEN = "{n}"


@dataclass(frozen=True)
class StationPage:
    """一页说明。

    ``body`` 由 ``lines`` 用换行拼成，渲染时原样塞进只读 ``QTextEdit``，
    所以行内空格、全角半角标点都按配置原样保留。
    """

    page_id: str
    title: str
    group_title: str = ""
    lines: tuple[str, ...] = ()

    @property
    def body(self) -> str:
        """渲染用的正文。

        **每行都以换行结束，包括最后一行** —— 历史实现是逐行 ``"...\\n"``
        拼接后交给 ``setPlainText``，末尾因此带一个换行。这里保持同样的产物，
        否则界面上会少一个空段落，与改动前的显示不完全一致。
        """
        return "".join(f"{line}\n" for line in self.lines)

    @property
    def box_title(self) -> str:
        """``QGroupBox`` 用标题：没配就退回导航标题。"""
        return self.group_title or self.title

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "group_title": self.group_title,
            "lines": list(self.lines),
        }


@dataclass(frozen=True)
class StationGroup:
    """一组匹配片段 + 命中后要显示的页。"""

    patterns: tuple[str, ...]
    pages: tuple[StationPage, ...] = field(default_factory=tuple)

    def matches(self, group_name: str) -> bool:
        if not group_name:
            return False
        return any(p and p in group_name for p in self.patterns)


def _normalize_lines(value: Any) -> tuple[str, ...]:
    """把 ``lines`` 收成字符串元组；容忍单个字符串和 None。"""
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(line for line in value.replace("\r\n", "\n").split("\n"))
    if isinstance(value, Iterable):
        return tuple("" if item is None else str(item) for item in value)
    return ()


def _expand_pages(raw: dict[str, Any]) -> tuple[StationPage, ...]:
    """把一条 ``pages`` 配置展开成若干 :class:`StationPage`（处理 ``{n}``）。

    缺 ``page_id`` / ``title`` 的条目直接丢弃：目录是"能用的就多用点"的语义，
    一条写坏的页不该让整份配置失效。
    """
    page_id = str(raw.get("page_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not page_id or not title:
        return ()

    group_title = str(raw.get("group_title") or "").strip()
    lines = _normalize_lines(raw.get("lines"))

    try:
        count = int(raw.get("count") or 1)
    except (TypeError, ValueError):
        count = 1

    if count <= 1:
        return (StationPage(page_id, title, group_title, lines),)

    # count>1 但没写 {n}：生成的页会撞键，退化成单页而不是抛错
    if INDEX_TOKEN not in page_id or INDEX_TOKEN not in title:
        return (StationPage(page_id, title, group_title, lines),)

    expanded = []
    for index in range(1, count + 1):
        expanded.append(
            StationPage(
                page_id=page_id.replace(INDEX_TOKEN, str(index)),
                title=title.replace(INDEX_TOKEN, str(index)),
                group_title=group_title.replace(INDEX_TOKEN, str(index)) if group_title else "",
                lines=lines,
            )
        )
    return tuple(expanded)


class StationCatalog:
    """「组名特征 → 说明页」的目录。

    空目录是合法状态：属性面板据此显示"无可用配置"，而不是报错白屏。
    所以 :meth:`load` 对缺失文件和坏 JSON 都只返回空目录，不做异常抛出。
    """

    def __init__(self, groups: Sequence[StationGroup] = ()) -> None:
        self._groups: tuple[StationGroup, ...] = tuple(groups)

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any) -> "StationCatalog":
        if not isinstance(data, dict):
            raise ValueError("station pages: 顶层必须是对象")

        groups: list[StationGroup] = []
        for index, raw_group in enumerate(data.get("groups") or []):
            where = f"station pages: groups[{index}]"
            if not isinstance(raw_group, dict):
                raise ValueError(f"{where} 必须是对象")

            patterns = raw_group.get("match")
            if isinstance(patterns, str):
                patterns = [patterns]
            patterns = tuple(str(p) for p in (patterns or []) if str(p).strip())

            pages: list[StationPage] = []
            for raw_page in raw_group.get("pages") or []:
                if isinstance(raw_page, dict):
                    pages.extend(_expand_pages(raw_page))

            if patterns and pages:
                groups.append(StationGroup(patterns, tuple(pages)))

        return cls(groups)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None) -> "StationCatalog":
        """读配置文件。读不到就当空目录（运行态不能因为配置缺失起不来）。"""
        if not path:
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return cls.from_dict(json.load(handle))
        except (OSError, ValueError):
            return cls()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def __bool__(self) -> bool:
        return bool(self._groups)

    def __len__(self) -> int:
        return len(self._groups)

    @property
    def groups(self) -> tuple[StationGroup, ...]:
        return self._groups

    def match(self, group_name: str | None) -> tuple[StationPage, ...]:
        """返回该组名对应的页；未命中返回空元组（不是 None）。"""
        if not group_name:
            return ()
        for group in self._groups:
            if group.matches(group_name):
                return group.pages
        return ()


def build_station_page(page: StationPage, parent: QWidget | None = None) -> QWidget:
    """把一页说明渲染成只读文本框。

    布局层次与历史实现保持一致（页面 → ``QVBoxLayout`` → ``QGroupBox`` →
    ``QVBoxLayout`` → 只读 ``QTextEdit``），以免属性面板的边距/样式跟着变。
    """
    container = QWidget(parent)
    outer = QVBoxLayout(container)

    box = QGroupBox(page.box_title)
    inner = QVBoxLayout()

    text_edit = QTextEdit()
    text_edit.setPlainText(page.body)
    text_edit.setReadOnly(True)
    inner.addWidget(text_edit)

    box.setLayout(inner)
    outer.addWidget(box)
    return container
