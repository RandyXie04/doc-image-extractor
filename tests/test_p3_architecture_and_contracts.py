# -*- coding: utf-8 -*-
"""
Phase P3 Architecture & Contract Verification Suite (`tests/test_p3_architecture_and_contracts.py`)
====================================================================================================
Verifies:
1. Risk 1 & 5: `build_ocr_layout_contracts` in `process_ocr.py` enforces strict `LayoutRecordContract`.
2. Risk 2: Per-book image directory isolation (`images/{stem}/`) prevents cross-book figure overwrite.
3. Risk 3: `--style_mapping_file` JSON transport and `is_meaningful_progress_line` stdout filter.
4. P2-A..P2-D & Risk 4: Full-stack Pydantic v2 -> TypeScript contract sync and FastAPI `APIRouter` modularization.
"""

from __future__ import annotations
import json
from pathlib import Path
import fitz
from PIL import Image
import pytest
from pydantic import ValidationError


def test_p3_1_process_ocr_layout_contracts_validation() -> None:
    """Risk 1: Pure OCR assembled blocks are validated against strict LayoutRecordContract."""
    from src.scripts.process_ocr import build_ocr_layout_contracts

    pages_data = [
        {
            "page_num": 1,
            "page_size": [1000, 1400],
            "body": [
                {
                    "orig_idx": 0,
                    "md": "## 1 臨床診斷標準",
                    "block": {"original_label": "section-header", "bbox": [80, 100, 420, 135]},
                },
                {
                    "orig_idx": 1,
                    "md": "| 組別 | 例數 |\n| --- | --- |\n| 治療組 | 43 |",
                    "block": {"original_label": "table", "bbox": [80, 160, 500, 260]},
                },
                {
                    "orig_idx": 2,
                    "md": "![img]()",
                    "block": {"original_label": "figure", "bbox": [100, 280, 450, 480]},
                },
                {
                    "orig_idx": 3,
                    "md": "兩組患者治療後指標均顯著改善。",
                    "block": {"original_label": "text", "bbox": [80, 500, 500, 540]},
                },
            ],
            "footnotes": [
                {"id": "1", "content": "本研究經醫學倫理委員會批准。"},
            ],
        }
    ]

    contracts = build_ocr_layout_contracts(pages_data)
    assert len(contracts) == 5
    types = [c.type for c in contracts]
    assert types == ["heading", "table", "figure", "paragraph", "footnote"]


def test_p3_2_per_book_image_namespace_isolation(tmp_path: Path) -> None:
    """Risk 2: Sequential books with images on page 1 must not overwrite each other's image_p1_0.png."""
    from src.scripts.book_layout_extractor import process_book_vector_pdf

    def _make_pdf_with_color_image(pdf_path: Path, rgb: tuple[int, int, int]) -> None:
        from typing import Any
        doc: Any = fitz.open()
        page: Any = doc.new_page(width=500, height=700)
        page.insert_text(fitz.Point(60, 80), "正文標題與圖表測試", fontname="china-ts", fontsize=12.0)
        img = Image.new("RGB", (90, 90), color=rgb)
        img_path = tmp_path / f"sample_{rgb[0]}.png"
        img.save(img_path)
        page.insert_image(fitz.Rect(60, 120, 210, 270), filename=str(img_path))
        doc.save(str(pdf_path))
        doc.close()

    pdf_a = tmp_path / "book_alpha.pdf"
    pdf_b = tmp_path / "book_beta.pdf"
    _make_pdf_with_color_image(pdf_a, (220, 20, 60))
    _make_pdf_with_color_image(pdf_b, (20, 180, 90))

    out_dir = tmp_path / "output"
    md_a_str, _ = process_book_vector_pdf(str(pdf_a), str(out_dir), output_stem="book_alpha", ai_kaiti=False)
    md_b_str, _ = process_book_vector_pdf(str(pdf_b), str(out_dir), output_stem="book_beta", ai_kaiti=False)

    md_a = Path(md_a_str).read_text(encoding="utf-8")
    md_b = Path(md_b_str).read_text(encoding="utf-8")

    assert "![](images/book_alpha/image_p1_0.png)" in md_a
    assert "![](images/book_beta/image_p1_0.png)" in md_b

    img_a_path = out_dir / "images" / "book_alpha" / "image_p1_0.png"
    img_b_path = out_dir / "images" / "book_beta" / "image_p1_0.png"
    assert img_a_path.exists()
    assert img_b_path.exists()

    with Image.open(img_a_path) as im_a, Image.open(img_b_path) as im_b:
        px_a = im_a.convert("RGB").getpixel((10, 10))
        px_b = im_b.convert("RGB").getpixel((10, 10))
        assert px_a != px_b, "Book B must not overwrite Book A's extracted image_p1_0.png"


def test_p3_2_progress_line_filter_and_style_mapping_file(tmp_path: Path) -> None:
    """Risk 3: Subprocess stdout noise filtering & file-backed style_mapping JSON loading."""
    from src.web.app import is_meaningful_progress_line

    assert is_meaningful_progress_line("[INFO] 正在處理第 1~10 頁 (共 50 頁)...") is True
    assert is_meaningful_progress_line("正在套用樣式並產生 Word (.docx) 文件...") is True
    assert is_meaningful_progress_line("UserWarning: torch.meshgrid: in an upcoming release") is False
    assert is_meaningful_progress_line("C:\\Python312\\Lib\\site-packages\\transformers\\modeling.py:123") is False
    assert is_meaningful_progress_line("Traceback (most recent call last):") is False

    # Verify style_mapping_file JSON round-trip with quotes and CJK characters
    complex_style_map = {
        "FZShuSong-Z01 (10.5pt)": {"role": "正文", "docx_style": '內文 "標準" 樣式'},
        "FZHei-B01 (16.0pt)": {"role": "H1", "docx_style": "標題 1"},
    }
    sm_file = tmp_path / "style_mapping_test.json"
    sm_file.write_text(json.dumps(complex_style_map, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(sm_file.read_text(encoding="utf-8"))
    assert loaded["FZShuSong-Z01 (10.5pt)"]["docx_style"] == '內文 "標準" 樣式'


def test_p3_3_and_p3_4_expanded_schemas_and_modular_routers() -> None:
    """P2-A..P2-D & Risk 4: Expanded schemas reject unknown keys, TS contracts are in sync, and routers are mounted."""
    from src.web.schemas import (
        FontScanResponse,
        FontMappingSaveRequest,
        OcrProgressResponse,
        PodVlmContinuationResponse,
        FormulaTaskStatusResponse,
        HardwareStatusResponse,
    )
    from src.scripts.generate_ts_contracts import sync_typescript_contracts
    from src.web.app import app

    # 1. Verify TS contracts are 100% synced and contain P2-A..P2-D interfaces
    ts_path = sync_typescript_contracts(check_only=True)
    ts_text = ts_path.read_text(encoding="utf-8")
    for expected_symbol in (
        "export interface OcrProgressResponse",
        "export interface FontScanResponse",
        "export interface FontMappingSaveRequest",
        "export interface PodVlmContinuationResponse",
        "export interface FormulaTaskStatusResponse",
        "export interface HardwareStatusResponse",
        "export type OcrWorkbenchPhase =",
    ):
        assert expected_symbol in ts_text, f"Missing {expected_symbol} in contracts.ts"

    # 2. Verify extra="forbid" rejects hallucinated keys on new schemas
    valid_prog = OcrProgressResponse(progress=45, message="處理中", status="processing")
    assert valid_prog.progress == 45

    with pytest.raises(ValidationError):
        OcrProgressResponse.model_validate(
            {"progress": 45, "message": "處理中", "status": "processing", "hallucinated_key": 1}
        )

    valid_scan = FontScanResponse.model_validate(
        {
            "fonts": [{"name": "SimSun (10.5pt)", "full_name": "SimSun", "size_pt": 10.5}],
            "docx_styles": ["標題 1", "內文"],
            "default_roles": ["H1", "正文"],
        }
    )
    assert len(valid_scan.fonts) == 1

    valid_save = FontMappingSaveRequest.model_validate(
        {"mapping": {"SimSun (10.5pt)": {"role": "正文", "docx_style": "內文"}}, "remove_keys": []}
    )
    assert "SimSun (10.5pt)" in valid_save.mapping

    valid_vlm = PodVlmContinuationResponse(
        session_id="pod_vlm_123",
        result={"total_sections": 3},
        download_docx_url="/api/pod/download/pod_vlm_123/Book_VLM_Continued.docx",
        download_md_url="/api/pod/download/pod_vlm_123/Book_VLM_Continued.md",
        audit_report_url="/api/pod/download/pod_vlm_123/vlm_audit_report.json",
    )
    assert valid_vlm.status == "success"

    valid_formula = FormulaTaskStatusResponse(
        status="processing", progress=60, message="擷取公式中", mode="formula"
    )
    assert valid_formula.progress == 60

    valid_hw = HardwareStatusResponse(target_accelerator="CPU", is_accelerated=False)
    assert valid_hw.is_accelerated is False

    # 3. Verify modularized APIRouters (`pod_router` & `system_router`) are mounted on `app`
    registered_paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if isinstance(p, str):
            registered_paths.add(p)
        orig_router = getattr(r, "original_router", None)
        if orig_router is not None:
            for sub_r in getattr(orig_router, "routes", []):
                sub_p = getattr(sub_r, "path", None)
                if isinstance(sub_p, str):
                    registered_paths.add(sub_p)

    for required_route in (
        "/api/pod/1_extract_raw",
        "/api/pod/2_compile_blueprint",
        "/api/pod/3_propagate_and_validate",
        "/api/pod/vlm_continuation",
        "/api/hardware_status",
        "/api/version",
        "/api/founder/repair",
        "/api/upload_and_run_ocr",
    ):
        assert required_route in registered_paths, f"Missing route {required_route} after APIRouter modularization"


def test_p3_5_output_js_type_safety_and_attribute_escaping() -> None:
    """Verifies src/web/static/js/output.js enforces @ts-check JSDoc annotations and escapes retryHandler quotes."""
    output_js_path = Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "js" / "output.js"
    assert output_js_path.exists()
    content = output_js_path.read_text(encoding="utf-8")

    assert "// @ts-check" in content
    assert "@typedef {Object} NativeSaveOptions" in content
    assert "@typedef {Object} ToolboxGlobal" in content
    assert 'onclick="${tb.escape(retryHandler)}"' in content
    assert "err instanceof Error ? err.message : String(err)" in content
    assert "e instanceof Error ? e.message : String(e)" in content


def test_p3_6_viewport_manager_and_responsive_layout() -> None:
    """Verifies responsive viewport manager module, TypeScript scaffolding, and responsive CSS tokens."""
    base_dir = Path(__file__).resolve().parent.parent

    # 1. Verify viewport_manager.js
    vp_path = base_dir / "src" / "web" / "static" / "js" / "viewport_manager.js"
    assert vp_path.exists(), "viewport_manager.js must exist"
    vp_content = vp_path.read_text(encoding="utf-8")
    assert "// @ts-check" in vp_content
    assert "@typedef {'mobile' | 'tablet' | 'desktop' | 'ultrawide'} DeviceType" in vp_content
    assert "computeDevice" in vp_content
    assert "syncDOMAttributes" in vp_content
    assert "win.viewportManager = api" in vp_content

    # 2. Verify frontend TypeScript layout scaffold
    layout_dir = base_dir / "frontend" / "src" / "layout"
    for expected_file in ("viewportTypes.ts", "useViewport.ts", "ResponsiveShell.ts", "index.ts"):
        assert (layout_dir / expected_file).exists(), f"Missing {expected_file} in frontend/src/layout/"

    ts_types = (layout_dir / "viewportTypes.ts").read_text(encoding="utf-8")
    assert "export type DeviceCategory = 'mobile' | 'tablet' | 'desktop' | 'ultrawide'" in ts_types
    assert "export interface ViewportState" in ts_types

    # 3. Verify sidebar.css responsive tokens & drawer rules
    sidebar_css_path = base_dir / "src" / "web" / "static" / "sidebar.css"
    css_content = sidebar_css_path.read_text(encoding="utf-8")
    assert "--container-max-w" in css_content
    assert "--gutter-x" in css_content
    assert "@media (min-width: 1440px)" in css_content
    assert "@media (min-width: 1920px)" in css_content
    assert "#sidebarBackdrop" in css_content
    assert "#mobileNavbar" in css_content

    # 4. Verify sidebar.js mobile drawer integration
    sidebar_js_path = base_dir / "src" / "web" / "static" / "sidebar.js"
    js_content = sidebar_js_path.read_text(encoding="utf-8")
    assert "sidebarBackdrop" in js_content
    assert "sidebarToggleBtn" in js_content
    assert "viewport_manager.js" in js_content

    # 5. Verify all static HTML pages reference viewport_manager.js
    static_dir = base_dir / "src" / "web" / "static"
    for page_name in (
        "ocr_pipeline.html",
        "pod_studio.html",
        "formula.html",
        "extract_images.html",
        "founder_repair.html",
        "index.html",
    ):
        page_content = (static_dir / page_name).read_text(encoding="utf-8")
        assert 'src="/static/js/viewport_manager.js"' in page_content, f"{page_name} missing viewport_manager.js"


