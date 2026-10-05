import codecs
import re

with codecs.open('src/scripts/pdf_font_analyzer.py', 'r', 'utf-8') as f:
    content = f.read()

content = content.replace(
    'if text and text not in entry["texts"]:',
    'if text not in entry["texts"] and len(text) >= 3:'
)

old_sampling = '''            long_texts = [t for t in texts if len(t) >= 3]
            source_texts = long_texts if long_texts else texts
            step = max(1, len(source_texts) // max_samples)
            for i in range(0, len(source_texts), step):'''

new_sampling = '''            step = max(1, len(texts) // max_samples)
            for i in range(0, len(texts), step):'''

content = content.replace(old_sampling, new_sampling)
content = content.replace('samples.append(source_texts[i][:max_sample_len])', 'samples.append(texts[i][:max_sample_len])')

with codecs.open('src/scripts/pdf_font_analyzer.py', 'w', 'utf-8') as f:
    f.write(content)
print('Done')
