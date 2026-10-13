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
})();
