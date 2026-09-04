"""PDF parser with hybrid approach: PyMuPDF fast path + Gemini vision for selected pages."""
import time
import io
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from threading import Semaphore, Lock
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # Fallback if PyMuPDF not installed
from pdf2image import convert_from_path
from PIL import Image
try:
    from google import genai
    from google.genai import types as genai_types
    USE_GOOGLE_GENAI_SDK = True
except ImportError:
    import google.generativeai as genai  # type: ignore
    genai_types = None
    USE_GOOGLE_GENAI_SDK = False
from app.config import settings, resolve_gemini_model
from src.utils.pdf_cache import PDFCache
from src.utils.retry import (
    retry_with_backoff, classify_error, CircuitBreaker
)
from src.utils.prompts import get_prompt, PROMPT_TEMPLATES
from src.utils.logging_config import get_logger
from src.utils.token_usage import extract_usage_from_response

log = get_logger(__name__)

_EMPTY_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "thoughts_tokens": 0,
    "total_tokens": 0,
}


def routing_use_gemini_vision(
    *,
    force_pymupdf: bool,
    gemini_on_low_text_density: bool,
    text_density_threshold: float,
    gemini_on_visual_structure: bool,
    gemini_if_chars_below: int,
    density: float,
    text: str,
    has_visual_structure: bool,
) -> bool:
    """
    Decide whether to send a page to Gemini vision after PyMuPDF extraction.

    Density is len(text) / (page_width * page_height) in PDF points. A naive high
    threshold (e.g. 0.02) flags almost every normal page as low-density.
    """
    if force_pymupdf:
        return False
    stripped = text.strip()
    char_count = len(stripped)
    if char_count == 0:
        return True
    if char_count < gemini_if_chars_below:
        return True
    if gemini_on_visual_structure and has_visual_structure:
        return True
    if gemini_on_low_text_density and density < text_density_threshold:
        return True
    return False


def _detect_visual_structure_signals(
    page: Any,
    text: str,
    *,
    vector_path_min: int,
    embedded_image_area_ratio_min: float,
) -> tuple[bool, tuple[str, ...]]:
    """
    Heuristics for table/chart-like pages: tabular text, vector drawings, embedded images.

    Returns:
        (should_treat_as_visual, reason_tags for logging)
    """
    tags: list[str] = []
    raw = text or ""
    if "\t" in raw or raw.count("  ") > 5:
        tags.append("tabular_text")

    try:
        drawings = page.get_drawings() or []
    except Exception:
        drawings = []
    if len(drawings) >= vector_path_min:
        tags.append("vector_graphics")

    try:
        page_area = float(page.rect.width * page.rect.height)
    except Exception:
        page_area = 0.0

    try:
        images = page.get_images(full=True) or []
    except Exception:
        images = []

    if images and page_area > 0:
        if embedded_image_area_ratio_min <= 0.0:
            tags.append("embedded_image")
        else:
            for entry in images:
                xref = entry[0]
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []
                for rect in rects:
                    ratio = (rect.width * rect.height) / page_area
                    if ratio >= embedded_image_area_ratio_min:
                        tags.append("large_embedded_image")
                        break
                if tags and tags[-1] == "large_embedded_image":
                    break

    return bool(tags), tuple(tags)


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
        args: Tuple of (pdf_path_str, page_num, dpi)

    Returns:
        Tuple of (page_num, image) or (page_num, None) on error
    """
    if len(args) == 3:
        pdf_path_str, page_num, dpi = args
    else:
        pdf_path_str, page_num = args
        dpi = 150
    try:
        image = _convert_pdf_page_to_image(pdf_path_str, page_num, dpi=int(dpi))
        return page_num, image
    except Exception as e:
        log.warning(f"    Error converting page {page_num} to image: {str(e)}")
        return page_num, None


class PDFParser:
    """Hybrid PDF parser: PyMuPDF text extraction plus optional Gemini vision routing."""
    
    def __init__(
        self,
        max_workers: int = None,
        max_processes: int = None,
        text_density_threshold: float = None,
        prompt_template: Optional[str] = None,
        api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
    ):
        """
        Initialize the PDF parser.
        
        Args:
            max_workers: Maximum number of worker threads for Gemini API calls
            max_processes: Maximum number of processes for PDF to image conversion
            text_density_threshold: Used only when settings.pdf_gemini_on_low_text_density is True;
                density is chars / (page area in PDF points).
            prompt_template: Prompt template ID ("slide", "table", "ocr") or custom prompt string.
                            If None, uses default template.
            api_key: Google Gemini API key. If provided, will use this instead of settings.
            gemini_model: Optional Gemini model override for this parser instance.
        """
        # Use provided API key or fall back to settings
        api_key_to_use = api_key if api_key and api_key.strip() else settings.google_api_key
        if not api_key_to_use or not api_key_to_use.strip():
            raise ValueError("Google Gemini API key is required. Please provide api_key parameter or set GOOGLE_API_KEY in environment.")
        self.gemini_model = resolve_gemini_model(gemini_model)
        
        if USE_GOOGLE_GENAI_SDK:
            self.client = genai.Client(api_key=api_key_to_use.strip())
            self.model = None
        else:
            genai.configure(api_key=api_key_to_use.strip())
            self.client = None
            self.model = genai.GenerativeModel(self.gemini_model)
        
        # Thread pool for Gemini API calls (with rate limiting)
        self.max_workers = max_workers or settings.pdf_max_workers
        # Process pool for PDF to image conversion (CPU-intensive)
        self.max_processes = max_processes or settings.pdf_max_processes
        # Text density threshold (characters per page area ratio)
        self.text_density_threshold = text_density_threshold or settings.pdf_text_density_threshold
        
        # Optional: force PyMuPDF only (disable Gemini vision)
        self.force_pymupdf = getattr(settings, "pdf_force_pymupdf", False)
        self.gemini_on_low_text_density = settings.pdf_gemini_on_low_text_density
        self.gemini_on_visual_structure = settings.pdf_gemini_on_visual_structure
        self.gemini_vector_path_min = settings.pdf_gemini_vector_path_min
        self.gemini_embedded_image_area_ratio_min = settings.pdf_gemini_embedded_image_area_ratio_min
        self.gemini_if_chars_below = settings.pdf_gemini_if_chars_below
        
        # Rate limiting semaphore for Gemini API
        self.gemini_semaphore = Semaphore(self.max_workers)
        # Rate limiting: max requests per second
        self.gemini_rate_limit = settings.pdf_max_requests_per_second
        self.gemini_last_request_time = 0.0
        self.gemini_request_interval = 1.0 / self.gemini_rate_limit
        self.gemini_rate_limit_lock = Lock()
        
        # Initialize cache
        cache_dir = getattr(settings, 'pdf_cache_dir', None)
        self.cache = PDFCache(cache_dir=cache_dir)
        self.use_cache = settings.pdf_cache_enabled
        self.preserve_vision_assets = settings.pdf_preserve_vision_assets
        self.vision_asset_dpi = settings.pdf_vision_asset_dpi
        self.extract_embedded_images = settings.pdf_extract_embedded_images
        self.embedded_image_min_area = settings.pdf_embedded_image_min_area
        self.embedded_image_max_per_page = settings.pdf_embedded_image_max_per_page
        
        # Prompt template handling
        # If prompt_template is a template ID, use it; if it's a custom string, use it directly
        if prompt_template is None:
            self.prompt = get_prompt(None)  # Use default
        elif prompt_template in PROMPT_TEMPLATES:
            self.prompt = get_prompt(prompt_template)  # Use template ID
        elif isinstance(prompt_template, str) and prompt_template.strip():
            self.prompt = prompt_template.strip()  # Use custom prompt string
        else:
            self.prompt = get_prompt(None)  # Fallback to default
        
        # Initialize circuit breaker for Gemini vision API if enabled
        self.gemini_circuit_breaker = None
        if settings.pdf_circuit_breaker_enabled:
            self.gemini_circuit_breaker = CircuitBreaker(
                failure_threshold=settings.pdf_circuit_breaker_failure_threshold,
                recovery_timeout=settings.pdf_circuit_breaker_recovery_timeout,
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
    
    def _extract_text_with_pymupdf(
        self, pdf_path: str, page_num: int
    ) -> Tuple[str, float, bool, Tuple[str, ...]]:
        """
        Extract text from PDF page using PyMuPDF (fast path).

        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)

        Returns:
            Tuple of (extracted_text, text_density, has_visual_structure, visual_reason_tags)
        """
        if fitz is None:
            return "", 0.0, False, ()

        try:
            doc = fitz.open(pdf_path)
            try:
                page = doc[page_num - 1]  # Convert to 0-indexed

                text = page.get_text()

                page_rect = page.rect
                page_area = page_rect.width * page_rect.height

                text_density = self._calculate_text_density(text, page_area)

                has_visual, visual_tags = _detect_visual_structure_signals(
                    page,
                    text,
                    vector_path_min=self.gemini_vector_path_min,
                    embedded_image_area_ratio_min=self.gemini_embedded_image_area_ratio_min,
                )

                return text.strip(), text_density, has_visual, visual_tags
            finally:
                doc.close()

        except Exception as e:
            log.warning(f"Error extracting text with PyMuPDF from page {page_num}: {str(e)}")
            return "", 0.0, False, ()

    def _should_use_gemini_vision(
        self,
        density: float,
        text: str,
        has_visual_structure: bool,
    ) -> bool:
        """See routing_use_gemini_vision for routing rules."""
        return routing_use_gemini_vision(
            force_pymupdf=self.force_pymupdf,
            gemini_on_low_text_density=self.gemini_on_low_text_density,
            text_density_threshold=self.text_density_threshold,
            gemini_on_visual_structure=self.gemini_on_visual_structure,
            gemini_if_chars_below=self.gemini_if_chars_below,
            density=density,
            text=text,
            has_visual_structure=has_visual_structure,
        )

    def _extract_text_from_image(
        self, image_input, page_num: int
    ) -> Tuple[str, Dict[str, int]]:
        """
        Extract text from a single PDF page image using Gemini vision.

        Returns:
            (extracted_text, usage_dict with input/output/thoughts/total tokens)
        """
        # Acquire semaphore for rate limiting
        with self.gemini_semaphore:
            # Rate limiting: ensure minimum interval between requests
            with self.gemini_rate_limit_lock:
                current_time = time.time()
                time_since_last = current_time - self.gemini_last_request_time
                if time_since_last < self.gemini_request_interval:
                    time.sleep(self.gemini_request_interval - time_since_last)
                self.gemini_last_request_time = time.time()

            try:
                # Use the prompt from instance variable (set during initialization or parse_pdf call)
                prompt = self.prompt

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

                generate_config = {
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "top_k": 40,
                }

                def _call_gemini_model():
                    if USE_GOOGLE_GENAI_SDK:
                        image_bytes = io.BytesIO()
                        image.save(image_bytes, format="PNG")
                        image_part = genai_types.Part.from_bytes(
                            data=image_bytes.getvalue(),
                            mime_type="image/png",
                        )
                        return self.client.models.generate_content(
                            model=self.gemini_model,
                            contents=[prompt, image_part],
                            config=genai_types.GenerateContentConfig(**generate_config),
                        )

                    return self.model.generate_content(
                        [prompt, image],
                        generation_config=generate_config,
                    )

                # Use Gemini to extract text from image with retry and circuit breaker
                if settings.pdf_retry_enabled:
                    @retry_with_backoff(
                        max_retries=settings.pdf_retry_max_attempts,
                        initial_delay=settings.pdf_retry_initial_delay,
                        max_delay=settings.pdf_retry_max_delay,
                        exponential_base=settings.pdf_retry_exponential_base,
                        jitter=settings.pdf_retry_jitter,
                    )
                    def _generate_with_retry():
                        if self.gemini_circuit_breaker:
                            return self.gemini_circuit_breaker.call(
                                _call_gemini_model,
                            )
                        return _call_gemini_model()

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
                        if settings.pdf_graceful_degradation_enabled:
                            return (
                                f"[無法從第 {page_num} 頁提取文字: {error_type.value}]",
                                dict(_EMPTY_USAGE),
                            )
                        raise
                else:
                    response = _call_gemini_model()

                extracted_text = getattr(response, "text", "") or ""
                extracted_text = extracted_text.strip()
                return extracted_text, extract_usage_from_response(response)

            except Exception as e:
                error_type = classify_error(e)
                log.error(
                    f"Error extracting text from page {page_num} with Gemini",
                    extra={"page_num": page_num, "error_type": error_type.value, "error": str(e)},
                    exc_info=True
                )
                if settings.pdf_graceful_degradation_enabled:
                    return (
                        f"[無法從第 {page_num} 頁提取文字: {error_type.value}]",
                        dict(_EMPTY_USAGE),
                    )
                raise

    def parse_pdf(
        self,
        pdf_path: str,
        max_pages: int = None,
        prompt_template: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parse PDF file using hybrid approach: PyMuPDF first, Gemini vision when routing rules say so.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process (None for all)
            prompt_template: Optional prompt template ID or custom prompt string to override instance prompt.
                           If None, uses the prompt set during initialization.
            
        Returns:
            List of dictionaries with page number and extracted text
        """
        # Allow per-call prompt override
        if prompt_template is not None:
            if prompt_template in PROMPT_TEMPLATES:
                self.prompt = get_prompt(prompt_template)
            elif isinstance(prompt_template, str) and prompt_template.strip():
                # Custom prompt text from caller
                self.prompt = prompt_template.strip()
            # If prompt_template is invalid, keep using current self.prompt
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Open PDF to get page count
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        doc.close()
        
        log.info(f"Parsing PDF: {pdf_path.name} ({total_pages} pages)")
        
        # Check cache for resume capability
        if self.use_cache:
            cached_pages = self.cache.get_cached_page_numbers(pdf_path)
            
            if cached_pages:
                log.info(f"Cache found: {len(cached_pages)}/{total_pages} pages already processed")
                log.info("  Resuming from cache...")
            else:
                log.info("No cache found, starting fresh")
        
        log.info("Using hybrid approach: PyMuPDF fast path + Gemini vision when routing selects it")
        
        pages_data = []
        pages_need_gemini = []  # Pages that need Gemini vision processing
        pages_to_process = []  # Pages that need processing (not cached)
        fallback_pymupdf_text = {}
        
        # Step 1: Check cache and load cached pages
        if self.use_cache:
            for page_num in range(1, total_pages + 1):
                cached_page = self.cache.get_cached_page(pdf_path, page_num)
                if cached_page:
                    # Use cached page data (no API cost for this conversion run)
                    cached_page = dict(cached_page)
                    cached_page["usage_from_cache"] = True
                    cached_page["input_tokens"] = 0
                    cached_page["output_tokens"] = 0
                    cached_page["thoughts_tokens"] = 0
                    pages_data.append(cached_page)
                    log.info(f"  ✓ Page {page_num}: Loaded from cache ({cached_page.get('method', 'unknown')})")
                else:
                    pages_to_process.append(page_num)
        else:
            pages_to_process = list(range(1, total_pages + 1))
        
        if not pages_to_process:
            log.info("All pages already cached! Returning cached results.")
            pages_data.sort(key=lambda x: x["page_number"])
            self._ensure_vision_rasters(pdf_path, pages_data, total_pages)
            return pages_data
        
        log.info(f"\nStep 1: Fast text extraction with PyMuPDF ({len(pages_to_process)} pages to process)...")
        
        # Step 2: Fast extraction with PyMuPDF for uncached pages
        for page_num in pages_to_process:
            # Check cache again (in case it was updated)
            if self.use_cache:
                cached_page = self.cache.get_cached_page(pdf_path, page_num)
                if cached_page:
                    cached_page = dict(cached_page)
                    cached_page["usage_from_cache"] = True
                    cached_page["input_tokens"] = 0
                    cached_page["output_tokens"] = 0
                    cached_page["thoughts_tokens"] = 0
                    pages_data.append(cached_page)
                    continue
            
            text, density, has_visual, visual_tags = self._extract_text_with_pymupdf(
                str(pdf_path), page_num
            )

            needs_gemini = self._should_use_gemini_vision(density, text, has_visual)

            if needs_gemini:
                fallback_pymupdf_text[page_num] = text.strip()
                pages_need_gemini.append(page_num)
                reason_parts: list[str] = []
                if not text.strip():
                    reason_parts.append("no extractable text")
                elif len(text.strip()) < self.gemini_if_chars_below:
                    reason_parts.append(
                        f"few extracted chars ({len(text.strip())}<{self.gemini_if_chars_below})"
                    )
                if self.gemini_on_visual_structure and has_visual:
                    reason_parts.append(
                        "visual_structure(" + ",".join(visual_tags) + ")"
                        if visual_tags
                        else "visual_structure"
                    )
                if self.gemini_on_low_text_density and density < self.text_density_threshold:
                    reason_parts.append(f"low density ({density:.6f}<{self.text_density_threshold})")
                reason = ", ".join(reason_parts) if reason_parts else "vision routing"
                log.info(f"  Page {page_num}: {reason} — will use Gemini vision")
            else:
                # Use PyMuPDF result directly and cache it
                page_data = {
                    "page_number": page_num,
                    "text": text,
                    "total_pages": total_pages,
                    "method": "pymupdf",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "thoughts_tokens": 0,
                    "usage_from_cache": False,
                }
                if self.preserve_vision_assets and self.extract_embedded_images:
                    embedded = self._persist_embedded_images(
                        pdf_path, page_num, total_pages
                    )
                    if embedded:
                        page_data["embedded_image_assets"] = embedded
                        log.info(
                            f"  Page {page_num}: kept {len(embedded)} embedded image(s)"
                        )
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
                        cached_page = dict(cached_page)
                        cached_page["usage_from_cache"] = True
                        cached_page["input_tokens"] = 0
                        cached_page["output_tokens"] = 0
                        cached_page["thoughts_tokens"] = 0
                        pages_data.append(cached_page)
                        log.info(f"  ✓ Page {page_num}: Gemini result loaded from cache")
                        continue
                pages_to_process_gemini.append(page_num)
            
            if pages_to_process_gemini:
                log.info(f"\nStep 2: Processing {len(pages_to_process_gemini)} pages with Gemini vision (multiprocess image conversion + multithreaded API calls)...")
                
                # Convert PDF pages to images using multiprocessing
                log.info("  Converting PDF pages to images (multiprocess)...")
                images_dict = {}
                
                # Use ProcessPoolExecutor for CPU-intensive image conversion
                # Note: _convert_page_wrapper must be at module level for pickle serialization
                with ProcessPoolExecutor(max_workers=self.max_processes) as process_executor:
                    futures = {
                        process_executor.submit(
                            _convert_page_wrapper,
                            (str(pdf_path), page_num, self.vision_asset_dpi),
                        ): page_num
                        for page_num in pages_to_process_gemini
                    }
                    
                    for future in as_completed(futures):
                        page_num, image = future.result()
                        if image:
                            images_dict[page_num] = image
                
                # Process images with Gemini API using multithreading with rate limiting
                log.info("  Extracting text with Gemini vision (multithreaded with rate limiting)...")
                
                def process_gemini_page(page_num):
                    """Process a single page with Gemini."""
                    fallback_text = fallback_pymupdf_text.get(page_num, "").strip()
                    
                    if page_num not in images_dict:
                        return {
                            "page_number": page_num,
                            "text": fallback_text or "[無法轉換頁面為圖片]",
                            "total_pages": total_pages,
                            "method": "gemini_vision_error_fallback_pymupdf" if fallback_text else "gemini_vision_error",
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "thoughts_tokens": 0,
                            "usage_from_cache": False,
                        }

                    image = images_dict[page_num]

                    # Ensure image is in RGB mode and convert to bytes for Gemini API
                    if image.mode != 'RGB':
                        image = image.convert('RGB')

                    # Convert PIL Image to bytes once: reuse for Gemini + asset cache
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='PNG')
                    png_bytes = img_bytes.getvalue()
                    img_bytes.seek(0)

                    extracted_text, usage = self._extract_text_from_image(img_bytes, page_num)

                    # 如果 Gemini 失敗且有 PyMuPDF 備援，改用備援文本
                    if extracted_text.startswith("[無法從第") and fallback_text:
                        extracted_text = fallback_text

                    page_data = {
                        "page_number": page_num,
                        "text": extracted_text,
                        "total_pages": total_pages,
                        "method": "gemini_vision",
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "thoughts_tokens": usage.get("thoughts_tokens", 0),
                        "usage_from_cache": False,
                    }

                    if self.preserve_vision_assets or self.use_cache:
                        try:
                            asset_meta = self.cache.write_vision_asset(
                                pdf_path,
                                page_num,
                                png_bytes,
                                total_pages=total_pages,
                            )
                            page_data.update(asset_meta)
                        except Exception as e:
                            log.warning(
                                f"    Warning: Failed to persist vision raster "
                                f"for page {page_num}: {str(e)}"
                            )
                    
                    # Save to cache immediately after processing (with error handling)
                    if self.use_cache:
                        try:
                            self.cache.save_page(pdf_path, page_data)
                        except Exception as e:
                            # Log but don't fail if cache save fails
                            log.warning(f"    Warning: Failed to save page {page_num} to cache: {str(e)}")
                    
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
                            log.info(f"    Progress: {completed}/{len(pages_to_process_gemini)} pages processed with Gemini")
                
                # Add Gemini results to pages_data
                for page_num in pages_to_process_gemini:
                    if page_num in gemini_results:
                        pages_data.append(gemini_results[page_num])
        
        # Sort by page number to ensure correct order
        pages_data.sort(key=lambda x: x["page_number"])

        # Backfill missing vision rasters (e.g. old text-only cache entries)
        self._ensure_vision_rasters(pdf_path, pages_data, total_pages)
        
        # Count methods used
        pymupdf_count = sum(1 for p in pages_data if p.get("method") == "pymupdf")
        gemini_count = sum(1 for p in pages_data if p.get("method") == "gemini_vision")
        cached_count = sum(1 for p in pages_data if p.get("cached_at") is not None)
        
        log.info(f"\n✓ Successfully extracted text from {len(pages_data)} pages")
        log.info(f"  - PyMuPDF (fast): {pymupdf_count} pages")
        log.info(f"  - Gemini Vision: {gemini_count} pages")
        if cached_count > 0:
            log.info(f"  - From cache: {cached_count} pages")
        
        # Save all pages to cache in batch (for efficiency)
        # Note: Individual pages are already cached during processing, this is a final update
        if self.use_cache and pages_data:
            try:
                self.cache.save_pages_batch(pdf_path, pages_data)
            except Exception as e:
                # Log but don't fail if batch cache save fails
                log.warning(f"  Warning: Failed to save pages batch to cache: {str(e)}")
        
        return pages_data

    def _persist_embedded_images(
        self,
        pdf_path: Path,
        page_num: int,
        total_pages: int,
    ) -> list[dict[str, Any]]:
        """Extract and cache significant embedded images for a PyMuPDF-only page."""
        from src.utils.vision_assets import (
            embedded_asset_filename,
            extract_embedded_pngs_from_pdf_page,
        )

        extracted = extract_embedded_pngs_from_pdf_page(
            pdf_path,
            page_num,
            min_area=self.embedded_image_min_area,
            max_images=self.embedded_image_max_per_page,
        )
        assets: list[dict[str, Any]] = []
        for index, (png_bytes, width, height) in enumerate(extracted, start=1):
            asset_name = embedded_asset_filename(page_num, index, total_pages)
            try:
                meta = self.cache.write_vision_asset(
                    pdf_path,
                    page_num,
                    png_bytes,
                    total_pages=total_pages,
                    asset_name=asset_name,
                )
                meta["width"] = width
                meta["height"] = height
                assets.append(meta)
            except Exception as exc:
                log.warning(
                    f"    Failed to persist embedded image {asset_name}: {exc}"
                )
        return assets

    def _ensure_vision_rasters(
        self,
        pdf_path: Path,
        pages_data: List[Dict[str, Any]],
        total_pages: int,
    ) -> None:
        """
        Ensure vision pages have reusable PNG rasters on disk.

        Fresh Gemini runs already persist rasters. Cache hits with text but no
        PNG (legacy entries / deleted rasters) are backfilled here without
        calling Gemini again.
        """
        if not self.preserve_vision_assets and not self.use_cache:
            return

        from src.utils.vision_assets import vision_page_numbers

        missing: list[int] = []
        page_by_number = {int(p.get("page_number") or 0): p for p in pages_data}
        for page_number in vision_page_numbers(pages_data):
            page = page_by_number.get(page_number) or {}
            resolved = self.cache.resolve_vision_asset(pdf_path, page)
            if resolved is not None:
                page["vision_asset_path"] = str(resolved.resolve())
                if not page.get("vision_asset_name"):
                    page["vision_asset_name"] = resolved.name
                continue
            missing.append(page_number)

        if not missing:
            return

        log.info(
            f"  Backfilling {len(missing)} missing vision raster(s) "
            f"(no Gemini re-call)..."
        )
        with ProcessPoolExecutor(max_workers=self.max_processes) as process_executor:
            futures = {
                process_executor.submit(
                    _convert_page_wrapper,
                    (str(pdf_path), page_num, self.vision_asset_dpi),
                ): page_num
                for page_num in missing
            }
            for future in as_completed(futures):
                page_num, image = future.result()
                page = page_by_number.get(page_num)
                if page is None or image is None:
                    continue
                if image.mode != "RGB":
                    image = image.convert("RGB")
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                png_bytes = buffer.getvalue()
                try:
                    asset_meta = self.cache.write_vision_asset(
                        pdf_path,
                        page_num,
                        png_bytes,
                        total_pages=total_pages,
                    )
                    page.update(asset_meta)
                    if self.use_cache:
                        self.cache.save_page(pdf_path, page)
                except Exception as exc:
                    log.warning(
                        f"    Warning: Failed to backfill raster for page "
                        f"{page_num}: {exc}"
                    )
    
    def get_full_text(
        self,
        pdf_path: str,
        max_pages: int = None,
        prompt_template: Optional[str] = None,
    ) -> str:
        """
        Get full text content from PDF as a single string.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process
            prompt_template: Optional prompt template ID or custom prompt string
            
        Returns:
            Full text content with page markers
        """
        pages_data = self.parse_pdf(pdf_path, max_pages, prompt_template=prompt_template)
        
        full_text_parts = []
        for page_data in pages_data:
            page_num = page_data["page_number"]
            text = page_data["text"]
            method = page_data.get("method", "unknown")
            full_text_parts.append(f"\n--- 第 {page_num} 頁 ({method}) ---\n{text}\n")
        
        return "\n".join(full_text_parts)