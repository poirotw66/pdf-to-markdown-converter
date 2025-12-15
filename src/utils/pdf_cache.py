"""PDF page-level cache for resumable processing."""
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from threading import Lock


class PDFCache:
    """Cache manager for PDF page processing results."""
    
    def __init__(self, cache_dir: str = None):
        """
        Initialize PDF cache.
        
        Args:
            cache_dir: Directory to store cache files
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            # Default cache directory
            self.cache_dir = Path("./data/pdf_cache")
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Lock for thread-safe cache operations
        self._cache_locks: Dict[str, Lock] = {}  # Per-file locks
        self._locks_lock = Lock()  # Lock for managing cache locks
    
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
            # Include path, size, and modification time for uniqueness
            content = f"{pdf_path.absolute()}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(content.encode()).hexdigest()
        except Exception as e:
            # Fallback: use path and timestamp
            content = f"{pdf_path.absolute()}_{datetime.now().isoformat()}"
            return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cache_file(self, pdf_hash: str) -> Path:
        """Get cache file path for a PDF hash."""
        return self.cache_dir / f"{pdf_hash}.json"
    
    def _get_cache_lock(self, pdf_hash: str) -> Lock:
        """Get or create a lock for a specific cache file."""
        with self._locks_lock:
            if pdf_hash not in self._cache_locks:
                self._cache_locks[pdf_hash] = Lock()
            return self._cache_locks[pdf_hash]
    
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
        
        # Use file-specific lock for thread-safe operations
        cache_lock = self._get_cache_lock(pdf_hash)
        
        with cache_lock:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                # Verify PDF hasn't changed
                if cache_data.get("pdf_hash") != pdf_hash:
                    return None
                
                return cache_data
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error reading cache file {cache_file}: JSON corrupted - {str(e)}")
                # Try to backup corrupted file
                try:
                    backup_file = cache_file.with_suffix('.json.bak')
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
        
        if page_key in pages:
            return pages[page_key]
        
        return None
    
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
        
        # Use file-specific lock for thread-safe operations
        cache_lock = self._get_cache_lock(pdf_hash)
        
        with cache_lock:
            try:
                # Load existing cache or create new
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    except (json.JSONDecodeError, ValueError) as e:
                        # If JSON is corrupted, create new cache
                        print(f"    Warning: Cache file corrupted, recreating: {str(e)}")
                        cache_data = {
                            "pdf_path": str(pdf_path.absolute()),
                            "pdf_hash": pdf_hash,
                            "total_pages": None,
                            "pages": {},
                            "created_at": datetime.now().isoformat()
                        }
                else:
                    cache_data = {
                        "pdf_path": str(pdf_path.absolute()),
                        "pdf_hash": pdf_hash,
                        "total_pages": None,
                        "pages": {},
                        "created_at": datetime.now().isoformat()
                    }
                
                # Update page data
                if "pages" not in cache_data:
                    cache_data["pages"] = {}
                
                page_key = str(page_num)
                page_data_copy = page_data.copy()
                page_data_copy["cached_at"] = datetime.now().isoformat()
                cache_data["pages"][page_key] = page_data_copy
                
                # Update metadata
                cache_data["last_update"] = datetime.now().isoformat()
                if "total_pages" in page_data:
                    cache_data["total_pages"] = page_data["total_pages"]
                
                # Save to file atomically (write to temp file then rename)
                temp_file = cache_file.with_suffix('.json.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
                # Atomic rename
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
        
        # Use file-specific lock for thread-safe operations
        cache_lock = self._get_cache_lock(pdf_hash)
        
        with cache_lock:
            try:
                # Load existing cache or create new
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    except (json.JSONDecodeError, ValueError) as e:
                        # If JSON is corrupted, create new cache
                        print(f"    Warning: Cache file corrupted, recreating: {str(e)}")
                        cache_data = {
                            "pdf_path": str(pdf_path.absolute()),
                            "pdf_hash": pdf_hash,
                            "total_pages": None,
                            "pages": {},
                            "created_at": datetime.now().isoformat()
                        }
                else:
                    cache_data = {
                        "pdf_path": str(pdf_path.absolute()),
                        "pdf_hash": pdf_hash,
                        "total_pages": None,
                        "pages": {},
                        "created_at": datetime.now().isoformat()
                    }
                
                # Update pages
                if "pages" not in cache_data:
                    cache_data["pages"] = {}
                
                for page_data in pages_data:
                    page_num = page_data.get("page_number")
                    if page_num:
                        page_key = str(page_num)
                        page_data_copy = page_data.copy()
                        page_data_copy["cached_at"] = datetime.now().isoformat()
                        cache_data["pages"][page_key] = page_data_copy
                        
                        # Update total_pages if available
                        if "total_pages" in page_data:
                            cache_data["total_pages"] = page_data["total_pages"]
                
                # Update metadata
                cache_data["last_update"] = datetime.now().isoformat()
                
                # Save to file atomically
                temp_file = cache_file.with_suffix('.json.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
                # Atomic rename
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
                    print(f"Cleared cache for {pdf_path.name}")
            else:
                # Clear all cache files
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
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
                    "last_update": cache_data.get("last_update")
                }
            return {"pdf_path": str(pdf_path), "cached_pages": 0}
        else:
            # Get stats for all cached PDFs
            cache_files = list(self.cache_dir.glob("*.json"))
            total_pages = 0
            total_cached = 0
            
            for cache_file in cache_files:
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    pages = cache_data.get("pages", {})
                    total_cached += len(pages)
                    if cache_data.get("total_pages"):
                        total_pages += cache_data.get("total_pages", 0)
                except Exception:
                    pass
            
            return {
                "total_cache_files": len(cache_files),
                "total_cached_pages": total_cached,
                "cache_dir": str(self.cache_dir)
            }

