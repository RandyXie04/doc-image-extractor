with open('src/web/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad_line = 'filename=f"extracted_result_{tasks[task_id][\'filename\']}.zip"'
good_line = 'filename=f"extracted_result_{tasks[task_id].get(\'filename\', \'output\')}.zip"'

content = content.replace(bad_line, good_line)

with open('src/web/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed KeyError in download endpoint.')
