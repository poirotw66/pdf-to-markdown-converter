"""PDF page-level cache for resumable processing."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from src.utils.vision_assets import page_asset_filename


# Runtime-only keys must not be persisted in the JSON cache.
_TRANSIENT_PAGE_KEYS = frozenset({"vision_asset_path"})


class PDFCache:
    """Cache manager for PDF page processing results and vision rasters."""

    def __init__(self, cache_dir: str = None):
        """
        Initialize PDF cache.

        Args:
            cache_dir: Directory to store cache files
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path("./data/pdf_cache")

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._cache_locks: Dict[str, Lock] = {}
        self._locks_lock = Lock()

    def _compute_pdf_hash(self, pdf_path: Path) -> str:
        """
        Compute unique hash for PDF file based on path, size, and modification time.

        Args:
            pdf_path: Path to PDF file

        Returns:
            MD5 hash string
        """
        try:
            stat = pdf_path.stat()
            content = f"{pdf_path.absolute()}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(content.encode()).hexdigest()
        except Exception:
            content = f"{pdf_path.absolute()}_{datetime.now().isoformat()}"
            return hashlib.md5(content.encode()).hexdigest()

    def _get_cache_file(self, pdf_hash: str) -> Path:
        """Get cache file path for a PDF hash."""
        return self.cache_dir / f"{pdf_hash}.json"

    def rasters_dir(self, pdf_path: Path) -> Path:
        """Directory for persisted vision-page PNGs for this PDF."""
        return self.cache_dir / "rasters" / self._compute_pdf_hash(pdf_path)

    def _get_cache_lock(self, pdf_hash: str) -> Lock:
        """Get or create a lock for a specific cache file."""
        with self._locks_lock:
            if pdf_hash not in self._cache_locks:
                self._cache_locks[pdf_hash] = Lock()
            return self._cache_locks[pdf_hash]

    @staticmethod
    def _sanitize_page_for_storage(page_data: Dict[str, Any]) -> Dict[str, Any]:
        """Drop runtime-only fields before writing JSON."""
        return {
            key: value
            for key, value in page_data.items()
            if key not in _TRANSIENT_PAGE_KEYS
        }

    def write_vision_asset(
        self,
        pdf_path: Path,
        page_number: int,
        png_bytes: bytes,
        *,
        total_pages: int,
        asset_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a vision-page or embedded PNG next to the text cache.

        Returns metadata suitable for attaching to page_data (includes runtime path).
        """
        name = asset_name or page_asset_filename(page_number, total_pages)
        return self.write_asset_bytes(pdf_path, name, png_bytes)

    def write_asset_bytes(
        self,
        pdf_path: Path,
        asset_name: str,
        png_bytes: bytes,
    ) -> dict[str, Any]:
        """Write raw PNG bytes under the PDF raster cache directory."""
        dest_dir = self.rasters_dir(pdf_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / asset_name
        temp = dest.with_suffix(".png.tmp")
        temp.write_bytes(png_bytes)
        temp.replace(dest)
        sha256 = hashlib.sha256(png_bytes).hexdigest()
        return {
            "vision_asset_name": asset_name,
            "vision_asset_sha256": sha256,
            "vision_asset_path": str(dest.resolve()),
        }

    def resolve_vision_asset(
        self,
        pdf_path: Path,
        page_data: Dict[str, Any],
    ) -> Optional[Path]:
        """
        Resolve a cached/runtime vision PNG for a page.

        Verifies sha256 when present. Returns None if missing or mismatched.
        """
        runtime = page_data.get("vision_asset_path")
        if runtime:
            runtime_path = Path(str(runtime))
            if runtime_path.is_file():
                expected = page_data.get("vision_asset_sha256")
                if expected:
                    actual = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
                    if actual != expected:
                        return None
                return runtime_path

        asset_name = page_data.get("vision_asset_name")
        if not asset_name:
            page_number = int(page_data.get("page_number") or 0)
            total_pages = int(page_data.get("total_pages") or page_number or 1)
            if page_number > 0:
                asset_name = page_asset_filename(page_number, total_pages)
        if not asset_name:
            return None

        candidate = self.rasters_dir(pdf_path) / str(asset_name)
        if not candidate.is_file():
            return None

        expected = page_data.get("vision_asset_sha256")
        if expected:
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != expected:
                return None
        return candidate

    def hydrate_vision_asset_path(
        self,
        pdf_path: Path,
        page_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach ``vision_asset_path`` when a matching raster file exists."""
        hydrated = dict(page_data)
        resolved = self.resolve_vision_asset(pdf_path, hydrated)
        if resolved is not None:
            hydrated["vision_asset_path"] = str(resolved.resolve())
            if not hydrated.get("vision_asset_name"):
                hydrated["vision_asset_name"] = resolved.name
        else:
            hydrated.pop("vision_asset_path", None)

        embedded = hydrated.get("embedded_image_assets")
        if isinstance(embedded, list):
            refreshed: list[dict[str, Any]] = []
            for asset in embedded:
                if not isinstance(asset, dict):
                    continue
                item = dict(asset)
                name = item.get("vision_asset_name")
                if name:
                    candidate = self.rasters_dir(pdf_path) / str(name)
                    if candidate.is_file():
                        expected = item.get("vision_asset_sha256")
                        if expected:
                            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                            if actual != expected:
                                item.pop("vision_asset_path", None)
                                refreshed.append(item)
                                continue
                        item["vision_asset_path"] = str(candidate.resolve())
                refreshed.append(item)
            hydrated["embedded_image_assets"] = refreshed
        return hydrated

    def get_cached_pages(self, pdf_path: Path) -> Optional[Dict[str, Any]]:
        """
        Get cached pages for a PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Cache dictionary with pages data, or None if not cached
        """
        pdf_hash = self._compute_pdf_hash(pdf_path)
        cache_file = self._get_cache_file(pdf_hash)

        if not cache_file.exists():
            return None

        cache_lock = self._get_cache_lock(pdf_hash)

        with cache_lock:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)

                if cache_data.get("pdf_hash") != pdf_hash:
                    return None

                return cache_data
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error reading cache file {cache_file}: JSON corrupted - {str(e)}")
                try:
                    backup_file = cache_file.with_suffix(".json.bak")
                    cache_file.rename(backup_file)
                    print(f"  Backed up corrupted cache to {backup_file}")
                except Exception:
                    pass
                return None
            except Exception as e:
                print(f"Error reading cache file {cache_file}: {str(e)}")
                return None

    def get_cached_page(self, pdf_path: Path, page_num: int) -> Optional[Dict[str, Any]]:
        """
        Get cached data for a specific page.

        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)

        Returns:
            Page data dictionary, or None if not cached
        """
        cache_data = self.get_cached_pages(pdf_path)
        if not cache_data:
            return None

        pages = cache_data.get("pages", {})
        page_key = str(page_num)

        if page_key not in pages:
            return None

        return self.hydrate_vision_asset_path(pdf_path, pages[page_key])

    def save_page(self, pdf_path: Path, page_data: Dict[str, Any]) -> bool:
        """
        Save a page's processing result to cache.

        Args:
            pdf_path: Path to PDF file
            page_data: Page data dictionary with 'page_number' and other fields

        Returns:
            True if successful
        """
        pdf_hash = self._compute_pdf_hash(pdf_path)
        cache_file = self._get_cache_file(pdf_hash)
        page_num = page_data.get("page_number")

        if not page_num:
            return False

        cache_lock = self._get_cache_lock(pdf_hash)

        with cache_lock:
            try:
                if cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            cache_data = json.load(f)
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"    Warning: Cache file corrupted, recreating: {str(e)}")
                        cache_data = {
                            "pdf_path": str(pdf_path.absolute()),
                            "pdf_hash": pdf_hash,
                            "total_pages": None,
                            "pages": {},
                            "created_at": datetime.now().isoformat(),
                        }
                else:
                    cache_data = {
                        "pdf_path": str(pdf_path.absolute()),
                        "pdf_hash": pdf_hash,
                        "total_pages": None,
                        "pages": {},
                        "created_at": datetime.now().isoformat(),
                    }

                if "pages" not in cache_data:
                    cache_data["pages"] = {}

                page_key = str(page_num)
                page_data_copy = self._sanitize_page_for_storage(page_data)
                page_data_copy["cached_at"] = datetime.now().isoformat()
                cache_data["pages"][page_key] = page_data_copy

                cache_data["last_update"] = datetime.now().isoformat()
                if "total_pages" in page_data:
                    cache_data["total_pages"] = page_data["total_pages"]

                temp_file = cache_file.with_suffix(".json.tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)

                temp_file.replace(cache_file)

                return True
            except Exception as e:
                print(f"Error saving page to cache: {str(e)}")
                return False

    def save_pages_batch(self, pdf_path: Path, pages_data: List[Dict[str, Any]]) -> bool:
        """
        Save multiple pages to cache in batch.

        Args:
            pdf_path: Path to PDF file
            pages_data: List of page data dictionaries

        Returns:
            True if successful
        """
        pdf_hash = self._compute_pdf_hash(pdf_path)
        cache_file = self._get_cache_file(pdf_hash)

        cache_lock = self._get_cache_lock(pdf_hash)

        with cache_lock:
            try:
                if cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            cache_data = json.load(f)
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"    Warning: Cache file corrupted, recreating: {str(e)}")
                        cache_data = {
                            "pdf_path": str(pdf_path.absolute()),
                            "pdf_hash": pdf_hash,
                            "total_pages": None,
                            "pages": {},
                            "created_at": datetime.now().isoformat(),
                        }
                else:
                    cache_data = {
                        "pdf_path": str(pdf_path.absolute()),
                        "pdf_hash": pdf_hash,
                        "total_pages": None,
                        "pages": {},
                        "created_at": datetime.now().isoformat(),
                    }

                if "pages" not in cache_data:
                    cache_data["pages"] = {}

                for page_data in pages_data:
                    page_num = page_data.get("page_number")
                    if page_num:
                        page_key = str(page_num)
                        page_data_copy = self._sanitize_page_for_storage(page_data)
                        page_data_copy["cached_at"] = datetime.now().isoformat()
                        cache_data["pages"][page_key] = page_data_copy

                        if "total_pages" in page_data:
                            cache_data["total_pages"] = page_data["total_pages"]

                cache_data["last_update"] = datetime.now().isoformat()

                temp_file = cache_file.with_suffix(".json.tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)

                temp_file.replace(cache_file)

                return True
            except Exception as e:
                print(f"Error saving pages batch to cache: {str(e)}")
                return False

    def get_cached_page_numbers(self, pdf_path: Path) -> List[int]:
        """
        Get list of cached page numbers for a PDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            List of cached page numbers
        """
        cache_data = self.get_cached_pages(pdf_path)
        if not cache_data:
            return []

        pages = cache_data.get("pages", {})
        return sorted([int(k) for k in pages.keys() if k.isdigit()])

    def get_missing_page_numbers(self, pdf_path: Path, total_pages: int) -> List[int]:
        """
        Get list of page numbers that are not cached.

        Args:
            pdf_path: Path to PDF file
            total_pages: Total number of pages in PDF

        Returns:
            List of missing page numbers
        """
        cached_pages = set(self.get_cached_page_numbers(pdf_path))
        all_pages = set(range(1, total_pages + 1))
        missing = sorted(list(all_pages - cached_pages))
        return missing

    def clear_cache(self, pdf_path: Path = None) -> bool:
        """
        Clear cache for a specific PDF or all PDFs.

        Args:
            pdf_path: If provided, clear only this PDF's cache. Otherwise clear all.

        Returns:
            True if successful
        """
        try:
            if pdf_path:
                pdf_hash = self._compute_pdf_hash(pdf_path)
                cache_file = self._get_cache_file(pdf_hash)
                if cache_file.exists():
                    cache_file.unlink()
                rasters = self.cache_dir / "rasters" / pdf_hash
                if rasters.is_dir():
                    for png in rasters.glob("*.png"):
                        png.unlink(missing_ok=True)
                    try:
                        rasters.rmdir()
                    except OSError:
                        pass
                print(f"Cleared cache for {pdf_path.name}")
            else:
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
                rasters_root = self.cache_dir / "rasters"
                if rasters_root.is_dir():
                    for png in rasters_root.rglob("*.png"):
                        png.unlink(missing_ok=True)
                print(f"Cleared all cache files from {self.cache_dir}")

            return True
        except Exception as e:
            print(f"Error clearing cache: {str(e)}")
            return False

    def get_cache_stats(self, pdf_path: Path = None) -> Dict[str, Any]:
        """
        Get cache statistics.

        Args:
            pdf_path: If provided, get stats for this PDF only

        Returns:
            Dictionary with cache statistics
        """
        if pdf_path:
            cache_data = self.get_cached_pages(pdf_path)
            if cache_data:
                pages = cache_data.get("pages", {})
                return {
                    "pdf_path": str(pdf_path),
                    "cached_pages": len(pages),
                    "total_pages": cache_data.get("total_pages"),
                    "last_update": cache_data.get("last_update"),
                }
            return {"pdf_path": str(pdf_path), "cached_pages": 0}

        cache_files = list(self.cache_dir.glob("*.json"))
        total_cached = 0

        for cache_file in cache_files:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                pages = cache_data.get("pages", {})
                total_cached += len(pages)
            except Exception:
                pass

        return {
            "total_cache_files": len(cache_files),
            "total_cached_pages": total_cached,
            "cache_dir": str(self.cache_dir),
        }
