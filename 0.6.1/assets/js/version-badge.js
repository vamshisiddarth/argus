/* Fetch latest GitHub release tag and update the hero badge version span */
(function () {
  const REPO = "vamshisiddarth/argus";
  const el = document.querySelector(".hero-badge-version");
  if (!el) return;

  fetch(`https://api.github.com/repos/${REPO}/releases/latest`)
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (data && data.tag_name) {
        el.textContent = data.tag_name;
      }
    })
    .catch(function () { /* leave static fallback text */ });
})();
