import re


def postprocess_dictionary_markdown(md_text: str, style_mapping: dict = None) -> str:
    """
    Semantic post-processing for Dictionary OCR markdown.
    1. Converts false H1/H2 headings (caused by bold terms) into bold text **Term**.
    2. Heuristically identifies quote blocks (KaiTi) based on specific dictionary patterns
       (e.g., quotes starting with `〔`, citations) and converts them to blockquotes,
       optionally annotated with a custom Word style via Pandoc {custom-style="..."} syntax.
    3. Image blocks (markdown image syntax) are optionally annotated with a custom
       image caption Word style.

    Parameters
    ----------
    md_text : str
        Input markdown text from OCR pipeline.
    style_mapping : dict, optional
        Keys:
          - "kaiti"         : Word style name for KaiTi/quote blocks (e.g. "楷體引言")
          - "image_caption" : Word style name for image caption paragraphs (e.g. "圖片說明")
    """
    if style_mapping is None:
        style_mapping = {}

    kaiti_style: str = style_mapping.get("kaiti", "")
    image_caption_style: str = style_mapping.get("image_caption", "")

    lines = md_text.split('\n')
    processed_lines = []

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            processed_lines.append(line)
            continue

        # 1. Fix Term Headings
        # If line is a heading (e.g. "# 詞條") but very short and no punctuation,
        # it's likely a dictionary term, not a chapter heading.
        m_heading = re.match(r'^(#{1,3})\s+(.+)$', clean_line)
        if m_heading:
            text = m_heading.group(2).strip()
            # Remove custom-style if present for analysis
            text_no_style = re.sub(r'\s*\{custom-style=".*?"\}$', '', text).strip()

            # Dictionary term heuristic: short (<=10 chars), no sentence punctuation
            # Exceptions: Chapter titles (e.g., "第一章") or structural headings
            if len(text_no_style) <= 10 and not re.search(r'[。，；？！""''：:、]', text_no_style):
                if not re.match(r'^(第[一二三四五六七八九十百]+[章篇]|目\s*录|附\s*录|索\s*引|后\s*记|前\s*言)$', text_no_style):
                    # It's a dictionary term — convert to bold plain text
                    line = f"**{text_no_style}**"
                    processed_lines.append(line)
                    continue

        # 2. Heuristic KaiTi (Quotes/Citations)
        # Detect lines that start with typical citation/quote markers.
        if clean_line and not clean_line.startswith('> ') and not clean_line.startswith('!['):
            if re.match(r'^([〔\[【]|".*?出处.*?"|《.*?》)', clean_line):
                if kaiti_style:
                    # Use Pandoc custom-style div syntax for block-level custom style
                    # Wrap in a fenced div so Pandoc maps it to the correct Word style
                    line = f"::: {{custom-style=\"{kaiti_style}\"}}\n{clean_line}\n:::"
                else:
                    line = "> " + clean_line
                processed_lines.append(line)
                continue

        # 3. Image blocks — annotate with image_caption style if configured
        if image_caption_style and clean_line.startswith('!['):
            # Append a caption paragraph with the custom style immediately after the image
            processed_lines.append(line)
            # Pandoc image attribute syntax: add custom-style to the paragraph AFTER the image
            # We insert an empty-styled paragraph placeholder that Pandoc will apply the style to
            processed_lines.append(f"::: {{custom-style=\"{image_caption_style}\"}}\n\u3000\n:::")
            continue

        processed_lines.append(line)

    final_text = "\n".join(processed_lines)

    return final_text
