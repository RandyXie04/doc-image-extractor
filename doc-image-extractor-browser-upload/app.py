from __future__ import annotations

import hmac
import io
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image, ImageOps


APP_TITLE = "文件圖片提取器"
SUPPORTED_TYPES = ["pdf", "docx"]
MAX_PREVIEW_IMAGES = 12
MAX_FILES_PER_BATCH = 10
MAX_TOTAL_UPLOAD_MB = 500
MAX_PDF_PAGES = 250
MAX_PDF_IMAGES = 1000
MAX_IMAGE_WIDTH = 12_000
MAX_IMAGE_HEIGHT = 12_000
MAX_DOCX_MEDIA_FILES = 1_000
MAX_DOCX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_DOCX_TOTAL_MEDIA_BYTES = 300 * 1024 * 1024
MAX_OUTPUT_BYTES = 500 * 1024 * 1024
AUTH_SESSION_SECONDS = 4 * 60 * 60
AUTH_LOCKOUT_SECONDS = 5 * 60
MAX_LOGIN_ATTEMPTS = 5


@dataclass
class ExtractedImage:
    path: Path
    source_file: str
    source_type: str
    page: int | None = None
    original_name: str | None = None


@dataclass
class ExtractionResult:
    source_file: str
    source_type: str
    images: list[ExtractedImage]
    warnings: list[str]


def get_secret(name: str) -> str | None:
    """優先讀取環境變數，否則讀取 Streamlit Secrets；未設定時回傳 None。"""
    environment_value = os.environ.get(name)
    if environment_value:
        return environment_value.strip()
    try:
        secret_value = st.secrets.get(name)
    except (FileNotFoundError, KeyError, RuntimeError):
        return None
    return str(secret_value).strip() if secret_value else None


def auth_is_valid() -> bool:
    """檢查目前瀏覽器工作階段是否仍在登入有效期內。"""
    authenticated_at = st.session_state.get("authenticated_at")
    if not st.session_state.get("authenticated") or not authenticated_at:
        return False
    if time.time() - float(authenticated_at) > AUTH_SESSION_SECONDS:
        st.session_state.pop("authenticated", None)
        st.session_state.pop("authenticated_at", None)
        return False
    return True


def render_auth_gate() -> bool:
    """顯示公開服務的密碼門檻；密碼只從 Streamlit Secrets 或環境變數讀取。"""
    expected_password = get_secret("APP_PASSWORD")
    if not expected_password:
        st.error("服務尚未完成安全設定。請在 Streamlit Cloud 的 App settings → Secrets 設定 APP_PASSWORD。")
        st.code('APP_PASSWORD = "請在 Streamlit Cloud Secrets 貼上你的共用密碼"', language="toml")
        st.caption("密碼只放在 Cloud Secrets，不要寫入 app.py、README 或 GitHub。")
        return False

    lockout_until = float(st.session_state.get("lockout_until", 0))
    if lockout_until > time.time():
        remaining = int(lockout_until - time.time()) + 1
        st.warning(f"登入失敗次數過多，請在約 {remaining} 秒後再試。")
        return False

    if auth_is_valid():
        return True

    st.markdown(
        '<section class="hero"><h1>文件圖片提取器</h1>'
        '<p>這是受保護的公開服務，請輸入存取密碼後使用。</p></section>',
        unsafe_allow_html=True,
    )
    with st.form("login_form", clear_on_submit=True):
        password = st.text_input("存取密碼", type="password", help="密碼由服務管理者另行提供。")
        submitted = st.form_submit_button("登入", type="primary", use_container_width=True)

    if submitted:
        is_match = hmac.compare_digest(password, expected_password)
        if is_match:
            st.session_state["authenticated"] = True
            st.session_state["authenticated_at"] = time.time()
            st.session_state["login_attempts"] = 0
            st.session_state.pop("lockout_until", None)
            st.rerun()
        else:
            attempts = int(st.session_state.get("login_attempts", 0)) + 1
            st.session_state["login_attempts"] = attempts
            if attempts >= MAX_LOGIN_ATTEMPTS:
                st.session_state["lockout_until"] = time.time() + AUTH_LOCKOUT_SECONDS
                st.session_state["login_attempts"] = 0
                st.error("登入失敗次數過多，已暫時鎖定登入。")
            else:
                st.error(f"密碼不正確，剩餘嘗試次數：{MAX_LOGIN_ATTEMPTS - attempts}。")
    return False


def safe_stem(filename: str) -> str:
    """建立適合用於輸出檔名的簡單 stem，避免路徑穿越。"""
    stem = Path(filename).stem.strip() or "document"
    return "".join(c if c.isalnum() or c in "._- ()[]" else "_" for c in stem)


def normalize_image(img: Image.Image, color_space: str = "") -> Image.Image:
    """依原始程式的色彩空間規則轉成可穩定輸出的 PNG。"""
    is_printing_channel = color_space in {"DeviceN", "DeviceCMYK"} or img.mode == "CMYK"

    if is_printing_channel:
        if img.mode in ("L", "1"):
            return ImageOps.invert(img.convert("L"))
        if img.mode == "CMYK":
            return ImageOps.invert(img.convert("RGB"))
        return ImageOps.invert(img.convert("L"))

    if img.mode in ("P", "PA", "LA", "RGBA"):
        return img.convert("RGBA" if "A" in img.mode else "RGB")
    if img.mode not in ("RGB", "L"):
        return img.convert("RGB")
    return img


def extract_images_from_pdf(
    pdf_path: Path,
    output_dir: Path,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[ExtractedImage], list[str]]:
    """從 PDF 內嵌圖片提取 PNG，保留原程式的 DeviceN／CMYK 校正邏輯。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    images: list[ExtractedImage] = []
    warnings: list[str] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return [], [f"無法開啟 PDF：{exc}"]

    total_pages = len(doc)
    pages_to_process = min(total_pages, MAX_PDF_PAGES)
    if total_pages > MAX_PDF_PAGES:
        warnings.append(f"PDF 共 {total_pages} 頁，為保護公開服務只處理前 {MAX_PDF_PAGES} 頁。")
    output_bytes = 0
    try:
        for page_index in range(pages_to_process):
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                if len(images) >= MAX_PDF_IMAGES:
                    warnings.append(f"已達 PDF 圖片上限 {MAX_PDF_IMAGES} 張，後續圖片已略過。")
                    break
                xref = img_info[0]
                cs_name = img_info[5] if len(img_info) > 5 else ""
                alt_cs = img_info[6] if len(img_info) > 6 else ""
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image or not base_image.get("image"):
                        continue

                    raw_bytes = base_image["image"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    if width < 10 or height < 10:
                        continue
                    if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                        warnings.append(
                            f"第 {page_index + 1} 頁圖片 {img_index + 1} 尺寸 {width}×{height} 超過上限，已略過。"
                        )
                        continue

                    img = Image.open(io.BytesIO(raw_bytes))
                    color_space = "DeviceN" if cs_name == "DeviceN" else alt_cs
                    img = normalize_image(img, color_space)
                    filename = f"page{page_index + 1:04d}_img{img_index + 1:03d}.png"
                    png_buffer = io.BytesIO()
                    img.save(png_buffer, format="PNG")
                    png_bytes = png_buffer.getvalue()
                    if output_bytes + len(png_bytes) > MAX_OUTPUT_BYTES:
                        warnings.append(f"PDF 輸出容量已達 {MAX_OUTPUT_BYTES // (1024 * 1024)} MB 上限，後續圖片已略過。")
                        break
                    output_bytes += len(png_bytes)
                    save_path = output_dir / filename
                    save_path.write_bytes(png_bytes)
                    images.append(
                        ExtractedImage(
                            path=save_path,
                            source_file=pdf_path.name,
                            source_type="PDF",
                            page=page_index + 1,
                            original_name=filename,
                        )
                    )
                except Exception as exc:
                    warnings.append(
                        f"第 {page_index + 1} 頁圖片 {img_index + 1} 提取失敗：{exc}"
                    )

            if progress:
                progress(page_index + 1, max(pages_to_process, 1))
            if len(images) >= MAX_PDF_IMAGES or output_bytes >= MAX_OUTPUT_BYTES:
                break
    finally:
        doc.close()

    if not images:
        warnings.append("PDF 中沒有找到可提取的內嵌圖片，或圖片尺寸過小。")
    return images, warnings


def extract_images_from_docx(
    docx_path: Path,
    output_dir: Path,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[ExtractedImage], list[str]]:
    """從 DOCX 的 word/media 目錄提取原始圖片，不重新壓縮。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    images: list[ExtractedImage] = []
    warnings: list[str] = []
    image_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
        ".emf", ".wmf", ".svg", ".webp",
    }

    if not zipfile.is_zipfile(docx_path):
        return [], ["檔案不是有效的 DOCX／ZIP 格式。"]

    try:
        with zipfile.ZipFile(docx_path, "r") as archive:
            media_entries = sorted(
                name for name in archive.namelist()
                if name.lower().startswith("word/media/") and not name.endswith("/")
            )
            if len(media_entries) > MAX_DOCX_MEDIA_FILES:
                warnings.append(f"DOCX 媒體檔案數超過 {MAX_DOCX_MEDIA_FILES} 個，只處理前 {MAX_DOCX_MEDIA_FILES} 個。")
                media_entries = media_entries[:MAX_DOCX_MEDIA_FILES]
            if not media_entries:
                return [], ["Word 文件的 word/media/ 目錄中沒有找到圖片。"]

            candidates = [
                name for name in media_entries if Path(name).suffix.lower() in image_extensions
            ]
            skipped = len(media_entries) - len(candidates)
            if skipped:
                warnings.append(f"已略過 {skipped} 個非圖片媒體檔案。")

            output_bytes = 0
            for index, entry in enumerate(candidates, start=1):
                info = archive.getinfo(entry)
                if info.file_size > MAX_DOCX_MEMBER_BYTES:
                    warnings.append(f"DOCX 媒體檔案 {Path(entry).name} 超過單檔大小上限，已略過。")
                    continue
                if output_bytes + info.file_size > MAX_DOCX_TOTAL_MEDIA_BYTES:
                    warnings.append(f"DOCX 媒體總解壓容量超過 {MAX_DOCX_TOTAL_MEDIA_BYTES // (1024 * 1024)} MB，後續檔案已略過。")
                    break
                data = archive.read(entry)
                if output_bytes + len(data) > MAX_OUTPUT_BYTES:
                    warnings.append(f"DOCX 輸出容量已達 {MAX_OUTPUT_BYTES // (1024 * 1024)} MB 上限，後續檔案已略過。")
                    break
                output_bytes += len(data)
                original_name = Path(entry).name
                destination = output_dir / original_name
                if destination.exists():
                    destination = output_dir / f"{destination.stem}_{index}{destination.suffix}"
                destination.write_bytes(data)
                images.append(
                    ExtractedImage(
                        path=destination,
                        source_file=docx_path.name,
                        source_type="DOCX",
                        original_name=original_name,
                    )
                )
                if progress:
                    progress(index, max(len(candidates), 1))
    except Exception as exc:
        return images, warnings + [f"讀取 DOCX 時發生錯誤：{exc}"]

    return images, warnings


def cleanup_session_storage(force: bool = False) -> None:
    """清理目前工作階段的原始上傳檔與提取結果。"""
    session_dir = st.session_state.get("extraction_dir")
    keep_temp = bool(st.session_state.get("keep_temp", False))
    if session_dir and (force or not keep_temp):
        shutil.rmtree(session_dir, ignore_errors=True)
    st.session_state.pop("extraction_results", None)
    st.session_state.pop("extraction_dir", None)


def make_zip(results: list[ExtractionResult]) -> bytes:
    """把所有提取結果包成單一 ZIP，並以來源檔案分目錄。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for result in results:
            folder = safe_stem(result.source_file)
            for item in result.images:
                archive.write(item.path, arcname=f"{folder}/{item.path.name}")
    buffer.seek(0)
    return buffer.getvalue()


def render_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink: #172033; --muted: #667085; --accent: #4f46e5; }
        .block-container { max-width: 1120px; padding-top: 2.5rem; padding-bottom: 3rem; }
        .hero { padding: 1.7rem 1.8rem; border-radius: 24px; color: white;
                background: linear-gradient(135deg, #1e1b4b 0%, #3730a3 54%, #6366f1 100%);
                box-shadow: 0 18px 45px rgba(49, 46, 129, .22); margin-bottom: 1.4rem; }
        .hero h1 { font-size: clamp(2rem, 4vw, 3.2rem); letter-spacing: -.04em; margin: 0 0 .45rem; }
        .hero p { opacity: .86; margin: 0; font-size: 1.02rem; }
        .section-card { border: 1px solid #e7e9f2; border-radius: 18px; padding: 1.1rem 1.2rem;
                        background: rgba(255,255,255,.68); margin: .7rem 0; }
        .small-note { color: #667085; font-size: .9rem; }
        .file-pill { display: inline-block; padding: .3rem .6rem; margin: .15rem; border-radius: 999px;
                     background: #eef2ff; color: #3730a3; font-size: .84rem; }
        div[data-testid="stFileUploader"] { border: 1.5px dashed #818cf8; border-radius: 18px; padding: .5rem; background: #f8faff; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="▣", layout="wide", initial_sidebar_state="expanded")
    render_styles()
    if not render_auth_gate():
        st.stop()

    st.markdown(
        '<section class="hero"><h1>文件圖片提取器</h1>'
        '<p>拖曳 PDF 或 Word 文件，快速取出內嵌圖片並下載成一個 ZIP 檔。</p></section>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        if st.button("登出", use_container_width=True):
            cleanup_session_storage(force=True)
            st.session_state.pop("authenticated", None)
            st.session_state.pop("authenticated_at", None)
            st.rerun()
        st.subheader("處理設定")
        keep_temp = st.checkbox("保留本次處理的暫存檔", value=False, help="關閉時，工作階段結束或重新處理後會清除暫存內容。")
        st.divider()
        st.markdown("**支援格式**")
        st.markdown('<span class="file-pill">PDF → PNG</span><span class="file-pill">DOCX → 原始格式</span>', unsafe_allow_html=True)
        st.caption("PDF 會輸出無損 PNG；DOCX 會保留文件內嵌圖片的原始副檔名。")
        st.divider()
        st.caption("本工具只在目前 Streamlit 執行環境處理檔案，不會主動上傳到第三方服務。")

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "選擇或拖曳檔案到這裡",
        type=SUPPORTED_TYPES,
        accept_multiple_files=True,
        help="可一次上傳多個 PDF 或 DOCX。暫不支援舊版 .doc。",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if not uploaded_files:
        st.info("請先上傳至少一個 PDF 或 DOCX 檔案。")
        st.markdown(
            """
            <div class="section-card">
            <strong>使用方式</strong><br>
            1. 將檔案拖曳至上方區域。<br>
            2. 點選「開始提取圖片」。<br>
            3. 預覽結果並下載 ZIP；不同來源文件會各自放在 ZIP 子資料夾中。
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.write(f"已選取 **{len(uploaded_files)}** 個檔案。")
    total_upload_bytes = sum(uploaded.size for uploaded in uploaded_files)
    if len(uploaded_files) > MAX_FILES_PER_BATCH:
        st.error(f"單次最多處理 {MAX_FILES_PER_BATCH} 個檔案。")
        return
    if total_upload_bytes > MAX_TOTAL_UPLOAD_MB * 1024 * 1024:
        st.error(f"單次上傳總容量不可超過 {MAX_TOTAL_UPLOAD_MB} MB。")
        return

    if st.button("開始提取圖片", type="primary", use_container_width=True):
        cleanup_session_storage(force=False)
        session_dir = Path(tempfile.mkdtemp(prefix="doc_image_extractor_"))
        results: list[ExtractionResult] = []
        overall_progress = st.progress(0, text="準備處理…")
        status = st.empty()

        try:
            for file_index, uploaded in enumerate(uploaded_files):
                source_name = Path(uploaded.name).name
                suffix = Path(source_name).suffix.lower()
                input_path = session_dir / f"input_{file_index}{suffix}"
                input_path.write_bytes(uploaded.getbuffer())
                output_dir = session_dir / f"images_{file_index}_{safe_stem(source_name)}"
                status.info(f"正在處理：{source_name}")

                def update_progress(current: int, total: int, index: int = file_index) -> None:
                    fraction = (index + current / max(total, 1)) / len(uploaded_files)
                    overall_progress.progress(min(fraction, 1.0), text=f"處理中：{source_name}")

                try:
                    if suffix == ".pdf":
                        images, warnings = extract_images_from_pdf(input_path, output_dir, update_progress)
                        source_type = "PDF"
                    else:
                        images, warnings = extract_images_from_docx(input_path, output_dir, update_progress)
                        source_type = "DOCX"
                    results.append(ExtractionResult(source_name, source_type, images, warnings))
                finally:
                    input_path.unlink(missing_ok=True)

            overall_progress.progress(1.0, text="處理完成")
            status.success("所有檔案處理完成。")
            st.session_state["extraction_results"] = results
            st.session_state["extraction_dir"] = session_dir
            st.session_state["keep_temp"] = keep_temp
        except Exception as exc:
            status.error(f"處理失敗：{exc}")
            shutil.rmtree(session_dir, ignore_errors=True)
            st.session_state.pop("extraction_results", None)
            st.session_state.pop("extraction_dir", None)

    results = st.session_state.get("extraction_results", [])
    if not results:
        return

    total_images = sum(len(result.images) for result in results)
    total_warnings = sum(len(result.warnings) for result in results)
    col1, col2, col3 = st.columns(3)
    col1.metric("處理文件", len(results))
    col2.metric("提取圖片", total_images)
    col3.metric("警告訊息", total_warnings)

    st.subheader("處理結果")
    for result in results:
        with st.expander(f"{result.source_file} · {len(result.images)} 張圖片", expanded=True):
            if result.warnings:
                for warning in result.warnings:
                    st.warning(warning)
            if result.images:
                preview_items = result.images[:MAX_PREVIEW_IMAGES]
                preview_cols = st.columns(min(4, len(preview_items)))
                for index, item in enumerate(preview_items):
                    with preview_cols[index % len(preview_cols)]:
                        if item.path.suffix.lower() in {".svg", ".emf", ".wmf"}:
                            st.caption(item.path.name)
                            st.info("此格式已打包下載，預覽略過。")
                        else:
                            try:
                                st.image(str(item.path), caption=item.path.name, use_container_width=True)
                            except Exception:
                                st.caption(f"{item.path.name}（無法在瀏覽器預覽，仍可下載）")
                if len(result.images) > MAX_PREVIEW_IMAGES:
                    st.caption(f"僅預覽前 {MAX_PREVIEW_IMAGES} 張，完整內容請下載 ZIP。")
            else:
                st.info("此文件沒有成功提取圖片。")

    archive_bytes = make_zip(results)
    base_name = safe_stem(results[0].source_file) if len(results) == 1 else "extracted_images"
    st.download_button(
        "下載全部圖片 ZIP",
        data=archive_bytes,
        file_name=f"{base_name}_images.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
        help="ZIP 內會依來源文件建立子資料夾，避免同名圖片互相覆蓋。",
    )
    st.caption(f"ZIP 大小：{len(archive_bytes) / 1024:.1f} KB。檔案只會在你點擊下載時傳回目前瀏覽器。")
    if st.button("清除本次結果與暫存檔", use_container_width=True):
        cleanup_session_storage(force=True)
        st.rerun()
    st.caption("原始上傳檔會在提取完成後立即移除；提取結果會在重新處理、登出或按下清除按鈕時移除。")


if __name__ == "__main__":
    main()
