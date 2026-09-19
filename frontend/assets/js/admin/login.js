/* ==========================================================================
   login.js — 관리 화면 로그인 (A-00)
   --------------------------------------------------------------------------
   세션은 서버가 HttpOnly 쿠키로 내려준다. JavaScript 는 토큰을 만지지 않는다.
   여기서 하는 일은 로그인 요청과 실패 안내뿐이다.
   ========================================================================== */

(function () {
  'use strict';

  var API = '/api/v1/admin';

  var form     = document.getElementById('login-form');
  var button   = document.getElementById('login-btn');
  var elError  = document.getElementById('login-error');
  var elErrTxt = document.getElementById('login-error-text');

  function showError(message) {
    elErrTxt.textContent = message;
    elError.classList.add('is-visible');
  }

  function clearError() {
    elError.classList.remove('is-visible');
    elErrTxt.textContent = '';
  }

  function setBusy(busy) {
    button.disabled = busy;
    button.textContent = busy ? '確認中…' : 'ログイン';
  }

  /** 로그인 후 원래 가려던 화면으로 돌려보낸다. */
  function nextUrl() {
    var params = new URLSearchParams(location.search);
    var next = params.get('next');
    // 외부 주소로 튕겨 보내지지 않도록 같은 사이트의 경로만 허용한다
    if (next && next.charAt(0) === '/' && next.charAt(1) !== '/') return next;
    return './';
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    clearError();

    var loginId = document.getElementById('login-id').value.trim();
    var password = document.getElementById('password').value;

    if (!loginId || !password) {
      showError('ログインIDとパスワードの両方を入力してください。');
      return;
    }

    setBusy(true);

    fetch(API + '/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_id: loginId, password: password })
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (res) {
        if (res.status === 200 && res.body.success) {
          location.href = nextUrl();
          return;
        }

        setBusy(false);

        if (res.status === 422) {
          var fields = res.body.fields || [];
          showError(fields.length ? fields[0].message : '入力内容をご確認ください。');
          return;
        }

        showError((res.body.error && res.body.error.message) ||
                  'ログインできませんでした。');
        document.getElementById('password').value = '';
        document.getElementById('password').focus();
      })
      .catch(function () {
        setBusy(false);
        showError('サーバーに接続できませんでした。ネットワークの状態をご確認ください。');
      });
  });

  // 이미 로그인되어 있으면 바로 들여보낸다.
  // 로그인 화면을 다시 보여 주면 「로그아웃된 건가」 하고 헷갈린다.
  fetch(API + '/me')
    .then(function (res) { if (res.ok) location.replace(nextUrl()); })
    .catch(function () { /* 연결 실패는 로그인 시도에서 다시 알린다 */ });

  document.getElementById('login-id').focus();

})();
