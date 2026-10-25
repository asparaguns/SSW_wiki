#!/usr/bin/env python3
"""Import latest revisions from a Fandom MediaWiki XML dump into this Hugo site.

A safe, reviewable first-pass migration, not an emulation of MediaWiki.
Uses Pandoc's MediaWiki reader for the article body, and explicitly supports the
six article infobox templates found in The Sun Shining on the World Wiki.
Original wikitext and per-page provenance are preserved for manual audit.

Usage: python3 scripts/import_fandom.py /path/to/jasswmod_pages_full.xml [--assets images/] [--force]
Requirements: Python 3.9+ and pandoc on PATH; standard library only.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

WIKI_URL = 'https://ssw-mod.fandom.com/ja/wiki/'
WIKI_TITLE = 'The Sun Shining on the World Wiki'
CATEGORY_RE = re.compile(r'\[\[(?:Category|カテゴリ|カテゴリー|分類)\s*:\s*([^\]|]+)(?:\|[^\]]*)?\]\]', re.I)
REDIRECT_RE = re.compile(r'^\s*#(?:REDIRECT|転送|リダイレクト)\s*\[\[([^\]]+)\]\]', re.I)
LINK_RE = re.compile(r'\[\[([^\[\]]+)\]\]')
DEFAULTSORT_RE = re.compile(r'\{\{(?:DEFAULTSORT|デフォルトソート|DISPLAYTITLE):[^{}]*\}\}', re.I)
GALLERY_RE = re.compile(r'<gallery\b[^>]*>(.*?)</gallery\s*>', re.I | re.S)
FILENAME_RE = re.compile(r'\.(?:png|jpe?g|gif|webp|svg|avif|bmp)$', re.I)
INFOBOX_TEMPLATES = {'国家': 'country', '人物': 'person', '艦艇': 'ship', '陣営': 'faction', '戦闘': 'battle', 'Infobox': 'general'}
IMAGE_LABELS = {'国旗': '国旗', '国章': '国章', '紋章': '国章', 'image1': '画像', '画像': '画像', 'image': '画像', 'flag': '国旗', 'flag_image': '国旗'}
HIDE_KEYS = {'タイトル','title','title1','caption1','caption-image1','画像解説','基本情報','艦歴','要目'}
INFER_CATEGORY = {'country': '国家', 'person': '人物', 'ship': '艦艇', 'faction': '陣営', 'battle': '戦闘'}
IMAGE_NAMESPACES = {'file', 'image', 'ファイル', '画像'}


def json_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def source_url(title: str) -> str:
    return WIKI_URL + urllib.parse.quote(title.replace(' ', '_'), safe='()')


def slug(title: str) -> str:
    title = unicodedata.normalize('NFC', title).replace(' ', '_')
    return re.sub(r'[\\/:?#%\[\]]', '-', title).strip('.-') or 'page'


def article_name(page: dict) -> str:
    uid = str(page['id'])
    if not uid.isdecimal():
        uid = hashlib.sha256(page['title'].encode()).hexdigest()[:12]
    return 'article-' + uid + '.md'


def read_xml(path: Path):
    pages = []
    # XML is untrusted, and no external entity resolution is attempted by ElementTree.
    for event, node in ET.iterparse(str(path), events=('end',)):
        if node.tag.split('}')[-1] != 'page':
            continue
        def get(name):
            child = next((v for v in node if v.tag.split('}')[-1] == name), None)
            return child.text or '' if child is not None else ''
        revs = [v for v in node if v.tag.split('}')[-1] == 'revision']
        def field(rev, key):
            if rev is None:
                return ''
            found = next((v for v in rev if v.tag.split('}')[-1] == key), None)
            if found is None and key == 'text':
                for x in rev.iter():
                    if x.tag.split('}')[-1] == 'text':
                        found = x
                        break
            return found.text or '' if found is not None else ''
        latest = max(revs, key=lambda r: field(r, 'timestamp')) if revs else None
        text = field(latest, 'text')
        redirect = next((v for v in node if v.tag.split('}')[-1] == 'redirect'), None)
        dest = redirect.get('title', '') if redirect is not None else ''
        if not dest:
            match = REDIRECT_RE.match(text)
            dest = match.group(1).split('|', 1)[0] if match else ''
        pages.append({
            'title': get('title'), 'ns': get('ns'), 'id': get('id'),
            'text': text, 'redirect': dest, 'revisions': len(revs),
            'last_revision': field(latest, 'timestamp'),
        })
        node.clear()
    return pages


def outer_templates(text):
    """Find outermost balanced double-brace spans, including nested template values."""
    found, stack = [], []
    i = 0
    while i < len(text) - 1:
        two = text[i:i+2]
        if two == '{{':
            stack.append(i)
            i += 2
        elif two == '}}' and stack:
            start = stack.pop()
            if not stack:
                found.append((start, i+2, text[start+2:i]))
            i += 2
        else:
            i += 1
    return found


def split_template(source):
    """Split parameters on top-level pipes; keep nested links and templates intact."""
    chunks, current, t_depth, l_depth = [], [], 0, 0
    i = 0
    while i < len(source):
        pair = source[i:i+2]
        if pair == '{{':
            t_depth += 1; current.append(pair); i += 2; continue
        if pair == '}}' and t_depth:
            t_depth -= 1; current.append(pair); i += 2; continue
        if pair == '[[':
            l_depth += 1; current.append(pair); i += 2; continue
        if pair == ']]' and l_depth:
            l_depth -= 1; current.append(pair); i += 2; continue
        if source[i] == '|' and not t_depth and not l_depth:
            chunks.append(''.join(current)); current = []; i += 1; continue
        current.append(source[i]); i += 1
    chunks.append(''.join(current))
    name = chunks.pop(0).strip() if chunks else ''
    params = {}
    for n, segment in enumerate(chunks, 1):
        if '=' in segment:
            key, value = segment.split('=', 1)
            params[key.strip()] = value.strip()
        else:
            params[str(n)] = segment.strip()
    return name, params


def image_filename(src):
    raw = src.strip()
    match = re.search(r'\[\[(?:File|Image|ファイル|画像)\s*:\s*([^\]|]+)', raw, re.I)
    if match:
        raw = match.group(1)
    raw = re.sub(r'^(?:File|Image|ファイル|画像)\s*:', '', raw, flags=re.I)
    raw = raw.split('|', 1)[0].strip().replace(' ', '_')
    if '/' in raw or '\\' in raw or len(raw) > 240 or not FILENAME_RE.search(raw):
        return ''
    return unicodedata.normalize('NFC', raw)


def plain_text(value):
    value = re.sub(r'\[\[(?:File|Image|ファイル|画像)\s*:[^\]]*\]\]', '', value, flags=re.I)
    value = re.sub(r'<br\s*/?>', ' ／ ', value, flags=re.I)
    value = LINK_RE.sub(lambda m: m.group(1).split('|')[-1].strip(), value)
    value = re.sub(r'<[^>]*>', '', value)
    value = re.sub(r"'{2,5}", '', value)
    value = re.sub(r'\{\{[^{}]*\}\}', '', value)
    value = html.unescape(value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value[:1600]


def infobox_for(name, params, missing_images, available_images):
    type_name = INFOBOX_TEMPLATES.get(name)
    if type_name is None:
        return None
    info = {'template': name, 'kind': type_name, 'images': [], 'fields': []}
    for key, raw in params.items():
        if key in IMAGE_LABELS:
            filename = image_filename(raw)
            if filename:
                info['images'].append({'label': IMAGE_LABELS[key], 'filename': filename})
                if filename not in available_images:
                    missing_images.add(filename)
            continue
        if key in HIDE_KEYS or key.isdecimal() or key.startswith('_'):
            continue
        v = plain_text(raw)
        if v:
            info['fields'].append({'label': key, 'value': v})
    if not info['fields'] and not info['images']:
        return None
    return info


def transform_galleries(src, mentioned_images):
    def callback(match):
        entries = []
        for line in match.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith('<!--'):
                continue
            parts = line.split('|')
            filename = image_filename(parts[0])
            if filename:
                mentioned_images.add(filename)
            link = next((v.split('=', 1)[1] for v in parts[1:] if v.startswith('link=')), '')
            if link:
                entries.append('* [[' + link + ']]')
            elif filename:
                caption = next((x for x in parts[1:] if x and '=' not in x), filename)
                entries.append('* [画像：' + caption + '](' + source_url('ファイル:' + filename) + ')')
        return '\n\n' + '\n'.join(entries) + '\n\n'
    return GALLERY_RE.sub(callback, src)


def strip_layout_html(text):
    # Display-only wrappers from Fandom (not arbitrary article text) can swallow
    # Markdown under the static generator's HTML sanitization, so remove wrappers.
    text = re.sub(r'</?(?:div|span|center|big|small|font)\b[^>]*>', '', text, flags=re.I)
    text = re.sub(r'\[\[(?:en|fr|de|es):[^\]]*\]\]', '', text, flags=re.I)
    return text


def replace_links(src, title_lookup, known_images, missing_links, missing_images):
    token_map = {}
    counter = 0
    def fn(match):
        nonlocal counter
        counter += 1
        token = f'SSWWIKILINKPLACEHOLDER{counter:07d}'
        expr = match.group(1).strip()
        target, bar, rest = expr.partition('|')
        target = target.lstrip(':').strip()
        bits = rest.split('|') if bar else []
        display = (bits[-1] if bits else target).strip()
        namespace = target.split(':', 1)[0].lower() if ':' in target else ''
        if namespace in IMAGE_NAMESPACES:
            filename = image_filename(target)
            if filename:
                if filename not in known_images:
                    missing_images.add(filename)
                inline = any(re.search(r'\b(?:1[0-9]|2[0-9]|3[0-9]|40)px\b', bit) for bit in bits)
                caption = next((bit.strip() for bit in reversed(bits) if bit and not re.match(r'^(?:\d+px|\d+x\d+px|thumb|thumbnail|frame|フレームなし|サムネイル|left|right|center|none|link=.*)$', bit, re.I)), '')
                shortcode = '{{< media file=' + json_quote(filename)
                shortcode += ' alt=' + json_quote(caption or filename)
                shortcode += ' inline=' + ('true' if inline else 'false') + ' >}}'
                token_map[token] = shortcode
            else:
                token_map[token] = '[画像情報](' + source_url(target) + ')'
        elif namespace in {'category', 'カテゴリ', 'カテゴリー', '分類'}:
            token_map[token] = ''
        elif namespace in {'en', 'de', 'fr', 'es'}:
            token_map[token] = ''
        else:
            local, sep, anchor = target.partition('#')
            resolved = local.replace('_', ' ').strip()
            label = display if bar else (local or anchor)
            label = label.strip() or resolved
            if resolved in title_lookup:
                href = '{{< relref ' + json_quote(title_lookup[resolved]) + ' >}}'
                # MediaWiki fragments may differ from Hugo heading slugs; retain
                # content link but do not claim that fragment anchors will match.
                token_map[token] = '[' + label + '](' + href + ')'
            elif resolved == '' and anchor:
                token_map[token] = label
            else:
                missing_links.add(resolved)
                token_map[token] = '[' + label + '](' + source_url(target) + ')'
        return token
    return LINK_RE.sub(fn, src), token_map


def write_frontmatter(page, categories, infobox, aliases):
    front = ['---', 'title: ' + json_quote(page['title']),
             'source_url: ' + json_quote(source_url(page['title'])),
             'wiki_page_id: ' + json_quote(page['id'])]
    if page['title'] != WIKI_TITLE:
        front.append('url: ' + json_quote('/wiki/' + slug(page['title']) + '/'))
    if page['last_revision']:
        front.append('lastmod: ' + json_quote(page['last_revision']))
    if categories:
        front.append('categories:')
        front.extend('  - ' + json_quote(c) for c in categories)
    if aliases:
        front.append('aliases:')
        front.extend('  - ' + json_quote('/wiki/' + slug(a) + '/') for a in sorted(set(aliases)))
    if infobox:
        front.extend(['infobox:', '  template: ' + json_quote(infobox['template']),
                      '  kind: ' + json_quote(infobox['kind'])])
        if infobox['images']:
            front.append('  images:')
            for img in infobox['images']:
                front.extend(['    - label: ' + json_quote(img['label']),
                              '      filename: ' + json_quote(img['filename'])])
        if infobox['fields']:
            front.append('  fields:')
            for item in infobox['fields']:
                front.extend(['    - label: ' + json_quote(item['label']),
                              '      value: ' + json_quote(item['value'])])
    return '\n'.join(front + ['---', '']) + '\n'


def pandoc_mediawiki(raw, pandoc):
    run = subprocess.run([pandoc, '--from=mediawiki', '--to=gfm', '--wrap=none'],
                         input=raw, text=True, capture_output=True, encoding='utf-8')
    if run.returncode:
        raise RuntimeError('Pandoc failed: ' + run.stderr[:1000])
    return run.stdout


def import_dump(options):
    base = Path(__file__).resolve().parents[1]
    xml_path = Path(options.xml)
    if xml_path.suffix.lower() != '.xml':
        raise SystemExit('展開済み XML を指定してください（7z は先に展開）。')
    pandoc = shutil.which('pandoc')
    if not pandoc:
        raise SystemExit('Pandoc が見つかりません。Pandoc をインストールしてください。')
    output = base / 'content' / 'wiki'
    raw_dir = base / 'migration' / 'raw'
    output.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    image_dir = base / 'static' / 'images'
    image_dir.mkdir(parents=True, exist_ok=True)
    if options.assets:
        for asset in Path(options.assets).rglob('*'):
            if asset.is_file() and asset.suffix.lower() in {'.png','.jpg','.jpeg','.gif','.svg','.webp','.avif'}:
                target = image_dir / asset.name.replace(' ', '_')
                shutil.copy2(asset, target)
    local_images = {p.name for p in image_dir.iterdir() if p.is_file()}
    pages = read_xml(xml_path)
    main = [p for p in pages if p['ns'] == '0']
    redirects = {p['title'].replace('_',' '): p['redirect'].split('#',1)[0].replace('_',' ') for p in main if p['redirect']}
    articles = [p for p in main if not p['redirect']]
    target_by_title = {p['title'].replace('_',' '): ('_index.md' if p['title'] == WIKI_TITLE else 'wiki/' + article_name(p)) for p in articles}
    alias_by_title = collections.defaultdict(list)
    unresolved_redirects = []
    for alias, target in redirects.items():
        visited = set()
        while target in redirects and target not in visited:
            visited.add(target)
            target = redirects[target]
        if target in target_by_title:
            target_by_title[alias] = target_by_title[target]
            alias_by_title[target].append(alias)
        else:
            unresolved_redirects.append({'alias': alias, 'target': target})
    if list(output.glob('article-*.md')) and not options.force:
        raise SystemExit('既存の取り込み記事が存在。再取込には --force を指定してください。')
    if options.force:
        for old in output.glob('article-*.md'):
            old.unlink()
    template_counter = collections.Counter()
    images_referenced = set()
    image_missing = set()
    missing_links = set()
    unsupported_by_page = {}
    imported = []
    inferred_categories = collections.Counter()
    for pg in articles:
        txt = pg['text']
        page_id = pg['id'] or hashlib.sha1(pg['title'].encode()).hexdigest()[:12]
        (raw_dir / f'page-{page_id}.wiki').write_text(txt, encoding='utf-8')
        categories = list(dict.fromkeys(c.strip().replace('{{SITENAME}}', WIKI_TITLE) for c in CATEGORY_RE.findall(txt) if c.strip()))
        body = CATEGORY_RE.sub('', txt)
        body = DEFAULTSORT_RE.sub('', body)
        body = transform_galleries(body, images_referenced)
        body = strip_layout_html(body)
        infobox = None
        unsupported = []
        for start, end, tokenbody in reversed(outer_templates(body)):
            name, params = split_template(tokenbody)
            template_counter[name] += 1
            candidate = infobox_for(name, params, image_missing, local_images)
            if candidate and infobox is None:
                infobox = candidate
                for image in candidate['images']:
                    images_referenced.add(image['filename'])
                replacement = ''
            elif re.match(r'^(?:DEFAULTSORT|DISPLAYTITLE|デフォルトソート|SITENAME)\b', name, re.I):
                replacement = ''
            elif name == '!':
                replacement = '|'
            else:
                unsupported.append(name)
                replacement = f'SSWUNSUPPORTEDTEMPLATE{len(unsupported):05d}'
            body = body[:start] + replacement + body[end:]
        if infobox and not categories and infobox['kind'] in INFER_CATEGORY:
            categories.append(INFER_CATEGORY[infobox['kind']])
            inferred_categories[categories[-1]] += 1
        body, substitutions = replace_links(body, target_by_title, local_images, missing_links, image_missing)
        for rep in substitutions.values():
            match = re.search(r'\{\{< media file="([^"]+)', rep)
            if match:
                images_referenced.add(match.group(1))
        markdown = pandoc_mediawiki(body, pandoc)
        for marker, replacement in substitutions.items():
            markdown = markdown.replace(marker, replacement)
        for n, name in enumerate(unsupported, 1):
            # Preserve the missing expansion visibly but without implying success.
            markdown = markdown.replace(f'SSWUNSUPPORTEDTEMPLATE{n:05d}', f'**[未移植テンプレート: {name}]**')
        if unsupported:
            unsupported_by_page[pg['title']] = list(reversed(unsupported))
        newtext = write_frontmatter(pg, categories, infobox, alias_by_title[pg['title'].replace('_', ' ')]) + markdown.strip() + '\n'
        relative = '_index.md' if pg['title'] == WIKI_TITLE else 'wiki/' + article_name(pg)
        (base/'content'/relative).write_text(newtext, encoding='utf-8')
        imported.append({
            'title': pg['title'], 'file': 'content/' + relative, 'url': '/' if pg['title'] == WIKI_TITLE else '/wiki/' + slug(pg['title']) + '/',
            'categories': categories, 'infobox': infobox['template'] if infobox else None,
            'source_url': source_url(pg['title']), 'original_revisions': pg['revisions'],
        })
    preserved_ns = collections.Counter()
    excluded_ns = collections.Counter()
    for pg in pages:
        if pg['ns'] == '0':
            continue
        if pg['ns'] in {'6','10','14'}:
            key = pg['id'] if pg['id'].isdecimal() else hashlib.sha1(pg['title'].encode()).hexdigest()[:12]
            (raw_dir/f"nonarticle-{pg['ns']}-{key}.wiki").write_text(pg['text'], encoding='utf-8')
            preserved_ns[pg['ns']] += 1
        else:
            excluded_ns[pg['ns']] += 1
    # The original XML contains actual revisions; the public repository ships
    # only current wikitext, not raw edit histories or user-space pages.
    nav_titles = ['通史','国家一覧','イデオロギー一覧','開発状況','アップデート履歴','大東亜戦争']
    nav_items = [{'title': t, 'path': ('wiki/' + slug(t) + '/') if t in target_by_title else ''}
                 for t in nav_titles if t in target_by_title]
    data = base/'data'; data.mkdir(exist_ok=True)
    (data/'navigation.json').write_text(json.dumps(nav_items, ensure_ascii=False, indent=2), encoding='utf-8')
    lookup_pages = {p['title']:p for p in articles}
    search_rows=[]
    for item in imported:
        txt = lookup_pages[item['title']]['text']
        # Search index retains textual context without publishing wikitext markup.
        txt = re.sub(r'\{\{.*?\}\}', '', txt, flags=re.S)
        txt = plain_text(txt)[:400]
        search_rows.append({'title':item['title'],'path':item['url'].lstrip('/'), 'description':txt,
                            'categories':item['categories']})
    (base/'static'/'search-index.json').write_text(json.dumps(search_rows, ensure_ascii=False), encoding='utf-8')
    total_refs = images_referenced | image_missing
    report = {
        'source': WIKI_URL, 'xml_page_count':len(pages),
        'namespace_counts':dict(collections.Counter(p['ns'] for p in pages)),
        'content_pages_in_namespace_0':len(articles), 'articles_written':len(imported),
        'redirects':redirects, 'redirects_resolved_count': len(redirects)-len(unresolved_redirects), 'redirects_unresolved_count':len(unresolved_redirects), 'redirects_unresolved':unresolved_redirects,
        'infobox_counts':dict(collections.Counter(a['infobox'] for a in imported if a['infobox'])),
        'template_usage':template_counter.most_common(),
        'unconverted_templates':unsupported_by_page,
        'uncategorized_articles':sorted(a['title'] for a in imported if not a['categories']),
        'inferred_categories':dict(inferred_categories),
        'missing_internal_link_targets':sorted(missing_links),
        'images_referenced_in_articles':len(total_refs),
        'images_missing_from_static_images':sorted(name for name in total_refs if name not in local_images),
        'images_present_locally':sorted(name for name in total_refs if name in local_images),
        'raw_files_by_namespace_preserved':dict(preserved_ns),
        'raw_user_and_system_pages_excluded':dict(excluded_ns),
        'articles':imported,
        'limitations':[
            '画像本体はFandom XMLに入っていない。static/images/ に別途コピーが必要。',
            'Fandom固有テンプレート/高度なHTML/表/ギャラリーは手動確認が必要。',
            '過去版の編集履歴はGit履歴に再現していない（元XMLを手元で保存）。',
            '元Fandomサイト上のページ別履歴への帰属リンクを残している。',
            'Fandomのカテゴリ階層やLuaテンプレートはHugoで自動実行されない。',
        ],
    }
    (base/'migration'/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    (base/'migration'/'README.txt').write_text('各ページの最新原文（Wikitext）です。Fandomサイトと原XMLも保管してください。\n',encoding='utf-8')
    print('Imported:',len(imported),'articles,',len(redirects),'redirects')
    print('Infoboxes:', report['infobox_counts'])
    print('Missing image files:',len(report['images_missing_from_static_images']))
    print('Missing internal link targets:',len(missing_links))
    print('Unsupported templates per pages:',len(unsupported_by_page))
    print('Details:',base/'migration'/'report.json')


def main():
    parser=argparse.ArgumentParser(description='SSW Fandom XML -> GitHub Pages/Hugo converter')
    parser.add_argument('xml', help='展開した Fandom MediaWiki XML ダンプ')
    parser.add_argument('--assets', help='画像ファイルを集めたフォルダ（任意）')
    parser.add_argument('--force', action='store_true', help='既存の自動生成記事を上書き')
    opts=parser.parse_args()
    import_dump(opts)


if __name__ == '__main__':
    main()
