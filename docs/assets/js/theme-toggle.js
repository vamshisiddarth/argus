/* Replace Material's default toggle with a polished sun/moon pill */
(function () {
  function init() {
    if (document.querySelector('.tt-pill')) return;

    /* Both palette labels exist in the DOM; Material shows/hides them via CSS.
       We need to keep them in the DOM so Material can switch them — just make
       them invisible. Do NOT set pointer-events:none because `.click()` calls
       on hidden elements still dispatch the event. */
    var origLabels = document.querySelectorAll(
      '.md-header__button[title^="Switch"]'
    );
    if (!origLabels.length) return;

    origLabels.forEach(function (l) {
      /* Hide visually but keep in layout flow so Material can toggle display */
      l.style.cssText =
        'position:absolute;opacity:0;width:0;height:0;overflow:hidden;';
    });

    /* Build pill */
    var pill = document.createElement('div');
    pill.className = 'tt-pill';
    pill.setAttribute('role', 'button');
    pill.setAttribute('tabindex', '0');
    pill.setAttribute('aria-label', 'Toggle light / dark mode');
    pill.innerHTML =
      '<svg class="tt-icon tt-sun" viewBox="0 0 24 24">' +
        '<path d="M12 7a5 5 0 1 0 0 10A5 5 0 0 0 12 7zm-9 4H1a1 1 0 0 0 0 2h2a1 1 0 0 0 0-2zm20 0h-2a1 1 0 0 0 0 2h2a1 1 0 0 0 0-2zM11 2V0a1 1 0 0 1 2 0v2a1 1 0 0 1-2 0zm0 20v-2a1 1 0 0 1 2 0v2a1 1 0 0 1-2 0zM5.64 4.22 4.22 2.8a1 1 0 0 0-1.42 1.42l1.42 1.42a1 1 0 0 0 1.42-1.42zm14.14 14.14-1.42-1.42a1 1 0 0 0-1.42 1.42l1.42 1.42a1 1 0 0 0 1.42-1.42zm0-16.97a1 1 0 0 0-1.42 0l-1.42 1.42a1 1 0 0 0 1.42 1.42l1.42-1.42a1 1 0 0 0 0-1.42zM5.64 19.78l-1.42-1.42a1 1 0 0 0-1.42 1.42l1.42 1.42a1 1 0 0 0 1.42-1.42z"/>' +
      '</svg>' +
      '<div class="tt-track"><div class="tt-thumb"></div></div>' +
      '<svg class="tt-icon tt-moon" viewBox="0 0 24 24">' +
        '<path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>' +
      '</svg>';

    /* Insert right after the first original label */
    origLabels[0].parentNode.insertBefore(pill, origLabels[0].nextSibling);

    function isDark() {
      return document.body.getAttribute('data-md-color-scheme') === 'slate';
    }

    function syncPill() {
      pill.classList.toggle('tt-dark', isDark());
    }
    syncPill();

    new MutationObserver(syncPill).observe(document.body, {
      attributes: true,
      attributeFilter: ['data-md-color-scheme'],
    });

    function doToggle() {
      /* Click whichever palette label Material is currently showing.
         Material controls visibility via CSS display:none/block — find the
         one that is NOT hidden. */
      var labels = document.querySelectorAll('[for^="__palette_"]');
      var active = Array.from(labels).find(function (l) {
        return getComputedStyle(l).display !== 'none';
      });
      if (active) active.click();
    }

    pill.addEventListener('click', doToggle);
    pill.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        doToggle();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('DOMContentSwitch', init);
})();
