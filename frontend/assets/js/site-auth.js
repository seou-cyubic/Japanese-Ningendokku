/* ==========================================================================
   site-auth.js — 입장 로그인이 풀렸을 때 로그인 화면으로
   --------------------------------------------------------------------------
   이용자 화면은 로그인해야 들어올 수 있다(서버의 site_auth_gate 가 막는다).
   화면을 연 채 세션 시간이 지나면, 그 뒤의 API 호출은 401 과 함께
   `X-Site-Auth: required` 표시를 받는다. 화면마다 이것을 처리하게 하면
   빠뜨리는 곳이 생기므로, fetch 를 한 번 감싸 여기서 한꺼번에 처리한다.

   표시가 붙은 401 만 본다. 다른 이유의 401 은 각 화면의 처리 그대로다.
   다른 화면 스크립트보다 **먼저** 불러야 한다.
   ========================================================================== */

(function () {
  'use strict';

  if (!window.fetch) return;

  var originalFetch = window.fetch;
  var leaving = false;

  window.fetch = function () {
    return originalFetch.apply(this, arguments).then(function (res) {
      if (res.status === 401 && res.headers.get('X-Site-Auth') === 'required' && !leaving) {
        leaving = true;
        location.href = '/login.html?next=' +
          encodeURIComponent(location.pathname + location.search);
      }
      return res;
    });
  };
})();
