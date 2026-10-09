import codecs
import re

with codecs.open('src/scripts/pdf_font_analyzer.py', 'r', 'utf-8') as f:
    content = f.read()

# Replace condition
content = re.sub(
    r'if text not in entry\["texts"\] and len\(text\) >= 3:\s*entry\["texts"\].append\(text\)',
    'if text and text not in entry["texts"]:\n                        entry["texts"].append(text)',
    content
)

# Replace sampling logic
new_sampling = '''        samples = []
        texts = data["texts"]
        if texts:
            long_texts = [t for t in texts if len(t) >= 3]
            source_texts = long_texts if long_texts else texts
            step = max(1, len(source_texts) // max_samples)
            for i in range(0, len(source_texts), step):
                if len(samples) >= max_samples:
                    break
                samples.append(source_texts[i][:max_sample_len])'''

content = re.sub(
    r'# .*?\s*samples = \[\]\s*for t in data\["texts"\]:\s*if len\(samples\) >= max_samples:\s*break\s*samples\.append\(t\[:max_sample_len\]\)',
    new_sampling,
    content
)

with codecs.open('src/scripts/pdf_font_analyzer.py', 'w', 'utf-8') as f:
    f.write(content)

print('Done')
