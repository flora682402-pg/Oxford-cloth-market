// Oxford Cloth Market — site behaviour. One small file for every page; each
// feature checks for its own elements, so a page only runs what it contains.
// Type-checked with `tsc --checkJs` (see tests/run_all.sh).
(() => {
  'use strict';

  const phone = window.matchMedia('(max-width:900px)');

  /** @param {MediaQueryList} mq @param {() => void} fn */
  const onMediaChange = (mq, fn) => {
    if (mq.addEventListener) mq.addEventListener('change', fn);
    else mq.addListener(fn); // Safari 13 and older
  };

  // Header: dock the badge once the page scrolls; only touch the DOM on change.
  const hdr = document.getElementById('hdr');
  if (hdr) {
    let docked = false;
    let queued = false;
    const update = () => {
      queued = false;
      const next = window.scrollY > 60;
      if (next !== docked) { docked = next; hdr.classList.toggle('scrolled', docked); }
    };
    window.addEventListener('scroll', () => {
      if (!queued) { queued = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  // Phone menu: toggle, close on link tap, Escape, or widening to desktop.
  const btn = document.getElementById('menuBtn');
  const drawer = document.getElementById('drawer');
  if (hdr && btn && drawer) {
    /** @param {boolean} open @param {boolean} [restoreFocus] */
    const setMenu = (open, restoreFocus) => {
      drawer.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      hdr.classList.toggle('menu-open', open);
      if (!open && restoreFocus) btn.focus();
    };
    btn.addEventListener('click', () => setMenu(!hdr.classList.contains('menu-open')));
    drawer.addEventListener('click', (e) => {
      if (e.target instanceof Element && e.target.closest('a')) setMenu(false);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !drawer.hidden) setMenu(false, true);
    });
    onMediaChange(phone, () => { if (!phone.matches) setMenu(false); });
  }

  // Footer: link groups are always open on desktop, collapsible on phones.
  const groups = /** @type {HTMLDetailsElement[]} */ ([...document.querySelectorAll('.ftr details')]);
  if (groups.length) {
    const sync = () => groups.forEach((d) => { d.open = !phone.matches; });
    groups.forEach((d) => {
      const summary = d.querySelector('summary');
      if (summary) summary.addEventListener('click', (e) => { if (!phone.matches) e.preventDefault(); });
    });
    onMediaChange(phone, sync);
    sync();
  }

  // Newsletter. With a sign-up provider configured the form posts to it
  // natively and this code does nothing. Without one, never claim success.
  const form = document.getElementById('nl');
  const email = document.getElementById('email');
  const msg = document.getElementById('nlMsg');
  if (form instanceof HTMLFormElement && email instanceof HTMLInputElement && msg && !form.getAttribute('action')) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!/^\S+@\S+\.\S+$/.test(email.value.trim())) {
        msg.textContent = 'Enter a valid email address.';
        return;
      }
      msg.textContent = 'Email sign-up opens soon. Until then, new arrivals go up first on ';
      const a = document.createElement('a');
      a.href = 'https://www.instagram.com/oxfordclothmarket';
      a.textContent = 'Instagram';
      msg.append(a, '.');
    });
    email.addEventListener('input', () => { msg.textContent = ''; });
  }

  // Pop-ups: hide events whose date has passed (pages are also rebuilt, but
  // this keeps the list right between builds).
  const events = /** @type {HTMLElement[]} */ ([...document.querySelectorAll('.events [data-date]')]);
  if (events.length) {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    let shown = 0;
    events.forEach((li) => {
      const past = (li.dataset.date || '') < today;
      li.hidden = past;
      if (!past) shown += 1;
    });
    const none = document.getElementById('noEvents');
    if (none) none.hidden = shown > 0;
  }

  // Clothing page: category filter driven by the URL hash (#shirts, #ties...).
  const rack = document.querySelector('.rack');
  if (rack) {
    const items = /** @type {HTMLElement[]} */ ([...rack.querySelectorAll('.item')]);
    const chips = /** @type {HTMLAnchorElement[]} */ ([...document.querySelectorAll('.chips a')]);
    const title = document.getElementById('shopTitle');
    const empty = document.getElementById('empty');
    /** @type {Record<string, string>} */
    const names = {};
    chips.forEach((a) => { if (a.dataset.k && a.dataset.k !== 'all') names[a.dataset.k] = a.dataset.label || a.dataset.k; });
    const apply = () => {
      const hash = window.location.hash.slice(1);
      const cat = Object.prototype.hasOwnProperty.call(names, hash) ? hash : 'all';
      let n = 0;
      items.forEach((i) => {
        const show = cat === 'all' || i.dataset.cat === cat;
        i.hidden = !show;
        if (show) n += 1;
      });
      if (empty) empty.hidden = n > 0;
      if (title) title.textContent = cat === 'all' ? 'Clothing' : names[cat];
      chips.forEach((a) => a.setAttribute('aria-current', String(a.dataset.k === cat)));
    };
    window.addEventListener('hashchange', apply);
    apply();
  }
})();
