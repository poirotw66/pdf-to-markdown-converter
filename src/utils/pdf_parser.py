"""PDF parser with hybrid approach: PyMuPDF fast path + Gemini vision for low-density pages."""
import time
import io
from pathlib import Path
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from threading import Semaphore
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # Fallback if PyMuPDF not installed
from pdf2image import convert_from_path
from PIL import Image
import google.generativeai as genai
from app.config import settings
from src.utils.pdf_cache import PDFCache
from src.utils.retry import (
    retry_with_backoff, classify_error, ErrorType, CircuitBreaker
)
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def _convert_pdf_page_to_image(pdf_path: str, page_num: int, dpi: int = 150) -> Image.Image:
    """
    Convert a single PDF page to image using pdf2image.
    This function is designed to run in a separate process.
    
    Args:
        pdf_path: Path to PDF file
        page_num: Page number (1-indexed)
        dpi: DPI for image conversion
        
    Returns:
        PIL Image object
    """
    try:
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=page_num,
            last_page=page_num,
            single_file=True
        )
        return images[0] if images else None
    except Exception as e:
        raise ValueError(f"Failed to convert page {page_num} to image: {str(e)}")


def _convert_page_wrapper(args):
    """
    Wrapper function for process pool to convert PDF page to image.
    Must be at module level for pickle serialization.
    
    Args:
        args: Tuple of (pdf_path_str, page_num)
        
    Returns:
        Tuple of (page_num, image) or (page_num, None) on error
    """
    pdf_path_str, page_num = args
    try:
        image = _convert_pdf_page_to_image(pdf_path_str, page_num, dpi=150)
        return page_num, image
    except Exception as e:
        print(f"    Error converting page {page_num} to image: {str(e)}")
        return page_num, None


class PDFParser:
    """Hybrid PDF parser: PyMuPDF for text extraction, Gemini vision for low-density pages."""
    
    def __init__(self, max_workers: int = None, max_processes: int = None, text_density_threshold: float = None):
        """
        Initialize the PDF parser.
        
        Args:
            max_workers: Maximum number of worker threads for Gemini API calls
            max_processes: Maximum number of processes for PDF to image conversion
            text_density_threshold: Text density threshold (0-1) below which to use Gemini vision
        """
        genai.configure(api_key=settings.google_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
        
        # Thread pool for Gemini API calls (with rate limiting)
        self.max_workers = max_workers or getattr(settings, 'max_workers', 20)
        # Process pool for PDF to image conversion (CPU-intensive)
        self.max_processes = max_processes or getattr(settings, 'max_processes', 4)
        # Text density threshold (characters per page area ratio)
        self.text_density_threshold = text_density_threshold or getattr(settings, 'text_density_threshold', 0.02)
        
        # Optional: force PyMuPDF only (disable Gemini vision)
        self.force_pymupdf = getattr(settings, 'pdf_force_pymupdf', False)
        
        # Rate limiting semaphore for Gemini API
        self.gemini_semaphore = Semaphore(self.max_workers)
        # Rate limiting: max requests per second
        self.gemini_rate_limit = getattr(settings, 'gemini_rate_limit', 50)  # requests per second
        self.gemini_last_request_time = 0.0
        self.gemini_request_interval = 1.0 / self.gemini_rate_limit
        
        # Initialize cache
        cache_dir = getattr(settings, 'pdf_cache_dir', None)
        self.cache = PDFCache(cache_dir=cache_dir)
        self.use_cache = getattr(settings, 'use_pdf_cache', True)
        
        # Initialize circuit breaker for Gemini vision API if enabled
        self.gemini_circuit_breaker = None
        if getattr(settings, 'circuit_breaker_enabled', True):
            self.gemini_circuit_breaker = CircuitBreaker(
                failure_threshold=getattr(settings, 'circuit_breaker_failure_threshold', 5),
                recovery_timeout=getattr(settings, 'circuit_breaker_recovery_timeout', 60.0)
            )
    
    def _calculate_text_density(self, text: str, page_area: float = None) -> float:
        """
        Calculate text density (characters per unit area).
        
        Args:
            text: Extracted text
            page_area: Page area in square points (optional, for normalization)
            
        Returns:
            Text density score
        """
        if not text or len(text.strip()) == 0:
            return 0.0
        
        char_count = len(text.strip())
        # If page area provided, normalize by area; otherwise use character count
        if page_area and page_area > 0:
            return char_count / page_area
        return char_count / 10000.0  # Normalize by arbitrary area
    
    def _extract_text_with_pymupdf(self, pdf_path: str, page_num: int) -> Tuple[str, float, bool]:
        """
        Extract text from PDF page using PyMuPDF (fast path).
        
        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)
            
        Returns:
            Tuple of (extracted_text, text_density, has_table)
        """
        if fitz is None:
            return "", 0.0, False
        
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]  # Convert to 0-indexed
            
            # Extract text
            text = page.get_text()
            
            # Get page dimensions for density calculation
            page_rect = page.rect
            page_area = page_rect.width * page_rect.height
            
            # Calculate text density
            text_density = self._calculate_text_density(text, page_area)
            
            # Check for tables (simple heuristic: if text contains tab characters or multiple spaces)
            has_table = '\t' in text or text.count('  ') > 5
            
            doc.close()
            
            return text.strip(), text_density, has_table
            
        except Exception as e:
            print(f"Error extracting text with PyMuPDF from page {page_num}: {str(e)}")
            return "", 0.0, False
    
    def _extract_text_from_image(self, image_input, page_num: int) -> str:
        """
        Extract text from a single PDF page image using Gemini vision.
        
        Args:
            image_input: PIL Image object or BytesIO containing image bytes
            page_num: Page number for error reporting
        """
        # Acquire semaphore for rate limiting
        with self.gemini_semaphore:
            # Rate limiting: ensure minimum interval between requests
            current_time = time.time()
            time_since_last = current_time - self.gemini_last_request_time
            if time_since_last < self.gemini_request_interval:
                time.sleep(self.gemini_request_interval - time_since_last)
            self.gemini_last_request_time = time.time()
            
            try:
                # Prepare the prompt for text extraction
                prompt = """
                # 角色

你是一個高度精確的資料結構化引擎。你的唯一任務是分析一張簡報投影片的圖片，並將其中所有具備資訊價值的內容，轉換為一個乾淨、結構化的 Markdown 文字檔案。

# 最終目標

產出的文字將直接作為「檢索增強生成 (RAG)」系統的知識庫。因此，輸出的品質標準是最大化「事實密度」與最小化「描述性噪音」。關於純粹美學設計、裝飾性元素的描述，都會降低知識庫的檢索效率，應予以排除。

# 指導原則 (務必遵守)

1.  **資訊優先，設計其次**：你的焦點是文字、數據、表格、以及明確的邏輯關係（如流程圖）。投影片的背景、顏色、裝飾圖形、或版面風格不屬於資訊範疇。
2.  **區分「資訊圖」與「裝飾圖」**：
    * **資訊圖 (需要分析)**：指傳達具體數據或流程的圖，例如：數據圖表、架構圖、流程圖、軟體介面截圖。
    * **裝飾圖 (需要忽略)**：指僅為美化或營造氛圍的圖，例如：無關的庫存照片 (如會議、握手、城市風景)、通用小圖示 (如燈泡、齒輪)、抽象的幾何形狀。

# 指令

請分析提供的投影片圖片，並嚴格按照以下指令，將所有分析結果整合成一份結構化的 Markdown 文件：

1.  **主要標題擷取**: 識別投影片的主要標題，並將其格式化為 H1 標題 (`#`)。
2.  **內文與列表擷取**: 按照邏輯閱讀順序，精確擷取所有文字內容。必須保留原始的項目符號 (`- `) 或數字列表 (`1. `) 格式。
3.  **表格資料提取**: 若有表格，將其完整轉換為 Markdown 表格格式。確保所有欄位和儲存格資料都被精確轉錄。
4.  **流程/架構圖轉譯 (資訊圖分析)**:
    * 若有流程圖、架構圖或任何使用箭頭/方塊表達邏輯關係的圖表：
    * 嚴禁描述形狀或顏色，例如「一個藍色方塊指向一個綠色圓形」。
    * 必須以文字清晰地說明整個流程的步驟、組件的關係、或數據的流向。
    * 例如，將 `[A: 輸入資料]` -> `[B: 驗證資料]` 轉譯為：「流程開始於『A: 輸入資料』，接著進入下一步『B: 驗證資料』。」
5.  **圖像內容處理 (區分對待)**:
    * 對於「資訊圖」(如軟體截圖、數據圖表)：簡潔地描述其核心內容及功能。例如：「此為軟體的使用者設定介面截圖，顯示了『通知』、『外觀』和『語言』三個可調整的選項。」
    * 對於「裝飾圖」(如庫存照片、通用圖示)：完全忽略，不要在輸出中描述或提及這些圖片。

# 排除項目
* 禁止描述任何純粹的背景設計元素（如抽象形狀、漸層、線條）。
* 禁止對裝飾性圖片或通用圖示進行任何形式的描述或象徵意義分析。
* 禁止使用任何主觀或形容詞類的詞彙來評論投影片的設計風格（例如「現代感」、「專業」、「簡潔」）。

# 輸出格式

請務必使用「繁體中文」，並以單一、連貫的 Markdown 格式提供所有分析後的內容。
                """
                
                # Convert BytesIO to PIL Image if needed, or use directly
                if isinstance(image_input, io.BytesIO):
                    # Load image from bytes
                    image_input.seek(0)
                    image = Image.open(image_input)
                    # Ensure RGB mode
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                else:
                    # Assume it's already a PIL Image
                    image = image_input
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                
                # Use Gemini to extract text from image with retry and circuit breaker
                if getattr(settings, 'retry_enabled', True):
                    @retry_with_backoff(
                        max_retries=getattr(settings, 'retry_max_attempts', 3),
                        initial_delay=getattr(settings, 'retry_initial_delay', 1.0),
                        max_delay=getattr(settings, 'retry_max_delay', 60.0),
                        exponential_base=getattr(settings, 'retry_exponential_base', 2.0),
                        jitter=getattr(settings, 'retry_jitter', True)
                    )
                    def _generate_with_retry():
                        if self.gemini_circuit_breaker:
                            return self.gemini_circuit_breaker.call(
                                self.model.generate_content,
                                [prompt, image],
                                generation_config={
                                    "temperature": 0.1,
                                    "top_p": 0.95,
                                    "top_k": 40,
                                }
                            )
                        return self.model.generate_content(
                            [prompt, image],
                            generation_config={
                                "temperature": 0.1,
                                "top_p": 0.95,
                                "top_k": 40,
                            }
                        )
                    
                    try:
                        response = _generate_with_retry()
                    except Exception as e:
                        error_type = classify_error(e)
                        log.warning(
                            f"Failed to extract text from page {page_num} after retries",
                            extra={
                                "page_num": page_num,
                                "error_type": error_type.value,
                                "error": str(e)
                            }
                        )
                        # Graceful degradation: return error message
                        if getattr(settings, 'graceful_degradation_enabled', True):
                            return f"[無法從第 {page_num} 頁提取文字: {error_type.value}]"
                        raise
                else:
                    response = self.model.generate_content(
                        [prompt, image],
                        generation_config={
                            "temperature": 0.1,
                            "top_p": 0.95,
                            "top_k": 40,
                        }
                    )
                
                extracted_text = response.text.strip()
                return extracted_text
                
            except Exception as e:
                error_type = classify_error(e)
                log.error(
                    f"Error extracting text from page {page_num} with Gemini",
                    extra={"page_num": page_num, "error_type": error_type.value, "error": str(e)},
                    exc_info=True
                )
                # Graceful degradation
                if getattr(settings, 'graceful_degradation_enabled', True):
                    return f"[無法從第 {page_num} 頁提取文字: {error_type.value}]"
                return f"[無法從第 {page_num} 頁提取文字: {str(e)}]"
    
    def parse_pdf(self, pdf_path: str, max_pages: int = None) -> List[Dict[str, Any]]:
        """
        Parse PDF file using hybrid approach: PyMuPDF first, Gemini vision for low-density pages.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process (None for all)
            
        Returns:
            List of dictionaries with page number and extracted text
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Open PDF to get page count
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        doc.close()
        
        print(f"Parsing PDF: {pdf_path.name} ({total_pages} pages)")
        
        # Check cache for resume capability
        if self.use_cache:
            cached_pages = self.cache.get_cached_page_numbers(pdf_path)
            
            if cached_pages:
                print(f"Cache found: {len(cached_pages)}/{total_pages} pages already processed")
                print("  Resuming from cache...")
            else:
                print("No cache found, starting fresh")
        
        print("Using hybrid approach: PyMuPDF fast path + Gemini vision for low-density pages")
        
        pages_data = []
        pages_need_gemini = []  # Pages that need Gemini vision processing
        pages_to_process = []  # Pages that need processing (not cached)
        fallback_pymupdf_text = {}
        
        # Step 1: Check cache and load cached pages
        if self.use_cache:
            for page_num in range(1, total_pages + 1):
                cached_page = self.cache.get_cached_page(pdf_path, page_num)
                if cached_page:
                    # Use cached page data
                    pages_data.append(cached_page)
                    print(f"  ✓ Page {page_num}: Loaded from cache ({cached_page.get('method', 'unknown')})")
                else:
                    pages_to_process.append(page_num)
        else:
            pages_to_process = list(range(1, total_pages + 1))
        
        if not pages_to_process:
            print("All pages already cached! Returning cached results.")
            pages_data.sort(key=lambda x: x["page_number"])
            return pages_data
        
        print(f"\nStep 1: Fast text extraction with PyMuPDF ({len(pages_to_process)} pages to process)...")
        
        # Step 2: Fast extraction with PyMuPDF for uncached pages
        for page_num in pages_to_process:
            # Check cache again (in case it was updated)
            if self.use_cache:
                cached_page = self.cache.get_cached_page(pdf_path, page_num)
                if cached_page:
                    pages_data.append(cached_page)
                    continue
            
            text, density, has_table = self._extract_text_with_pymupdf(str(pdf_path), page_num)
            
            # Determine if we need Gemini vision
            # Use Gemini if: low text density OR has table (PyMuPDF may miss table structure)
            needs_gemini = (
                not self.force_pymupdf
                and (
                    density < self.text_density_threshold
                    or has_table
                    or len(text.strip()) < 50  # Very short text might be image-based
                )
            )
            
            if needs_gemini:
                fallback_pymupdf_text[page_num] = text.strip()
                pages_need_gemini.append(page_num)
                print(f"  Page {page_num}: Low density ({density:.4f}) or has table - will use Gemini vision")
            else:
                # Use PyMuPDF result directly and cache it
                page_data = {
                    "page_number": page_num,
                    "text": text,
                    "total_pages": total_pages,
                    "method": "pymupdf"
                }
                pages_data.append(page_data)
                
                # Save to cache
                if self.use_cache:
                    self.cache.save_page(pdf_path, page_data)
        
        # Step 3: Process pages that need Gemini vision
        if pages_need_gemini:
            # Filter out already cached Gemini pages
            pages_to_process_gemini = []
            for page_num in pages_need_gemini:
                if self.use_cache:
                    cached_page = self.cache.get_cached_page(pdf_path, page_num)
                    if cached_page and cached_page.get("method") == "gemini_vision":
                        pages_data.append(cached_page)
                        print(f"  ✓ Page {page_num}: Gemini result loaded from cache")
                        continue
                pages_to_process_gemini.append(page_num)
            
            if pages_to_process_gemini:
                print(f"\nStep 2: Processing {len(pages_to_process_gemini)} pages with Gemini vision (multiprocess image conversion + multithreaded API calls)...")
                
                # Convert PDF pages to images using multiprocessing
                print("  Converting PDF pages to images (multiprocess)...")
                images_dict = {}
                
                # Use ProcessPoolExecutor for CPU-intensive image conversion
                # Note: _convert_page_wrapper must be at module level for pickle serialization
                with ProcessPoolExecutor(max_workers=self.max_processes) as process_executor:
                    futures = {
                        process_executor.submit(_convert_page_wrapper, (str(pdf_path), page_num)): page_num
                        for page_num in pages_to_process_gemini
                    }
                    
                    for future in as_completed(futures):
                        page_num, image = future.result()
                        if image:
                            images_dict[page_num] = image
                
                # Process images with Gemini API using multithreading with rate limiting
                print("  Extracting text with Gemini vision (multithreaded with rate limiting)...")
                
                def process_gemini_page(page_num):
                    """Process a single page with Gemini."""
                    fallback_text = fallback_pymupdf_text.get(page_num, "").strip()
                    
                    if page_num not in images_dict:
                        return {
                            "page_number": page_num,
                            "text": fallback_text or "[無法轉換頁面為圖片]",
                            "total_pages": total_pages,
                            "method": "gemini_vision_error_fallback_pymupdf" if fallback_text else "gemini_vision_error"
                        }
                    
                    image = images_dict[page_num]
                    
                    # Ensure image is in RGB mode and convert to bytes for Gemini API
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                    
                    # Convert PIL Image to bytes to avoid PIL plugin issues in multiprocessing
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='PNG')
                    img_bytes.seek(0)
                    
                    extracted_text = self._extract_text_from_image(img_bytes, page_num)
                    
                    # 如果 Gemini 失敗且有 PyMuPDF 備援，改用備援文本
                    if extracted_text.startswith("[無法從第") and fallback_text:
                        extracted_text = fallback_text
                    
                    page_data = {
                        "page_number": page_num,
                        "text": extracted_text,
                        "total_pages": total_pages,
                        "method": "gemini_vision"
                    }
                    
                    # Save to cache immediately after processing (with error handling)
                    if self.use_cache:
                        try:
                            self.cache.save_page(pdf_path, page_data)
                        except Exception as e:
                            # Log but don't fail if cache save fails
                            print(f"    Warning: Failed to save page {page_num} to cache: {str(e)}")
                    
                    return page_data
                
                # Use ThreadPoolExecutor for Gemini API calls (with semaphore rate limiting)
                gemini_results = {}
                with ThreadPoolExecutor(max_workers=self.max_workers) as thread_executor:
                    futures = {
                        thread_executor.submit(process_gemini_page, page_num): page_num
                        for page_num in pages_to_process_gemini
                    }
                    
                    completed = 0
                    for future in as_completed(futures):
                        result = future.result()
                        gemini_results[result["page_number"]] = result
                        completed += 1
                        if completed % 5 == 0 or completed == len(pages_to_process_gemini):
                            print(f"    Progress: {completed}/{len(pages_to_process_gemini)} pages processed with Gemini")
                
                # Add Gemini results to pages_data
                for page_num in pages_to_process_gemini:
                    if page_num in gemini_results:
                        pages_data.append(gemini_results[page_num])
        
        # Sort by page number to ensure correct order
        pages_data.sort(key=lambda x: x["page_number"])
        
        # Count methods used
        pymupdf_count = sum(1 for p in pages_data if p.get("method") == "pymupdf")
        gemini_count = sum(1 for p in pages_data if p.get("method") == "gemini_vision")
        cached_count = sum(1 for p in pages_data if p.get("cached_at") is not None)
        
        print(f"\n✓ Successfully extracted text from {len(pages_data)} pages")
        print(f"  - PyMuPDF (fast): {pymupdf_count} pages")
        print(f"  - Gemini Vision: {gemini_count} pages")
        if cached_count > 0:
            print(f"  - From cache: {cached_count} pages")
        
        # Save all pages to cache in batch (for efficiency)
        # Note: Individual pages are already cached during processing, this is a final update
        if self.use_cache and pages_data:
            try:
                self.cache.save_pages_batch(pdf_path, pages_data)
            except Exception as e:
                # Log but don't fail if batch cache save fails
                print(f"  Warning: Failed to save pages batch to cache: {str(e)}")
        
        return pages_data
    
    def get_full_text(self, pdf_path: str, max_pages: int = None) -> str:
        """
        Get full text content from PDF as a single string.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process
            
        Returns:
            Full text content with page markers
        """
        pages_data = self.parse_pdf(pdf_path, max_pages)
        
        full_text_parts = []
        for page_data in pages_data:
            page_num = page_data["page_number"]
            text = page_data["text"]
            method = page_data.get("method", "unknown")
            full_text_parts.append(f"\n--- 第 {page_num} 頁 ({method}) ---\n{text}\n")
        
        return "\n".join(full_text_parts)
