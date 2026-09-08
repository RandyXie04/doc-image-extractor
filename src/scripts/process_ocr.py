import os
import glob
import sys
import re
import datetime
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).parent.parent.parent.absolute()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from rapid_doc import RapidDoc
    from rapid_doc.backend.pipeline.pipeline_middle_json_mkcontent import make_blocks_to_markdown
    from rapid_doc.utils.enum_class import MakeMode, BlockType
except ImportError:
    print("rapid_doc not installed yet.")
    RapidDoc = None

try:
    from src.founder_tools.core.marker_detector import MarkerDetector
except ImportError:
    try:
        from founder_tools.core.marker_detector import MarkerDetector
    except ImportError:
        MarkerDetector = None


def extract_block_text(block):
    """
    Extract full concatenated text content from a layout block.
    """
    text_parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            content = span.get("content", "")
            if content:
                text_parts.append(content)
    return "".join(text_parts).strip()


def is_strong_citation_text(text: str) -> bool:
    """
    Check if a text candidate has strong literature citation characteristics:
    e.g., book marks 《...》, journal tags [M]/[J]/[Z]/[D], '出版社', '年版', '第X页', 'pp.'.
    """
    if not text:
        return False
    citation_patterns = [
        r'《[^》]+》',
        r'\[[A-Z]\]',
        r'(?:出版社|出版|Press)',
        r'(?:\d{4}\s*年\s*版|\d{4}\s*年)',
        r'(?:第\s*\d+\s*页|[Pp]\.?\s*\d+)',
        r'(?:参阅|参见|转引自|译|主编)',
    ]
    for pat in citation_patterns:
        if re.search(pat, text):
            return True
    return False


def parse_footnote_entries(text):
    """
    Parse one or more footnote entries from a footnote block text.
    Supports circled numbers (①..㊿), brackets ([1]), superscript digits,
    '注1:', '(1)', '1.' prefixes.
    """
    if not text or not text.strip():
        return []

    pattern = re.compile(
        r'(?:^|\n)\s*([①-⑩\u2460-\u2473]|\[\d+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|注\s*\d+[:：.]?|\(?\d+\)[.、]?|\d+[.、])\s*'
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return [{"id": 1, "raw_marker": "", "content": text.strip()}]

    entries = []
    for i, m in enumerate(matches):
        marker_str = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        num_val = 1
        if MarkerDetector:
            if marker_str and marker_str[0] in MarkerDetector.CIRCLED_NUMBERS:
                num_val = MarkerDetector.CIRCLED_NUMBERS.index(marker_str[0]) + 1
            elif all(c in MarkerDetector.SUPERSCRIPT_DIGITS for c in marker_str if c):
                num_val = int("".join(str(MarkerDetector.SUPERSCRIPT_DIGITS.index(c)) for c in marker_str))
            else:
                digits = re.findall(r'\d+', marker_str)
                if digits:
                    num_val = int(digits[0])
        else:
            digits = re.findall(r'\d+', marker_str)
            if digits:
                num_val = int(digits[0])

        entries.append({
            "id": num_val,
            "raw_marker": marker_str,
            "content": content
        })

    return entries


def process_page_footnotes(page_info, page_num, previous_open_footnote, audit_records):
    """
    Process layout blocks of a single page:
    1. Separate candidate footnote blocks from definite body blocks while tracking indices.
    2. Handle cross-page continuation.
    3. Match body anchors or verify strong citation characteristics.
    4. If unmatched and lacking citation semantics, preserve block in original reading order.
    5. Render page markdown with Pandoc footnotes [^n].
    """
    page_size = page_info.get("page_size", [1000, 1000])
    page_h = page_size[1] if len(page_size) >= 2 else 1000
    para_blocks = page_info.get("para_blocks", [])

    # Keep track of blocks by original order
    # item: {"block": block, "is_candidate_fn": bool, "orig_idx": int}
    indexed_blocks = []
    for idx, block in enumerate(para_blocks):
        b_type = block.get("type")
        orig_label = block.get("original_label", "")
        bbox = block.get("bbox", [0, 0, 0, 0])
        y0 = bbox[1] if len(bbox) >= 2 else 0

        # Criterion A: Explicit footnote tag from layout model
        is_fn = orig_label in ["footnote", "vision_footnote"]

        # Criterion B: Heuristic fallback in lower 28% of page with footnote prefix
        if not is_fn and y0 > (page_h * 0.72) and b_type not in [BlockType.TITLE, BlockType.TABLE]:
            blk_txt = extract_block_text(block)
            if re.search(r'^(?:[①-⑩\u2460-\u2473]|\[\d+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|注\s*\d+|\(?\d+\)\s*[\u4e00-\u9fff])', blk_txt):
                is_fn = True

        indexed_blocks.append({
            "block": block,
            "is_candidate_fn": is_fn,
            "orig_idx": idx
        })

    # Render candidate body text for marker detection
    initial_body_blocks = [item["block"] for item in indexed_blocks if not item["is_candidate_fn"]]
    candidate_fn_items = [item for item in indexed_blocks if item["is_candidate_fn"]]

    # Extract footnote entries
    new_open_footnote = None
    parsed_entries_map = {}  # orig_idx -> entries

    for fn_item in candidate_fn_items:
        blk_txt = extract_block_text(fn_item["block"]).strip()
        entries = parse_footnote_entries(blk_txt)
        parsed_entries_map[fn_item["orig_idx"]] = entries

    # Initial body markdown list
    body_markdown_list = make_blocks_to_markdown(initial_body_blocks, MakeMode.MM_MD, img_buket_path="")

    final_footnotes = []
    blocks_to_restore = []

    # Evaluate each candidate footnote block
    for fn_item in candidate_fn_items:
        orig_idx = fn_item["orig_idx"]
        entries = parsed_entries_map.get(orig_idx, [])
        blk_txt = extract_block_text(fn_item["block"])

        # Check cross-page continuation
        if entries and not entries[0]["raw_marker"] and previous_open_footnote:
            previous_open_footnote["content"] += " " + entries[0]["content"]
            audit_records.append({
                "page": page_num,
                "type": "CONTINUATION",
                "id": previous_open_footnote["id"],
                "msg": f"跨頁接續注釋：已自動拼接至前頁注釋 [{previous_open_footnote['id']}] 末尾。"
            })
            entries = entries[1:]

        block_has_matched_anchor = False
        valid_entries_in_block = []

        for entry in entries:
            fn_id = entry["id"]
            marker_str = entry["raw_marker"]
            content = entry["content"]
            fn_ref_tag = f"[^p{page_num}_{fn_id}]"

            matched = False
            # Check in body markdown
            for p_idx, p_text in enumerate(body_markdown_list):
                if marker_str and marker_str in p_text:
                    body_markdown_list[p_idx] = p_text.replace(marker_str, fn_ref_tag, 1)
                    matched = True
                    break
                elif MarkerDetector:
                    detected = MarkerDetector.detect(p_text, "auto")
                    for d in detected:
                        if d.number == fn_id:
                            body_markdown_list[p_idx] = p_text[:d.start_char] + fn_ref_tag + p_text[d.end_char:]
                            matched = True
                            break
                    if matched:
                        break

            if matched:
                block_has_matched_anchor = True
                valid_entries_in_block.append(entry)
                audit_records.append({
                    "page": page_num,
                    "type": "MATCHED",
                    "id": fn_id,
                    "msg": f"注釋 [{fn_id}] 雙向匹配成功，已替換正文標記。"
                })
            else:
                # Missing anchor in body: Check if it's genuinely a citation
                if is_strong_citation_text(content):
                    # Genuine footnote with lost OCR superscript -> safely append reference
                    target_p_idx = -1
                    for idx in range(len(body_markdown_list) - 1, -1, -1):
                        if body_markdown_list[idx].strip():
                            target_p_idx = idx
                            break
                    if target_p_idx >= 0:
                        body_markdown_list[target_p_idx] = body_markdown_list[target_p_idx].rstrip() + fn_ref_tag
                    else:
                        body_markdown_list.append(fn_ref_tag)

                    valid_entries_in_block.append(entry)
                    audit_records.append({
                        "page": page_num,
                        "type": "FALLBACK",
                        "id": fn_id,
                        "msg": f"⚠️ 警告：文獻注釋 [{fn_id}] 正文未偵測到上標，已安全降級插入至當頁段落末端。內容：{content[:35]}..."
                    })
                else:
                    # It is regular body text (e.g. ordered list items like ⑤执行...)
                    # DO NOT convert to footnote! Mark block for restoration.
                    pass

        if valid_entries_in_block:
            final_footnotes.extend(valid_entries_in_block)
            new_open_footnote = valid_entries_in_block[-1]
        else:
            # Entire block is body text -> restore to body!
            blocks_to_restore.append(fn_item)

    # If blocks need to be restored to original reading order, re-render body with them included
    if blocks_to_restore:
        for item in blocks_to_restore:
            item["is_candidate_fn"] = False

        # Sort all blocks by original index to ensure pristine reading order
        final_body_blocks = [item["block"] for item in sorted(indexed_blocks, key=lambda x: x["orig_idx"]) if not item["is_candidate_fn"]]
        
        # Re-render complete body with preserved order
        body_markdown_list = make_blocks_to_markdown(final_body_blocks, MakeMode.MM_MD, img_buket_path="")

        # Re-apply matched footnote references to the re-rendered body
        for fn in final_footnotes:
            fn_id = fn["id"]
            marker_str = fn["raw_marker"]
            fn_ref_tag = f"[^p{page_num}_{fn_id}]"
            for p_idx, p_text in enumerate(body_markdown_list):
                if marker_str and marker_str in p_text:
                    body_markdown_list[p_idx] = p_text.replace(marker_str, fn_ref_tag, 1)
                    break

    return body_markdown_list, final_footnotes, new_open_footnote


def generate_audit_report(pdf_name, total_pages, audit_records, report_path):
    """
    Generate structured footnote review audit report (footnote_review.txt).
    """
    total_fns = len([r for r in audit_records if r["type"] in ["MATCHED", "FALLBACK"]])
    matched_fns = len([r for r in audit_records if r["type"] == "MATCHED"])
    fallback_fns = len([r for r in audit_records if r["type"] == "FALLBACK"])
    continuation_fns = len([r for r in audit_records if r["type"] == "CONTINUATION"])
    warning_fns = len([r for r in audit_records if r["type"] == "FALLBACK"])

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "=" * 80,
        "書籍 PDF OCR 腳注提取與雙向審計覆核報告",
        f"處理時間：{now_str}",
        f"處理檔案：{pdf_name}",
        "=" * 80,
        "【統計總覽】",
        f"  總處理頁數    ：{total_pages} 頁",
        f"  提取腳注總數  ：{total_fns} 條",
        f"  精準雙向匹配  ：{matched_fns} 條",
        f"  安全降級錨定  ：{fallback_fns} 條",
        f"  跨頁拼接接續  ：{continuation_fns} 條",
        f"  需人工覆核警告：{warning_fns} 處",
        "-" * 80,
        "【逐頁審計明細】",
    ]

    if not audit_records:
        lines.append("  (本檔案無偵測到注釋或無異常項目)")
    else:
        for r in audit_records:
            icon = "✅" if r["type"] == "MATCHED" else "⚠️"
            lines.append(f"  [第 {r['page']:03d} 頁] {icon} {r['msg']}")

    lines.extend([
        "=" * 80,
        "說明：標記為 ⚠️ 警告的項目，表示因 OCR 上標模糊或原書缺標記，系統已自動將其",
        "保存在該頁末尾，未丟失任何文字。非文獻之正文編號已完整保留於內文原處。",
        "=" * 80,
        ""
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    if not RapidDoc:
        print("RapidDoc is not available.")
        return

    layout_cfg = {
        "markdown_ignore_labels": [
            "number",
            "header",
            "header_image",
            "footer",
            "footer_image",
            "aside_text",
        ]
    }
    engine = RapidDoc(layout_config=layout_cfg)

    input_dir = os.path.join('data', 'database_text')
    output_dir = os.path.join('data', '03_output')
    os.makedirs(output_dir, exist_ok=True)

    pdf_files = glob.glob(os.path.join(input_dir, 'OCR*.pdf'))
    if not pdf_files:
        pdf_files = [
            f for f in glob.glob(os.path.join(input_dir, '*.pdf'))
            if not os.path.basename(f).startswith('temp_')
        ]

    print(f"Found {len(pdf_files)} PDF files to process.")

    for pdf_path in pdf_files:
        print(f"Processing: {pdf_path}")
        pdf_name = os.path.basename(pdf_path)
        try:
            res = engine(pdf_path)

            all_page_contents = []
            audit_records = []
            previous_open_footnote = None
            total_pages = 0

            if hasattr(res, 'middle_json') and res.middle_json and 'pdf_info' in res.middle_json:
                pdf_info_list = res.middle_json['pdf_info']
                total_pages = len(pdf_info_list)

                pages_data = []
                for page_info in pdf_info_list:
                    page_idx = page_info.get('page_idx', 0)
                    page_num = page_idx + 1

                    body_list, parsed_entries, previous_open_footnote = process_page_footnotes(
                        page_info, page_num, previous_open_footnote, audit_records
                    )
                    pages_data.append({
                        "page_num": page_num,
                        "body": body_list,
                        "footnotes": parsed_entries
                    })

                # Second pass: Assemble final Markdown with full cross-page spliced footnotes
                for p in pages_data:
                    p_num = p["page_num"]
                    page_str = "\n\n".join(p["body"])
                    if p["footnotes"]:
                        defs = [f"[^p{p_num}_{fn['id']}]: {fn['content']}" for fn in p["footnotes"]]
                        page_str += "\n\n" + "\n\n".join(defs)
                    if page_str.strip():
                        all_page_contents.append(page_str.strip())

                final_md = "\n\n".join(all_page_contents)
            else:
                # Fallback to default markdown string
                if hasattr(res, 'markdown'):
                    final_md = res.markdown
                elif isinstance(res, tuple) and len(res) >= 1:
                    final_md = res[0].markdown if hasattr(res[0], 'markdown') else str(res[0])
                else:
                    final_md = str(res)

            out_name = Path(pdf_path).stem + ".md"
            out_path = os.path.join(output_dir, out_name)

            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(final_md)

            print(f"Saved MD with footnotes to {out_path}")

            # Generate footnote review audit report
            report_path = os.path.join(output_dir, "footnote_review.txt")
            generate_audit_report(pdf_name, total_pages, audit_records, report_path)
            print(f"Saved Footnote Review Report to {report_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error processing {pdf_path}: {e}")


if __name__ == '__main__':
    main()
