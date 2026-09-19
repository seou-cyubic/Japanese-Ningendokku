/* ==========================================================================
   contact-info.js — 문의처를 설정값으로 채운다
   --------------------------------------------------------------------------
   전화 · 메일 · 접수 시간은 서버 설정(`CONTACT_*`) 한 곳에만 둔다.
   HTML 에 적힌 값은 API 를 못 읽었을 때 보이는 기본값일 뿐이다.

     <span data-contact="tel">03-1234-5678</span>
     <a data-contact-href="tel">…</a>         → href="tel:0312345678"
   ========================================================================== */

(function () {
  'use strict';

  var targets = document.querySelectorAll('[data-contact], [data-contact-href]');
  if (!targets.length || !window.fetch) return;

  fetch('/api/v1/contact')
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (body) {
      var data = body && body.success && body.data;
      if (!data) return;

      Array.prototype.forEach.call(document.querySelectorAll('[data-contact]'), function (node) {
        var value = data[node.getAttribute('data-contact')];
        if (value) node.textContent = value;
      });

      Array.prototype.forEach.call(document.querySelectorAll('[data-contact-href]'), function (node) {
        var key = node.getAttribute('data-contact-href');
        var value = data[key];
        if (!value) return;
        node.setAttribute('href', key === 'tel'
          ? 'tel:' + String(value).replace(/[^0-9+]/g, '')
          : 'mailto:' + value);
      });
    })
    .catch(function () { /* 기본값을 그대로 보여 준다 */ });
})();
