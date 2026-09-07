with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_line = "if (b_type == 'isolated' and score >= 0.45) or (box_w > w * 0.25 and box_h > 25 and score >= 0.50):"
new_line = "if (b_type == 'isolated' and score >= 0.20) or (b_type == 'inline' and box_w > w * 0.15 and box_h > 15 and score >= 0.20):"

content = content.replace(old_line, new_line)

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated filter thresholds")
