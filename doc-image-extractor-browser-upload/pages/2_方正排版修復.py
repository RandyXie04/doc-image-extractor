from __future__ import annotations

import io
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# 加入 Founder Fonts 修正腳本目錄至 sys.path
current_dir = Path(__file__).resolve().parent
app_dir = current_dir.parent

# 優先讀取專案內建模組 (GitHub/雲端部署支援)，若無則回退至本機路徑
search_paths = [
    app_dir / "founder_tools",
    app_dir.parent / "founder_tools",
    app_dir.parents[2] / "Founder Fonts_修正腳本",
    Path(r"C:\Users\sonbo\Desktop\書籍轉檔公式提取／word裁切邊界包\Founder Fonts_修正腳本"),
]
founder_dir = next((p for p in search_paths if p.exists()), app_dir / "founder_tools")

if str(founder_dir) not in sys.path:
    sys.path.insert(0, str(founder_dir))

# 引入核心修復函數
try:
    from fix_founder_fonts import clean_founder_text, repair_docx_file, repair_pdf_file
except ImportError as e:
    st.error(f"無法載入方正排版核心修復模組：{e}。目錄路徑：{founder_dir}")
    st.stop()


def render_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink: #172033; --muted: #667085; --accent: #0284c7; }
        .block-container { max-width: 1120px; padding-top: 2.2rem; padding-bottom: 3rem; }
        .hero-repair {
            padding: 1.6rem 1.8rem; border-radius: 24px; color: white;
            background: linear-gradient(135deg, #0f172a 0%, #0369a1 50%, #0284c7 100%);
            box-shadow: 0 18px 45px rgba(2, 132, 199, .22); margin-bottom: 1.4rem;
        }
        .hero-repair h1 { font-size: clamp(1.8rem, 3.8vw, 2.8rem); letter-spacing: -.03em; margin: 0 0 .4rem; }
        .hero-repair p { opacity: .88; margin: 0; font-size: 1.02rem; }
        .section-card {
            border: 1px solid #e2e8f0; border-radius: 18px; padding: 1.2rem 1.3rem;
            background: rgba(255,255,255,.8); margin: .8rem 0; box-shadow: 0 2px 8px rgba(0,0,0,.03);
        }
        .pill-badge {
            display: inline-block; padding: .25rem .55rem; margin: .15rem; border-radius: 999px;
            background: #e0f2fe; color: #0369a1; font-size: .82rem; font-weight: 500;
        }
        .log-terminal {
            background-color: #0f172a; color: #38bdf8; font-family: 'Consolas', 'Courier New', monospace;
            padding: 1rem; border-radius: 12px; font-size: .88rem; max-height: 260px;
            overflow-y: auto; white-space: pre-wrap; line-height: 1.45; border: 1px solid #1e293b;
        }
        div[data-testid="stFileUploader"] {
            border: 1.5px dashed #38bdf8; border-radius: 18px; padding: .5rem; background: #f0f9ff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def add_log(message: str) -> None:
    if "founder_logs" not in st.session_state:
        st.session_state["founder_logs"] = []
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state["founder_logs"].append(f"[{timestamp}] {message}")


def main() -> None:
    st.set_page_config(
        page_title="方正排版標點符號修復",
        page_icon="🛠️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_styles()

    if "founder_logs" not in st.session_state:
        st.session_state["founder_logs"] = [
            f"[{datetime.now().strftime('%H:%M:%S')}] 系統就緒：方正排版 CMap 標點修復模組已載入。"
        ]

    # Hero 橫幅
    st.markdown(
        """
        <section class="hero-repair">
            <h1>🛠️ 方正排版 PDF / Word 標點符號自動修復工具</h1>
            <p>自動還原方正排版系統 (Founder Bookmaker / InDesign) 匯出 PDF 產生的 ToUnicode CMap 編碼缺陷，修復彝文字母、圈號數字 ⑪~㊿ 與中英文標點。</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    # 側邊欄：修復規則參考與狀態
    with st.sidebar:
        st.page_link("app.py", label="返回工具箱首頁", icon="🏠")
        st.divider()
        st.subheader("📌 支援修復規則對照")
        st.markdown(
            """
            <span class="pill-badge">ꎬ → ， (逗號)</span>
            <span class="pill-badge">ꎮ → 。 (句號)</span>
            <span class="pill-badge">ꎻ → ； (分號)</span>
            <span class="pill-badge">ꎺ → ： (冒號)</span>
            <span class="pill-badge">ꎹ → ！ (驚嘆號)</span>
            <span class="pill-badge">ꎸ → ？ (問號)</span>
            <span class="pill-badge">« » → 《 》 (書名號)</span>
            <span class="pill-badge">PUA → ⑪~㊿ (圈號)</span>
            <span class="pill-badge">PUA → · (間隔號)</span>
            <span class="pill-badge">PUA → …… (省略號)</span>
            <span class="pill-badge">PUA → 喎 (中醫字)</span>
            """,
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("支援演算法：GBK 全形位移自動解碼 + Unicode 私用區序列拼合。")
        if st.button("清空執行日誌", use_container_width=True):
            st.session_state["founder_logs"] = [
                f"[{datetime.now().strftime('%H:%M:%S')}] 日誌已重置。"
            ]
            st.rerun()

    # 功能區 1: ⚡ 即時文字 / 剪貼簿文字修復
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("⚡ 快速功能：即時文字 / 剪貼簿修復")
    st.caption("貼上含有方正亂碼的文字，點選修復後即可即時預覽、統計並複製乾淨標點。")

    col_input, col_output = st.columns(2)

    with col_input:
        raw_text = st.text_area(
            "輸入或貼上含有方正亂碼的文字：",
            height=200,
            placeholder="例如：本草綱目«卷一»ꎬ凡例ꎮ氣味甘平ꎻ無毒ꎺ...",
            key="clip_input_area",
        )
        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            do_repair_text = st.button("📋 一鍵修復文字", type="primary", use_container_width=True)
        with btn_col2:
            if st.button("🧹 清空輸入", use_container_width=True):
                st.session_state["clip_input_area"] = ""
                st.rerun()

    repaired_text = ""
    if do_repair_text and raw_text:
        repaired_text = clean_founder_text(raw_text)
        st.session_state["last_repaired_text"] = repaired_text
        diff_count = sum(1 for a, b in zip(raw_text, repaired_text) if a != b) + abs(len(raw_text) - len(repaired_text))
        add_log(f"即時文字修復完成：處理 {len(raw_text)} 字元，還原/替換約 {diff_count} 處標點與符號。")

    current_output = st.session_state.get("last_repaired_text", "")

    with col_output:
        st.text_area(
            "修復後標準中文標點：",
            value=current_output,
            height=200,
            key="clip_output_area",
            help="點擊右上角複製按鈕或直接選取複製後貼上 Word。",
        )
        if current_output:
            st.caption(f"字數統計：原始 {len(raw_text)} 字 ➔ 修復後 {len(current_output)} 字")
            st.download_button(
                "📥 下載修復純文字檔 (.txt)",
                data=current_output.encode("utf-8"),
                file_name="已修復_方正文字.txt",
                mime="text/plain",
                use_container_width=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)

    # 功能區 2: 📁 檔案修復 (Word / PDF / TXT)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📁 檔案修復：選擇 Word、PDF 或純文字檔案")
    st.caption("支援 .docx (段落與表格全文置換)、.pdf (萃取並重構排版 DOCX 及 TXT)、.txt。")

    uploaded_file = st.file_uploader(
        "選擇要修復的檔案",
        type=["docx", "pdf", "txt"],
        help="單次選擇一個檔案進行修復轉換。",
    )

    if uploaded_file:
        file_name = uploaded_file.name
        file_ext = Path(file_name).suffix.lower()
        st.write(f"已選取檔案：**{file_name}** ({uploaded_file.size / 1024:.1f} KB)")

        if st.button("🚀 開始執行檔案修復", type="primary", use_container_width=True):
            progress_bar = st.progress(0, text="準備進行修復...")
            status_placeholder = st.empty()

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_input = Path(temp_dir) / file_name
                temp_input.write_bytes(uploaded_file.getvalue())

                try:
                    progress_bar.progress(25, text=f"正在解析並修復 {file_name}...")
                    add_log(f"開始處理檔案: {file_name}")

                    if file_ext == ".docx":
                        temp_output = Path(temp_dir) / f"{temp_input.stem}_已修復.docx"
                        out_path = repair_docx_file(str(temp_input), str(temp_output))
                        progress_bar.progress(85, text="讀取修復結果...")

                        if out_path and os.path.exists(out_path):
                            repaired_bytes = Path(out_path).read_bytes()
                            add_log(f"Word 檔案修復成功：已更新所有段落與表格文字。")
                            status_placeholder.success("🎉 Word 檔案已成功修復！")
                            st.download_button(
                                "📥 下載修復後的 Word 檔 (.docx)",
                                data=repaired_bytes,
                                file_name=f"{temp_input.stem}_已修復.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                type="primary",
                                use_container_width=True,
                            )

                    elif file_ext == ".pdf":
                        temp_txt = Path(temp_dir) / f"{temp_input.stem}_修復純文字.txt"
                        temp_docx = Path(temp_dir) / f"{temp_input.stem}_修復文字稿.docx"
                        txt_out, docx_out = repair_pdf_file(str(temp_input), str(temp_txt), str(temp_docx))
                        progress_bar.progress(85, text="整理輸出成品...")

                        if txt_out and os.path.exists(txt_out) and docx_out and os.path.exists(docx_out):
                            txt_bytes = Path(txt_out).read_bytes()
                            docx_bytes = Path(docx_out).read_bytes()
                            add_log(f"PDF 檔案修復成功：已產出 TXT 與 DOCX 排版稿。")
                            status_placeholder.success("🎉 PDF 檔案已修復並轉換完成！")

                            d_col1, d_col2 = st.columns(2)
                            with d_col1:
                                st.download_button(
                                    "📄 下載修復純文字 (.txt)",
                                    data=txt_bytes,
                                    file_name=f"{temp_input.stem}_修復純文字.txt",
                                    mime="text/plain",
                                    use_container_width=True,
                                )
                            with d_col2:
                                st.download_button(
                                    "📘 下載修復 Word 檔 (.docx)",
                                    data=docx_bytes,
                                    file_name=f"{temp_input.stem}_修復文字稿.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    type="primary",
                                    use_container_width=True,
                                )

                    elif file_ext == ".txt":
                        raw_content = temp_input.read_text(encoding="utf-8", errors="ignore")
                        cleaned_content = clean_founder_text(raw_content)
                        txt_bytes = cleaned_content.encode("utf-8")
                        add_log(f"純文字檔修復成功：長度 {len(cleaned_content)} 字元。")
                        status_placeholder.success("🎉 純文字檔案已修復完成！")

                        st.download_button(
                            "📥 下載修復純文字檔 (.txt)",
                            data=txt_bytes,
                            file_name=f"{temp_input.stem}_已修復.txt",
                            mime="text/plain",
                            type="primary",
                            use_container_width=True,
                        )

                    progress_bar.progress(100, text="處理完成！")

                except Exception as exc:
                    status_placeholder.error(f"修復過程發生錯誤：{exc}")
                    add_log(f"錯誤：{exc}")

    st.markdown('</div>', unsafe_allow_html=True)

    # 功能區 3: 執行紀錄 (Execution Log Terminal)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📋 執行紀錄 (Execution Log)")
    logs_str = "\n".join(st.session_state.get("founder_logs", []))
    st.markdown(f'<div class="log-terminal">{logs_str}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
