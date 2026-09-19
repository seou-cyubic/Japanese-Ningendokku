/* ==========================================================================
   search.js — 검색 결과 (#/search?q=…)
   --------------------------------------------------------------------------
   예약자가 2만 명이다. 이름 하나로는 수백 명이 걸리고, 위의 빠른 검색
   드롭다운은 다섯 줄이라 늘 넘친다. 그래서 Enter 를 치면 여기로 온다.

   프로토타입(guide-search-proto)과 같은 모양이다.
     · 맨 위 : 「<검색어> の検索結果 · N件」 + 갈래 칩. 칩을 누르면 그 갈래만
       남긴다. 0건 갈래는 눌리지 않는다.
     · 갈래 : 会場 → 予約・受診者 → その会場の予約 → オプション検査 → 操作ログ.
       회장이 예약보다 앞이다. 회장은 한두 곳이라 짧고, 「その会場の予約」가
       그 바로 아래 이어져야 읽힌다.
     · 한 줄 = 번호 · 제목(검색어 강조) · 부제 · **어디서 걸렸는가** · 상태/갈 곳.
       「なぜ出たのか」를 줄마다 보이므로 300건이라도 훑을 수 있다.
     · 어느 갈래든 통틀어 **1건뿐이면 결과 화면을 건너뛰고** 그 화면으로 간다.
       예약번호를 친 사람은 결과 목록이 아니라 그 예약을 보러 온 것이다.
     · 갈래마다 10줄. 그 위는 「すべて見る ›」로 본 화면（予約検索 · 操作ログ）에
       같은 검색어를 들고 건너간다.

   예약 줄의 부제에 **생년월일**을 둔다. 전화로 동명이인을 가르는 첫 질문이
   「生年月日は?」이기 때문이다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var ROWS = 10;     // 갈래마다 보여 주는 줄 수. 그 위는 본 화면에서 좁힌다
  var FETCH = 50;    // 서버에 청하는 수. 건수(total)는 따로 온다

  var state = null;  // { q, kind, res, hos, via, opt, log, resTotal, logTotal }

  A.route('search', function (view, params) {
    var q = String(params.q || '').trim();
    A.setTitle('検索結果', q ? '予約・会場・オプション検査・操作ログの横断検索' : '');

    if (!q) {
      A.clear(view).appendChild(el('div.empty', {}, [
        el('p.empty__title', { text: '検索語を入力してください' }),
        el('p', { text: '上の検索欄に氏名・予約番号・電話番号・メール・会場名を入力し、Enter を押してください。' })
      ]));
      return;
    }

    // 검색 칸에도 같은 말을 남긴다. 고쳐서 다시 치는 자리가 거기다.
    var input = document.getElementById('global-search-input');
    if (input && input.value !== q) input.value = q;

    A.clear(view).appendChild(A.loading('「' + q + '」を探しています…'));

    state = { q: q, kind: 'all', res: [], hos: [], via: [], opt: [], log: [],
              resTotal: 0, logTotal: 0 };
    // 검색어를 빠르게 바꾸면 앞 검색의 응답이 뒤에 도착한다. 그때 앞 것이
    // 새 화면 위에 그려지면 안 된다 — 내 state 가 아직 현재인지로 가른다.
    var mine = state;

    // 한 갈래가 실패해도 나머지는 보여 준다. 접수 직원이 검색으로 하는 일은
    // 대부분 「환자 찾기」인데, 예전에는 회장 조회(아래) 하나가 막히면
    // 예약 결과까지 통째로 「権限がありません」이 되어 아무것도 못 찾았다.
    // 그래서 갈래마다 .catch 로 자기 자리만 비운다.
    var jobs = [
      A.api.get('/reservations' + A.query({ keyword: q, size: FETCH }))
        .then(function (body) {
          var page = body.data || {};
          state.res = (Array.isArray(page) ? page : (page.items || [])).map(function (r) {
            r._why = reservationWhy(r, q);
            return r;
          });
          state.resTotal = page.total != null ? page.total : state.res.length;
        })
        .catch(function () { state.res = []; state.resTotal = 0; })
    ];

    // 회장 목록 API 는 L2 이상 전용이다. 접수 직원(L1)은 애초에 부르지
    // 않는다 — 부르면 403 이고, 예전에는 그 거절이 화면 전체를 삼켰다.
    if (canSee(2)) {
      jobs.push(A.api.get('/hospitals').then(function (body) {
        var qh = A.toHiragana(q).trim().toLowerCase();
        state.hos = [];
        (body.data || []).forEach(function (h) {
          var hit = A.hospMatch(h, qh);
          if (hit) state.hos.push({ h: h, field: hit.field, upcoming: upcomingCount(h) });
        });
      }).catch(function () { state.hos = []; }));
    }

    if (canSee(2)) {
      jobs.push(A.api.get('/bulk/exam-options').then(function (body) {
        var qh = A.toHiragana(q).trim().toLowerCase();
        state.opt = [];
        ((body.data || {}).rows || []).forEach(function (o) {
          var why = null;
          if (hit(o.code, qh)) why = 'コード';
          else if (hit(o.name, qh)) why = '検査名';
          else if (hit(o.description, qh)) why = '説明';
          if (why) state.opt.push({ o: o, why: why });
        });
      }).catch(function () { state.opt = []; }));
    }

    if (canSee(3)) {
      jobs.push(A.api.get('/audit-logs' + A.query({ keyword: q, size: FETCH }))
        .then(function (body) {
          var page = body.data || {};
          state.log = (page.items || []).map(function (l) {
            l._why = logWhy(l, q);
            return l;
          });
          state.logTotal = page.total != null ? page.total : state.log.length;
        }).catch(function () { state.log = []; state.logTotal = 0; }));
    }

    Promise.all(jobs)
      .then(function () {
        if (state !== mine) return;
        // 회장이 걸리면 그 회장의 예약을 이어서 보인다 (최대 3곳)
        var already = {};
        state.res.forEach(function (r) { already[r.id] = 1; });
        return Promise.all(state.hos.slice(0, 3).map(function (x) {
          return A.api.get('/reservations' + A.query({ hospital_id: x.h.id, size: ROWS }))
            .then(function (body) {
              var page = body.data || {};
              x.resTotal = page.total != null ? page.total : 0;
              (page.items || []).forEach(function (r) {
                if (!already[r.id]) { already[r.id] = 1; r._via = x.h; state.via.push(r); }
              });
            })
            .catch(function () { x.resTotal = null; });
        }));
      })
      .then(function () {
        if (state !== mine || A.parseHash().name !== 'search') return;
        // 「すべての結果を見る」로 왔으면(all=1) 1건이어도 결과 화면을 보여 준다.
        if (!params.all && jumpIfSingle()) return;
        paint(view);
      })
      .catch(function (error) { A.fail(A.clear(view), error); });
  });

  /* ----------------------------------------------------------------------
     도우미
     ---------------------------------------------------------------------- */
  function canSee(level) {
    return !!(A.me && Number(A.me.level) >= level);
  }

  function norm(s) {
    return A.toHiragana(String(s == null ? '' : s)).replace(/\s+/g, '').toLowerCase();
  }

  function hit(text, qh) {
    return !!qh && norm(text).indexOf(qh.replace(/\s+/g, '')) >= 0;
  }

  function digits(s) { return String(s || '').replace(/\D/g, ''); }

  /** 예약번호 검색용 뭉개기 — 서버(core/reservation_no.py fold_for_search)와 같은 규칙.
      전화로 들은 번호는 대소문자도 0/O·1/l/I 도 가려지지 않는다. */
  function foldNo(s) {
    return String(s || '').toLowerCase().replace(/o/g, '0').replace(/[li]/g, '1');
  }

  /* 생년월일 파서 — 서버(core/birth_query.py)와 같은 규칙.
     서기·和暦·8자리를 읽고, 연도(·월)만이면 범위로 돌려준다. */
  var ERA = { M: 1868, T: 1912, S: 1926, H: 1989, R: 2019,
              '明治': 1868, '大正': 1912, '昭和': 1926, '平成': 1989, '令和': 2019,
              '明': 1868, '大': 1912, '昭': 1926, '平': 1989, '令': 2019 };
  function nfkc(s) { s = String(s || ''); return s.normalize ? s.normalize('NFKC') : s; }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(y, m, d) {
    var now = new Date();
    if (y < 1900 || y > now.getFullYear()) return null;
    if (m == null) return { lo: y + '-01-01', hi: y + '-12-31' };
    if (m < 1 || m > 12) return null;
    if (d == null) {
      return { lo: y + '-' + pad2(m) + '-01', hi: y + '-' + pad2(m) + '-' + new Date(y, m, 0).getDate() };
    }
    var dt = new Date(y, m - 1, d);
    if (dt.getMonth() !== m - 1 || dt.getDate() !== d || dt > now) return null;
    var iso = y + '-' + pad2(m) + '-' + pad2(d);
    return { lo: iso, hi: iso };
  }
  function parseBirth(tok) {
    var t = nfkc(tok).replace(/[\s\u3000]/g, '').toUpperCase();
    var m;
    if ((m = /^(\d{4})(\d{2})(\d{2})$/.exec(t))) return ymd(+m[1], +m[2], +m[3]);
    if ((m = /^(\d{4})[./\-年](\d{1,2})(?:[./\-月](\d{1,2}))?日?$/.exec(t))) return ymd(+m[1], +m[2], m[3] ? +m[3] : null);
    if ((m = /^(\d{4})年?$/.exec(t))) return ymd(+m[1], null, null);
    if ((m = /^(明治|大正|昭和|平成|令和|[MTSHR]|[明大昭平令])(元|\d{1,2})(?:[./\-年](\d{1,2})(?:[./\-月](\d{1,2}))?日?|年)?$/.exec(t))) {
      var base = ERA[m[1]]; if (!base) return null;
      var n = m[2] === '元' ? 1 : +m[2]; if (n < 1) return null;
      if (!m[3] && m[4]) return null;
      return ymd(base + n - 1, m[3] ? +m[3] : null, m[4] ? +m[4] : null);
    }
    return null;
  }
  /** 검색어를 「글 토막」과 「생년월일 범위」로 가른다 */
  function splitQuery(q) {
    var words = [], dates = [];
    String(q || '').trim().split(/[\s\u3000]+/).forEach(function (tok) {
      if (!tok) return;
      var r = parseBirth(tok);
      if (r) dates.push(r); else words.push(tok);
    });
    return { words: words, dates: dates };
  }
  function birthHit(iso, dates) {
    if (!iso) return false;
    var v = String(iso).slice(0, 10);
    return dates.some(function (r) { return v >= r.lo && v <= r.hi; });
  }
  /** 1958-11-03 → 'S33'. 창구에서 和暦로 묻는 사람을 위해 짧게 붙인다 */
  function eraLabel(iso) {
    if (!iso) return '';
    var v = String(iso).slice(0, 10);
    var eras = [['2019-05-01', 'R', 2019], ['1989-01-08', 'H', 1989], ['1926-12-25', 'S', 1926],
                ['1912-07-30', 'T', 1912], ['1868-01-25', 'M', 1868]];
    for (var i = 0; i < eras.length; i++) {
      if (v >= eras[i][0]) return eras[i][1] + (Number(v.slice(0, 4)) - eras[i][2] + 1);
    }
    return '';
  }

  /** 예약이 어느 칸에서 걸렸는가 — 서버와 같은 순서로 짚는다 */
  function reservationWhy(r, q) {
    var parts = splitQuery(q);
    var why = [];
    parts.words.forEach(function (w) {
      var qh = norm(w);
      var one = '';
      if (r.reservation_no && foldNo(r.reservation_no).indexOf(foldNo(w)) >= 0) one = '予約番号';
      else if (hit(r.full_name, qh)) one = '氏名';
      else if (hit(r.full_name_kana, qh)) one = 'フリガナ';
      else {
        var d = digits(w);
        if (d.length >= 4 && digits(r.tel_primary).indexOf(d) >= 0) one = '電話番号';
        else if (r.email && norm(r.email).indexOf(qh) >= 0) one = 'メール';
      }
      if (one && why.indexOf(one) < 0) why.push(one);
    });
    if (parts.dates.length && birthHit(r.birth_date, parts.dates)) why.push('生年月日');
    return why.join('・');
  }

  function logWhy(l, q) {
    var qh = norm(q);
    if (hit(l.target_label, qh)) return '対象';
    if (hit(l.admin_name, qh)) return '担当者';
    if (hit(l.admin_login_id, qh)) return 'ログインID';
    return '';
  }

  function upcomingCount(h) {
    var today = new Date(); today.setHours(0, 0, 0, 0);
    return (h.schedules || []).filter(function (s) {
      var d = new Date(String(s.event_date).slice(0, 10) + 'T00:00:00');
      return !isNaN(d) && d >= today;
    }).length;
  }

  /** 검색어와 겹치는 부분을 <mark> 로 감싼다. 히라가나·가타카나를 같게 본다 */
  function mark(text, q) {
    text = String(text == null ? '' : text);
    var box = el('span');
    var words = q ? splitQuery(q).words : [];
    var t = A.toHiragana(text).toLowerCase();
    for (var w = 0; w < words.length; w++) {
      var k = A.toHiragana(words[w]).toLowerCase();
      var i = k ? t.indexOf(k) : -1;
      if (i < 0) continue;
      box.appendChild(document.createTextNode(text.slice(0, i)));
      box.appendChild(el('mark', { text: text.slice(i, i + k.length) }));
      box.appendChild(document.createTextNode(text.slice(i + k.length)));
      return box;
    }
    box.textContent = text;
    return box;
  }

  function counts() {
    return {
      res: state.resTotal + state.via.length,
      hos: state.hos.length,
      opt: state.opt.length,
      log: state.logTotal
    };
  }

  /** 결과 화면을 건너뛰어도 되는 경우 — 뒤로가기는 결과 화면이 아니라 이전 화면으로.
      · 예약이 딱 1건이고 회장·검사가 없으면 그 예약으로. 예약번호를 친 사람은
        목록이 아니라 그 예약을 보러 온 것이다. 그 예약의 조작 이력은 상세
        화면에도 있으므로 로그가 같이 걸려도 건너뛴다.
      · 그 밖에는 통틀어 1건일 때만. */
  function jumpIfSingle() {
    var c = counts();
    var total = c.res + c.hos + c.opt + c.log;
    if (state.resTotal === 1 && state.res.length === 1 && !c.hos && !c.opt) {
      A.replace('reservation', { id: state.res[0].id });
    }
    else if (total !== 1) return false;
    else if (state.hos.length === 1) {
      var x = state.hos[0];
      A.replace('bulk-venues', { code: x.h.code, q: state.q, field: x.field });
    }
    else if (state.opt.length === 1) A.replace('bulk-exam-options', { code: state.opt[0].o.code });
    else if (state.log.length === 1) A.replace('audit-logs', { keyword: state.q });
    else return false;
    A.render();
    return true;
  }

  /* ----------------------------------------------------------------------
     그리기
     ---------------------------------------------------------------------- */
  function paint(view) {
    A.clear(view);
    var q = state.q;
    var c = counts();
    var total = c.res + c.hos + c.opt + c.log;

    view.appendChild(el('div.srch-head', {}, [
      el('span.srch-head__q', {}, [el('mark', { text: q }), document.createTextNode(' の検索結果')]),
      el('span.srch-head__n', { text: A.fmt.number(total) + '件' })
    ]));

    // L1 은 회장·검사·로그를 볼 권한이 없으므로 그 칩을 아예 띄우지 않는다.
    // (예전에는 회장 칩이 늘 「0」으로 남아 「왜 안 나오나」를 되묻게 했다.)
    var chips = [['all', 'すべて', total], ['res', '予約・受診者', c.res]];
    if (canSee(2)) chips.push(['hos', '会場', c.hos]);
    if (canSee(2)) chips.push(['opt', 'オプション検査', c.opt]);
    if (canSee(3)) chips.push(['log', '操作ログ', c.log]);

    view.appendChild(el('div.srch-kinds', {}, chips.map(function (k) {
      var zero = k[2] === 0 && k[0] !== 'all';
      return el('button.srch-kind' + (state.kind === k[0] ? '.is-on' : '') + (zero ? '.is-zero' : ''), {
        type: 'button', disabled: zero || null,
        onClick: function () { state.kind = k[0]; paint(view); }
      }, [document.createTextNode(k[1] + ' '), el('b', { text: A.fmt.number(k[2]) })]);
    })));

    if (!total) { view.appendChild(emptyBox()); return; }

    function group(key, title, n, rows, more) {
      if ((state.kind !== 'all' && state.kind !== key) || !n) return;
      var head = el('div.srch-group__head', {}, [
        el('span.srch-group__title', { text: title }),
        el('span.srch-group__n', { text: A.fmt.number(n) + '件' })
      ]);
      if (more) {
        head.appendChild(el('button.srch-group__more', {
          type: 'button', text: more.label + ' ›', onClick: more.go
        }));
      }
      view.appendChild(el('div.srch-group', {}, [head, el('div.srch-card', {}, rows)]));
    }

    // 会場
    group('hos', '会場', c.hos, state.hos.map(function (x) {
      var h = x.h;
      var sub = [h.area || h.region || '', '今後の開催 ' + x.upcoming + '回'];
      if (x.resTotal != null) sub.push('予約 ' + A.fmt.number(x.resTotal) + '件');
      var subNode = el('span.srch-row__s');
      if (x.field === 'name_kana') {
        subNode.appendChild(mark(h.name_kana, q));
        subNode.appendChild(document.createTextNode(' · '));
      }
      subNode.appendChild(document.createTextNode(sub.filter(Boolean).join(' · ')));
      return row({
        no: h.code,
        title: mark(h.name, q),
        sub: subNode,
        why: A.HOSP_FIELD_LABEL[x.field] + 'で一致',
        onClick: function () { A.go('bulk-venues', { code: h.code, q: q, field: x.field }); },
        tail: [
          mini('会場管理', function () { A.go('bulk-venues', { code: h.code, q: q, field: x.field }); }),
          mini('定員管理', function () { A.go('bulk-capacity', { hospital_id: h.id }); })
        ]
      });
    }));

    // 予約・受診者
    group('res', '予約・受診者', state.resTotal,
      state.res.slice(0, ROWS).map(function (r) { return resRow(r, q, true); }),
      state.resTotal > ROWS
        ? { label: '予約検索で絞り込む', go: function () { A.go('reservations', { keyword: q }); } }
        : null);

    // その会場の予約
    if (state.via.length) {
      var one = state.hos.length === 1 ? state.hos[0] : null;
      group('res', 'その会場の予約', state.via.length,
        state.via.slice(0, ROWS).map(function (r) { return resRow(r, '', false); }),
        one
          ? { label: one.h.name + ' の予約をすべて見る',
              go: function () { A.go('reservations', { hospital_id: one.h.id }); } }
          : null);
    }

    // オプション検査
    group('opt', 'オプション検査', c.opt, state.opt.map(function (x) {
      var o = x.o;
      return row({
        no: o.code,
        title: mark(o.name, q),
        sub: el('span.srch-row__s', {
          text: 'この検査を申し込んだ予約 ' + A.fmt.number(o._used_count || 0) + '件' +
                (o.is_active === 'はい' ? '' : ' · 利用停止中')
        }),
        why: x.why + 'で一致',
        onClick: function () { A.go('bulk-exam-options', { code: o.code }); },
        tail: [
          mini('検査を編集', function () { A.go('bulk-exam-options', { code: o.code }); }),
          mini('申込を見る', function () { A.go('reservations', { option_id: o.id }); })
        ]
      });
    }));

    // 操作ログ
    group('log', '操作ログ', c.log, state.log.slice(0, ROWS).map(function (l) {
      var subNode = el('span.srch-row__s');
      subNode.appendChild(mark(l.admin_name || l.admin_login_id || '', q));
      subNode.appendChild(document.createTextNode(' · '));
      subNode.appendChild(mark(l.target_label || '', q));
      return row({
        no: A.fmt.datetime(l.created_at).slice(5),
        title: el('span', { text: l.action_label || l.action }),
        sub: subNode,
        why: l._why ? l._why + 'で一致' : '',
        onClick: function () { A.go('audit-logs', { keyword: q }); },
        tail: [mini('前後を見る', function () { A.go('audit-logs', { keyword: q }); })]
      });
    }), c.log > ROWS
      ? { label: '操作ログで絞り込む', go: function () { A.go('audit-logs', { keyword: q }); } }
      : null);
  }

  function resRow(r, q, showWhy) {
    var subNode = el('span.srch-row__s');
    var dates = q ? splitQuery(q).dates : [];
    var first = true;
    function sep() { if (!first) subNode.appendChild(document.createTextNode(' · ')); first = false; }
    if (r.full_name_kana) { sep(); subNode.appendChild(mark(r.full_name_kana, q)); }
    if (r.birth_date) {
      sep();
      var iso = String(r.birth_date).slice(0, 10);
      var era = eraLabel(iso);
      var bd = iso + (era ? ' (' + era + ')' : '');
      subNode.appendChild(birthHit(iso, dates) ? el('mark', { text: bd }) : document.createTextNode(bd));
    }
    if (r.hospital_name) { sep(); subNode.appendChild(document.createTextNode(r.hospital_name)); }
    if (r.slot_date) {
      sep();
      subNode.appendChild(document.createTextNode(A.fmt.dateShort(r.slot_date) + ' ' + (r.time_label || '')));
    }
    return row({
      no: r.reservation_no,
      title: mark(r.full_name || '受診者', q),
      sub: subNode,
      why: showWhy && r._why ? r._why + 'で一致' : '',
      onClick: function () { A.go('reservation', { id: r.id }); },
      tail: [A.statusBadge(r.status, r.status_label, r.is_holiday)]
    });
  }

  function row(o) {
    var main = el('span.srch-row__main', {}, [
      el('span.srch-row__t', {}, [o.title]),
      o.sub
    ]);
    var kids = [el('span.srch-row__no', { text: o.no || '' }), main];
    if (o.why) kids.push(el('span.srch-row__why', { text: o.why }));
    if (o.tail && o.tail.length) kids.push(el('span.srch-row__go', {}, o.tail));
    return el('div.srch-row', { onClick: o.onClick }, kids);
  }

  function mini(label, go) {
    return el('button.srch-mini', {
      type: 'button', text: label,
      onClick: function (ev) { ev.stopPropagation(); go(); }
    });
  }

  function emptyBox() {
    return el('div.srch-empty', {}, [
      el('b', { text: '該当する結果がありません' }),
      el('span', { text: '別のことばでお試しください。' }),
      el('ul', {}, [
        el('li', { text: '予約番号は大文字・小文字を区別せず、0とO・1とlとIも同じものとして探します' }),
        el('li', { text: 'お名前は漢字でもフリガナでも探せます' }),
        el('li', { text: '電話番号は続けて4桁以上、メールは @ の前の部分で探せます' }),
        el('li', { text: '生年月日は「1958-11-03」「S33.11.3」「昭和33年11月3日」のどの形でも探せます' }),
        el('li', { text: '「佐藤 1958」のように空白で区切ると、両方に当てはまる予約に絞れます' }),
        el('li', { text: '会場は漢字がわからなくても、ひらがなで探せます' })
      ])
    ]);
  }
})();
