with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if '# Global for multiprocessing worker' in line:
        skip = True
    
    if skip and 'def _mock_detect(img):' in line:
        skip = False
        new_lines.append('# Global for multiprocessing worker\n')
        new_lines.append('_mfd_analyzer = None\n\n')
        new_lines.append('def _init_mfd_worker(use_gpu=False):\n')
        new_lines.append('    global _mfd_analyzer\n')
        new_lines.append('    if _mfd_analyzer is None:\n')
        new_lines.append('        try:\n')
        new_lines.append('            from cnstd.yolov7.layout_analyzer import LayoutAnalyzer\n')
        new_lines.append('            import torch\n')
        new_lines.append("            device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'\n")
        new_lines.append("            _mfd_analyzer = LayoutAnalyzer('mfd', device=device)\n")
        new_lines.append('        except ImportError:\n')
        new_lines.append('            _mfd_analyzer = "MOCK"\n\n')
        
    if not skip:
        new_lines.append(line)

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
