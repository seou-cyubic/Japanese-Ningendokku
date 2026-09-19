/* ==========================================================================
   core.js — 관리 화면 공통 토대
   --------------------------------------------------------------------------
   프레임워크를 쓰지 않으므로(Vanilla JS), 화면마다 반복되는 것을
   여기에 모은다. 각 화면(views/*.js)은 이 위에서 자기 일만 한다.

     Admin.api      서버 호출 + 오류 처리 (401 → 로그인 화면)
     Admin.el       DOM 생성 (innerHTML 문자열 조립을 줄인다)
     Admin.fmt      날짜·숫자·상태 표기
     Admin.toast    조작 결과 알림
     Admin.modal    확인·입력 대화상자
     Admin.table    표 · 페이지네이션
     Admin.router   해시 라우팅 (#/reservations?status=PENDING)

   ⚠️ 화면에 들어가는 문자열은 전부 `textContent` 로 넣는다.
      이름·메모·검색어에는 이용자가 입력한 값이 들어오므로,
      innerHTML 로 꽂으면 그대로 스크립트가 된다.
   ========================================================================== */

var Admin = (function () {
  'use strict';

  var API = '/api/v1/admin';

  /* ======================================================================
     1. DOM 생성
     ====================================================================== */

  /**
   * el('div.card', { id: 'x' }, [child, '텍스트'])
   * 태그 문자열에 .클래스 를 붙여 쓸 수 있다.
   */
  function el(spec, attrs, children) {
    var parts = String(spec).split('.');
    var node = document.createElement(parts[0] || 'div');

    for (var i = 1; i < parts.length; i++) node.classList.add(parts[i]);

    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;

        if (key === 'text') { node.textContent = value; return; }
        if (key === 'html') { node.innerHTML = value; return; }   // 고정 문자열 전용
        if (key === 'onClick') { node.addEventListener('click', value); return; }
        if (key === 'onInput') { node.addEventListener('input', value); return; }
        if (key === 'onChange') { node.addEventListener('change', value); return; }
        if (key === 'onSubmit') { node.addEventListener('submit', value); return; }
        if (key === 'style') { node.setAttribute('style', value); return; }
        if (key === 'dataset') {
          Object.keys(value).forEach(function (k) { node.dataset[k] = value[k]; });
          return;
        }
        if (key in node && typeof node[key] !== 'object' && key !== 'list') {
          node[key] = value;
          return;
        }
        node.setAttribute(key, value);
      });
    }

    append(node, children);
    return node;
  }

  function append(node, children) {
    if (children === null || children === undefined || children === false) return node;

    if (Array.isArray(children)) {
      children.forEach(function (child) { append(node, child); });
      return node;
    }

    if (children instanceof Node) { node.appendChild(children); return node; }

    node.appendChild(document.createTextNode(String(children)));
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  /* ----------------------------------------------------------------------
     안쪽 스크롤이 끝에 닿으면 페이지를 이어서 굴린다
     ----------------------------------------------------------------------
     엑셀식 표는 화면 높이를 거의 다 쓴다. 그래서 커서는 대개 표 안에
     있는데, 표를 맨 아래(또는 맨 위)까지 굴린 뒤 더 굴려도 **아무 일도
     일어나지 않았다.** 화면 아래의 저장 결과나 경고를 보려면 커서를 표
     밖으로 빼서 다시 굴려야 했고, 그것을 아는 사람만 그렇게 했다.

     CSS 의 `overscroll-behavior` 만으로는 되지 않는다. 브라우저는 휠
     제스처를 **처음 닿은 스크롤러에 붙잡아 두기**(scroll latching) 때문에,
     그 스크롤러가 끝에 닿아 있어도 바깥으로 넘겨주지 않는다. 그래서
     끝에 닿았을 때만 우리가 대신 페이지를 굴린다.

     끝에 닿았을 때만 `preventDefault` 한다 — 표 안을 굴리는 보통의 경우는
     브라우저에게 그대로 맡긴다.

     가로(deltaY 가 0인 휠·Shift+휠)는 건드리지 않는다. 옆으로 흘려보내면
     트랙패드의 뒤로 가기 제스처가 걸리는데, 이 표들은 저장하지 않은
     수정을 담고 있다.
     ---------------------------------------------------------------------- */

  /** 휠 한 칸이 실제로 몇 px 인가. 브라우저마다 단위가 다르다. */
  function wheelPixels(event, node) {
    if (event.deltaMode === 1) return event.deltaY * 16;              // 줄
    if (event.deltaMode === 2) return event.deltaY * node.clientHeight; // 쪽
    return event.deltaY;                                              // px
  }

  function chainScroll(node) {
    node.addEventListener('wheel', function (event) {
      if (event.ctrlKey) return;          // 확대·축소
      var delta = wheelPixels(event, node);
      if (!delta) return;                 // 가로 휠

      var top = node.scrollTop <= 0;
      var bottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
      if (!((delta < 0 && top) || (delta > 0 && bottom))) return;

      event.preventDefault();
      window.scrollBy(0, delta);
    }, { passive: false });
    return node;
  }

  /** 인라인 SVG 아이콘. 외부 요청을 만들지 않기 위해 직접 그린다. */
  var ICONS = {
    dashboard: 'M4 13h7V4H4v9zm0 7h7v-5H4v5zm9 0h7v-9h-7v9zm0-16v5h7V4h-7z',
    list:      'M4 6h16M4 12h16M4 18h10',
    postal:    'M3 6.5h18v11H3zM3 7l9 6 9-6',
    hospital:  'M4 21V9l8-5 8 5v12M9 21v-6h6v6M12 7v4M10 9h4',
    calendar:  'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
    option:    'M5 6.5h14M5 12h14M5 17.5h9',
    mail:      'M3 6.5h18v11H3zM3 7l9 6 9-6',
    account:   'M12 12a4 4 0 100-8 4 4 0 000 8zM4 20a8 8 0 0116 0',
    log:       'M6 4h9l3 3v13H6zM9 12h7M9 16h5M9 8h4',
    database:  'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
    phone:     'M4.5 5.5c0-1 .8-1.8 1.8-1.8h2c.8 0 1.5.5 1.7 1.3l.8 2.6c.2.7 0 1.4-.6 1.8l-1.3 1a12.5 12.5 0 005 5l1-1.3c.4-.6 1.1-.8 1.8-.6l2.6.8c.8.2 1.3.9 1.3 1.7v2c0 1-.8 1.8-1.8 1.8A15.5 15.5 0 014.5 5.5z',
    copy:      'M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H8a2 2 0 01-2-2v-2M8 4h4a2 2 0 012 2v4H8V4zM4 8h4a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V10a2 2 0 012-2z'
  };

  function icon(name, options) {
    options = options || {};
    var size = options.size || 24;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.9');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    if (options.className) svg.setAttribute('class', options.className);
    if (options.style) svg.setAttribute('style', options.style);

    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', ICONS[name] || ICONS.list);
    svg.appendChild(path);
    return svg;
  }

  /* ======================================================================
     2. 서버 호출
     ====================================================================== */

  function request(method, path, payload) {
    var options = {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin'
    };
    if (payload !== undefined) options.body = JSON.stringify(payload);

    return fetch(API + path, options).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (res.ok) return body;
        throw failure(res, body);
      });
    });
  }

  /** 실패 응답을 오류 객체로. request · upload · download 가 함께 쓴다. */
  function failure(res, body) {
    body = body || {};

    // 세션이 끊기면 화면을 그리는 대신 로그인으로 보낸다.
    // 「목록이 안 뜬다」로 보이게 두면 원인을 알 수 없다.
    if (res.status === 401) {
      toLogin();
      return new ApiError('ログインが必要です。', res.status, body);
    }

    var message =
      (body.error && body.error.message) ||
      (body.fields && body.fields.length && body.fields[0].message) ||
      'リクエストを処理できませんでした。(' + res.status + ')';

    // 입력 검증 실패(422)는 제목 문장이 「入力内容をご確認ください。」뿐이다.
    // 어느 칸이 왜 틀렸는지(`fields`)를 붙이지 않으면, 폼 화면에서 담당자는
    // 무엇을 고쳐야 할지 알 수 없다.
    if (res.status === 422 && body.fields && body.fields.length && body.error) {
      var details = body.fields
        .map(function (f) { return f && f.message; })
        .filter(Boolean);
      if (details.length) message += ' ' + details.join(' ');
    }

    return new ApiError(message, res.status, body);
  }

  /**
   * 파일 업로드.
   * Content-Type 을 직접 지정하지 않는다 — FormData 의 경계 문자열은
   * 브라우저가 붙여야 하며, 손으로 적으면 서버가 본문을 못 읽는다.
   */
  function upload(path, file, fieldName) {
    var form = new FormData();
    form.append(fieldName || 'file', file, file.name);

    return fetch(API + path, {
      method: 'POST',
      body: form,
      credentials: 'same-origin'
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (res.ok) return body;
        throw failure(res, body);
      });
    });
  }

  /**
   * 파일 내려받기.
   *
   * 보낼 것이 표 한 장이라 GET 이 아니라 POST 이고, 그래서 `<a href>` 로는
   * 안 된다. 성공하면 blob 을, 실패하면 JSON 오류를 받으므로 본문을 읽는
   * 방식이 갈린다. 성공 응답을 json 으로 읽으려 하면 파일이 깨진다.
   */
  function download(path, payload) {
    return fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload || {})
    }).then(function (res) {
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          throw failure(res, body);
        });
      }
      return res.blob().then(function (blob) {
        var name = fileNameOf(res.headers.get('Content-Disposition'));
        saveBlob(blob, name);
        return name;
      });
    });
  }

  /**
   * Content-Disposition 에서 파일 이름을 꺼낸다.
   * 헤더는 ASCII 만 담을 수 있어 한글 이름은 `filename*=UTF-8''…` 로 온다.
   */
  function fileNameOf(disposition) {
    var text = disposition || '';
    var encoded = text.match(/filename\*=UTF-8''([^;]+)/i);
    if (encoded) {
      try { return decodeURIComponent(encoded[1]); } catch (e) { /* 아래로 */ }
    }
    var plain = text.match(/filename="?([^";]+)"?/i);
    return plain ? plain[1] : 'download';
  }

  function saveBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var link = el('a', { href: url, download: name, style: 'display:none' });
    document.body.appendChild(link);
    link.click();
    link.remove();
    // すぐに消すとブラウザが保存を開始する前にアドレスが消える場合がある。
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function ApiError(message, status, body) {
    this.name = 'ApiError';
    this.message = message;
    this.status = status;
    this.body = body || {};
  }
  ApiError.prototype = Object.create(Error.prototype);

  function toLogin() {
    var next = location.pathname + location.hash;
    location.replace('login.html?next=' + encodeURIComponent(next));
  }

  var api = {
    get: function (path) { return request('GET', path); },
    post: function (path, payload) { return request('POST', path, payload || {}); },
    put: function (path, payload) { return request('PUT', path, payload || {}); },
    del: function (path) { return request('DELETE', path); },
    upload: upload,
    download: download,
    ApiError: ApiError
  };

  /** オブジェクトをクエリ文字列に。空の値は除外してアドレスを短く保つ。 */
  function query(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === '' || value === false) return;
      parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  /* ======================================================================
     3. 表記
     ====================================================================== */

  var WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];

  var fmt = {
    /** '2026-08-10' → '2026-08-10（月）' */
    date: function (iso) {
      if (!iso) return '—';
      var p = String(iso).slice(0, 10).split('-').map(Number);
      var wd = WEEKDAY[new Date(p[0], p[1] - 1, p[2]).getDay()];
      return p[0] + '-' + pad(p[1]) + '-' + pad(p[2]) + '（' + wd + '）';
    },

    /** '2026-08-10' → '8/10（月）' — テーブルの幅を節約する */
    dateShort: function (iso) {
      if (!iso) return '—';
      var p = String(iso).slice(0, 10).split('-').map(Number);
      var wd = WEEKDAY[new Date(p[0], p[1] - 1, p[2]).getDay()];
      return p[1] + '/' + p[2] + '（' + wd + '）';
    },

    /** ISO 日時 → '2026-08-06 14:32' */
    datetime: function (iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      if (isNaN(d)) return String(iso);
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
             ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },

    number: function (n) {
      return (n === null || n === undefined) ? '—' : Number(n).toLocaleString('ja-JP');
    },

    /** 値がない場合は「—」で埋める。空欄のままだと欠落と区別がつかない */
    or: function (value, fallback) {
      return (value === null || value === undefined || value === '')
        ? (fallback || '—') : value;
    },

    /** 「きょう」を **日本標準時(JST)** で返す。'2026-09-09' の形。

        担当者の PC の時刻設定に関わらず、この予約システムの「きょう」は
        つねに日本の日付である。以前は `toISOString()`（世界標準時）を
        使っていた箇所があり、日本の午前0時〜9時のあいだは前日が返って
        いた。健診の受付は朝に始まるため、まさにその時間帯に
        「今日」ボタンが昨日の日付を入れ、統計が前日の集計を出していた。 */
    today: function () {
      return fmt.dateInJst(new Date());
    },

    /** Date を JST の 'YYYY-MM-DD' にする。 */
    dateInJst: function (d) {
      var parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Tokyo',
        year: 'numeric', month: '2-digit', day: '2-digit'
      }).formatToParts(d || new Date());
      var got = {};
      for (var i = 0; i < parts.length; i++) got[parts[i].type] = parts[i].value;
      return got.year + '-' + got.month + '-' + got.day;
    },

    /** 'YYYY-MM-DD' を days 日ずらす。時差をはさまない。

        new Date('2026-09-14') は世界標準時の深夜と解釈されるため、
        Date に載せて計算すると地域によって1日ずれる。ここでは日付を
        数値として足し引きするだけにして、時差が入る余地をなくす。 */
    shiftDate: function (iso, days) {
      var d = fmt.toUtcDate(iso);
      if (!d) return '';
      d.setUTCDate(d.getUTCDate() + days);
      return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
    },

    /** 'YYYY-MM-DD' の曜日。0 が日曜。 */
    weekdayOf: function (iso) {
      var d = fmt.toUtcDate(iso);
      return d ? d.getUTCDay() : null;
    },

    /** 日付計算のための内部ヘルパ。不正な文字列なら null。 */
    toUtcDate: function (iso) {
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
      if (!m) return null;
      var d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
      return isNaN(d.getTime()) ? null : d;
    },

    month: function (d) {
      return d.getFullYear() + '-' + pad(d.getMonth() + 1);
    },

    monthLabel: function (ym) {
      var p = String(ym).split('-');
      return p[0] + '年' + Number(p[1]) + '月';
    }
  };

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /** 予約ステータスバッジ */
  /* ステータスバッジ。 `isHoliday` を渡すと「休診日」を **追加する。**
     -------------------------------------------------------------------
     休診日は保存されたステータスではなく開催回の締切から導かれる事実のため、,
     確定・保留・キャンセルを上書きせずに並べて表示する。「確定だがその日は締め切られた」が
     実際の状況であり、担当者が電話で新しい日程に変更すれば自動的に消える。

     第3引数は省略可能のため、渡さない既存の呼び出し元はそのまま動作する。 */
  function statusBadge(status, label, isHoliday) {
    var displayLabel = label || status;
    if (status === 'CONFIRMED' && (!label || label === '確定')) displayLabel = '予約確定';
    if (status === 'PENDING' && (!label || label === '仮（要確認）')) displayLabel = '仮受付（要確認）';
    // 取り消しの種類はサーバーが cancel_type 列から付けて送ってくる。
    // ここで推し量って「事前」と決めつけない — 分からないものは「キャンセル」のままにする。

    var tone = { CONFIRMED: 'ok', PENDING: 'warn', CANCELLED: 'muted' }[status] || 'muted';
    if (displayLabel === '当日キャンセル' || (displayLabel && displayLabel.indexOf('当日') !== -1)) tone = 'danger';

    var main = el('span.badge.badge--' + tone, { text: displayLabel });
    // 이미 취소된 예약에는 휴진으로 인한 일정변경 상태를 붙이지 않는다.
    if (!isHoliday || status === 'CANCELLED') return main;

    return el('span', {
      style: 'display:inline-flex;align-items:center;justify-content:center;gap:4px;flex-wrap:wrap;'
    }, [
      main,
      el('span.badge.badge--danger', {
        text: '日程変更要（要連絡）',
        title: 'この受診日は休診のため締め切られました。予約はそのまま残っていますので、'
             + '電話で連絡し、新しい日程を調整してください。'
      })
    ]);
  }

  /* ======================================================================
     4. トースト
     ====================================================================== */

  var toastRoot = null;

  function toast(message, tone) {
    if (!toastRoot) toastRoot = document.getElementById('toasts');
    if (!toastRoot) return;

    var box = el('div.toast' + (tone ? '.toast--' + tone : ''), {}, [
      el('span', { text: message }),
      el('button.toast__close', {
        type: 'button',
        'aria-label': '閉じる',
        text: '×',
        onClick: function () { box.remove(); }
      })
    ]);

    toastRoot.appendChild(box);
    announce(message);

    // エラーは読む時間を長くとる
    window.setTimeout(function () { box.remove(); }, tone === 'danger' ? 9000 : 5000);
  }

  function announce(text) {
    var live = document.getElementById('live-status');
    if (live) live.textContent = text;
  }

  /* ======================================================================
     5. モーダル
     ====================================================================== */

  var openModals = [];

  /**
   * modal({ title, body, size, actions: [{label, tone, onClick, keepOpen}] })
   * onClick がPromiseを返すと、その間ボタンをロックする。
   */
  function modal(options) {
    var root = document.getElementById('modal-root');
    var previousFocus = document.activeElement;

    var backdrop = el('div.modal-backdrop', { role: 'presentation' });
    var box = el('div.modal' + (options.size ? '.modal--' + options.size : ''), {
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': options.title || ''
    });
    if (options.style) {
      box.style.cssText = (box.style.cssText ? box.style.cssText + ';' : '') + options.style;
    }

    var closed = false;

    function close() {
      // × とEscapeとアクションボタンがすべてここに来る。2回呼ばれても
      // `onClose` は1回だけ実行されなければならない。
      if (closed) return;
      closed = true;

      backdrop.remove();
      openModals = openModals.filter(function (m) { return m !== close; });
      document.removeEventListener('keydown', onKey);
      if (previousFocus && previousFocus.focus) previousFocus.focus();

      // 閉じられたことを呼び出し元が把握する必要がある。これがないと × やEscapeで
      // 閉じた際にダイアログのPromiseが解決されないままになる。
      if (options.onClose) options.onClose();
    }

    function onKey(ev) {
      if (ev.key === 'Escape' && openModals[openModals.length - 1] === close) {
        ev.stopPropagation();
        close();
      }
    }

    box.appendChild(el('div.modal__head', {}, [
      el('h2.modal__title', { text: options.title || '' }),
      el('button.modal__close', {
        type: 'button', 'aria-label': '閉じる', text: '×', onClick: close
      })
    ]));

    var body = el('div.modal__body');
    append(body, options.body);
    box.appendChild(body);

    if (options.actions && options.actions.length) {
      var foot = el('div.modal__foot');
      options.actions.forEach(function (action) {
        var button = el('button.btn' + (action.tone ? '.btn--' + action.tone : ''), {
          type: 'button',
          text: action.label,
          onClick: function () {
            if (!action.onClick) { close(); return; }

            var result = action.onClick(close);
            if (result && typeof result.then === 'function') {
              button.disabled = true;
              var original = button.textContent;
              button.textContent = '処理中…';
              result.then(function () {
                if (!action.keepOpen) close();
              }).catch(function () {
                // エラー案内は呼び出し元がトーストで表示する。モーダルは開いたままにする。
              }).then(function () {
                button.disabled = false;
                button.textContent = original;
              });
              return;
            }

            if (!action.keepOpen) close();
          }
        });
        foot.appendChild(button);
      });
      box.appendChild(foot);
    }

    // 背景をクリックして閉じない。長いフォームの入力中に誤って消してしまう事故が多いため。
    backdrop.appendChild(box);
    root.appendChild(backdrop);
    openModals.push(close);
    document.addEventListener('keydown', onKey);

    var focusable = box.querySelector(
      'input:not([type=hidden]), select, textarea, button.btn'
    );
    if (focusable) focusable.focus();

    return { close: close, box: box, body: body };
  }

  /** 元に戻せない操作の前に表示する確認ダイアログ。 */
  /* 1つの問いに1つの答え。
     ---------------------------------------------------------------------
     通常は「はい / いいえ」の2つでよく、 × とEscapeは「いいえ」である。

     しかし、 **「いいえ」と「キャンセル」が異なる問い**がある。「健診日を変更するが、
     案内メールも送信しますか」がそうだ — 「送信しない」は変更自体は行い、
     × は変更自体を取りやめることである。その場では
     `closeValue: null` を渡し、呼び出し側が `null` を個別に処理する。

     デフォルト値は `false` なので、このオプションを渡さない既存の呼び出し元はそのまま動作する。 */
  function confirm(options) {
    return new Promise(function (resolve) {
      // 閉じることも答えである。通知しないとPromiseが解決されず呼び出し側が
      // 待ち続けることになる（保存ボタンが「保存中…」のまま残る）。
      var onClose = options.hasOwnProperty('closeValue') ? options.closeValue : false;
      var decided = false;
      function decide(value) {
        if (decided) return;
        decided = true;
        resolve(value);
      }

      modal({
        title: options.title,
        size: options.size || 'slim',
        body: [
          el('p', { text: options.message, style: 'margin:0 0 8px;line-height:1.7;white-space:pre-wrap' }),
          options.detail ? el('p.field__hint', { text: options.detail }) : null
        ],
        onClose: function () { decide(onClose); },
        actions: [
          { label: options.cancelLabel || 'キャンセル', onClick: function () { decide(false); } },
          {
            label: options.okLabel || '確認',
            tone: options.tone || 'danger',
            onClick: function () { decide(true); }
          }
        ]
      });
    });
  }

  /* ======================================================================
     6. テーブル
     ====================================================================== */

  /**
   * table({ columns: [{key, label, align, render}], rows, onRowClick, empty })
   */
  function table(config) {
    var wrap = el('div.table-wrap');
    var node = el('table.table');

    var thead = el('thead');
    var tr = el('tr');
    config.columns.forEach(function (column) {
      var th = el('th', {
        style: column.width ? 'width:' + column.width : null,
        'class': column.align === 'right' ? 'num'
               : column.align === 'center' ? 'center' : null
      });
      if (column.label instanceof Node) {
        th.appendChild(column.label);
      } else {
        th.textContent = column.label || '';
      }
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    node.appendChild(thead);

    var tbody = el('tbody');

    if (!config.rows.length) {
      tbody.appendChild(el('tr', {}, el('td', {
        colSpan: config.columns.length
      }, el('div.empty', {}, [
        el('p.empty__title', { text: (config.empty && config.empty.title) || '表示する内容がありません' }),
        el('p', { text: (config.empty && config.empty.desc) || '' })
      ]))));
    } else {
      config.rows.forEach(function (row, index) {
        var line = el('tr', {
          'class': [
            config.onRowClick ? 'is-clickable' : '',
            config.rowClass ? config.rowClass(row) : ''
          ].filter(Boolean).join(' ') || null
        });

        config.columns.forEach(function (column) {
          var cell = el('td', {
            'class': [
              column.align === 'right' ? 'num' : '',
              column.align === 'center' ? 'center' : '',
              column.wrap ? 'wrap' : '',
              column.mono ? 'mono' : '',
              column.dim ? 'dim' : ''
            ].filter(Boolean).join(' ') || null
          });

          var value = column.render ? column.render(row, index) : row[column.key];
          if (Array.isArray(value)) {
            value.forEach(function (child) {
              if (child instanceof Node) cell.appendChild(child);
              else if (child !== null && child !== undefined && child !== '') {
                cell.appendChild(document.createTextNode(String(child)));
              }
            });
          } else if (value instanceof Node) {
            cell.appendChild(value);
          } else {
            cell.textContent = (value === null || value === undefined || value === '')
              ? '—' : String(value);
          }

          line.appendChild(cell);
        });

        if (config.onRowClick) {
          line.addEventListener('click', function (ev) {
            // 行内のボタンをクリックした際に重複して行遷移しないようにする
            if (ev.target.closest('button, a, input, select')) return;
            config.onRowClick(row);
          });
        }

        tbody.appendChild(line);
      });
    }

    node.appendChild(tbody);
    wrap.appendChild(node);
    return wrap;
  }

  /** ページネーション。totalが0の場合は何も描画しない。 */
  function pager(page, size, total, onMove) {
    if (!total) return null;

    var pages = Math.max(1, Math.ceil(total / size));
    var from = (page - 1) * size + 1;
    var to = Math.min(total, page * size);

    return el('div.pager', {}, [
      el('span', { text: '全 ' + fmt.number(total) + '件中 ' + from + '–' + to }),
      el('span.pager__spacer'),
      el('button.btn.btn--sm', {
        type: 'button', text: '前へ', disabled: page <= 1,
        onClick: function () { onMove(page - 1); }
      }),
      el('span', { text: page + ' / ' + pages }),
      el('button.btn.btn--sm', {
        type: 'button', text: '次へ', disabled: page >= pages,
        onClick: function () { onMove(page + 1); }
      })
    ]);
  }

  /* ======================================================================
     7. フォーム部品
     ====================================================================== */

  function field(label, control, options) {
    options = options || {};
    return el('div.field' + (options.span ? '.' + options.span : ''), {}, [
      el('label.field__label', { htmlFor: control.id || null }, [
        label,
        options.required ? el('span.req', { text: '*' }) : null
      ]),
      control,
      options.hint ? el('p.field__hint', { text: options.hint }) : null
    ]);
  }

  /* 日付欄はブラウザ既定のプレースホルダを使わない。
     `<input type="date">` の「年-月-日」は**ブラウザの言語**に従うため、
     担当者の PC が韓国語だと日本語画面の中でその欄だけ韓国語(연도-월-일)
     になる。画面の言語に関わらず同じ表示にするため text で置き、
     カレンダーは datepicker.js が日本語で描く。 */
  function input(attrs) {
    attrs = attrs || {};
    if (attrs.type === 'date') {
      // birth: true — 生年月日の欄。カレンダーが対象年齢の年から開き、
      // 「今日」を出さない（datepicker.js）。
      var birth = !!attrs.birth;
      attrs = Object.assign({}, attrs, {
        type: 'text',
        'data-date': '1',
        placeholder: attrs.placeholder || (birth ? '例: 1965-02-20' : '年-月-日'),
        inputmode: 'numeric',
        autocomplete: 'off'
      });
      delete attrs.birth;
      if (birth) attrs['data-date-kind'] = 'birth';
    }
    return el('input.input', Object.assign({ type: 'text' }, attrs));
  }

  function select(attrs, options) {
    var node = el('select.select', attrs || {});
    (options || []).forEach(function (option) {
      node.appendChild(el('option', {
        value: option.value,
        text: option.label,
        selected: option.selected || false
      }));
    });
    return node;
  }

  function textarea(attrs) {
    return el('textarea.textarea', attrs || {});
  }

  function checkbox(label, attrs) {
    var box = el('input', Object.assign({ type: 'checkbox' }, attrs || {}));
    return el('label.check', {}, [box, el('span', { text: label })]);
  }

  function notice(tone, text) {
    return el('div.notice.notice--' + tone, {}, [
      el('span', { text: text })
    ]);
  }

  function loading(message) {
    return el('div.loading', {}, [
      el('span.spin'),
      el('span', { text: message || '読み込み中…' })
    ]);
  }

  /**
   * カード。
   *   options.collapsible  折りたたみ可能にする
   *   options.collapseKey  折りたたみ状態を保持するキー名（指定がない場合は保持しない）
   *
   * なぜ折りたためる必要があるか：検索条件カードが縦320pxを占有し、,
   * 結果の先頭行を見るためにスクロールが必要だったため。条件を一度指定した後は、
   * 結果のみを閲覧するため、折りたたんでおくことでそのスペースをすべて結果表示に充てられる。
   */
  function card(title, options) {
    options = options || {};
    var node = el('div.card');
    var body = el('div.card__body' + (options.flush ? '.card__body--flush' : ''));

    if (title || options.tools || options.desc || options.collapsible) {
      var titleNode;
      if (title && (title instanceof Node)) {
        titleNode = title;
      } else {
        titleNode = el('h2.card__title', { text: title || '' });
      }

      var head = el('div.card__head', {}, [
        el('div', { style: 'flex:1;min-width:0;' }, [
          titleNode,
          options.desc ? el('p.card__desc', { text: options.desc }) : null
        ])
      ]);

      var tools = el('div.card__tools');
      if (options.tools) append(tools, options.tools);

      if (options.collapsible) {
        var key = options.collapseKey ? 'kenshin.admin.fold.' + options.collapseKey : '';
        var folded = false;
        if (key) {
          try { folded = localStorage.getItem(key) === '1'; } catch (e) { /* 無視 */ }
        }

        var toggle = el('button.card__fold', { type: 'button' });

        function paint() {
          node.classList.toggle('is-folded', folded);
          toggle.setAttribute('aria-expanded', folded ? 'false' : 'true');
          toggle.textContent = folded ? '条件を開く' : '条件を閉じる';
          if (key) {
            try { localStorage.setItem(key, folded ? '1' : '0'); } catch (e) { /* 無視 */ }
          }
        }

        toggle.addEventListener('click', function () { folded = !folded; paint(); });
        tools.appendChild(toggle);
        paint();
      }

      if (tools.childNodes.length) head.appendChild(tools);
      node.appendChild(head);
    }

    append(body, options.body);
    node.appendChild(body);
    return node;
  }

  /* ======================================================================
     7-B. 住所検索
     --------------------------------------------------------------------
     郵送受付画面でスタッフが紙の申込書を見て漢字の住所を手入力する
     作業が、この画面で最も時間がかかり最も誤りの起きやすい部分である。
     利用者画面と同じデータ(`postal_codes`)を同じAPIで検索して入力する。

         addressSearch(postalInput, addressInput)

     利用者画面とは異なり、 **手動での修正も許可する。** 紙の申込書に記載された
     住所がデータ上に存在しない場合があり、その際スタッフは本人に電話で確認できる
     状況にある。制限してしまうと受付自体ができなくなる。
     ====================================================================== */

  function addressSearch(postalInput, addressInput) {
    var box = el('input.input', {
      type: 'search',
      placeholder: '郵便番号または住所で検索（例: 101-0021・千代田区外神田）',
      autocomplete: 'off'
    });

    var results = el('div.addr-hits.is-hidden');
    var status = el('span.field__hint');

    function close() {
      results.textContent = '';
      results.classList.add('is-hidden');
    }

    function run() {
      var keyword = box.value.trim();
      if (!keyword) return;

      status.textContent = '検索中…';
      close();

      // 住所検索は管理者専用APIではない(`/api/v1/postal`).
      // `request()` は `/api/v1/admin` を先頭に付与するため、ここでは使用しない。
      fetch('/api/v1/postal/search?keyword=' + encodeURIComponent(keyword))
        .then(function (res) {
          return res.json().then(function (body) {
            if (!res.ok) {
              throw new Error((body.error && body.error.message) || '見つかりませんでした。');
            }
            return body;
          });
        })
        .then(function (body) {
          var items = body.data.items;
          if (!items.length) {
            status.textContent = '見つかりませんでした。市区町村名のみを入力してみてください。';
            return;
          }

          status.textContent = items.length + '件';
          items.forEach(function (item) {
            results.appendChild(el('button.addr-hit', {
              type: 'button',
              onClick: function () {
                postalInput.value = item.zipcode.slice(0, 3) + '-' + item.zipcode.slice(3);
                addressInput.value = item.address;
                // 値を変更するだけでは、詳細編集パネルのようにinputイベントで状態を
                // 同期する画面に変更が伝わらない。
                postalInput.dispatchEvent(new Event('input', { bubbles: true }));
                addressInput.dispatchEvent(new Event('input', { bubbles: true }));
                close();
                status.textContent = '住所を入力しました。続けて番地を入力してください。';
                box.value = '';
              }
            }, [
              el('span.addr-hit__zip', { text: '〒' + item.zipcode.slice(0, 3) + '-' + item.zipcode.slice(3) }),
              el('span', { text: item.address })
            ]));
          });
          results.classList.remove('is-hidden');
        })
        .catch(function (error) { status.textContent = error.message; });
    }

    box.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); run(); }
      if (e.key === 'Escape') close();
    });

    return el('div.addr-find', {}, [
      el('div.addr-find__row', {}, [
        box,
        el('button.btn.btn--sm', { type: 'button', text: '住所検索', onClick: run })
      ]),
      status,
      results
    ]);
  }

  /* ======================================================================
     8. ハッシュルーター
     --------------------------------------------------------------------
     #/reservations?status=PENDING&page=2
     URLで画面状態が表現されるため、ダッシュボードで「要対応の予約N件」を
     クリックした際にその条件が適用された一覧へ直接遷移できる。
     ====================================================================== */

  var routes = {};
  var current = null;

  /* 廃止された画面の旧URL。
     --------------------------------------------------------------------
     画面を統合したり名称を変更したりしても **URLは残っている** — 担当者のブックマーク、,
     メールでやり取りしたリンク、操作ログ内のリンク。それらが「画面が見つかり
     ません」になると不具合のように見えてしまう。

     クエリ(`?hospital_id=3`)はそのまま引き継ぐ。遷移先の画面が同じ条件を
     読み取れなければ、旧リンクの意味が損なわれてしまう。 */
  var ALIASES = {
    'hospitals': 'bulk-venues',        // 会場管理 → 会場管理（グリッド）へ統合
    'hospitals-bulk': 'bulk-venues',   // マスターファイル取り込み → 会場管理内のボタン
    'exam-options': 'bulk-exam-options' // オプション検査管理 → グリッド版
  };

  function route(name, handler) { routes[name] = handler; }

  // 화면 이름 → 메뉴에 적힌 이름. 권한과 무관하게 전부 담는다. (app.js)
  var routeLabels = {};

  function parseHash() {
    var raw = location.hash.replace(/^#\/?/, '');
    var split = raw.split('?');
    var name = split[0] || 'dashboard';
    var params = {};

    if (split[1]) {
      split[1].split('&').forEach(function (pair) {
        var kv = pair.split('=');
        if (kv[0]) params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
      });
    }
    return { name: name, params: params };
  }

  function go(name, params) {
    location.hash = '#/' + name + query(params);
  }

  /** 同一画面内で条件のみを変更する場合。履歴を汚さない。 */
  function replace(name, params) {
    history.replaceState(null, '', '#/' + name + query(params));
  }

  function render() {
    var target = parseHash();

    // 旧URLは新画面へ転送する。replaceのため「戻る」操作で旧URLに
    // 戻って無限ループになるのを防ぐ。
    var alias = ALIASES[target.name];
    if (alias && routes[alias]) {
      location.replace('#/' + alias + query(target.params));
      return;
    }

    var handler = routes[target.name];
    var view = document.getElementById('view');

    if (!handler) {
      clear(view).appendChild(el('div.empty', {}, [
        el('p.empty__title', { text: '画面が見つかりません' }),
        el('p', { text: '左側のメニューから再度選択してください。' })
      ]));
      return;
    }

    current = target;
    clear(view).appendChild(loading());
    setActiveNav(target.name);

    // 먼저 메뉴 이름으로 제목을 바꿔 둔다. 화면이 데이터를 못 읽고 실패하면
    // (권한 없음 등) 자기 제목을 쓰기 전에 끝나, 앞 화면의 제목과 단추가 남았다.
    // 권한 때문에 메뉴에 감춘 화면도 이름은 알아야 하므로 메뉴 DOM 이 아니라
    // 메뉴 정의(`routeLabels`, app.js 가 채운다)에서 찾는다.
    setTitle(routeLabels[target.name] || '', '');

    try {
      handler(view, target.params);
    } catch (error) {
      clear(view).appendChild(errorPanel(error));
    }
  }

  function errorPanel(error) {
    return el('div.empty', {}, [
      el('p.empty__title', { text: '画面を表示できませんでした' }),
      el('p', { text: (error && error.message) || '不明なエラーです。' })
    ]);
  }

  function setActiveNav(name) {
    var links = document.querySelectorAll('#nav-menu .nav__link');
    Array.prototype.forEach.call(links, function (link) {
      var target = link.dataset.route;
      var active = target === name ||
        (link.dataset.match && name.indexOf(link.dataset.match) === 0);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function setTitle(title, desc, tools) {
    document.getElementById('view-title').textContent = title;
    document.getElementById('view-desc').textContent = desc || '';
    var slot = clear(document.getElementById('view-tools'));
    if (tools) append(slot, tools);
    document.title = title + ' | 健康診断予約管理';
    // 画面が変わるたびに「使い方」もその画面のものに差し替える (guide.js)
    if (window.AdminGuide) window.AdminGuide.mount(parseHash().name);
  }

  /** 画面描画の失敗を共通で処理する。 */
  function fail(view, error) {
    clear(view).appendChild(errorPanel(error));
    if (error && error.message) toast(error.message, 'danger');
  }

  /* ======================================================================
     新規UIコンポーネントヘルパー
     ====================================================================== */

  function switchToggle(options) {
    options = options || {};
    var input = el('input.switch__input', {
      type: 'checkbox',
      checked: !!options.checked,
      onChange: function (e) {
        if (options.onChange) options.onChange(e.target.checked);
      }
    });
    var slider = el('span.switch__slider');
    var label = options.label ? el('span.switch__label', { text: options.label }) : null;
    return el('label.switch', {}, [input, slider, label]);
  }

  function progressBar(percent, text, level) {
    percent = Math.min(100, Math.max(0, Math.round(percent || 0)));
    level = level || (percent >= 90 ? 'danger' : percent >= 75 ? 'warn' : 'ok');
    var fill = el('div.cap-bar__fill.cap-bar__fill--' + level, { style: 'width:' + percent + '%' });
    var track = el('div.cap-bar__track', {}, [fill]);

    // 説明文言がない場合はバーのみ描画する。以前は同じパーセントを左右に
    // 2回記載して（「95%  95%」）枠だけが高くなっていた。
    if (!text) return el('div.cap-bar', {}, [track]);

    var info = el('div.cap-bar__info', {}, [
      el('span', { text: text }),
      el('span', { text: percent + '%' })
    ]);
    return el('div.cap-bar', {}, [track, info]);
  }

  /* 후리가나를 전각 가타카나로 맞춘다.

     담당자는 종이 신청서를 보고 빠르게 친다. IME 가 히라가나 상태면 「さとう」가
     그대로 들어가고, 반각으로 치면 「ｻﾄｳ」가 된다. 저장된 뒤에는 목록·검색·CSV
     까지 그 표기가 따라다닌다. 이용자 화면(verify.js)이 이미 같은 변환을 하므로
     관리 화면도 맞춘다. 규칙은 서버 text_utils.normalize_kana 와 같다. */
  function toKatakana(text) {
    if (!text) return '';
    // NFKC — 반각 가타카나를 전각으로 (ﾀﾅｶ → タナカ, ﾀﾞ → ダ). 공백은 뺀다
    // (서버 normalize_kana·이용자 화면과 같은 규칙).
    var s = String(text).normalize('NFKC').replace(/\s+/g, '');
    // 히라가나 → 가타카나 (ぁ U+3041 ~ ゖ U+3096 은 +0x60)
    return s.replace(/[ぁ-ゖ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) + 0x60);
    });
  }

  /** 후리가나 입력칸에 자동 변환을 건다. 입력 도중(IME 조합 중)에는 건드리지 않는다. */
  function attachKana(input, onChanged) {
    if (!input || input.dataset.kanaAuto) return input;
    input.dataset.kanaAuto = '1';

    function convert() {
      var after = toKatakana(input.value);
      if (after === input.value) return;
      input.value = after;
      if (onChanged) onChanged(after);
    }

    input.addEventListener('blur', convert);
    input.addEventListener('compositionend', convert);
    return input;
  }

  function toHiragana(text) {
    return String(text || '').replace(/[ァ-ヶ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0x60);
    });
  }

  /* クイック検索が会場で参照する項目 — この3つのみである。
     --------------------------------------------------------------------
     以前は住所・地域・電話・郵便番号・開催日までひとまとめに検索していた。
     広範囲で良さそうに見えるが、「東京都」で検索すると一度に会場が5〜6件ヒットし、
     そのうち何がなぜヒットしたのか結果を見ただけでは分からなかった。会場を特定する
     値はコードと名称（およびその読み）であるため、その3つに絞り込む。
     住所・電話で検索する方法は「会場管理」テーブルの検索欄にそのまま残っている。

     フリガナ(`name_kana`)は **サーバーから返却される。** 以前はこのファイルが会場20件の
     フリガナを保持していたが、担当者がテーブル上で修正しても検索は古いコピーを参照しており、
     21件目の会場はひらがなで全く検索できなかった。 */
  var HOSP_FIELDS = ['code', 'name', 'name_kana'];

  /**
   * 会場1件が検索キーワードにヒットするか。ヒットする場合、 **どの項目で** ヒットしたか。
   *
   * 「どの項目か」が必要な理由：会場管理テーブルへ遷移した際、その項目を
   * 強調表示するためである。コードで検索した場合はコード欄を、フリガナで検索した場合は
   * フリガナ欄を強調表示する。
   */
  function hospMatch(h, qHira) {
    for (var i = 0; i < HOSP_FIELDS.length; i++) {
      var raw = String(h[HOSP_FIELDS[i]] || '');
      if (!raw) continue;
      if (toHiragana(raw).toLowerCase().indexOf(qHira) >= 0) {
        return { hospital: h, field: HOSP_FIELDS[i], text: raw };
      }
    }
    return null;
  }

  var HOSP_FIELD_LABEL = {
    code: '会場コード',
    name: '会場名',
    name_kana: 'フリガナ'
  };

  /** クイック検索ドロップダウンの会場1行。同じ会場が「遷移先」ごとに1行ずつ表示される。 */
  function hospItem(h, action, desc, onClick) {
    return el('div.quick-search__item', { onClick: onClick }, [
      el('div.quick-search__item-main', {}, [
        el('span.quick-search__item-title', {
          text: h.name + ' [' + h.code + '] · ' + action
        }),
        el('span.quick-search__item-sub', { text: desc })
      ]),
      el('span.badge.badge--' + (h.is_visible ? 'ok' : 'muted'), {
        text: h.is_visible ? '表示' : '非表示'
      })
    ]);
  }

  function initQuickSearch() {
    var input = document.getElementById('global-search-input');
    var dropdown = document.getElementById('global-search-dropdown');
    if (!input || !dropdown) return;

    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        dropdown.hidden = true;
        var q = input.value.trim();
        // Enter は検索結果ページへ。予約者が2万人規模のため、ドロップダウンの
        // 数行では溢れる。結果ページが種類別の件数と各画面への入口を示す。
        if (q) go('search', { q: q });
      }
    });

    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (!q) {
        dropdown.hidden = true;
        clear(dropdown);
        return;
      }
      timer = setTimeout(function () {
        performQuickSearch(q, dropdown);
      }, 250);
    });

    document.addEventListener('click', function (e) {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.hidden = true;
      }
    });
  }

  function performQuickSearch(query, dropdown) {
    clear(dropdown);
    dropdown.appendChild(loading());
    dropdown.hidden = false;

    Promise.all([
      request('GET', '/reservations?keyword=' + encodeURIComponent(query) + '&size=5').catch(function () { return { data: { items: [] } }; }),
      request('GET', '/hospitals').catch(function () { return { data: [] }; })
    ]).then(function (results) {
      clear(dropdown);
      var resData = (results[0] && results[0].data) || {};
      var resList = Array.isArray(resData) ? resData : (resData.items || []);
      var allHospitals = (results[1] && results[1].data) || [];
      var qHira = toHiragana(query).trim().toLowerCase();

      // 会場1件が **2行**になるため（会場管理 / 定員管理）件数を
      // 3件に絞る。5件だと10行になり予約結果が押し出される。
      var hospList = [];
      allHospitals.forEach(function (h) {
        if (hospList.length >= 3) return;
        var hit = qHira ? hospMatch(h, qHira) : { hospital: h, field: 'name', text: h.name };
        if (hit) hospList.push(hit);
      });

      if (!resList.length && !hospList.length) {
        dropdown.appendChild(el('div', { style: 'padding:14px;text-align:center;color:var(--a-ink-weak);font-size:13px;', text: '検索結果がありません。' }));
        return;
      }

      if (resList.length) {
        dropdown.appendChild(el('div.quick-search__group-title', { text: '予約 / 受診者検索' }));
        resList.forEach(function (r) {
          dropdown.appendChild(el('div.quick-search__item', {
            onClick: function () {
              dropdown.hidden = true;
              go('reservation', { id: r.id });
            }
          }, [
            el('div.quick-search__item-main', {}, [
              el('span.quick-search__item-title', { text: (r.full_name || '受診者') + ' (' + (r.reservation_no || '') + ')' }),
              el('span.quick-search__item-sub', { text: (r.hospital_name || '') + ' | ' + (r.slot_date ? (fmt.dateShort(r.slot_date) + ' ' + (r.time_label || '')) : '') })
            ]),
            statusBadge(r.status, r.status_label, r.is_holiday)
          ]));
        });
      }

      if (hospList.length) {
        dropdown.appendChild(el('div.quick-search__group-title', {
          text: '会場検索（コード・会場名・フリガナ）'
        }));

        // 会場1件に対して遷移先が2箇所ある。「どこを修正しに来たか」が異なり、,
        // それをドロップダウンで選択できなければ、一度遷移してから移動し直す必要がある。
        //
        //   会場管理 → 住所・表示・順序。ヒットした項目を強調表示する。
        //   定員管理 → その会場の開催回別定員。
        hospList.forEach(function (hit) {
          var h = hit.hospital;

          dropdown.appendChild(hospItem(h, '会場管理', HOSP_FIELD_LABEL[hit.field] +
            '（で一致） — 該当項目を強調表示します。', function () {
            dropdown.hidden = true;
            go('bulk-venues', { code: h.code, q: query, field: hit.field });
          }));

          dropdown.appendChild(hospItem(h, '定員管理', 'この会場の開催回別定員',
            function () {
              dropdown.hidden = true;
              go('bulk-capacity', { hospital_id: h.id });
            }));
        });
      }

      // 一番下 — 検索結果ページへ。
      // 「すべて」を押したときは1件でも結果ページを見せる(all=1)。
      // 1件のとき詳細へ直行するのは Enter だけ。
      dropdown.appendChild(el('div.quick-search__item.quick-search__item--all', {
        onClick: function () {
          dropdown.hidden = true;
          go('search', { q: query, all: '1' });
        }
      }, [
        el('div.quick-search__item-main', {}, [
          el('span.quick-search__item-title', { text: 'すべての結果を見る' }),
          el('span.quick-search__item-sub', { text: '予約・会場・オプション検査・操作ログをまとめて表示(Enter)' })
        ])
      ]));
    });
  }

  function initTheme() {
    try {
      localStorage.removeItem('kenshin_admin_theme');
      document.body.classList.remove('theme-light', 'theme-dark', 'theme-eyecare');
    } catch (e) {}
  }

  /* ======================================================================
     右スライドドロワー（Drawer Modal）
     ====================================================================== */
  function drawer(options) {
    var root = document.getElementById('drawer-root');
    clear(root);

    var backdrop = el('div.drawer-backdrop');
    var panel = el('div.drawer-panel');

    var header = el('div.drawer-header', {}, [
      el('div.drawer-header__title', { text: options.title || '詳細情報' }),
      el('button.drawer-close', { type: 'button', text: '✕', onClick: close })
    ]);

    var body = el('div.drawer-body');
    if (options.content instanceof Node) body.appendChild(options.content);
    else if (Array.isArray(options.content)) options.content.forEach(function(c){ append(body, c); });
    else body.textContent = String(options.content || '');

    append(panel, [header, body]);
    append(root, [backdrop, panel]);

    requestAnimationFrame(function () {
      backdrop.classList.add('is-visible');
      panel.classList.add('is-visible');
    });

    function close() {
      panel.classList.remove('is-visible');
      backdrop.classList.remove('is-visible');
      setTimeout(function () { clear(root); if (options.onClose) options.onClose(); }, 240);
    }

    backdrop.addEventListener('click', close);

    return { close: close, body: body };
  }

  /* ======================================================================
     CSV ダウンロードヘルパー
     ====================================================================== */
  function exportCSV(filename, headers, rows) {
    var content = '\uFEFF';
    content += headers.map(function (h) { return '"' + String(h).replace(/"/g, '""') + '"'; }).join(',') + '\n';

    rows.forEach(function (row) {
      content += row.map(function (val) {
        if (val === null || val === undefined) val = '';
        return '"' + String(val).replace(/"/g, '""') + '"';
      }).join(',') + '\n';
    });

    var blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  // DOM ロード完了時にクイック検索とテーマを初期化
  document.addEventListener('DOMContentLoaded', function() {
    initQuickSearch();
    initTheme();
  });

  /* ======================================================================
     公開
     ====================================================================== */

  return {
    api: api,
    query: query,
    el: el,
    append: append,
    clear: clear,
    chainScroll: chainScroll,
    icon: icon,
    fmt: fmt,
    statusBadge: statusBadge,
    toast: toast,
    announce: announce,
    modal: modal,
    drawer: drawer,
    confirm: confirm,
    table: table,
    pager: pager,
    field: field,
    input: input,
    select: select,
    textarea: textarea,
    checkbox: checkbox,
    notice: notice,
    loading: loading,
    card: card,
    addressSearch: addressSearch,
    route: route,
    routeLabels: routeLabels,
    render: render,
    go: go,
    replace: replace,
    setTitle: setTitle,
    fail: fail,
    parseHash: parseHash,
    toLogin: toLogin,
    switchToggle: switchToggle,
    progressBar: progressBar,
    initQuickSearch: initQuickSearch,
    toHiragana: toHiragana,
    toKatakana: toKatakana,
    attachKana: attachKana,
    hospMatch: hospMatch,
    HOSP_FIELD_LABEL: HOSP_FIELD_LABEL,
    initTheme: initTheme,
    exportCSV: exportCSV,
    me: null   // app.js がログイン情報を設定する
  };

})();
