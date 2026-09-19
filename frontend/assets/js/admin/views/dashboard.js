/* ==========================================================================
   dashboard.js — A-01 대시보드 (현황 / 통계 탭 분리)
   --------------------------------------------------------------------------
   아침에 로그인해서 **가장 먼저 봐야 할 것만** 올린다.
   운영 현황과 검진 통계를 탭으로 분리하여 필요한 정보에 빠르게 접근하도록 함.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;
  var cachedHospitalsList = [];
  var currentSelectedHospId = '';
  // 통계 탭이 그려지면 「화면에서 고른 회장·기간」을 돌려주는 함수로 바뀐다.
  // 조회와 내보내기가 같은 조건을 쓰도록 바깥에 둔다.
  var statsParams = function () {
    return currentSelectedHospId ? ['hospital_id=' + currentSelectedHospId] : [];
  };

  function ensureHospitals() {
    if (cachedHospitalsList.length > 0) return Promise.resolve(cachedHospitalsList);
    // 会場一覧は **`/reservations/filters` から取得する。** 以前は L2 専用の
    // `/hospitals` を呼んでいたため、受付スタッフ(L1)には 403 となり、その
    // catch が空配列を返し、「今後の開催日程」が L1 には常に空に見えていた —
    // その日程を最も見るべき人に。filters は L1 も読め、ここで必要な
    // id・name・schedules(開催日)をそのまま含む。
    return A.api.get('/reservations/filters').then(function (res) {
      cachedHospitalsList = ((res.data || {}).hospitals) || [];
      return cachedHospitalsList;
    }).catch(function () {
      return [];
    });
  }

  function toHiragana(text) {
    return String(text || '').replace(/[ァ-ヶ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0x60);
    });
  }

  /* 회장 콤보의 검색 대상.
     --------------------------------------------------------------------
     읽기(후리가나)는 **서버가 준다** (`name_kana`). 예전에는 이 파일에
     회장 20곳의 읽기를 박아 두었는데, 담당자가 「회장 관리」 표에서 읽기를
     고쳐도 이 사본은 바뀌지 않았고 21번째 회장은 아예 찾을 수 없었다.

     콤보는 빠른 검색과 달리 지역·주소까지 훑는다. 여기서는 「이 근처 회장」을
     고르는 일이 잦기 때문이다. */
  function haystack(h) {
    return toHiragana([
      h.name, h.name_kana, h.code, h.region, h.area, h.city,
      h.address, h.tel, h.access_info, h.postal_code, h.event_date
    ].join(' ')).toLowerCase();
  }

  A.route('dashboard', function (view) {
    A.setTitle('ダッシュボード', '本日の対応事項および健診統計', [
      el('button.btn.btn--sm.btn--csv', {
        type: 'button',
        text: 'CSV 書き出し',
        title: '健診統計タブで選んだ会場・期間で、必要な表だけ書き出します。',
        onClick: openExportDialog
      }),
      el('button.btn.btn--sm', {
        type: 'button', text: '再読み込み',
        onClick: function () { A.render(); }
      })
    ]);

    /* 회장 목록을 **기다렸다가** 그린다.

       예전에는 ensureHospitals() 를 띄워 두고 곧바로 대시보드를 그렸다.
       두 요청이 경쟁하므로, 회장 목록이 늦게 오면 cachedHospitalsList 가
       아직 비어 있는 채로 화면이 그려진다. 그러면 오늘 개최가 없는 날
       「다가오는 개최 일정」이 통째로 빠지고 「예정된 검진 일정이 없습니다」가
       뜬다 — 실제로는 일정이 있는데도 없다고 말하는 셈이다.

       회장 목록은 실패해도 빈 배열을 돌려주므로(ensureHospitals 의 catch)
       이 기다림이 대시보드를 막지는 않는다. */
    Promise.all([ensureHospitals(), A.api.get('/dashboard')])
      .then(function (results) {
        var body = results[1];
        var dashData = (body && body.data) ? body.data : body;
        draw(view, dashData);
      })
      .catch(function (error) { A.fail(view, error); });
  });

  function draw(view, data) {
    A.clear(view);
    if (!data || !data.counters) {
      view.appendChild(A.notice('danger', 'ダッシュボードのデータを取得できませんでした。一覧を再読み込みしてください。'));
      return;
    }

    // --- 상단 카운터 카드 --------------------------------------------------
    var counters = el('div.counters');
    data.counters.forEach(function (counter) {
      var tone = counter.tone && counter.tone !== 'neutral'
        ? '.counter--' + counter.tone : '';

      var node = el(counter.link ? 'a.counter' + tone : 'div.counter' + tone,
        counter.link ? { href: counter.link } : {}, [
        el('p.counter__label', { text: counter.label }),
        el('p.counter__value', {}, [
          String(A.fmt.number(counter.value)),
          el('span.counter__unit', { text: counter.unit || '件' })
        ]),
        el('p.counter__hint', { text: counter.hint || '' })
      ]);

      counters.appendChild(node);
    });
    view.appendChild(counters);

    // --- 탭 메뉴 (현황 / 통계) ----------------------------------------------
    var tabNav = el('div.dash-tabs', {
      style: 'display:flex;gap:12px;margin:20px 0 16px;border-bottom:2px solid var(--a-line);padding-bottom:2px'
    });

    var btnStatus = el('button.dash-tab-btn.is-active', {
      type: 'button',
      style: 'padding:10px 20px;font-size:15px;font-weight:700;border:none;background:none;cursor:pointer;border-bottom:3px solid #0A3A31;margin-bottom:-4px;color:#0A3A31',
      text: '運営状況'
    });

    var btnStats = el('button.dash-tab-btn', {
      type: 'button',
      style: 'padding:10px 20px;font-size:15px;font-weight:700;border:none;background:none;cursor:pointer;color:var(--a-ink-sub);margin-bottom:-4px',
      text: '健診統計'
    });

    tabNav.appendChild(btnStatus);
    tabNav.appendChild(btnStats);
    view.appendChild(tabNav);

    var panelStatus = el('div.dash-panel', { style: 'display:block;' });
    var panelStats = el('div.dash-panel.is-hidden', { style: 'display:none;' });

    view.appendChild(panelStatus);
    view.appendChild(panelStats);

    btnStatus.addEventListener('click', function () {
      btnStatus.style.borderBottom = '3px solid #0A3A31';
      btnStatus.style.color = '#0A3A31';
      btnStats.style.borderBottom = 'none';
      btnStats.style.color = 'var(--a-ink-sub)';
      panelStatus.style.display = 'block';
      panelStats.style.display = 'none';
      panelStatus.classList.remove('is-hidden');
      panelStats.classList.add('is-hidden');
    });

    btnStats.addEventListener('click', function () {
      btnStats.style.borderBottom = '3px solid #0A3A31';
      btnStats.style.color = '#0A3A31';
      btnStatus.style.borderBottom = 'none';
      btnStatus.style.color = 'var(--a-ink-sub)';
      panelStats.style.display = 'block';
      panelStatus.style.display = 'none';
      panelStats.classList.remove('is-hidden');
      panelStatus.classList.add('is-hidden');
      // 숨겨진 채 그린 차트는 크기가 0 이었다. 보이게 된 지금 크기로 다시 그린다.
      // (ResizeObserver 는 화면이 그려지는 틈에만 알려 주므로 여기서 직접 부른다.)
      if (statsRedraw) statsRedraw();
    });

    // =========================================================================
    // 탭 1: 운영 현황 (Status View)
    // =========================================================================
    // 자동 삭제 안내는 매일 확인할 값이 아니라 참고 사항이라 맨 아래에 둔다.
    // 맨 위에 두면 「오늘 어떤 날인가」보다 먼저 읽히게 된다.
    var purgeNotice = A.notice('info',
      '受診時刻を過ぎた予約は ' + (data.purge_grace_minutes || 60) + '分後に自動的に削除されます。' +
      (data.purge_pending
        ? '現在削除待ちの予約が ' + data.purge_pending + '件あります。'
        : '現在削除待ちの予約はありません。')
    );


    /* ====================================================================
       오늘 검진 현황 — 회장별 가로 막대

       카드를 격자로 늘어놓으면 회장이 늘수록 아래로 길어지고, 회장끼리
       얼마나 찼는지 비교하기 어렵다. 막대를 같은 축에 세로로 쌓으면
       길이 차이가 그대로 비교가 된다.

       색은 초록 한 계열만 쓴다. 거의 찬 회장은 다른 색이 아니라
       **더 진한 초록**으로 구분한다. 색 수를 늘리면 통계 영역과 톤이 어긋난다.
       ==================================================================== */
    var todayRows = (data.today_rows && data.today_rows.length) ? data.today_rows : [];
    var gridContainer;

    if (todayRows.length) {
      gridContainer = el('div', { style: 'padding:14px 16px;' });

      var totalReserved = 0;
      todayRows.forEach(function (r) { totalReserved += (r.reserved || 0); });

      gridContainer.appendChild(el('p', {
        style: 'margin:0 0 12px;font-size:12.5px;color:var(--a-ink-sub);',
        text: A.fmt.dateShort(data.today) + ' · ' + todayRows.length + '会場 ・ '
          + totalReserved + '名'
      }));

      todayRows.forEach(function (r, index) {
        var hId = r.hospital_id || r.id;
        var name = r.hospital_name || r.name || '';
        var reserved = r.reserved || 0;
        var cap = r.capacity || 0;
        var pct = cap ? Math.min(100, Math.round((reserved / cap) * 100)) : 0;
        var nearlyFull = pct >= 90;

        gridContainer.appendChild(el('a', {
          href: '#/capacity?hospital_id=' + hId,
          style: 'display:flex;align-items:center;gap:10px;text-decoration:none;color:inherit;'
            + (index ? 'margin-top:9px;' : ''),
          title: name + ' — 定員カレンダーへ移動'
        }, [
          el('span', {
            style: 'flex:0 0 auto;width:150px;font-size:12.5px;color:var(--a-ink-sub);'
              + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
            text: name
          }),
          el('span', {
            style: 'flex:1;height:10px;background:var(--a-line-2);border-radius:999px;'
              + 'overflow:hidden;display:block;'
          }, el('span', {
            style: 'display:block;height:100%;width:' + pct + '%;'
              + 'background:' + (nearlyFull ? '#0A3A31' : '#0B6E5B') + ';'
          })),
          el('span', {
            style: 'flex:0 0 auto;width:64px;text-align:right;font-size:12px;'
              + 'font-variant-numeric:tabular-nums;'
              + (nearlyFull
                ? 'color:var(--a-ink);font-weight:700;'
                : 'color:var(--a-ink-sub);'),
            text: reserved + ' / ' + cap
          })
        ]));
      });

    } else {
      /* 오늘 여는 회장이 없을 때.
         회장 1곳이 1년에 하루만 열기 때문에 이 날이 훨씬 많다.
         「없다」로 끝내면 담당자가 달력을 따로 열어야 하므로
         다음 개최일을 같이 알려 준다. */
      gridContainer = el('div', { style: 'padding:16px;' }, [
        // 「없습니다」 옆에 0건을 붙인다. 개최일이 있는 날과 같은 자리에
        // 같은 형식으로 숫자가 서므로, 확인한 결과 0이라는 뜻이 된다.
        el('div', {
          style: 'display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:4px;'
        }, [
          el('span', { style: 'font-size:14px;font-weight:700;', text: '本日開催の会場はありません' }),
          el('span', {
            style: 'font-size:14px;font-weight:700;color:var(--a-ink-weak);'
              + 'font-variant-numeric:tabular-nums;',
            text: '0会場 ・ 0名'
          })
        ])
      ]);

      /* 다가오는 개최 일정.

         회장이 1년에 며칠만 열기 때문에 「오늘 없음」인 날이 훨씬 많다.
         「없습니다」로 끝내면 담당자가 회장 목록으로 가서 다시 찾아야 한다.
         지난 개최일은 뺀다 — 넣어 두면 맨 위가 늘 이미 끝난 회장이 된다. */
      // 회장이 아니라 **회차**를 늘어놓는다. 회장 단위로 세면 같은 회장이
      // 9월·11월·2월에 열어도 한 줄만 뜨고, 나머지 두 날은 화면 어디에도
      // 나오지 않는다. 담당자가 알아야 하는 것은 「다음에 무엇이 열리는가」다.
      // 「きょう」は日本標準時。世界標準時だと日本の午前0時〜9時のあいだ
      // 前日になり、すでに終わった昨日の回が先頭に残っていた。
      var todayIso = A.fmt.today();
      var upcoming = [];
      (cachedHospitalsList || []).forEach(function (h) {
        (h.schedules || []).forEach(function (s) {
          if (s.event_date >= todayIso) {
            upcoming.push({ id: h.id, name: h.name, event_date: s.event_date });
          }
        });
      });
      upcoming.sort(function (a, b) { return a.event_date < b.event_date ? -1 : 1; });
      upcoming = upcoming.slice(0, 4);

      if (upcoming.length) {
        gridContainer.appendChild(el('p.dim', {
          style: 'margin:0 0 8px;font-size:13px;',
          text: '今後の開催日程'
        }));

        upcoming.forEach(function (h, index) {
          gridContainer.appendChild(el('a', {
            href: '#/capacity?hospital_id=' + h.id
              + '&month=' + h.event_date.slice(0, 7)
              + '&date=' + h.event_date,
            style: 'display:flex;align-items:baseline;gap:12px;text-decoration:none;'
              + 'color:inherit;font-size:13.5px;padding:3px 0;'
              + (index ? 'border-top:1px solid var(--a-line-2);' : ''),
            title: h.name + ' ' + h.event_date + ' 開催回 — 定員カレンダーへ移動'
          }, [
            el('span', {
              style: 'flex:0 0 auto;width:78px;color:var(--a-ink-sub);'
                + 'font-variant-numeric:tabular-nums;',
              text: A.fmt.dateShort(h.event_date)
            }),
            el('span', {
              style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
              text: h.name
            })
          ]));
        });
      } else {
        gridContainer.appendChild(el('p.dim', {
          style: 'margin:0;font-size:13px;',
          text: '予定されている受診日程はありません。'
        }));
      }
    }

    var hospitalStatusCard = A.card('本日の健診状況', {
      desc: '会場をクリックすると定員カレンダーへ移動します。',
      flush: true,
      tools: [el('a.btn.btn--sm', { href: '#/capacity', text: 'すべて表示' })],
      body: gridContainer
    });

    panelStatus.appendChild(hospitalStatusCard);

    /* ====================================================================
       지금 처리할 일

       「대응이 필요한 예약」과 「메일 발송 실패」를 한 목록으로 세운다.
       담당자에게는 둘 다 그냥 할 일인데, 지금은 서로 다른 화면에 흩어져
       있어 두 군데를 따로 열어야 했다. 위쪽 지표 카드로도 갈 수 있지만
       그건 각각 다른 화면으로 가므로, 「오늘 손댈 게 뭔가」에 답하지 못한다.

       줄 세우는 기준은 접수 순서가 아니라 **검진일까지 남은 날**이다.
       검진일이 지나면 손쓸 수 없다 — 임시 접수인 채로 당일을 맞으면
       이용자가 헛걸음한다. 30건이 밀려 있어도 먼저 볼 것은 코앞인 건이다.

       화면에는 앞의 다섯 줄만 둔다. 개수가 늘어도 높이는 그대로다.
       ==================================================================== */
    var TODO_VISIBLE = 5;
    var URGENT_DAYS = 3;

    function daysUntil(iso) {
      if (!iso) return null;
      var parts = String(iso).split('-');
      if (parts.length !== 3) return null;
      var target = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
      var base = new Date();
      base.setHours(0, 0, 0, 0);
      return Math.round((target - base) / 86400000);
    }

    var todo = [];

    (data.attention || []).forEach(function (r) {
      // 배지에는 상태를, 본문에는 무엇이 빠졌는지를 적는다.
      // 「임시 (확인 필요)」만으로는 예약을 열어 봐야 이유를 알 수 있다.
      todo.push({
        kind: r.status,
        name: r.full_name,
        detail: A.fmt.dateShort(r.slot_date) + ' ' + (r.hospital_name || '')
          + (r.defect_note ? ' · ' + r.defect_note + ' 漏れ' : ''),
        slot_date: r.slot_date,
        go: function () { A.go('reservation', { id: r.id }); }
      });
    });

    /* 휴진으로 닫힌 날에 남아 있는 예약.
       -------------------------------------------------------------------
       마감해도 예약은 지워지지 않는다. 연락하지 않으면 그 사람들은 그 날
       그대로 회장에 온다. 검진일이 지나면 되돌릴 수 없는 일이라 「확인 필요」
       보다 급하고, 그래서 같은 목록에 섞어 **검진일 순으로** 세운다.

       누르면 예약 상세로 간다 — 거기서 전화번호를 보고 걸고, 새 날짜를
       합의하면 「검진일 변경」으로 옮긴다. 옮기는 순간 이 줄이 사라진다. */
    (data.holiday || []).forEach(function (r) {
      todo.push({
        kind: '休診連絡',
        name: r.full_name,
        detail: A.fmt.dateShort(r.slot_date) + ' ' + (r.hospital_name || '')
          + ' · ' + (r.tel || '連絡先なし'),
        slot_date: r.slot_date,
        go: function () { A.go('reservation', { id: r.id }); }
      });
    });

    (data.mail_failures || []).forEach(function (m) {
      todo.push({
        kind: 'メール再送',
        name: m.full_name || m.reservation_no,
        detail: (m.slot_date ? A.fmt.dateShort(m.slot_date) + ' ' : '')
          + m.to_email + ' · ' + (m.error_message || '送信失敗'),
        slot_date: m.slot_date,
        go: function () { A.go('mail-templates', { key: 'logs', status: 'FAILED' }); }
      });
    });

    // 검진일이 없는 건(예약이 이미 정리된 메일 실패 등)은 뒤로 보낸다.
    todo.sort(function (a, b) {
      var da = daysUntil(a.slot_date);
      var db_ = daysUntil(b.slot_date);
      if (da === null) return 1;
      if (db_ === null) return -1;
      return da - db_;
    });

    var todoTotal = (data.attention_total || 0)
      + (data.holiday_total || 0)
      + (data.mail_failed_total || 0);
    var todoCard = el('div.card', { style: 'padding:0;overflow:hidden;' });

    // 제목 줄에만 옅은 빨간 톤. 목록 본문까지 물들이면 급한 줄(D-1)이 묻힌다.
    var todoHead = el('div', {
      style: 'padding:13px 16px;border-bottom:1px solid var(--a-line-2);'
        + 'background:var(--a-danger-soft);'
        + 'display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;'
    }, [
      el('span', {
        style: 'font-size:17px;font-weight:700;color:var(--a-danger);',
        text: '要対応タスク'
      }),
      el('span', {
        style: 'font-size:13.5px;color:var(--a-ink-sub);',
        text: todoTotal + '件'
          + (data.holiday_total ? ' ・ 休診連絡 ' + data.holiday_total : '')
          + ' ・ 要確認 ' + (data.attention_total || 0)
          + ' ・ メール再送 ' + (data.mail_failed_total || 0)
      })
    ]);

    // 색은 급한 것에만 쓴다. 여기저기 쓰면 신호가 죽는다.
    var urgent = (data.urgent_total || 0) + (data.holiday_urgent_total || 0);
    if (urgent) {
      todoHead.appendChild(el('span', {
        style: 'margin-left:auto;font-size:13.5px;font-weight:700;color:var(--a-warn);',
        text: '受診日 ' + URGENT_DAYS + '日以内 ' + urgent + '件'
      }));
    }
    todoCard.appendChild(todoHead);

    if (!todo.length) {
      todoCard.appendChild(el('div', {
        style: 'padding:18px 16px;font-size:14px;color:var(--a-ink-sub);',
        text: '現在、対応が必要なタスクはありません。'
      }));
    } else {
      /* 남은 날에 따라 세 단계로 나눈다.

           지났거나 사흘 이내  빨강 — 놓치면 이용자가 헛걸음한다
           일주일 이내        주황 — 이번 주 안에 처리
           그 밖              회색 — 아직 시간이 있다

         전부 색을 칠하면 급한 줄이 묻히므로 마지막은 색을 빼 둔다. */
      function ddayStyle(left) {
        if (left === null) return 'background:var(--a-bg-sub);color:var(--a-ink-weak);';
        if (left <= URGENT_DAYS) return 'background:var(--a-danger-soft);color:var(--a-danger);';
        if (left <= 7) return 'background:var(--a-warn-soft);color:var(--a-warn);';
        return 'background:var(--a-bg-sub);color:var(--a-ink-sub);';
      }

      // 할 일 종류. 확인 전화는 사람에게 거는 일, 메일 재발송은 시스템 조작이라
      // 손이 가는 곳이 다르다. 색으로 나눠 두면 목록에서 골라 처리하기 쉽다.
      // 키는 서버가 보내는 문자열과 **한 글자도 다르면 안 된다.**
      // 예전에는 여기만 전각 괄호(仮（要確認）)로 적혀 있었는데 서버가 보내는
      // 값은 반각에 앞 공백이 붙은 「仮 (要確認)」이라, 색을 찾지 못해
      // 이 줄만 배경 없이 나왔다. 休診連絡·メール再送 는 우연히 맞아 있었다.
      // 라벨은 backend/app/services/admin_reservation_service.py 의
      // STATUS_LABELS 가 정한다.
      var KIND_STYLE = {
        '仮受付（要確認）': 'background:var(--a-warn-soft);color:var(--a-warn);',
        '仮（要確認）': 'background:var(--a-warn-soft);color:var(--a-warn);',
        'メール再送': 'background:var(--a-info-soft);color:var(--a-info);',
        // 휴진 연락만 빨강이다. 나머지는 늦어도 당일에 채우면 되지만,
        // 이쪽은 검진일이 지나면 그 사람이 이미 헛걸음한 뒤다.
        '休診連絡': 'background:var(--a-danger-soft);color:var(--a-danger);'
      };

      /** 할 일 한 줄. 접힌 줄과 펼친 줄이 같아야 하므로 함수로 뽑았다. */
      function todoRow(item, index) {
        var left = daysUntil(item.slot_date);

        return el('div', {
          style: 'display:flex;align-items:center;gap:12px;padding:11px 16px;cursor:pointer;'
            + (index ? 'border-top:1px solid var(--a-line-2);' : ''),
          onClick: item.go
        }, [
          el('span', {
            style: 'flex:0 0 auto;font-size:12px;font-weight:700;padding:3px 9px;'
              + 'border-radius:999px;font-variant-numeric:tabular-nums;'
              + ddayStyle(left),
            text: left === null ? '—' : (left < 0 ? '超過' : 'D-' + left)
          }),
          el('span', {
            style: 'flex:0 0 auto;font-size:12px;font-weight:700;padding:3px 10px;'
              + 'border-radius:999px;white-space:nowrap;'
              + (KIND_STYLE[item.kind] || 'background:var(--a-bg-sub);color:var(--a-ink-sub);'),
            text: item.kind
          }),
          el('span', { style: 'flex:0 0 auto;font-size:14px;', text: item.name }),
          el('span', {
            style: 'font-size:13.5px;color:var(--a-ink-weak);overflow:hidden;'
              + 'text-overflow:ellipsis;white-space:nowrap;',
            text: item.detail
          }),
          // 누를 수 있다는 표시. 줄 전체가 링크라 커서만으로는 알기 어렵다.
          el('span', {
            style: 'margin-left:auto;flex:0 0 auto;color:var(--a-ink-weak);'
              + 'font-size:15px;line-height:1;',
            text: '›'
          })
        ]);
      }

      var todoList = el('div');
      todo.slice(0, TODO_VISIBLE).forEach(function (item, index) {
        todoList.appendChild(todoRow(item, index));
      });
      todoCard.appendChild(todoList);

      /* 「나머지 N건」은 여기서 아래로 펼친다.
         -----------------------------------------------------------------
         전에는 예약 검색으로 넘어갔는데, 이 목록은 확인 필요·휴진 연락·
         메일 재발송이 섞여 있어서 예약 검색의 어떤 필터로도 그대로 재현되지
         않았다. 다섯 줄 더 보려고 화면을 떠나는 것도 손해다.

         받아 온 것보다 실제 건수가 많을 수 있다(서버가 종류별로 잘라서 준다).
         그럴 때는 다 펼친 뒤 남는 수를 알려 주고 예약 검색으로 안내한다. */
      var hidden = todo.length - TODO_VISIBLE;
      if (hidden > 0) {
        var expanded = false;
        var moreBox = el('div');
        var moreBtn = el('button', {
          type: 'button',
          style: 'display:block;width:100%;border:0;border-top:1px solid var(--a-line-2);'
            + 'padding:11px;font-size:13.5px;text-align:center;cursor:pointer;'
            + 'background:var(--a-bg-sub);color:var(--a-ink-sub);font-family:inherit;',
          text: '残り ' + hidden + '件を表示',
          onClick: function () {
            expanded = !expanded;
            if (expanded) {
              todo.slice(TODO_VISIBLE).forEach(function (item, i) {
                moreBox.appendChild(todoRow(item, TODO_VISIBLE + i));
              });
              moreBtn.textContent = '折りたたむ';
            } else {
              moreBox.innerHTML = '';
              moreBtn.textContent = '残り ' + hidden + '件を表示';
            }
          }
        });
        todoCard.appendChild(moreBox);
        todoCard.appendChild(moreBtn);
      }

      // 서버가 종류별로 잘라 보낸 탓에 화면에 못 담은 건이 남았을 때만.
      if (todoTotal > todo.length) {
        todoCard.appendChild(el('a', {
          href: '#/reservations',
          style: 'display:block;padding:9px;font-size:12.5px;text-align:center;'
            + 'border-top:1px solid var(--a-line-2);'
            + 'background:var(--a-bg-sub);color:var(--a-ink-weak);text-decoration:none;',
          text: 'このほかに ' + (todoTotal - todo.length) + '件あります › 予約検索で確認'
        }));
      }
    }

    panelStatus.appendChild(todoCard);

    // 최근 접수
    /* 최근 접수 — 표가 아니라 줄로 그린다.

       열이 넷뿐이라 회색 머리글 줄이 없어도 무엇인지 읽힌다.
       머리글을 빼면 「지금 처리할 일」과 결이 맞고 높이도 한 줄 줄어든다.
       여기는 훑어보는 참고 정보라 위쪽 두 영역보다 조용해야 한다. */
    /** 접수 시각의 시:분. 「최근」 목록에서는 몇 시에 들어왔는지가 의미 있다. */
    function hhmm(iso) {
      var d = new Date(iso);
      if (isNaN(d)) return '';
      return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    }

    var right = el('div');
    var recentBox = el('div', { style: 'padding:0 0 6px;' });
    var recentRows = data.recent || [];

    /* 열 이름 줄.

       머리글 없이 값만 늘어놓으니 오른쪽 날짜가 검진일로 읽혔다.
       이 목록은 「최근 접수」이므로 그 날짜는 **접수한 시각**이다.
       회색 표 머리글까지는 필요 없고, 옅은 글자 한 줄이면 충분하다. */
    if (recentRows.length) {
      recentBox.appendChild(el('div', {
        style: 'display:flex;align-items:center;gap:20px;padding:7px 16px;'
          + 'font-size:12px;color:var(--a-ink-weak);'
          + 'border-bottom:1px solid var(--a-line-2);'
      }, [
        el('span', { style: 'flex:0 0 auto;width:132px;', text: '予約番号' }),
        el('span', { style: 'flex:0 0 auto;width:110px;', text: 'お名前' }),
        el('span', { style: 'flex:0 0 auto;width:52px;', text: '経路' }),
        el('span', { style: 'flex:0 0 auto;', text: '連絡先' }),
        el('span', { style: 'margin-left:auto;flex:0 0 auto;', text: '受付日時' })
      ]));
    }

    if (!recentRows.length) {
      recentBox.appendChild(el('p.dim', {
        style: 'margin:0;padding:14px 16px;font-size:14px;',
        text: '受付済みの予約はありません。'
      }));
    } else {
      recentRows.forEach(function (r) {
        var isPostal = r.channel_code === 'POSTAL';
        // 글자 크기는 검진 통계 영역의 주력(14px)에 맞춘다.
        // 탭을 오갈 때 글자가 줄었다 늘었다 하면 같은 화면으로 안 읽힌다.
        /* 열을 고정 폭으로 잡아 줄마다 세로로 맞춘다.
           flex 로 흘려보내면 이름 길이에 따라 뒤쪽이 들쭉날쭉해진다.
           전화번호를 넣은 이유는, 이 시스템의 주 업무가 전화 응대이기
           때문이다. 예약을 열지 않고도 목록에서 바로 걸 수 있다. */
        recentBox.appendChild(el('div', {
          style: 'display:flex;align-items:center;gap:20px;padding:8px 16px;'
            + 'font-size:14px;cursor:pointer;',
          onClick: function () { A.go('reservation', { id: r.id }); }
        }, [
          el('span.mono', {
            style: 'flex:0 0 auto;width:132px;font-size:13px;color:var(--a-ink-weak);',
            text: r.reservation_no
          }),
          el('span', {
            style: 'flex:0 0 auto;width:110px;overflow:hidden;'
              + 'text-overflow:ellipsis;white-space:nowrap;',
            text: r.full_name
          }),
          el('span', { style: 'flex:0 0 auto;width:52px;' }, el('span.badge', {
            style: (isPostal
              ? 'background:var(--a-ok-soft);color:var(--a-ok);'
              : 'background:var(--a-info-soft);color:var(--a-info);')
              + 'font-weight:700;padding:2px 10px;font-size:12px;',
            text: r.channel
          })),
          el('span.mono', {
            style: 'flex:0 0 auto;font-size:13.5px;color:var(--a-ink-sub);'
              + 'font-variant-numeric:tabular-nums;',
            text: r.tel || '—'
          }),
          el('span', {
            style: 'margin-left:auto;flex:0 0 auto;font-size:13.5px;'
              + 'color:var(--a-ink-sub);font-variant-numeric:tabular-nums;',
            text: A.fmt.dateShort(r.created_at) + ' ' + hhmm(r.created_at)
          })
        ]));
      });
    }

    right.appendChild(A.card('直近の受付', {
      desc: 'Webと郵送を合わせた直近10件',
      flush: true,
      tools: [el('a.btn.btn--sm', { href: '#/reservations', text: 'すべて表示' })],
      body: recentBox
    }));

    // 위 두 영역과 같은 폭으로 둔다. 예전 2열 격자(.dash-cols)는
    // 「대응이 필요한 예약」과 짝일 때 쓰던 것이라 이제 필요 없다.
    panelStatus.appendChild(right);
    panelStatus.appendChild(purgeNotice);

    // =========================================================================
    // 탭 2: 검진 통계 (Statistics View)
    // =========================================================================
    renderStatsPanel(panelStats, data);
  }

  function renderStatsPanel(panelStats, data) {
    A.clear(panelStats);

    // --- 1. 필터 바 (일별 / 주차별 / 월별 선택에 따른 가변 컨트롤 수평 일자 배치) ------
    var filterCard = el('div.card', { style: 'margin-bottom:20px;padding:16px;' });
    var filterRow = el('div', { style: 'display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between;' });

    var leftFilter = el('div', { style: 'display:flex;flex-wrap:wrap;gap:16px;align-items:center;' });

    // 필터 단위 선택 버튼 (일별 / 주차별 / 월별)
    var activePeriod = 'day'; // 'day', 'week', 'month'

    var btnDay = el('button.btn.btn--sm', {
      type: 'button',
      style: 'background:#0A3A31;color:#fff;font-weight:700;',
      text: '日別'
    });
    var btnWeek = el('button.btn.btn--sm', {
      type: 'button',
      style: 'background:none;border:none;color:var(--a-ink-sub);',
      text: '週別'
    });
    var btnMonth = el('button.btn.btn--sm', {
      type: 'button',
      style: 'background:none;border:none;color:var(--a-ink-sub);',
      text: '月別'
    });

    var periodGroup = el('div.btn-group', { style: 'display:inline-flex;gap:4px;background:var(--a-surface-sub);padding:3px;border-radius:6px;' }, [
      btnDay, btnWeek, btnMonth
    ]);

    leftFilter.appendChild(periodGroup);

    // ① 일별 컨테이너 (단일 날짜 선택)
    var dayInput = A.input({
      type: 'date',
      value: data.target_date || A.fmt.today(),
      style: 'width:150px;padding:6px 12px;border:1px solid var(--a-line);border-radius:6px;font-size:14px;font-family:var(--font-base);'
    });
    var dayContainer = el('div', { style: 'display:flex;align-items:center;gap:8px;white-space:nowrap;flex-shrink:0;' }, [
      el('label', { style: 'font-weight:700;font-size:14px;white-space:nowrap;flex-shrink:0;', text: '申込日:' }),
      dayInput
    ]);

    // ② 주차별 컨테이너 (며칠부터 며칠까지 범위 선택)
    // 日本標準時の「きょう」を起点に、その週の月曜〜日曜を出す。
    // 日付は文字列のまま足し引きするので、時差が入る余地がない。
    var todayIsoForWeek = A.fmt.today();
    var dayOfWeek = A.fmt.weekdayOf(todayIsoForWeek);
    var mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
    var mondayIso = A.fmt.shiftDate(todayIsoForWeek, mondayOffset);
    var sundayIso = A.fmt.shiftDate(mondayIso, 6);

    var weekStartInput = A.input({
      type: 'date',
      value: mondayIso,
      style: 'width:150px;padding:6px 12px;border:1px solid var(--a-line);border-radius:6px;font-size:14px;font-family:var(--font-base);'
    });
    var weekEndInput = A.input({
      type: 'date',
      value: sundayIso,
      style: 'width:150px;padding:6px 12px;border:1px solid var(--a-line);border-radius:6px;font-size:14px;font-family:var(--font-base);'
    });

    var weekContainer = el('div', { style: 'display:none;align-items:center;gap:8px;white-space:nowrap;flex-shrink:0;' }, [
      el('label', { style: 'font-weight:700;font-size:14px;white-space:nowrap;flex-shrink:0;', text: '申込期間:' }),
      weekStartInput,
      el('span', { style: 'color:var(--a-ink-sub);font-weight:700;', text: '~' }),
      weekEndInput
    ]);

    // ③ 월별 컨테이너 (년도와 월 선택)
    // 연·월 선택지는 **오늘**에서 만든다. 예전에는 2025~2027년 · 8월이 박혀 있어
    // 「月別」을 누르면 늘 지난달(0건)이 떴고, 2028년이 되면 고를 해가 없었다.
    var now = new Date();
    var thisYear = now.getFullYear();
    var thisMonth = now.getMonth() + 1;
    var yearOptions = [];
    for (var y = thisYear - 2; y <= thisYear + 1; y++) {
      yearOptions.push(el('option', { value: String(y), text: y + '年', selected: y === thisYear }));
    }
    var yearSelect = el('select.input', { style: 'padding:6px 12px;border-radius:6px;font-size:13px;' }, yearOptions);
    var monthOptions = [el('option', { value: '', text: 'すべての月（年間）' })];
    for (var m = 1; m <= 12; m++) {
      monthOptions.push(el('option', { value: String(m), text: m + '月', selected: m === thisMonth }));
    }
    var monthSelect = el('select.input', { style: 'padding:6px 12px;border-radius:6px;font-size:13px;' }, monthOptions);

    var monthContainer = el('div', { style: 'display:none;align-items:center;gap:8px;white-space:nowrap;flex-shrink:0;' }, [
      el('label', { style: 'font-weight:700;font-size:14px;white-space:nowrap;flex-shrink:0;', text: '申込年月:' }),
      yearSelect,
      monthSelect
    ]);

    leftFilter.appendChild(dayContainer);
    leftFilter.appendChild(weekContainer);
    leftFilter.appendChild(monthContainer);

    /* 날짜의 뜻을 화면에 적어 둔다.

       이 화면의 통계는 「그 날 신청을 받은 건」을 센다. 「그 날 검진을 받는 건」이
       아니다. 라벨이 「기준 날짜」였을 때는 둘 중 어느 쪽인지 알 수 없어,
       9월 9일 회장에 몇 분이 오시는지 보려고 9월 9일을 골랐다가 엉뚱한
       숫자를 읽을 수 있었다. 세는 기준은 화면에 적혀 있어야 한다. */
    // 같은 줄에 두면(nowrap) 줄이 넘쳐 오른쪽 회장 선택이 다음 줄로 밀렸다.
    // 필터 줄 아래 한 줄로 내려, 화면 폭과 상관없이 자리를 다투지 않게 한다.
    // 書き出し 버튼은 화면 오른쪽 위(제목 줄)에 있어 이 조건 줄과 떨어져 있다.
    // 「어디서 출력하나」를 조건 바로 아래에서 안내한다.
    var basisNote = el('div', { style: 'margin:8px 0 0;font-size:12.5px;line-height:1.7;color:var(--a-ink-weak);' }, [
      el('p', { style: 'margin:0;', text: '※ 受診日ではなく、予約を受け付けた日付が基準です。' }),
      el('p', { style: 'margin:0;', text: '※ CSVは右上の「CSV 書き出し」から、選んだ期間・会場のまま出力できます。' })
    ]);

    function setPeriodMode(mode) {
      activePeriod = mode;
      btnDay.style.cssText = mode === 'day' ? 'background:#0A3A31;color:#fff;font-weight:700;' : 'background:none;border:none;color:var(--a-ink-sub);';
      btnWeek.style.cssText = mode === 'week' ? 'background:#0A3A31;color:#fff;font-weight:700;' : 'background:none;border:none;color:var(--a-ink-sub);';
      btnMonth.style.cssText = mode === 'month' ? 'background:#0A3A31;color:#fff;font-weight:700;' : 'background:none;border:none;color:var(--a-ink-sub);';

      dayContainer.style.display = mode === 'day' ? 'flex' : 'none';
      weekContainer.style.display = mode === 'week' ? 'flex' : 'none';
      monthContainer.style.display = mode === 'month' ? 'flex' : 'none';

      updateStatsView();
    }

    btnDay.addEventListener('click', function () { setPeriodMode('day'); });
    btnWeek.addEventListener('click', function () { setPeriodMode('week'); });
    btnMonth.addEventListener('click', function () { setPeriodMode('month'); });

    dayInput.addEventListener('change', updateStatsView);
    weekStartInput.addEventListener('change', function () {
      // 6日後を文字列のまま出す。Date に載せると時差でずれることがある。
      var end = A.fmt.shiftDate(weekStartInput.value, 6);
      if (end) weekEndInput.value = end;
      updateStatsView();
    });
    weekEndInput.addEventListener('change', updateStatsView);
    yearSelect.addEventListener('change', updateStatsView);
    monthSelect.addEventListener('change', updateStatsView);

    var rightFilter = el('div', { style: 'display:flex;gap:12px;align-items:center;margin-left:auto;flex-shrink:0;' });

    var comboWrap = el('div', { style: 'position:relative;width:240px;' });
    var comboInput = el('input.input', {
      type: 'text',
      placeholder: '会場検索（ひらがな対応）',
      value: '全会場（20か所）',
      autocomplete: 'off',
      style: 'width:100%;padding:6px 28px 6px 12px;border-radius:6px;font-size:14px;font-weight:600;'
    });
    var comboArrow = el('span', {
      style: 'position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;color:#64748B;font-size:12px;padding:4px;',
      text: '▾'
    });
    var comboDropdown = el('div', {
      style: 'position:absolute;top:calc(100% + 4px);left:0;right:0;background:#ffffff;border:1.5px solid #CBD5E1;border-radius:8px;max-height:240px;overflow-y:auto;z-index:200;box-shadow:0 4px 12px rgba(0,0,0,0.12);display:none;'
    });

    comboWrap.appendChild(comboInput);
    comboWrap.appendChild(comboArrow);
    comboWrap.appendChild(comboDropdown);

    function renderComboItems(filterText) {
      comboDropdown.innerHTML = '';
      var selObj = (cachedHospitalsList || []).filter(function (h) { return String(h.id) === String(currentSelectedHospId); })[0];
      var query = toHiragana(filterText || '').trim().toLowerCase();

      // 이미 선택된 회장 이름과 동일할 경우, 검색어를 비워 전체 20개 회장 목록을 모두 보여준다.
      if (selObj && query === toHiragana(selObj.name).trim().toLowerCase()) {
        query = '';
      }

      var countText = (cachedHospitalsList && cachedHospitalsList.length) ? ('（' + cachedHospitalsList.length + 'か所）') : '';
      var allOption = { id: '', name: '全会場' + countText, code: '' };
      var allList = [allOption].concat(cachedHospitalsList || []);

      var matched = allList.filter(function (h) {
        if (!query) return true;
        if (!h.id) return '全会場'.indexOf(query) !== -1 || 'ぜんたい'.indexOf(query) !== -1;
        return haystack(h).indexOf(query) !== -1;
      });

      if (!matched.length) {
        comboDropdown.appendChild(el('div', {
          style: 'padding:10px 12px;color:#94A3B8;font-size:13px;',
          text: '検索結果がありません。'
        }));
      } else {
        matched.forEach(function (h) {
          var isSelected = String(h.id) === String(currentSelectedHospId);
          var itemNode = el('div', {
            style: 'padding:8px 12px;font-size:13.5px;cursor:pointer;background:' + (isSelected ? '#F0FDF4' : '#fff') + ';color:' + (isSelected ? '#0B6E5B' : '#1E293B') + ';font-weight:' + (isSelected ? '700' : '500') + ';border-bottom:1px solid #F1F5F9;',
            text: h.name
          });

          itemNode.addEventListener('mouseenter', function () {
            if (!isSelected) itemNode.style.background = '#F8FAFC';
          });
          itemNode.addEventListener('mouseleave', function () {
            if (!isSelected) itemNode.style.background = '#fff';
          });

          itemNode.addEventListener('mousedown', function (ev) {
            ev.preventDefault();
            currentSelectedHospId = String(h.id);
            comboInput.value = h.name;
            comboDropdown.style.display = 'none';
            updateStatsView();
          });

          comboDropdown.appendChild(itemNode);
        });
      }
    }

    function openDropdown() {
      comboInput.select();
      renderComboItems('');
      comboDropdown.style.display = 'block';
    }

    comboInput.addEventListener('focus', openDropdown);
    comboInput.addEventListener('click', openDropdown);

    comboArrow.addEventListener('mousedown', function (ev) {
      ev.preventDefault();
      if (comboDropdown.style.display === 'block') {
        comboDropdown.style.display = 'none';
      } else {
        comboInput.focus();
        openDropdown();
      }
    });

    comboInput.addEventListener('input', function () {
      renderComboItems(comboInput.value);
      comboDropdown.style.display = 'block';
    });

    comboInput.addEventListener('blur', function () {
      setTimeout(function () {
        comboDropdown.style.display = 'none';
        var selObj = (cachedHospitalsList || []).filter(function (h) { return String(h.id) === String(currentSelectedHospId); })[0];
        var countText = (cachedHospitalsList && cachedHospitalsList.length) ? ('（' + cachedHospitalsList.length + 'か所）') : '';
        comboInput.value = selObj ? selObj.name : ('全会場' + countText);
      }, 200);
    });

    rightFilter.appendChild(comboWrap);


    filterRow.appendChild(leftFilter);
    filterRow.appendChild(rightFilter);
    filterCard.appendChild(filterRow);
    filterCard.appendChild(basisNote);
    panelStats.appendChild(filterCard);

    var statsContainer = el('div');
    panelStats.appendChild(statsContainer);
    // システムの状態 — 메일 실적이 위에서 고른 기간을 따르므로 통계와 함께 다시 그린다.
    var sysContainer = el('div');
    panelStats.appendChild(sysContainer);

    statsParams = function () {
      var params = [];
      if (currentSelectedHospId) params.push('hospital_id=' + currentSelectedHospId);
      if (activePeriod === 'day' && dayInput.value) {
        params.push('date=' + dayInput.value);
      } else if (activePeriod === 'week' && weekStartInput.value) {
        params.push('week_start=' + weekStartInput.value);
        if (weekEndInput.value) params.push('week_end=' + weekEndInput.value);
      } else if (activePeriod === 'month') {
        if (yearSelect.value) params.push('year=' + yearSelect.value);
        if (monthSelect.value) params.push('month=' + monthSelect.value);
      }
      return params;
    };

    function updateStatsView() {
      A.clear(statsContainer);

      var selectedHospId = currentSelectedHospId;
      var selectedHospObj = (cachedHospitalsList || []).filter(function (h) { return String(h.id) === selectedHospId; })[0];
      var hospName = selectedHospObj ? selectedHospObj.name : '全会場';

      // 로딩 뱃지 안내
      var loadingNode = A.notice('info', hospName + ' の統計を集計中です…');
      statsContainer.appendChild(loadingNode);

      var params = statsParams();

      var apiUrl = '/dashboard' + (params.length ? '?' + params.join('&') : '');
      A.api.get(apiUrl).then(function (body) {
        A.clear(statsContainer);
        var apiData = (body && body.data) ? body.data : body;

        var gStats = apiData.gender_stats || { male: 0, female: 0, age_buckets: [] };
        var cStats = apiData.channel_stats || {};
        var sStats = apiData.status_stats || {};
        var series = apiData.stats_series || { kind: 'day', label: '日別', points: [] };
        var total = sStats.total || 0;
        var cancelled = sStats.cancelled || 0;
        var periodText = statsPeriodText(series);
        renderSystemCard(apiData, periodText, series);

        // 비율(%)은 화면에 두지 않는다. 항목이 2~3개라 건수가 더 빨리 읽히고,
        // 비율이 필요하면 CSV 書き出し의 割合(%) 열에 있다.
        function kvItem(color, label, value) {
          return el('span', null, [
            el('span.stats-sw', { style: 'background:' + color }),
            label,
            el('b', { className: value ? '' : 'is-zero', text: String(value) })
          ]);
        }
        function kvRow(label, items) {
          return el('div.stats-kv', null, [el('span.stats-kv__k', { text: label }), el('div.stats-kv__v', null, items)]);
        }

        // 통계에서는 「キャンセル」 한 덩어리를 쓰지 않는다. 事前·当日 로 나눠 센다.
        // 이 구분이 생기기 전에 취소된 건이 있으면, 합이 맞도록 그때만 한 칸 더 보여준다.
        var cancelAdvance = sStats.cancelled_advance || 0;
        var cancelSameDay = sStats.cancelled_same_day || 0;
        var cancelUnknown = cancelled - cancelAdvance - cancelSameDay;
        // 행마다 **새 노드**를 만든다. 같은 DOM 노드를 두 행에 append 하면
        // 뒤의 행으로 옮겨 가 버려, 「受付経路」 행에서 취소가 사라졌다.
        function cancelItems() {
          var items = [
            kvItem('#7A8785', '事前キャンセル', cancelAdvance),
            kvItem('#B54708', '当日キャンセル', cancelSameDay)
          ];
          if (cancelUnknown > 0) {
            items.push(kvItem('#C9D5D2', 'キャンセル（種類なし）', cancelUnknown));
          }
          return items;
        }

        // ① 申込の概要 — 합계와 곡선(왼쪽), 숫자(오른쪽)
        var curveSvg = svgEl(null, 'svg', { 'class': 'stats-curve', viewBox: '0 0 600 140', role: 'img', 'aria-label': series.label + 'の申込件数' });
        drawStatsCurve(curveSvg, series, total);

        statsContainer.appendChild(el('div.card.stats-overview', null, [
          el('div.stats-overview__left', null, [
            el('h3.stats-h', null, ['申込の概要', el('small', { text: hospName + '・申込日基準' })]),
            el('div.stats-big', null, [
              el('b', { text: String(total) }),
              el('span.u', { text: '件' }),
              el('span.h', { text: (periodText ? periodText + ' の申込' : '申込') + '（キャンセル含む）' })
            ]),
            total ? null : el('div.stats-empty', { text: 'この期間・会場の申込はありません。' }),
            el('div.stats-curve-head', null, [el('span', { text: series.label + 'の申込件数' }), el('span', { text: '件' })]),
            curveSvg
          ]),
          el('div.stats-overview__right', null, [
            kvRow('受付経路', [
              kvItem('#0E7490', 'Web', (cStats.web || 0) - (cStats.web_cancelled || 0)),
              kvItem('#B54708', '郵送', (cStats.postal || 0) - (cStats.postal_cancelled || 0))
            ].concat(cancelItems())),
            kvRow('予約ステータス', [
              kvItem('#0B6E5B', '予約確定', sStats.confirmed || 0),
              kvItem('#D97706', '仮受付（要確認）', sStats.pending || 0)
            ].concat(cancelItems())),
            kvRow('男女', [
              kvItem('#1565C0', '男性', gStats.male || 0),
              kvItem('#E91E63', '女性', gStats.female || 0)
            ])
          ])
        ]));

        // ② 年代別・男女別(세로 묶음 막대) + オプション検査(표 + 얇은 막대)
        var ageBuckets = (gStats.age_buckets && gStats.age_buckets.length) ? gStats.age_buckets : [
          { label: '40代', male: 0, female: 0 },
          { label: '50代', male: 0, female: 0 },
          { label: '60代', male: 0, female: 0 },
          { label: '70代以上', male: 0, female: 0 }
        ];
        var colsBox = el('div.stats-cols-box');
        var colsSvg = svgEl(colsBox, 'svg', { role: 'img', 'aria-label': '年代別・男女別の人数' });
        var drawCols = function () { drawAgeColumns(colsSvg, colsBox, ageBuckets); };

        var optList = el('div.stats-opts');
        var rawOptions = apiData.options || [];
        rawOptions.forEach(function (o) {
          var n = o.count || 0;
          // 막대 칸 전체 = 신청 전체(100%). 가장 큰 값에 맞춰 늘리면 20% 가 절반 넘게 보인다.
          var w = total ? Math.min(100, n * 100 / total) : 0;
          optList.appendChild(el('span.stats-opts__name', { text: o.name }));
          optList.appendChild(el('span.stats-opts__bar', { title: o.name + ' ' + n + '件' }, [
            el('span', null, [el('i', { style: 'width:' + w + '%' })])
          ]));
          optList.appendChild(el('span.stats-opts__n' + (n ? '' : '.is-zero'), { text: n + '件' }));
        });
        optList.appendChild(el('span.stats-opts__blank'));
        optList.appendChild(el('span.stats-opts__foot', null, [el('span', { text: '0' }), el('span', { text: '50' }), el('span', { text: '100%' })]));
        optList.appendChild(el('span.stats-opts__blank'));

        statsContainer.appendChild(el('div.stats-row', null, [
          el('div.card', null, [
            el('h3.stats-h', null, [
              '年代別・男女別',
              el('small', { text: '人数' }),
              el('span.stats-legend', null, [
                el('span', null, [el('span.stats-sw', { style: 'background:#1565C0' }), '男性']),
                el('span', null, [el('span.stats-sw', { style: 'background:#E91E63' }), '女性'])
              ])
            ]),
            colsBox
          ]),
          el('div.card', null, [
            el('h3.stats-h', null, ['オプション検査', el('small', { text: '申込 ' + total + '件のうち' })]),
            rawOptions.length ? optList : el('div.stats-empty', { text: 'オプション検査が登録されていません。' })
          ])
        ]));

        // 차트는 옆 카드 높이에 맞춰 늘어나므로 상자 크기가 정해진 뒤에 그린다.
        // 탭이 숨겨진 채 그려지면 크기가 0 이라, 보이는 순간 다시 그린다.
        if (statsResizeObserver) statsResizeObserver.disconnect();
        if (window.ResizeObserver) {
          statsResizeObserver = new ResizeObserver(drawCols);
          statsResizeObserver.observe(colsBox);
        }
        statsRedraw = drawCols;
        drawCols();
      }).catch(function (err) {
        A.clear(statsContainer);
        statsContainer.appendChild(A.notice('danger', '統計データを取得できませんでした: ' + err.message));
        renderSystemCard({}, '');
      });
    }

    // Initial render
    updateStatsView();

    // --- 4. システムの状態 --------------------------------------------------
    // 「괜찮은지」가 먼저 보이게 상태 표시를 두고, 숫자는 그 옆에 적는다.
    // SKIPPED(메일 미설정으로 보내지 않음)는 실패가 아니므로 따로 센다.
    // 메일 실적은 健診統計에서 고른 기간(日別·週別·月別)을 따른다. 자동 삭제는
    // 기간과 상관없는 「지금」의 값이다.
    function renderSystemCard(d, periodText, series) {
      A.clear(sysContainer);
      var mailOk = d.mail_period_success || 0;
      var mailNg = d.mail_period_failed || 0;
      var mailSkip = d.mail_period_skipped || 0;
      var mailPill = mailNg
        ? el('a.stats-pill.is-danger', { href: '#/mail-templates?key=logs&status=FAILED', text: '失敗 ' + mailNg + '件' })
        : el('span.stats-pill' + (mailSkip && !mailOk ? '.is-warn' : mailOk ? '.is-ok' : '.is-muted'), {
          text: mailSkip && !mailOk ? 'メール未設定' : mailOk ? '正常' : '送信なし'
        });
      var mailHint = mailNg
        ? '「失敗」を押すと送信に失敗したメールの一覧を開きます。'
        : (mailSkip && !mailOk ? 'メール送信が設定されていないため送信していません。' : '予約受付・リマインドなどの自動メール（全会場・送信日時基準）');

      var purgePending = data.purge_pending || 0;
      // 기간 안에 지워진 건수. 무엇이 지워졌는지는 조작 로그에 남아 있으므로 그 목록으로 잇는다.
      var purgeDeleted = d.purge_period_deleted || 0;
      var purgeLink = series && series.start
        ? '#/audit-logs?action=RESERVATION_PURGE&from=' + series.start + '&to=' + series.end
        : '';
      sysContainer.appendChild(el('div.card.stats-sys-card', null, [
        el('h3.stats-h', { text: 'システムの状態' }),
        el('div.stats-sys', null, [
          el('div', null, [
            el('span.stats-sys__k', { text: 'メール送信（' + (periodText || '直近24時間') + '）' }),
            mailPill,
            el('span.stats-sys__v', null, ['成功', el('b', { text: String(mailOk) }), '　失敗', el('b', { text: String(mailNg) }), '　未設定', el('b', { text: String(mailSkip) })]),
            el('span.stats-sys__h', { text: mailHint })
          ]),
          el('div', null, [
            el('span.stats-sys__k', { text: '自動削除（' + (periodText || '直近24時間') + '）' }),
            purgeDeleted && purgeLink
              ? el('a.stats-pill.is-muted', { href: purgeLink, text: '削除 ' + purgeDeleted + '件' })
              : el('span.stats-pill.is-ok', { text: '削除なし' }),
            el('span.stats-sys__v', null, [
              '削除', el('b', { text: String(purgeDeleted) }), '件',
              '　現在の削除待ち', el('b', { text: String(purgePending) }), '件'
            ]),
            el('span.stats-sys__h', { text: '受診時刻の' + (data.purge_grace_minutes || 60) + '分後に予約データを自動で削除します。' })
          ])
        ])
      ]));
    }
  }

  /* ---- CSV 書き出し -------------------------------------------------------

     표를 한 장에 모아 두면 「필요한 표만 쓰고 싶다」에 맞지 않는다.
     무엇을 받을지 고르게 하고, 고른 표마다 파일을 따로 내려받는다. */

  var CSV_PARTS = [
    {
      key: 'summary',
      label: '集計（状態・受付経路・男女）',
      desc: '予約状態（確定・仮受付・キャンセル等）、受付経路（WEB・郵送）、男女別の内訳データ'
    },
    {
      key: 'age',
      label: '年代別・男女別',
      desc: '年代区分（40代〜70代以上）および性別のクロス集計データ'
    },
    {
      key: 'option',
      label: 'オプション検査',
      desc: 'オプション検査ごとの申込件数と割合のデータ'
    },
    {
      key: 'time',
      label: '日別（期間が31日を超える場合は月別）',
      desc: '選択された集計期間における日別または月別の予約推移データ'
    },
    {
      key: 'venue',
      label: '会場別',
      desc: '会場ごとの予約確定件数および定員枠の消化状況データ'
    }
  ];

  function downloadParts(parts) {
    // 2つ以上ならサーバーがZIPにまとめる。解凍すると1つのフォルダになる。
    var query = ['format=csv', 'part=' + parts.join(',')].concat(statsParams());
    var link = document.createElement('a');
    link.href = '/api/v1/admin/dashboard/export-csv?' + query.join('&');
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function openExportDialog() {
    var boxes = CSV_PARTS.map(function (part) {
      var input = el('input', {
        type: 'checkbox',
        value: part.key,
        checked: true,
        style: 'width: 18px; height: 18px; accent-color: var(--c-primary, #0B6E5B); margin-top: 2px; cursor: pointer; flex-shrink: 0;'
      });
      var card = el('label', {
        style: 'display: flex; align-items: flex-start; gap: 14px; padding: 14px 18px; border: 1.5px solid #E2E8F0; border-radius: 8px; background: #ffffff; cursor: pointer; transition: all .15s ease;'
      }, [
        input,
        el('div', { style: 'flex: 1; min-width: 0;' }, [
          el('div', { style: 'font-weight: 700; font-size: 15px; color: var(--a-ink, #0F172A); line-height: 1.4;', text: part.label }),
          part.desc ? el('div', { style: 'font-size: 13px; color: var(--a-ink-sub, #64748B); margin-top: 4px; line-height: 1.4;', text: part.desc }) : null
        ])
      ]);

      function updateCardState() {
        if (input.checked) {
          card.style.borderColor = 'var(--c-primary, #0B6E5B)';
          card.style.background = '#F0FDF4';
        } else {
          card.style.borderColor = '#E2E8F0';
          card.style.background = '#ffffff';
        }
      }
      input.addEventListener('change', updateCardState);
      updateCardState();

      return { key: part.key, input: input, node: card, update: updateCardState };
    });

    var selectAllBtn = el('button.btn.btn--sm', {
      type: 'button',
      text: 'すべて選択',
      style: 'font-size: 12.5px; padding: 4px 12px;',
      onClick: function () {
        boxes.forEach(function (b) { b.input.checked = true; b.update(); });
      }
    });

    var deselectAllBtn = el('button.btn.btn--sm', {
      type: 'button',
      text: 'すべて解除',
      style: 'font-size: 12.5px; padding: 4px 12px; color: var(--a-ink-sub);',
      onClick: function () {
        boxes.forEach(function (b) { b.input.checked = false; b.update(); });
      }
    });

    A.modal({
      title: 'CSV 書き出し',
      size: 'wide',
      body: [
        A.notice('info', '2つ以上選ぶと、まとめてZIP（解凍すると1つのフォルダ）で書き出します。期間・会場は健診統計タブの条件をそのまま使います。'),
        el('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin: 18px 0 10px;' }, [
          el('span', { style: 'font-weight: 700; font-size: 14px; color: var(--a-ink);', text: '出力対象の表を選択' }),
          el('div', { style: 'display: flex; gap: 8px;' }, [selectAllBtn, deselectAllBtn])
        ]),
        el('div', { style: 'display: flex; flex-direction: column; gap: 10px;' },
          boxes.map(function (box) { return box.node; }))
      ],
      actions: [
        { label: 'キャンセル' },
        {
          label: '書き出し',
          tone: 'primary',
          onClick: function () {
            var picked = boxes.filter(function (box) { return box.input.checked; });
            if (!picked.length) {
              A.toast('書き出す表を1つ以上選んでください。', 'danger');
              return Promise.reject(new Error('empty'));
            }
            downloadParts(picked.map(function (box) { return box.key; }));
            A.toast(picked.length > 1
              ? picked.length + '件の表をZIP（1フォルダ）で書き出しました。'
              : '1件の表を書き出しました。', 'ok');
          }
        }
      ]
    });
  }

  /* ---- 健診統計のグラフ -------------------------------------------------- */
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var statsResizeObserver = null;
  var statsRedraw = null;

  function svgEl(parent, tag, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (parent) parent.appendChild(node);
    return node;
  }

  function clearSvg(svg) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
  }

  /** 축 끝. 가장 큰 값을 담는 가장 작은 값 가운데, 절반·4등분 눈금이 정수가 되는 것. */
  function statsNiceMax(peak) {
    var steps = [4, 8, 20, 40, 60, 100, 200, 400, 600, 1000, 2000, 4000, 6000, 10000];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i] >= peak) return steps[i];
    }
    return Math.ceil(peak / 10000) * 10000;
  }

  function statsPeriodText(series) {
    if (!series || !series.start) return '';
    if (series.start === series.end) return series.start;
    var sameYear = series.start.slice(0, 4) === series.end.slice(0, 4);
    return series.start + ' ～ ' + (sameYear ? series.end.slice(5) : series.end);
  }

  /** 가로축 글자를 둘 칸. 모두 적으면 겹치는 경우만 솎는다. */
  function statsTickIndexes(kind, n) {
    var out = [], i;
    if (kind === 'hour') return [0, 6, 12, 18, 23];
    if (kind === 'month' ? n <= 12 : n <= 8) {
      for (i = 0; i < n; i++) out.push(i);
      return out;
    }
    var step = kind === 'month' ? Math.ceil(n / 8) : 7;
    for (i = 0; i < n - Math.ceil(step / 2); i += step) out.push(i);
    out.push(n - 1);
    return out;
  }

  /** 申込件数의 곡선. 값 사이는 부드럽게 잇되 0 아래로 내려가거나 실제 값보다 튀지 않게(단조 3차). */
  function drawStatsCurve(svg, series, total) {
    clearSvg(svg);
    var ser = series.points || [];
    var W = 600, H = 140, L = 30, R = 10, T = 16, B = 20;
    var n = ser.length;
    var peak = 0;
    ser.forEach(function (p) { peak = Math.max(peak, p.count); });
    var ymax = statsNiceMax(peak || 1);
    var X = function (i) { return n <= 1 ? (L + W - R) / 2 : L + i * (W - L - R) / (n - 1); };
    var Y = function (v) { return T + (H - T - B) * (1 - v / ymax); };
    var weak = '#7A8785';

    [0, ymax / 2, ymax].forEach(function (v) {
      svgEl(svg, 'line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: v ? '#EDF2F1' : '#C9D5D2', 'stroke-width': 1 });
      svgEl(svg, 'text', { x: L - 6, y: Y(v) + 3.5, 'text-anchor': 'end', 'font-size': 10.5, fill: weak }, v);
    });
    if (!n) return;

    statsTickIndexes(series.kind, n).forEach(function (i) {
      var anchor = n > 1 && i === 0 ? 'start' : (n > 1 && i === n - 1 ? 'end' : 'middle');
      svgEl(svg, 'text', { x: X(i), y: H - 5, 'text-anchor': anchor, 'font-size': 10.5, fill: weak }, ser[i].label);
    });

    var pts = ser.map(function (p, i) { return [X(i), Y(p.count)]; });
    var path = 'M' + pts[0][0] + ',' + pts[0][1];
    if (n > 1) {
      var dx = [], m = [], t = [], i;
      for (i = 0; i < n - 1; i++) {
        dx[i] = pts[i + 1][0] - pts[i][0];
        m[i] = (pts[i + 1][1] - pts[i][1]) / dx[i];
      }
      t[0] = m[0];
      t[n - 1] = m[n - 2];
      for (i = 1; i < n - 1; i++) {
        t[i] = (m[i - 1] * m[i] <= 0) ? 0
          : 3 * (dx[i - 1] + dx[i]) / ((2 * dx[i] + dx[i - 1]) / m[i - 1] + (dx[i] + 2 * dx[i - 1]) / m[i]);
      }
      for (i = 0; i < n - 1; i++) {
        var h = dx[i] / 3;
        path += ' C' + (pts[i][0] + h) + ',' + (pts[i][1] + t[i] * h) + ' ' +
          (pts[i + 1][0] - h) + ',' + (pts[i + 1][1] - t[i + 1] * h) + ' ' + pts[i + 1][0] + ',' + pts[i + 1][1];
      }
    }
    if (total) {
      svgEl(svg, 'path', { d: path + ' L' + X(n - 1) + ',' + Y(0) + ' L' + X(0) + ',' + Y(0) + ' Z', fill: 'rgba(11,110,91,.12)' });
    }
    svgEl(svg, 'path', { d: path, fill: 'none', stroke: total ? '#0B6E5B' : '#C9D5D2', 'stroke-width': 2 });

    var cell = n <= 1 ? W - L - R : (W - L - R) / (n - 1);
    ser.forEach(function (p, i) {
      if (p.count) {
        svgEl(svg, 'circle', { cx: X(i), cy: Y(p.count), r: 3, fill: '#0B6E5B' });
        // 칸이 적으면 모든 점에, 많으면 가장 큰 점에만 숫자를 적는다.
        if (n <= 12 || p.count === peak) {
          var anchor = n > 1 && i === 0 ? 'start' : (n > 1 && i === n - 1 ? 'end' : 'middle');
          svgEl(svg, 'text', { x: X(i), y: Y(p.count) - 6, 'text-anchor': anchor, 'font-size': 11, 'font-weight': 700, fill: '#16211F' }, p.count);
        }
      }
      var hit = svgEl(svg, 'rect', { x: X(i) - cell / 2, y: T, width: cell, height: H - T - B, fill: 'transparent' });
      svgEl(hit, 'title', {}, p.label + '　' + p.count + '件');
    });
  }

  /** 年代別・男女別 세로 묶음 막대. 상자 크기에 맞춰 그리므로 글자가 늘어나지 않는다. */
  function drawAgeColumns(svg, box, ages) {
    clearSvg(svg);
    var W = Math.max(240, Math.round(box.clientWidth || 0));
    var H = Math.max(180, Math.round(box.clientHeight || 0));
    var L = 30, R = 6, T = 22, B = 26;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

    var peak = 0;
    ages.forEach(function (a) { peak = Math.max(peak, a.male || 0, a.female || 0); });
    var ymax = statsNiceMax(peak || 1);
    var Y = function (v) { return T + (H - T - B) * (1 - v / ymax); };

    for (var g = 0; g <= 4; g++) {
      var v = ymax * g / 4;
      svgEl(svg, 'line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: g ? '#EDF2F1' : '#C9D5D2', 'stroke-width': 1 });
      svgEl(svg, 'text', { x: L - 6, y: Y(v) + 3.5, 'text-anchor': 'end', 'font-size': 10.5, fill: '#7A8785' }, v);
    }
    svgEl(svg, 'text', { x: L - 6, y: 10, 'text-anchor': 'end', 'font-size': 10, fill: '#7A8785' }, '名');

    var gw = (W - L - R) / ages.length;
    var bw = Math.min(34, gw * 0.3);
    var gap = 4;
    ages.forEach(function (a, i) {
      var cx = L + gw * i + gw / 2;
      [[a.male || 0, '#1565C0', '男性', -1], [a.female || 0, '#E91E63', '女性', 1]].forEach(function (b) {
        var x = b[3] < 0 ? cx - gap / 2 - bw : cx + gap / 2;
        var y = b[0] ? Y(b[0]) : Y(0) - 1.5;
        var rect = svgEl(svg, 'rect', { x: x, y: y, width: bw, height: Y(0) - y, rx: 2, fill: b[0] ? b[1] : '#C9D5D2' });
        svgEl(rect, 'title', {}, a.label + ' ' + b[2] + '　' + b[0] + '名');
        svgEl(svg, 'text', { x: x + bw / 2, y: y - 5, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 700, fill: b[0] ? '#16211F' : '#7A8785' }, b[0]);
      });
      svgEl(svg, 'text', { x: cx, y: H - 8, 'text-anchor': 'middle', 'font-size': 12.5, 'font-weight': 600, fill: '#55625F' }, a.label);
    });
  }

})();
