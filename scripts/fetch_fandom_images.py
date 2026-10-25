#!/usr/bin/env python3
"""OPTIONAL: request Fandom image URLs and (with --download) save local copies.

The XML export contains file description pages but not the image bytes. Confirm
rights/licenses for each file before use on another website. Network access to
Fandom can be blocked, rate-limited, or changed by Fandom without notice.
"""
import argparse
import json
import mimetypes
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'migration' / 'report.json'
API = 'https://ssw-mod.fandom.com/api.php'
USER_AGENT = 'SSWWiki-Migration/1.0 (community wiki export; respectful batching)'
ALLOWED_DOMAINS = {'static.wikia.nocookie.net', 'vignette.wikia.nocookie.net', 'images.wikia.nocookie.net', 'ssw-mod.fandom.com'}


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def chunks(seq, length):
    for i in range(0, len(seq), length):
        yield seq[i:i+length]


def accepted_url(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname in ALLOWED_DOMAINS


def main():
    ap = argparse.ArgumentParser(description='SSW Wiki画像の取得候補を整理（権利確認後に--download）')
    ap.add_argument('--download', action='store_true', help='許諾を確認した画像を保存する')
    ap.add_argument('--limit', type=int, default=0, help='先頭N個だけ処理（0はすべて）')
    ap.add_argument('--pause', type=float, default=0.6, help='問い合わせ間隔（秒）')
    args=ap.parse_args()
    report=json.loads(REPORT.read_text(encoding='utf-8'))
    items=report.get('images_missing_from_static_images', [])
    if args.limit:
        items=items[:args.limit]
    output=ROOT / 'static' / 'images'
    output.mkdir(parents=True, exist_ok=True)
    records=[]
    for batch in chunks(items, 20):
        titles='|'.join('File:'+s for s in batch)
        params=urllib.parse.urlencode({
            'action':'query','format':'json','formatversion':'2', 'prop':'imageinfo',
            'iiprop':'url|mime', 'titles': titles,
        })
        try:
            data=get_json(API+'?'+params)
        except Exception as exc:
            print('Fandom API request failed:', exc)
            print('A sign-in, new API route or manual asset export may be required.')
            break
        found={}
        for pg in data.get('query', {}).get('pages', []):
            title=pg.get('title','')
            filename=title.split(':',1)[-1].replace(' ', '_')
            entry=(pg.get('imageinfo') or [{}])[0]
            found[filename]=entry
        for name in batch:
            entry=found.get(name, {})
            url=entry.get('url','')
            meta={'file':name,'source':'https://ssw-mod.fandom.com/ja/wiki/ファイル:'+name,
                  'remote_url':url,'mime':entry.get('mime', ''), 'status':'metadata_only'}
            if args.download:
                if not url or not accepted_url(url):
                    meta['status']='no_usable_url'
                elif not name.lower().endswith(('.jpg','.jpeg','.png','.svg','.gif','.webp','.avif')):
                    meta['status']='unsupported_extension'
                else:
                    try:
                        request=urllib.request.Request(url, headers={'User-Agent':USER_AGENT})
                        with urllib.request.urlopen(request, timeout=35) as response:
                            if not accepted_url(response.geturl()):
                                raise RuntimeError('Unexpected redirect host')
                            raw=response.read(25*1024*1024+1)
                            if len(raw)>25*1024*1024:
                                raise RuntimeError('File exceeds 25 MB')
                            # Ensure remote response looks like an image before saving.
                            mime=response.headers.get_content_type()
                            if not mime.startswith('image/'):
                                raise RuntimeError('Not an image response: '+mime)
                        (output/name).write_bytes(raw)
                        meta['status']='downloaded'
                    except Exception as exc:
                        meta['status']='error: '+str(exc)
            records.append(meta)
        time.sleep(max(0,args.pause))
    manifest=ROOT / 'migration' / 'image-fetch-log.json'
    manifest.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Checked:',len(records), 'Downloaded:',sum(r['status']=='downloaded' for r in records))
    print('Log:',manifest)
    print('NOTE: Check each image license and add attribution before public redistribution.')


if __name__=='__main__':
    main()
