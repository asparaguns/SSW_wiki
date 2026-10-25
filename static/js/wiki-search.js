(() => {
  'use strict';
  const input = document.getElementById('wiki-search');
  const results = document.getElementById('wiki-search-results');
  if (!input || !results) return;
  let indexPromise;
  const indexURL = input.dataset.indexUrl;
  const rootURL = new URL(input.dataset.root, window.location.origin);
  function getIndex() {
    if (!indexPromise) {
      indexPromise = fetch(indexURL).then(r => {
        if (!r.ok) throw new Error('search-index request failed');
        return r.json();
      }).catch(() => []);
    }
    return indexPromise;
  }
  function render(matches) {
    results.replaceChildren();
    if (!matches.length) {
      if (input.value.trim()) results.textContent = '該当する記事はありません。';
      return;
    }
    const ul = document.createElement('ul');
    for (const item of matches.slice(0, 12)) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = new URL(item.path, rootURL).href;
      a.textContent = item.title;
      li.appendChild(a);
      ul.appendChild(li);
    }
    results.appendChild(ul);
  }
  let serial = 0;
  input.addEventListener('input', async () => {
    const current = ++serial;
    const query = input.value.normalize('NFKC').trim().toLocaleLowerCase();
    if (!query) { results.replaceChildren(); return; }
    const items = await getIndex();
    if (serial !== current) return;
    const tokens = query.split(/\s+/).filter(Boolean);
    const ranked = items.map(item => {
      const title = item.title.normalize('NFKC').toLocaleLowerCase();
      const text = (item.description + ' ' + item.categories.join(' ')).normalize('NFKC').toLocaleLowerCase();
      if (!tokens.every(t => title.includes(t) || text.includes(t))) return null;
      return { item, rank: tokens.every(t => title.includes(t)) ? 0 : 1 };
    }).filter(Boolean).sort((a, b) => a.rank - b.rank || a.item.title.localeCompare(b.item.title, 'ja'));
    render(ranked.map(x => x.item));
  });
})();
