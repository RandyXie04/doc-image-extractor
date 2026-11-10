import zipfile
from pathlib import Path

from src.utils.docx_style_profiles import read_docx_style_profiles


def test_template_style_profiles_expose_properties_needed_for_role_suggestions(tmp_path: Path):
    styles_xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:style w:type="paragraph" w:styleId="Heading1">
        <w:name w:val="章標題"/><w:outlineLvl w:val="0"/>
        <w:rPr><w:b/><w:sz w:val="36"/></w:rPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="Normal">
        <w:name w:val="內文"/><w:rPr><w:sz w:val="24"/></w:rPr>
      </w:style>
      <w:style w:type="character" w:styleId="Emphasis"><w:name w:val="強調"/></w:style>
    </w:styles>'''
    template = tmp_path / "styles.docx"
    with zipfile.ZipFile(template, "w") as archive:
        archive.writestr("word/styles.xml", styles_xml)

    profiles = read_docx_style_profiles(template)

    assert profiles == [
        {"name": "章標題", "outline_level": 0, "font_size_pt": 18.0, "bold": True},
        {"name": "內文", "outline_level": None, "font_size_pt": 12.0, "bold": False},
    ]
