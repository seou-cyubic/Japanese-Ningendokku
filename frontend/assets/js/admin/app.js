/* ==========================================================================
   app.js — 관리 화면 부팅 · 메뉴 구성
   --------------------------------------------------------------------------
   ① 로그인 상태를 확인한다 (아니면 로그인 화면으로)
   ② 권한(L1/L2/L3)에 맞는 메뉴만 그린다
   ③ 해시 라우팅을 시작한다

   ⚠️ 메뉴를 감추는 것은 **실수 방지**이지 보안이 아니다.
      실제 차단은 서버가 한다 (core/deps.py). 화면과 API 양쪽에서 막는다.
      (plan.md 자체 피드백 M-9)
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  // 메뉴 정의 — level 은 이 화면을 쓸 수 있는 최소 권한
  var MENU = [
    {
      group: '予約業務',
      items: [
        { route: 'dashboard', label: 'ダッシュボード', icon: 'dashboard', level: 1 },
        {
          route: 'reservations', label: '予約検索', icon: 'list', level: 1,
          match: 'reservation'
        },
        { route: 'postal', label: '郵送受付入力', icon: 'postal', level: 1 },
        { route: 'postal-bulk', label: '郵送受付一括入力', icon: 'postal', level: 1 }
      ]
    },
    {
      group: 'マスター管理',
      items: [
        // 회장 정보와 정원을 나눠 둔다. 「회장 A 의 8/28·8/29 정원을 본다」에
        // 주소·좌표 열이 딸려 오지 않게 하기 위함이고, 같은 회장의 주소가
        // 한 번만 적히게 두기 위함이다. (bulk-venues.js 도입부 참조)
        //
        // 예전에는 「회장 관리」(조회 전용)와 「회장 정보 일괄」(편집)이
        // 따로 있었다. 같은 데이터를 보는 화면이 둘이라 담당자가 매번
        // 「어느 쪽에서 고치는 거였지」를 되짚어야 했다. 검색과 삭제를
        // 일괄 표로 옮기고 조회 전용 화면은 없앴다.
        { route: 'bulk-venues', label: '会場管理', icon: 'hospital', level: 2 },
        { route: 'bulk-capacity', label: '定員管理', icon: 'calendar', level: 2 },
        // 정원 달력은 L2 다. 예전에는 L1 로 두었는데, 이 화면이 쓰는
        // `/hospitals` 계열 API 가 통째로 L2 전용이라 (api/admin/hospitals.py)
        // L1 이 열면 403 만 보였다. 「마스터 관리」 구획에서 L1 에게 보이는
        // 항목이 이것뿐이라, 구획 제목과 함께 못 쓰는 줄 하나가 남아 있었다.
        { route: 'capacity', label: '定員カレンダー', icon: 'calendar', level: 2 },
        { route: 'bulk-exam-options', label: 'オプション検査管理', icon: 'option', level: 2 }
      ]
    },
    {
      group: 'システム',
      items: [
        { route: 'system-data', label: 'システムデータ', icon: 'database', level: 1 },
        { route: 'mail-templates', label: 'メール文面', icon: 'mail', level: 3 },
        { route: 'accounts', label: 'アカウント管理', icon: 'account', level: 3 },
        { route: 'audit-logs', label: '操作ログ', icon: 'log', level: 3 }
      ]
    }
  ];

  /* ======================================================================
     메뉴 그리기
     ====================================================================== */

  function buildMenu(me) {
    var root = A.clear(document.getElementById('nav-menu'));

    // 권한으로 감추는 항목까지 이름을 넘긴다. 주소를 직접 쳐서 들어온 화면이
    // 「권한 없음」으로 끝나도 제목은 그 화면의 이름이어야 한다. (core.js dispatch)
    MENU.forEach(function (section) {
      section.items.forEach(function (item) { A.routeLabels[item.route] = item.label; });
    });

    MENU.forEach(function (section) {
      var items = section.items.filter(function (item) {
        return me.level >= item.level;
      });

      // 쓸 수 있는 항목이 하나도 없는 구획은 제목까지 감춘다.
      // 「마스터 관리」만 덩그러니 남으면 고장으로 보인다.
      if (!items.length) return;

      root.appendChild(el('p.nav__group', { text: section.group }));

      var list = el('ul.nav__list');
      items.forEach(function (item) {
        list.appendChild(el('li', {}, el('a.nav__link', {
          href: '#/' + item.route,
          dataset: { route: item.route, match: item.match || '' }
        }, [
          A.icon(item.icon),
          el('span.nav__label', { text: item.label }),
          item.route === 'reservations'
            ? el('span.nav__badge.is-hidden', { id: 'nav-attention', text: '0' })
            : null,
          item.route === 'system-data'
            ? el('span.nav__badge.nav__badge--warn.is-hidden', {
              id: 'nav-postal', text: '!'
            })
            : null
        ])));
      });

      root.appendChild(list);
    });

    document.getElementById('nav-me').textContent = me.name;
    document.getElementById('nav-role').textContent =
      me.role_label + ' · ' + me.login_id;
  }

  var attentionTimer = null;

  function updateBadgeUI(badge, count) {
    var prev = badge.getAttribute('data-count');
    var strCount = String(count);
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : strCount;
      badge.classList.remove('is-hidden');
      badge.title = '対応が必要な予約 ' + count + '件';
      if (prev && prev !== strCount) {
        badge.classList.add('nav__badge--pulse');
        setTimeout(function () { badge.classList.remove('nav__badge--pulse'); }, 600);
      }
      badge.setAttribute('data-count', strCount);
    } else {
      badge.classList.add('is-hidden');
      badge.removeAttribute('data-count');
    }
  }

  /**
   * 「대응이 필요한 예약」 건수를 메뉴에 배지로 띄운다.
   * 실시간으로 즉시 반영되며, 10초 주기 폴링 및 화면 전환/포커스 시 자동 갱신된다.
   */
  function refreshAttentionBadge() {
    var badge = document.getElementById('nav-attention');
    if (!badge) return;

    A.api.get('/dashboard/attention-count').then(function (res) {
      var count = (res && res.data && typeof res.data.count === 'number') ? res.data.count : 0;
      updateBadgeUI(badge, count);
    }).catch(function () {
      // 폴백: /dashboard 전체 조회
      A.api.get('/dashboard').then(function (body) {
        var counter = (body.data.counters || []).filter(function (c) {
          return c.key === 'attention';
        })[0];
        updateBadgeUI(badge, counter ? counter.value : 0);
      }).catch(function () {});
    });
  }

  function startAttentionPolling() {
    if (attentionTimer) clearInterval(attentionTimer);
    attentionTimer = setInterval(function () {
      if (document.visibilityState === 'visible') {
        refreshAttentionBadge();
      }
    }, 10000);
  }

  A.refreshAttentionBadge = refreshAttentionBadge;

  /**
   * 우편번호 데이터가 비어 있으면 알린다.
   *
   * 「주소 찾기가 안 된다」는 이용자 화면에서만 드러나고, 관리 화면에서는
   * 아무 증상도 없다. 담당자가 서버 로그를 볼 수 없으므로, 문의가 들어오기
   * 전까지 아무도 모른다. 메뉴에 표를 하나 세워 두고, 처음 들어온 순간에는
   * 토스트로도 한 번 말한다.
   */
  function refreshPostalBadge() {
    var badge = document.getElementById('nav-postal');
    if (!badge) return;

    A.api.get('/system/postal-status').then(function (body) {
      var data = body.data || {};
      var broken = data.state === 'MISSING' || data.state === 'FAILED' ||
        data.state === 'DISABLED';

      badge.classList.toggle('is-hidden', !broken);
      if (!broken) return;

      badge.title = '郵便番号データがないため「住所検索」が動作しません。';

      // 세션마다 한 번만. 화면을 옮길 때마다 뜨면 그냥 닫는 습관이 붙는다.
      try {
        if (sessionStorage.getItem('kenshin.admin.postalWarned') === '1') return;
        sessionStorage.setItem('kenshin.admin.postalWarned', '1');
      } catch (e) { /* 무시 */ }

      A.toast('郵便番号データがないため、利用者画面の「住所検索」が' +
        '動作しません。「システムデータ」をご確認ください。', 'warn');
    }).catch(function () { /* 배지는 부가 정보다. 실패해도 조용히 넘긴다 */ });
  }

  A.refreshPostalBadge = refreshPostalBadge;

  /* ======================================================================
     메뉴 접기
     --------------------------------------------------------------------
     좁은 노트북(1366px)에서 예약 목록 표가 가로로 넘친다. 표를 보는 동안에는
     메뉴가 필요 없으므로 접어서 그 폭을 표에 넘긴다.

     접은 상태를 기억하는 이유 : 화면을 옮길 때마다 다시 접게 하면
     접는 기능 자체가 번거로움이 된다.
     ====================================================================== */

  var NAV_KEY = 'kenshin.admin.navCollapsed';

  function setNavCollapsed(on) {
    document.body.classList.toggle('is-nav-collapsed', on);
    var shell = document.getElementById('shell');
    if (shell) shell.classList.toggle('is-collapsed', on);

    var toggleBtn = document.getElementById('sidebar-toggle');
    if (toggleBtn) {
      toggleBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      toggleBtn.title = (on ? 'メニューを開く' : 'メニューを閉じる') + '（ショートカット: [）';
    }

    try {
      localStorage.setItem(NAV_KEY, on ? '1' : '0');
      localStorage.setItem('kenshin_sidebar_collapsed', on ? 'true' : 'false');
    } catch (e) { /* 무시 */ }
  }

  function initNavCollapse() {
    var saved = '0';
    try {
      var s1 = localStorage.getItem(NAV_KEY);
      var s2 = localStorage.getItem('kenshin_sidebar_collapsed');
      saved = (s1 === '1' || s2 === 'true') ? '1' : '0';
    } catch (e) { /* 무시 */ }
    setNavCollapsed(saved === '1');

    var toggleBtn = document.getElementById('sidebar-toggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', function () {
        setNavCollapsed(!document.body.classList.contains('is-nav-collapsed'));
      });
    }
  }

  /* ======================================================================
     키보드 단축키
     --------------------------------------------------------------------
     하루 8시간 쓰는 화면이다. 자주 하는 일 두 가지만 손에 붙여 준다.
       /  → 검색 칸으로 (목록 화면에서)
       [  → 메뉴 접기 / 펴기
     입력 중에는 가로채지 않는다.
     ====================================================================== */

  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    var tag = (e.target.tagName || '').toLowerCase();
    var typing = tag === 'input' || tag === 'textarea' || tag === 'select' ||
      e.target.isContentEditable;

    if (e.key === '/' && !typing) {
      var box = document.querySelector('[data-shortcut="search"]');
      if (!box) return;

      e.preventDefault();

      // 검색 칸이 접힌 카드 안에 있으면 먼저 펴야 한다.
      // 감춰진 요소에는 포커스가 가지 않아, 아무 일도 일어나지 않은 것처럼 보인다.
      var folded = box.closest('.card.is-folded');
      if (folded) {
        var fold = folded.querySelector('.card__fold');
        if (fold) fold.click();
      }

      box.focus();
      box.select();
      return;
    }

    if (e.key === '[' && !typing) {
      e.preventDefault();
      setNavCollapsed(!document.body.classList.contains('is-nav-collapsed'));
    }
  });

  /* ======================================================================
     로그아웃
     ====================================================================== */

  document.getElementById('logout-btn').addEventListener('click', function () {
    A.confirm({
      title: 'ログアウトしますか？',
      message: '入力中の内容がある場合、保存されません。',
      okLabel: 'ログアウト',
      tone: 'primary'
    }).then(function (ok) {
      if (!ok) return;
      A.api.post('/logout')
        .then(function () { location.replace('login.html'); })
        .catch(function () { location.replace('login.html'); });
    });
  });

  /* ======================================================================
     시작
     ====================================================================== */

  A.api.get('/me')
    .then(function (body) {
      A.me = body.data;

      buildMenu(A.me);
      initNavCollapse();

      document.getElementById('shell').hidden = false;

      window.addEventListener('hashchange', function () {
        A.render();
        refreshAttentionBadge();
      });

      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
          refreshAttentionBadge();
        }
      });

      window.addEventListener('focus', function () {
        refreshAttentionBadge();
      });

      if (!location.hash) location.replace('#/dashboard');
      A.render();

      refreshAttentionBadge();
      refreshPostalBadge();
      startAttentionPolling();
    })
    .catch(function (error) {
      // 401 은 core.js 가 이미 로그인 화면으로 보냈다.
      if (error && error.status === 401) return;

      document.getElementById('shell').hidden = false;
      A.clear(document.getElementById('view')).appendChild(
        el('div.empty', {}, [
          el('p.empty__title', { text: 'サーバーに接続できませんでした' }),
          el('p', { text: 'バックエンドが起動しているか確認し、再読み込みしてください。' })
        ])
      );
    });

})();
