(function () {
  var CSS = [
    '.argus-logo{display:flex;align-items:center;gap:0;text-decoration:none;}',
    '.argus-logo .al-bracket{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:20px;font-weight:400;line-height:1;color:#8b8fff;}',
    '.argus-logo .al-word{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;font-weight:700;letter-spacing:-0.01em;line-height:1;color:#fff;padding:0 4px;}',
    '[data-md-color-scheme="default"] .argus-logo .al-bracket{color:#4f46e5;}',
    '[data-md-color-scheme="default"] .argus-logo .al-word{color:#1a1a2e;}',
    '@keyframes argus-dart{0%,75%{transform:translate(0,0)}80%{transform:translate(2px,-1px)}87%{transform:translate(-2px,1.5px)}94%,100%{transform:translate(0,0)}}',
    '.argus-logo .al-pupil{animation:argus-dart 4s ease-in-out infinite;}',
  ].join('');

  function injectStyle() {
    if (document.getElementById('argus-logo-css')) return;
    var s = document.createElement('style');
    s.id = 'argus-logo-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildLogo() {
    var wrap = document.createElement('a');
    wrap.className = 'argus-logo';
    wrap.href = '.';
    wrap.setAttribute('aria-label', 'Argus home');

    wrap.innerHTML =
      '<span class="al-bracket">[</span>' +
      '<svg width="26" height="26" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg" style="margin:0 5px;flex-shrink:0;" aria-hidden="true">' +
        '<circle cx="13" cy="13" r="12" fill="#2a2a3e" stroke="#8b8fff" stroke-width="2.2"/>' +
        '<circle cx="13" cy="13" r="9" fill="white"/>' +
        '<g class="al-pupil">' +
          '<circle cx="13" cy="13" r="5.2" fill="#3b2a1a"/>' +
          '<circle cx="13" cy="13" r="3" fill="#1a0f0a"/>' +
          '<circle cx="11" cy="11" r="1.4" fill="white"/>' +
          '<circle cx="14.5" cy="14.5" r="0.7" fill="white" opacity="0.6"/>' +
        '</g>' +
        '<ellipse cx="8.5" cy="8" rx="2" ry="1.1" fill="white" opacity="0.3" transform="rotate(-30 8.5 8)"/>' +
      '</svg>' +
      '<span class="al-word">argus</span>' +
      '<span class="al-bracket">]</span>';

    return wrap;
  }

  function init() {
    injectStyle();
    var logoEl = document.querySelector('.md-header__button.md-logo');
    if (!logoEl || logoEl.querySelector('.argus-logo')) return;
    logoEl.innerHTML = '';
    logoEl.appendChild(buildLogo());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('DOMContentSwitch', init);
})();
