// Small progressive enhancements. Every page also works without JavaScript.
(function () {
  // Parent name appears (and becomes required) for students under 14.
  var age = document.getElementById('age');
  var parentField = document.getElementById('parent-field');
  var parentInput = document.getElementById('parent_name');
  function syncParent() {
    if (!age || !parentField) return;
    var v = parseInt(age.value, 10);
    var minor = v > 0 && v < 14;
    parentField.classList.toggle('show', minor || (parentInput && parentInput.value));
    if (parentInput) parentInput.required = minor;
  }
  if (age) { age.addEventListener('input', syncParent); syncParent(); }

  // Confirm before bulk / destructive actions.
  document.querySelectorAll('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });
  document.querySelectorAll('[data-confirm-click]').forEach(function (b) {
    b.addEventListener('click', function (e) { if (!confirm(b.dataset.confirmClick)) e.preventDefault(); });
  });

  // Copy-to-clipboard buttons.
  document.querySelectorAll('[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function () { b.textContent = 'Copied'; });
    });
  });

  // Calendar: tap a class or demo to see details and act on it.
  var dlg = document.getElementById('ev-dialog');
  if (dlg) {
    var form = document.getElementById('ev-form');
    var btn = document.getElementById('ev-action');
    document.querySelectorAll('[data-ev]').forEach(function (el) {
      el.addEventListener('click', function () {
        var ev = JSON.parse(el.dataset.ev);
        document.getElementById('ev-date').textContent = el.dataset.date;
        document.getElementById('ev-title').textContent = ev.title;
        document.getElementById('ev-when').textContent = ev.when;
        document.getElementById('ev-info').textContent = ev.info;
        if (ev.action) {
          form.action = ev.action; btn.textContent = ev.action_label; form.style.display = '';
        } else {
          form.style.display = 'none';
        }
        if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
      });
    });
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
  }

  // Homepage carousel: auto-advances, swipe on phones, arrows and dots.
  document.querySelectorAll('[data-carousel]').forEach(function (car) {
    var slides = car.querySelectorAll('.slide');
    var dots = car.querySelectorAll('[data-go]');
    if (slides.length < 2) return;
    var i = 0, timer = null;
    function show(n) {
      var prev = slides[i];
      i = (n + slides.length) % slides.length;
      var vid = prev.querySelector('video'); if (vid) vid.pause();
      prev.classList.remove('active');
      slides[i].classList.add('active');
      var v = slides[i].querySelector('video'); if (v) { v.currentTime = 0; v.play().catch(function () {}); }
      dots.forEach(function (d, k) { d.classList.toggle('active', k === i); });
    }
    function next() { show(i + 1); }
    function restart() {
      clearInterval(timer);
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) timer = setInterval(next, 5500);
    }
    car.querySelector('[data-next]').addEventListener('click', function () { next(); restart(); });
    car.querySelector('[data-prev]').addEventListener('click', function () { show(i - 1); restart(); });
    dots.forEach(function (d) { d.addEventListener('click', function () { show(+d.dataset.go); restart(); }); });
    var x0 = null;
    car.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; }, { passive: true });
    car.addEventListener('touchend', function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0; x0 = null;
      if (Math.abs(dx) > 40) { show(dx < 0 ? i + 1 : i - 1); restart(); }
    });
    document.addEventListener('visibilitychange', function () { if (document.hidden) clearInterval(timer); else restart(); });
    restart();
  });

  // Background music. Browsers block sound until the visitor interacts with the page,
  // so we try straight away and otherwise start on the first tap, click or key press.
  // The position carries over between pages, and the visitor's on/off choice is remembered.
  var bgm = document.getElementById('bgm');
  var bgmBtn = document.getElementById('bgm-toggle');
  if (bgm && bgmBtn) {
    var store = {
      get: function (s, k) { try { return window[s].getItem(k); } catch (e) { return null; } },
      set: function (s, k, v) { try { window[s].setItem(k, v); } catch (e) {} }
    };
    var off = store.get('localStorage', 'bgm-off') === '1';
    var target = 0.35;
    bgm.volume = 0;
    var t = parseFloat(store.get('sessionStorage', 'bgm-t'));
    if (t > 0) bgm.addEventListener('loadedmetadata', function () { if (t < bgm.duration) bgm.currentTime = t; }, { once: true });
    function setBtn(on) { bgmBtn.setAttribute('aria-pressed', on ? 'true' : 'false'); }
    function fadeIn() {
      var step = setInterval(function () {
        bgm.volume = Math.min(target, bgm.volume + 0.02);
        if (bgm.volume >= target) clearInterval(step);
      }, 80);
    }
    function start() {
      if (off) return;
      var p = bgm.play();
      if (p && p.then) p.then(function () { setBtn(true); fadeIn(); unlisten(); }).catch(function () {});
      else { setBtn(true); fadeIn(); unlisten(); }
    }
    var evs = ['pointerdown', 'keydown', 'touchend'];
    function onFirst(e) { if (e.target.closest && e.target.closest('#bgm-toggle')) return; start(); }
    function unlisten() { evs.forEach(function (ev) { document.removeEventListener(ev, onFirst, true); }); }
    evs.forEach(function (ev) { document.addEventListener(ev, onFirst, true); });
    bgmBtn.addEventListener('click', function () {
      if (bgm.paused) { off = false; store.set('localStorage', 'bgm-off', '0'); start(); }
      else { bgm.pause(); off = true; store.set('localStorage', 'bgm-off', '1'); setBtn(false); }
    });
    setBtn(false);
    start();
    function savePos() { if (!bgm.paused) store.set('sessionStorage', 'bgm-t', String(bgm.currentTime)); }
    setInterval(savePos, 1500);
    window.addEventListener('pagehide', savePos);
  }

  // Admin → Website: the custom colour picker selects the "Custom" swatch.
  var bgCustom = document.getElementById('bg-custom');
  if (bgCustom) {
    var radio = document.getElementById('bg-custom-radio');
    bgCustom.addEventListener('input', function () { radio.value = bgCustom.value; radio.checked = true; document.body.style.setProperty('--bg', bgCustom.value); });
    document.querySelectorAll('.swatch input[type=radio]').forEach(function (r) {
      r.addEventListener('change', function () { document.body.style.setProperty('--bg', r.value); });
    });
  }
})();
