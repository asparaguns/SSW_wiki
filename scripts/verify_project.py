#!/usr/bin/env python3
"""Static integrity checks that do not require Hugo or third-party packages."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report = json.loads((root/'migration/report.json').read_text(encoding='utf-8'))
articles = sorted((root/'content/wiki').glob('article-*.md'))
expected = report['articles_written'] - 1 # home page is in content/_index.md
assert len(articles) == expected, (len(articles), expected)
assert len(report['infobox_counts']) == 6
assert (root/'content/_index.md').is_file()
urls = set()
num_links = 0
for path in articles + [root/'content/_index.md']:
    text = path.read_text(encoding='utf-8')
    assert text.startswith('---\n') and '\n---\n' in text[4:]
    assert 'source_url:' in text, str(path)
    for link in re.findall(r'\{\{<\s*relref\s+"([^"]+)"\s*>\}\}',text):
        assert (root/'content'/link).is_file(), (path.name,link)
        num_links += 1
    assert 'SSWWIKILINKPLACEHOLDER' not in text
    assert 'SSWUNSUPPORTEDTEMPLATE' not in text
    pathurl = re.search(r'^url: "([^"]+)"$',text,re.M)
    if pathurl:
        value = pathurl.group(1)
        assert value not in urls, ('duplicate URL', value)
        urls.add(value)
assert not list((root/'migration/raw').glob('nonarticle-2-*.wiki')), 'User pages must not be packaged.'
assert not list((root/'migration/raw').glob('nonarticle-4-*.wiki'))
print(f'PASS: {len(articles)+1} articles including home; {len(urls)} unique article URLs; {num_links} local links.')
print('PASS: Images to provide:', len(report['images_missing_from_static_images']))
print('PASS: Raw user namespace content excluded.')
print('Note: Hugo build must be verified on a machine with Hugo installed.')
