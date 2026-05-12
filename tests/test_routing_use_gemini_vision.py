"""Unit tests for PyMuPDF vs Gemini vision routing (no API calls)."""

from unittest.mock import MagicMock

from src.utils.pdf_parser import _detect_visual_structure_signals, routing_use_gemini_vision


def test_routing_long_text_no_visual_uses_pymupdf() -> None:
    """Typical body text without chart/table signals stays on PyMuPDF."""
    assert not routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=False,
        text_density_threshold=0.02,
        gemini_on_visual_structure=True,
        gemini_if_chars_below=55,
        density=0.0001,
        text="x" * 200,
        has_visual_structure=False,
    )


def test_routing_empty_text_uses_gemini() -> None:
    assert routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=False,
        text_density_threshold=0.02,
        gemini_on_visual_structure=False,
        gemini_if_chars_below=55,
        density=0.0,
        text="   ",
        has_visual_structure=False,
    )


def test_routing_short_text_uses_gemini() -> None:
    assert routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=False,
        text_density_threshold=0.02,
        gemini_on_visual_structure=False,
        gemini_if_chars_below=55,
        density=0.5,
        text="short",
        has_visual_structure=False,
    )


def test_routing_visual_structure_when_enabled() -> None:
    long_text = "word " * 30
    assert routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=False,
        text_density_threshold=0.02,
        gemini_on_visual_structure=True,
        gemini_if_chars_below=55,
        density=0.01,
        text=long_text,
        has_visual_structure=True,
    )


def test_routing_visual_structure_disabled_ignores_flag() -> None:
    long_text = "word " * 30
    assert not routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=False,
        text_density_threshold=0.02,
        gemini_on_visual_structure=False,
        gemini_if_chars_below=55,
        density=0.001,
        text=long_text,
        has_visual_structure=True,
    )


def test_routing_legacy_low_density_when_enabled() -> None:
    assert routing_use_gemini_vision(
        force_pymupdf=False,
        gemini_on_low_text_density=True,
        text_density_threshold=0.02,
        gemini_on_visual_structure=False,
        gemini_if_chars_below=55,
        density=0.001,
        text="x" * 200,
        has_visual_structure=False,
    )


def test_routing_force_pymupdf_never_gemini() -> None:
    assert not routing_use_gemini_vision(
        force_pymupdf=True,
        gemini_on_low_text_density=True,
        text_density_threshold=0.000001,
        gemini_on_visual_structure=True,
        gemini_if_chars_below=999999,
        density=0.0,
        text="",
        has_visual_structure=True,
    )


def test_detect_tabular_text_signal() -> None:
    page = MagicMock()
    page.rect.width = 400.0
    page.rect.height = 600.0
    page.get_drawings.return_value = []
    page.get_images.return_value = []
    ok, tags = _detect_visual_structure_signals(
        page,
        "col1\tcol2\tcol3",
        vector_path_min=40,
        embedded_image_area_ratio_min=0.02,
    )
    assert ok is True
    assert "tabular_text" in tags


def test_detect_vector_graphics_signal() -> None:
    page = MagicMock()
    page.rect.width = 400.0
    page.rect.height = 600.0
    page.get_drawings.return_value = [{"type": "l"} for _ in range(50)]
    page.get_images.return_value = []
    ok, tags = _detect_visual_structure_signals(
        page,
        "plain text " * 20,
        vector_path_min=40,
        embedded_image_area_ratio_min=0.02,
    )
    assert ok is True
    assert "vector_graphics" in tags


def test_detect_large_embedded_image_signal() -> None:
    page = MagicMock()
    page.rect.width = 400.0
    page.rect.height = 600.0
    page.get_drawings.return_value = []
    page.get_images.return_value = [(7, 0, 0, 0, 0, 0, 0)]
    rect = MagicMock()
    rect.width = 200.0
    rect.height = 300.0
    page.get_image_rects.return_value = [rect]
    ok, tags = _detect_visual_structure_signals(
        page,
        "plain text " * 20,
        vector_path_min=400,
        embedded_image_area_ratio_min=0.2,
    )
    assert ok is True
    assert "large_embedded_image" in tags


def test_detect_any_image_when_ratio_min_zero() -> None:
    page = MagicMock()
    page.rect.width = 400.0
    page.rect.height = 600.0
    page.get_drawings.return_value = []
    page.get_images.return_value = [(7, 0, 0, 0, 0, 0, 0)]
    ok, tags = _detect_visual_structure_signals(
        page,
        "plain text " * 20,
        vector_path_min=9999,
        embedded_image_area_ratio_min=0.0,
    )
    assert ok is True
    assert "embedded_image" in tags
