import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    # Remove the first broken _mock_detect and the onnx init
    if 'def _mock_detect(img):' in line and '"""' in lines[i+1]:
        skip = True
        
    if skip and 'def _mock_detect(img):' in line and '#' in lines[i+1]:
        skip = False
        
    if not skip:
        new_lines.append(line)

content = "".join(new_lines)
content = content.replace('global _onnx_session\n    if _onnx_session is None:', 'global _mfd_analyzer\n    if _mfd_analyzer is None:')
content = content.replace('if getattr(sys.modules[__name__], \'_mfd_analyzer\', \'MOCK\') != \'MOCK\':', 'if _mfd_analyzer != "MOCK":')

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
