// Public site motion: welcome curtain, header, menu, scroll reveals, parallax, rails, lightbox.
(function () {
  document.documentElement.classList.add('js');
  document.body.classList.add('js');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function ss(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } }

  // Welcome curtain, once per visit. The tap on it also lets the browser start the music.
  var curtain = document.querySelector('[data-curtain]');
  if (curtain && !ss('sanskriti-entered') && !/[?&]preview=/.test(location.search)) {
    curtain.hidden = false;
    document.body.classList.add('curtain-open');
    curtain.querySelectorAll('[data-enter]').forEach(function (b) {
      b.addEventListener('click', function () {
        ss('sanskriti-entered', '1');
        if (window.sanskritiMusic) {
          if (b.dataset.enter === 'music') window.sanskritiMusic.on(); else window.sanskritiMusic.off();
        }
        curtain.classList.add('leaving');
        document.body.classList.remove('curtain-open');
        setTimeout(function () { curtain.hidden = true; }, 900);
      });
    });
    var first = curtain.querySelector('[data-enter]'); if (first) first.focus();
  }

  // Header turns solid after scrolling.
  var head = document.querySelector('[data-head]');
  function onScroll() { if (head) head.classList.toggle('scrolled', window.scrollY > 40 || !document.querySelector('.s-hero')); }
  window.addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // Mobile menu.
  var burger = document.querySelector('[data-burger]'), nav = document.getElementById('s-nav');
  if (burger && nav) {
    burger.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    nav.querySelectorAll('a').forEach(function (a) { a.addEventListener('click', function () { nav.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); }); });
  }

  // Reveal on scroll.
  var items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    items.forEach(function (el) { io.observe(el); });
  } else items.forEach(function (el) { el.classList.add('in'); });

  // Videos play only while on screen (saves data and battery).
  var vids = document.querySelectorAll('video[data-inview]');
  if ('IntersectionObserver' in window) {
    var vo = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        var v = e.target;
        if (e.isIntersecting) { if (v.preload === 'none') v.preload = 'auto'; v.play().catch(function () {}); } else v.pause();
      });
    }, { threshold: 0.25 });
    vids.forEach(function (v) { vo.observe(v); });
  }

  // Gentle parallax.
  var par = document.querySelectorAll('[data-parallax]');
  if (par.length && !reduce) {
    var ticking = false;
    function para() {
      par.forEach(function (el) {
        var r = el.getBoundingClientRect();
        var off = (r.top + r.height / 2 - window.innerHeight / 2) * parseFloat(el.dataset.parallax);
        el.style.transform = 'translate3d(0,' + off.toFixed(1) + 'px,0)';
      });
      ticking = false;
    }
    window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(para); } }, { passive: true });
    para();
  }

  // Hero arch tilts slightly with the mouse.
  var tilt = document.querySelector('[data-tilt]');
  if (tilt && !reduce && window.matchMedia('(pointer: fine)').matches) {
    document.querySelector('.s-hero').addEventListener('mousemove', function (e) {
      var x = e.clientX / window.innerWidth - .5, y = e.clientY / window.innerHeight - .5;
      tilt.style.rotate = '';
      tilt.style.transform = 'perspective(900px) rotateY(' + (x * 8).toFixed(2) + 'deg) rotateX(' + (-y * 8).toFixed(2) + 'deg)';
    });
  }

  // Rail arrows.
  document.querySelectorAll('[data-rail-prev],[data-rail-next]').forEach(function (b) {
    b.addEventListener('click', function () {
      var rail = document.getElementById(b.dataset.railPrev || b.dataset.railNext);
      if (!rail) return;
      var step = rail.clientWidth * 0.8 * (b.dataset.railPrev ? -1 : 1);
      rail.scrollBy({ left: step, behavior: reduce ? 'auto' : 'smooth' });
    });
  });

  // Lightbox for moments.
  var dlg = document.querySelector('[data-lightbox-dialog]');
  if (dlg && dlg.showModal) {
    var box = dlg.querySelector('.lb-media'), cap = dlg.querySelector('.lb-cap');
    document.querySelectorAll('[data-lightbox]').forEach(function (b) {
      b.addEventListener('click', function () {
        box.innerHTML = '';
        var el = document.createElement(b.dataset.kind === 'video' ? 'video' : 'img');
        el.src = b.dataset.lightbox;
        if (b.dataset.kind === 'video') { el.controls = true; el.autoplay = true; el.playsInline = true; } else el.alt = b.dataset.caption || '';
        box.appendChild(el);
        cap.textContent = b.dataset.caption || '';
        dlg.showModal();
      });
    });
    function close() { var v = box.querySelector('video'); if (v) v.pause(); dlg.close(); }
    dlg.querySelector('[data-lb-close]').addEventListener('click', close);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) close(); });
  }
})();
