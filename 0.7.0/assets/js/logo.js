(function () {
  var CSS = [
    '.argus-logo{display:flex;align-items:center;gap:0;text-decoration:none;}',
    '.argus-logo .al-bracket{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:20px;font-weight:400;line-height:1;color:#8b8fff;display:inline-block;}',
    '.argus-logo .al-word{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;font-weight:700;letter-spacing:-0.01em;line-height:1;color:#fff;padding:0 4px;display:inline-block;}',
    '.argus-logo .al-eye{display:inline-block;margin:0 5px;flex-shrink:0;}',
    '[data-md-color-scheme="default"] .argus-logo .al-bracket{color:#4f46e5;}',
    '[data-md-color-scheme="default"] .argus-logo .al-word{color:#1a1a2e;}',

    '@keyframes argus-bracket-l{0%{transform:translateX(52px);opacity:0}60%{transform:translateX(-4px);opacity:1}80%{transform:translateX(2px)}100%{transform:translateX(0)}}',
    '@keyframes argus-bracket-r{0%{transform:translateX(-52px);opacity:0}60%{transform:translateX(4px);opacity:1}80%{transform:translateX(-2px)}100%{transform:translateX(0)}}',
    '@keyframes argus-word{0%,25%{opacity:0;transform:scaleX(0.6)}70%{opacity:1;transform:scaleX(1.04)}100%{opacity:1;transform:scaleX(1)}}',
    '@keyframes argus-eye-pop{0%,40%{transform:scale(0);opacity:0}70%{transform:scale(1.3);opacity:1}85%{transform:scale(0.88)}95%{transform:scale(1.06)}100%{transform:scale(1)}}',
    '@keyframes argus-dart{0%,75%{transform:translate(0,0)}80%{transform:translate(2px,-1px)}87%{transform:translate(-2px,1.5px)}94%,100%{transform:translate(0,0)}}',

    '.argus-logo.intro .al-bracket-l{animation:argus-bracket-l 0.7s cubic-bezier(.22,1,.36,1) 0.05s both;}',
    '.argus-logo.intro .al-bracket-r{animation:argus-bracket-r 0.7s cubic-bezier(.22,1,.36,1) 0.05s both;}',
    '.argus-logo.intro .al-word{animation:argus-word 0.6s cubic-bezier(.22,1,.36,1) 0.15s both;}',
    '.argus-logo.intro .al-eye{animation:argus-eye-pop 0.7s cubic-bezier(.34,1.56,.64,1) 0.3s both;}',
    '.argus-logo.intro .al-pupil{animation:argus-dart 4s ease-in-out 1.2s infinite;}',
    '.argus-logo:not(.intro) .al-pupil{animation:argus-dart 4s ease-in-out infinite;}',
  ].join('');

  function injectStyle() {
    if (document.getElementById('argus-logo-css')) return;
    var s = document.createElement('style');
    s.id = 'argus-logo-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildLogo(playIntro) {
    var wrap = document.createElement('a');
    wrap.className = 'argus-logo' + (playIntro ? ' intro' : '');
    wrap.href = '.';
    wrap.setAttribute('aria-label', 'Argus home');

    wrap.innerHTML =
      '<span class="al-bracket al-bracket-l">[</span>' +
      '<svg class="al-eye" width="26" height="26" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
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
      '<span class="al-bracket al-bracket-r">]</span>';

    return wrap;
  }

  function init() {
    injectStyle();
    var logoEl = document.querySelector('.md-header__button.md-logo');
    if (!logoEl || logoEl.querySelector('.argus-logo')) return;

    /* Play intro once per browser session */
    var played = sessionStorage.getItem('argus-logo-played');
    var playIntro = !played;
    if (playIntro) sessionStorage.setItem('argus-logo-played', '1');

    logoEl.innerHTML = '';
    logoEl.appendChild(buildLogo(playIntro));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('DOMContentSwitch', init);
})();
