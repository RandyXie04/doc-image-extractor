from __future__ import annotations

import io
import logging
import os
import shutil
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

# 引入核心校註引擎模組
try:
    from auto_footnote import AutoFootnoteEngine
    from core.annotation_profile import AnnotationProfile
    from core.footnote_matcher import FootnoteMatcher
    from core.preflight_auditor import PreflightAuditor
    from core.openxml_builder import OpenXMLBuilder
except ImportError as e:
    st.error(f"無法載入自動化校註核心模組：{e}。請檢查路徑：{founder_dir}")
    st.stop()


def render_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink: #172033; --muted: #667085; --accent: #7c3aed; }
        .block-container { max-width: 1120px; padding-top: 2.2rem; padding-bottom: 3rem; }
        .hero-footnote {
            padding: 1.6rem 1.8rem; border-radius: 24px; color: white;
            background: linear-gradient(135deg, #1e1b4b 0%, #581c87 50%, #7c3aed 100%);
            box-shadow: 0 18px 45px rgba(124, 58, 237, .22); margin-bottom: 1.4rem;
        }
        .hero-footnote h1 { font-size: clamp(1.8rem, 3.8vw, 2.8rem); letter-spacing: -.03em; margin: 0 0 .4rem; }
        .hero-footnote p { opacity: .88; margin: 0; font-size: 1.02rem; }
        .section-card {
            border: 1px solid #e2e8f0; border-radius: 18px; padding: 1.2rem 1.3rem;
            background: rgba(255,255,255,.8); margin: .8rem 0; box-shadow: 0 2px 8px rgba(0,0,0,.03);
        }
        .pill-badge-violet {
            display: inline-block; padding: .25rem .55rem; margin: .15rem; border-radius: 999px;
            background: #f3e8ff; color: #6b21a8; font-size: .82rem; font-weight: 500;
        }
        .step-tag {
            font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
            color: #7c3aed; background: #ede9fe; padding: 3px 8px; border-radius: 6px; margin-right: 6px;
        }
        .log-terminal {
            background-color: #0f172a; color: #a78bfa; font-family: 'Consolas', 'Courier New', monospace;
            padding: 1rem; border-radius: 12px; font-size: .88rem; max-height: 260px;
            overflow-y: auto; white-space: pre-wrap; line-height: 1.45; border: 1px solid #1e293b;
        }
        div[data-testid="stFileUploader"] {
            border: 1.5px dashed #a78bfa; border-radius: 18px; padding: .5rem; background: #faf5ff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def add_log(message: str) -> None:
    if "footnote_logs" not in st.session_state:
        st.session_state["footnote_logs"] = []
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state["footnote_logs"].append(f"[{timestamp}] {message}")


def main() -> None:
    st.set_page_config(
        page_title="自動化校註系統",
        page_icon="📖",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_styles()

    if "footnote_logs" not in st.session_state:
        st.session_state["footnote_logs"] = [
            f"[{datetime.now().strftime('%H:%M:%S')}] 系統就緒：自動化校註引擎 (v2.0 Zero-Unexplained Error) 已準備完畢。"
        ]

    default_template = founder_dir / "template.docx"

    # Hero 橫幅
    st.markdown(
        """
        <section class="hero-footnote">
            <h1>📖 自動化校註系統 v2.0 (Zero-Unexplained Error)</h1>
            <p>古籍與學術文檔標記探勘 (AI偵察兵)、雙向校註精準匹配及 OpenXML 無損腳註注入轉換引擎。</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    # 側邊欄
    with st.sidebar:
        st.subheader("⚙️ 引擎設定與狀態")
        if default_template.exists():
            st.success("基礎範本：template.docx [已載入]")
        else:
            st.warning("⚠️ 未找到預設 template.docx，請在下方上傳自訂範本。")

        custom_template = st.file_uploader(
            "上傳自訂基礎範本 (可選)",
            type=["docx"],
            help="若不提供，系統將預設使用 Founder Fonts_修正腳本 目錄下的 template.docx",
        )
        st.divider()
        st.markdown("**架構流程說明**")
        st.markdown(
            """
            1. **來源解析 (Phase 1)**：DOCX / PDF 抽取
            2. **結構探勘 (AI Scout)**：推斷標籤與標記型態
            3. **人工閘門 (Human Gate)**：審查並確認 Profile
            4. **雙向審計 (Phase 2)**：Pre-flight 比對驗證
            5. **無損注入 (Builder)**：寫入標準 Word 腳註
            """
        )
        if st.button("清空執行日誌", use_container_width=True):
            st.session_state["footnote_logs"] = [
                f"[{datetime.now().strftime('%H:%M:%S')}] 日誌已重置。"
            ]
            st.rerun()

    # 決定使用的 template.docx 路徑
    active_template_bytes = None
    if custom_template:
        active_template_bytes = custom_template.getvalue()
    elif default_template.exists():
        active_template_bytes = default_template.read_bytes()

    # 功能區 1: 來源檔案上傳與 Phase 1 分析
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<span class="step-tag">Phase 1</span> <strong>來源檔案上傳與結構探勘</strong>', unsafe_allow_html=True)
    st.caption("支援包含古籍標記或行間註釋的 Word (.docx) 或 PDF 檔案。")

    uploaded_doc = st.file_uploader(
        "選擇要分析與轉換的檔案",
        type=["docx", "pdf"],
        help="支援包含手動標註或校註區塊的古籍文檔。",
    )

    if uploaded_doc:
        source_name = uploaded_doc.name
        st.write(f"目前選取文檔：**{source_name}** ({uploaded_doc.size / 1024:.1f} KB)")

        # 若使用者更換檔案，重置之前的分析狀態
        if st.session_state.get("current_analyzed_name") != source_name:
            st.session_state["analyzed_doc"] = None
            st.session_state["suggested_profile"] = None
            st.session_state["locked_profile"] = None
            st.session_state["conversion_done"] = False
            st.session_state["output_docx_bytes"] = None

        if st.button("🚀 開始分析文檔結構 (Phase 1)", type="primary", use_container_width=True):
            if not active_template_bytes:
                st.error("錯誤：找不到任何可用的 template.docx 基礎範本！請於側邊欄上傳範本檔案。")
                return

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_input = Path(temp_dir) / source_name
                temp_input.write_bytes(uploaded_doc.getvalue())
                temp_tpl = Path(temp_dir) / "template.docx"
                temp_tpl.write_bytes(active_template_bytes)

                add_log(f"開始分析文檔: {source_name} ...")
                with st.spinner("AI 偵察兵探勘文檔中... (Parsing & Analyzing)"):
                    try:
                        engine = AutoFootnoteEngine(str(temp_tpl))
                        doc, suggested_profile = engine.analyze_source(str(temp_input))
                        st.session_state["analyzed_doc"] = doc
                        st.session_state["suggested_profile"] = suggested_profile
                        st.session_state["current_analyzed_name"] = source_name
                        st.session_state["locked_profile"] = None
                        st.session_state["conversion_done"] = False
                        add_log(
                            f"Phase 1 分析完成！段落數: {sum(len(s.paragraphs) for s in doc.sections)}，"
                            f"推斷標籤: 【{suggested_profile.annotation_label or '無標籤'}】，"
                            f"標記型態: {suggested_profile.marker_type}，信心度: {suggested_profile.confidence*100:.0f}%"
                        )
                        st.success("Phase 1 分析成功！請在下方「人工確認閘門」審查或調整設定。")
                    except Exception as e:
                        st.error(f"分析失敗：{e}")
                        add_log(f"分析失敗錯誤：{e}")

    st.markdown('</div>', unsafe_allow_html=True)

    suggested: AnnotationProfile | None = st.session_state.get("suggested_profile")
    doc_model = st.session_state.get("analyzed_doc")

    # 功能區 2: 人工確認閘門 (Human Gate - 對應原 Tkinter AnnotationReviewDialog)
    if suggested and doc_model:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<span class="step-tag">Human Gate</span> <strong>註釋結構審查與確認 (Human Review Gate)</strong>', unsafe_allow_html=True)
        st.caption("這是符合 Zero-Unexplained Error 核心原則的人工覆核閘門，確保轉換設定符合實際文檔特徵。")

        # 1. AI 偵測結果提示 (對照原 Tkinter 藍字標籤)
        ai_banner_text = (
            f"💡 **AI 偵測建議**：推薦標籤為【**{suggested.annotation_label or '無標籤'}**】，"
            f"標記型態為【**{suggested.marker_type}**】，綜合信心度：**{suggested.confidence*100:.0f}%**。"
        )
        st.info(ai_banner_text)

        gate_col1, gate_col2 = st.columns(2)

        marker_options_map = {
            "①②③ (圓圈數字)": "circled_number",
            "[1][2][3] (方括號)": "square_bracket",
            "〔1〕〔2〕 (中文括號)": "chinese_bracket",
            "純數字 (1, 2)": "plain_number",
        }
        marker_options_rev = {v: k for k, v in marker_options_map.items()}

        with gate_col1:
            label_options = ["無標籤", "校注", "注釋", "注解", "注", "考證"]
            default_label = suggested.annotation_label if suggested.annotation_label in label_options else "無標籤"
            label_index = label_options.index(default_label)
            selected_label = st.selectbox(
                "① 註釋區塊標籤 (若有)",
                options=label_options,
                index=label_index,
                help="文檔中作為註釋開頭的段落標題，例如【校注】或【注釋】",
            )

        with gate_col2:
            default_marker_label = marker_options_rev.get(suggested.marker_type, "①②③ (圓圈數字)")
            marker_keys = list(marker_options_map.keys())
            marker_index = marker_keys.index(default_marker_label) if default_marker_label in marker_keys else 0
            selected_marker_text = st.radio(
                "② 腳註標記型態",
                options=marker_keys,
                index=marker_index,
                help="正文中指向腳註的標記字元格式",
            )
            selected_marker = marker_options_map[selected_marker_text]

        with st.expander("🛠️ 進階參數微調 (選用)"):
            adv_col1, adv_col2, adv_col3 = st.columns(3)
            with adv_col1:
                scope_choice = st.selectbox(
                    "標記重置範圍 (Marker Scope)",
                    ["chapter (每章重置)", "page (每頁重置)", "global (全書唯一)"],
                    index=0,
                )
                marker_scope = scope_choice.split(" ")[0]
            with adv_col2:
                numbering_choice = st.selectbox(
                    "腳註編號模式 (Numbering Scope)",
                    ["continuous (全書連續編號)", "restart_page (每頁重新編號)"],
                    index=0,
                )
                numbering_scope = numbering_choice.split(" ")[0]
            with adv_col3:
                location_choice = st.selectbox(
                    "註釋所在位置 (Footnote Location)",
                    ["section_end (段落/章節末)", "page_bottom (頁底)", "inline (行間)"],
                    index=0,
                )
                footnote_location = location_choice.split(" ")[0]

        if st.button("🔒 確認並鎖定設定 (Confirm & Lock Profile)", type="primary", use_container_width=True):
            final_label = None if selected_label == "無標籤" else selected_label
            locked_profile = AnnotationProfile(
                annotation_label=final_label,
                marker_type=selected_marker,
                marker_scope=marker_scope,
                numbering_scope=numbering_scope,
                footnote_location=footnote_location,
                extraction_strategy="explicit_label" if final_label else "marker_based",
                confidence=1.0,
                is_locked=True,
            )
            st.session_state["locked_profile"] = locked_profile
            add_log(f"Human Gate 已鎖定 Profile：標籤={final_label}, 標記={selected_marker}")
            st.success("✅ 註釋結構已由人工確認並正式鎖定！現在可以執行 Phase 2 轉換。")

        st.markdown('</div>', unsafe_allow_html=True)

    # 功能區 3: Phase 2 轉換執行與結果下載
    locked: AnnotationProfile | None = st.session_state.get("locked_profile")
    if locked and doc_model:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<span class="step-tag">Phase 2</span> <strong>正式轉換、Pre-flight 審計與 OpenXML 建構</strong>', unsafe_allow_html=True)
        st.caption("將正文標記與註釋關聯匹配，通過審計後注入至標準 Word 腳註結構。")

        if st.button("⚡ 開始執行正式腳註轉換 (Run Conversion)", type="primary", use_container_width=True):
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_tpl = Path(temp_dir) / "template.docx"
                temp_tpl.write_bytes(active_template_bytes)
                output_docx_path = Path(temp_dir) / f"{Path(st.session_state['current_analyzed_name']).stem}_自動腳註.docx"

                add_log("Phase 2 啟動：執行標記雙向關聯匹配 (FootnoteMatcher)...")
                with st.spinner("正在進行腳註比對、Pre-flight 審計與 OpenXML 渲染..."):
                    try:
                        # 執行 Matcher
                        match_results = FootnoteMatcher.match(doc_model, locked)
                        matched_count = len(match_results.get("matched", []))
                        warnings_count = len(match_results.get("warnings", []))
                        errors_count = len(match_results.get("errors", []))

                        add_log(f"匹配結果：成功關聯 {matched_count} 筆, 警告 {warnings_count} 筆, 錯誤 {errors_count} 筆")

                        # Preflight Auditor
                        audit_status = PreflightAuditor.audit(match_results, doc_model, locked)
                        add_log(f"PRE-FLIGHT 審計結果: {audit_status}")

                        if audit_status == "FAIL":
                            st.error(f"PRE-FLIGHT 審計失敗：存在 {errors_count} 處孤立標記或孤立註釋，系統拒絕產出損毀文檔。")
                            for err in match_results.get("errors", []):
                                st.warning(f"錯誤細節：{err.get('reason')}")
                        else:
                            # 執行 Builder
                            builder = OpenXMLBuilder(str(temp_tpl))
                            builder.build(doc_model, str(output_docx_path))

                            if output_docx_path.exists():
                                out_bytes = output_docx_path.read_bytes()
                                st.session_state["output_docx_bytes"] = out_bytes
                                st.session_state["conversion_done"] = True
                                st.session_state["match_stats"] = {
                                    "matched": matched_count,
                                    "warnings": warnings_count,
                                    "errors": errors_count,
                                }
                                add_log(f"DOCX 腳註建構完成！檔案大小: {len(out_bytes) / 1024:.1f} KB")
                                st.success("🎉 腳註注入與 DOCX 建構完成！")

                    except Exception as exc:
                        st.error(f"轉換過程發生錯誤：{exc}")
                        add_log(f"轉換發生例外錯誤：{exc}")

        if st.session_state.get("conversion_done") and st.session_state.get("output_docx_bytes"):
            stats = st.session_state.get("match_stats", {})
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("成功匹配腳註數", stats.get("matched", 0))
            m_col2.metric("審計警告數", stats.get("warnings", 0))
            m_col3.metric("審計錯誤數", stats.get("errors", 0))

            st.download_button(
                "📥 下載已注入腳註的 Word 檔 (.docx)",
                data=st.session_state["output_docx_bytes"],
                file_name=f"{Path(st.session_state['current_analyzed_name']).stem}_自動腳註.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )

        st.markdown('</div>', unsafe_allow_html=True)

    # 功能區 4: 系統狀態與執行紀錄 (System Status Terminal)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📋 系統狀態與執行紀錄 (System Status)")
    logs_str = "\n".join(st.session_state.get("footnote_logs", []))
    st.markdown(f'<div class="log-terminal">{logs_str}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
