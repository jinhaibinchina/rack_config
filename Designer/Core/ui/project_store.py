"""Project and page persistence for design mode.

A design project is a small metadata file plus one scene JSON file per page::

    datas/design/project.json
    datas/design/pages/page_1.json
    datas/design/pages/page_2.json

The scene files deliberately keep the exact JSON format produced by
``SceneSerializer`` so that the existing run-mode scene can be migrated and
later loaded by the run-mode application without conversion.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import List, Optional

from Designer.Core.myQuadTreeScene import SceneSerializer
from Designer.Core.myGraphicsScene import DEFAULT_BACKGROUND_COLOR


PROJECT_VERSION = 1
DEFAULT_PAGE_NAME = "主场景"
EMPTY_SCENE = {
    "sceneRect": {"x": 0, "y": 0, "width": 0, "height": 0},
    # Per-page background colour, ``#aarrggbb``.
    "backgroundColor": DEFAULT_BACKGROUND_COLOR,
    "items": [],
}


@dataclass
class PageMeta:
    """Metadata for one design page (scene)."""

    id: str
    name: str
    file: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PageMeta":
        page_id = str(data.get("id", "")).strip()
        name = str(data.get("name", "")).strip()
        file_path = str(data.get("file", "")).strip()
        if not page_id or not file_path:
            raise ValueError("页面元数据缺少 id 或 file")
        return cls(id=page_id, name=name or page_id, file=file_path)


class ProjectStore:
    """Owns the design project metadata and the page JSON files."""

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir is not None:
            resolved_root = root_dir
        elif getattr(sys, "frozen", False):
            # _MEIPASS is temporary; design projects must live next to the
            # executable so they survive a restart.
            resolved_root = os.path.dirname(sys.executable)
        else:
            resolved_root = SceneSerializer.get_json_path("")
        self.root_dir = os.path.abspath(resolved_root)
        self.design_dir = os.path.join(self.root_dir, "datas", "design")
        self.pages_dir = os.path.join(self.design_dir, "pages")
        self.project_path = os.path.join(self.design_dir, "project.json")
        self.legacy_scene_path = os.path.join(self.root_dir, "datas", "data.json")

        self.pages: List[PageMeta] = []
        self.current_page_id: Optional[str] = None
        self.load()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def get_page(self, page_id: str) -> Optional[PageMeta]:
        for page in self.pages:
            if page.id == page_id:
                return page
        return None

    def page_path(self, page: PageMeta) -> str:
        if os.path.isabs(page.file):
            return os.path.normpath(page.file)
        return os.path.abspath(os.path.join(self.root_dir, page.file))

    def current_page(self) -> Optional[PageMeta]:
        return self.get_page(self.current_page_id) if self.current_page_id else None

    # ------------------------------------------------------------------
    # Loading / bootstrap
    # ------------------------------------------------------------------
    def load(self) -> None:
        os.makedirs(self.pages_dir, exist_ok=True)

        if os.path.isfile(self.project_path):
            try:
                with open(self.project_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                pages = [
                    PageMeta.from_dict(item)
                    for item in data.get("pages", [])
                    if isinstance(item, dict)
                ]
                if pages:
                    self.pages = pages
                    self.current_page_id = str(data.get("current_page", "")).strip() or None
                    self._normalise_loaded_project()
                    return
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                # Keep the broken file for diagnosis instead of silently
                # deleting somebody's project metadata.
                print(f"项目文件读取失败，将重新初始化: {exc}")
                try:
                    os.replace(self.project_path, self.project_path + ".bak")
                except OSError:
                    pass

        self._bootstrap()

    def _normalise_loaded_project(self) -> None:
        """Repair missing page files and invalid current-page references."""

        changed = False
        for page in self.pages:
            path = self.page_path(page)
            if not os.path.isfile(path):
                # A missing file means an empty page, not a broken project.
                self._write_empty_page(path)
                changed = True

        page_ids = {page.id for page in self.pages}
        if self.current_page_id not in page_ids:
            self.current_page_id = self.pages[0].id
            changed = True

        if changed:
            self.save_project()

    def _bootstrap(self) -> None:
        """Create the first project, migrating the legacy scene if present."""

        # If project.json was lost but page files still exist, rebuild the
        # metadata instead of overwriting the user's pages with the legacy
        # run-mode scene.
        existing = self._existing_page_files()
        if existing:
            self.pages = []
            for page_id, page_file in existing:
                if len(existing) == 1:
                    name = DEFAULT_PAGE_NAME
                else:
                    name = f"页面 {page_id.removeprefix('page_')}"
                self.pages.append(PageMeta(id=page_id, name=name, file=page_file))
            self.current_page_id = self.pages[0].id
            self.save_project()
            print(f"已根据现有页面文件恢复项目: {len(self.pages)} 个页面")
            return

        page_id = self._next_page_id()
        page_file = self._relative_page_file(page_id)
        page_abs = os.path.abspath(os.path.join(self.root_dir, page_file))

        if os.path.isfile(self.legacy_scene_path) and os.path.getsize(self.legacy_scene_path) > 0:
            # Copy, never move: main.py must still be able to run unchanged.
            shutil.copy2(self.legacy_scene_path, page_abs)
            print(f"已从旧场景迁移设计页面: {self.legacy_scene_path} -> {page_abs}")
        else:
            self._write_empty_page(page_abs)

        self.pages = [PageMeta(id=page_id, name=DEFAULT_PAGE_NAME, file=page_file)]
        self.current_page_id = page_id
        self.save_project()

    def _existing_page_files(self):
        """Return ``(page_id, relative_file)`` pairs found on disk, sorted."""

        found = []
        try:
            filenames = os.listdir(self.pages_dir)
        except OSError:
            return found

        for filename in filenames:
            if not (filename.startswith("page_") and filename.endswith(".json")):
                continue
            page_id = filename[: -len(".json")]
            suffix = page_id.removeprefix("page_")
            if not suffix.isdigit():
                continue
            found.append((page_id, self._relative_page_file(page_id)))

        found.sort(key=lambda item: int(item[0].removeprefix("page_")))
        return found

    # ------------------------------------------------------------------
    # Project metadata
    # ------------------------------------------------------------------
    def save_project(self) -> None:
        os.makedirs(self.design_dir, exist_ok=True)
        payload = {
            "version": PROJECT_VERSION,
            "current_page": self.current_page_id,
            "pages": [page.to_dict() for page in self.pages],
        }
        tmp_path = self.project_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=4)
        os.replace(tmp_path, self.project_path)

    def set_current_page(self, page_id: str) -> None:
        if page_id == self.current_page_id:
            return
        if self.get_page(page_id) is None:
            return
        self.current_page_id = page_id
        self.save_project()

    # ------------------------------------------------------------------
    # Page CRUD
    # ------------------------------------------------------------------
    def create_page(self, name: Optional[str] = None, after_page_id: Optional[str] = None) -> PageMeta:
        page_id = self._next_page_id()
        page_file = self._relative_page_file(page_id)
        page_abs = os.path.abspath(os.path.join(self.root_dir, page_file))
        self._write_empty_page(page_abs)

        page = PageMeta(
            id=page_id,
            name=self._unique_page_name(name or self._default_page_name()),
            file=page_file,
        )
        insert_at = len(self.pages)
        if after_page_id:
            for index, existing in enumerate(self.pages):
                if existing.id == after_page_id:
                    insert_at = index + 1
                    break
        self.pages.insert(insert_at, page)
        self.save_project()
        return page

    def duplicate_page(self, page_id: str) -> PageMeta:
        source = self.get_page(page_id)
        if source is None:
            raise ValueError(f"页面不存在: {page_id}")

        new_page_id = self._next_page_id()
        new_file = self._relative_page_file(new_page_id)
        new_abs = os.path.abspath(os.path.join(self.root_dir, new_file))
        source_abs = self.page_path(source)
        if os.path.isfile(source_abs):
            shutil.copy2(source_abs, new_abs)
        else:
            self._write_empty_page(new_abs)

        page = PageMeta(
            id=new_page_id,
            name=self._unique_page_name(f"{source.name} 副本"),
            file=new_file,
        )
        insert_at = self.pages.index(source) + 1
        self.pages.insert(insert_at, page)
        self.save_project()
        return page

    def rename_page(self, page_id: str, new_name: str) -> PageMeta:
        page = self.get_page(page_id)
        if page is None:
            raise ValueError(f"页面不存在: {page_id}")
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("页面名称不能为空")
        if any(other.id != page_id and other.name == new_name for other in self.pages):
            raise ValueError(f"页面名称已存在: {new_name}")
        page.name = new_name
        self.save_project()
        return page

    def delete_page(self, page_id: str) -> bool:
        if len(self.pages) <= 1:
            return False
        page = self.get_page(page_id)
        if page is None:
            return False

        was_current = self.current_page_id == page_id
        self.pages.remove(page)
        try:
            path = self.page_path(page)
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            # Metadata removal is still valid; report the orphan file but do
            # not prevent the user from deleting the page.
            print(f"删除页面文件失败: {exc}")

        if was_current:
            self.current_page_id = self.pages[0].id
        self.save_project()
        return True


    # ------------------------------------------------------------------
    # Scene files
    # ------------------------------------------------------------------
    def save_page(self, page: PageMeta, scene) -> None:
        path = self.page_path(page)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scene.save_element_info(path)

    def write_empty_page(self, page: PageMeta) -> None:
        self._write_empty_page(self.page_path(page))

    def _write_empty_page(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(EMPTY_SCENE, handle, ensure_ascii=False, indent=4)

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------
    def _relative_page_file(self, page_id: str) -> str:
        return f"datas/design/pages/{page_id}.json"

    def _next_page_id(self) -> str:
        used_numbers = []
        for page in self.pages:
            suffix = page.id.removeprefix("page_")
            if suffix.isdigit():
                used_numbers.append(int(suffix))
        next_number = max(used_numbers, default=0) + 1
        while self.get_page(f"page_{next_number}") is not None:
            next_number += 1
        return f"page_{next_number}"

    def _default_page_name(self) -> str:
        return f"页面 {len(self.pages) + 1}"

    def _unique_page_name(self, base_name: str) -> str:
        base_name = (base_name or "页面").strip()
        existing = {page.name for page in self.pages}
        if base_name not in existing:
            return base_name
        index = 2
        while f"{base_name} {index}" in existing:
            index += 1
        return f"{base_name} {index}"

    def move_page(self, page_id: str, delta: int) -> bool:
        page = self.get_page(page_id)
        if page is None or delta == 0:
            return False
        old_index = self.pages.index(page)
        new_index = max(0, min(len(self.pages) - 1, old_index + delta))
        if new_index == old_index:
            return False
        self.pages.pop(old_index)
        self.pages.insert(new_index, page)
        self.save_project()
        return True

