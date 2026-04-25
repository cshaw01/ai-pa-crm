// Chiefpa marketing site — partial loader.
// Each page declares <div data-partial="header"></div> and <div data-partial="footer"></div>
// where the shared chrome should land. We fetch and inject on DOMContentLoaded.
//
// Note: <head> contents (Tailwind, meta tags, tracking pixels) are NOT injected here —
// they live directly in each page's <head> for correct load timing. The single edit
// point for tracking pixels is /tracking.js, included from each page's <head>.

(function () {
  function loadPartial(el) {
    var name = el.getAttribute('data-partial');
    if (!name) return Promise.resolve();
    return fetch('/_' + name, { credentials: 'omit' })
      .then(function (res) {
        if (!res.ok) throw new Error('partial ' + name + ' ' + res.status);
        return res.text();
      })
      .then(function (html) { el.innerHTML = html; })
      .catch(function (err) { console.warn('Partial load failed:', name, err); });
  }

  function initMobileNav() {
    var toggle = document.querySelector('[data-mobile-nav-toggle]');
    var menu = document.querySelector('[data-mobile-nav]');
    if (!toggle || !menu) return;
    toggle.addEventListener('click', function () { menu.classList.toggle('hidden'); });
  }

  function fillCurrentYear() {
    var slot = document.querySelector('[data-year]');
    if (slot) slot.textContent = String(new Date().getFullYear());
  }

  function highlightCurrentNav() {
    var path = (window.location.pathname || '/').replace(/\/$/, '') || '/';
    document.querySelectorAll('[data-partial="header"] a[href]').forEach(function (a) {
      var href = (a.getAttribute('href') || '').replace(/\/$/, '');
      if (href === path) a.style.color = 'var(--brand-blue)';
    });
  }

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var targets = Array.prototype.slice.call(document.querySelectorAll('[data-partial]'));
    Promise.all(targets.map(loadPartial)).then(function () {
      initMobileNav();
      fillCurrentYear();
      highlightCurrentNav();
    });
  });
})();
