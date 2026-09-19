/* ==========================================================================
   bulk-venues.js — 회장 관리
   --------------------------------------------------------------------------
   **한 행이 회장 하나다.** 장소 정보만 다룬다 — 코드·이름·주소·좌표·교통편.
   개최일과 정원은 여기에 없다. 그것은 「정원 관리」의 일이다.

   왜 한 행이 회장 하나인가
   ------------------------
   예전에는 한 행이 개최 회차였다. 그래서

     · 회장 A 가 세 번 열면 주소도 세 벌이었다. 한 행의 위도만 잘못 고치면
       같은 회장의 행끼리 값이 어긋났다. 코드로 막을 수는 있었지만,
       **애초에 한 번만 적히게 두는 편이 낫다.**

     · 정원을 고치러 온 사람에게 주소·좌표 열이 스무 개 딸려 왔다.

   조회 화면을 따로 두지 않는다
   ----------------------------
   예전에는 「회장 관리」(조회 전용 목록)와 「회장 정보 일괄」(편집 표)이
   따로 있었다. 같은 데이터를 보는 화면이 둘이라, 담당자가 매번 「어느
   쪽에서 고치는 거였지」를 되짚어야 했다. 조회 화면에만 있던 것 —
   검색·삭제·경고 — 을 전부 이 표로 옮기고 그쪽을 없앴다.

   지우지 않는다 (저장할 때)
   -------------------------
   표에 없는 회장은 저장으로 지워지지 않는다. 삭제는 행 메뉴(우클릭)에서만
   하며, 앞으로의 예약이 남은 회장은 서버가 거절한다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var grid = null;
  var state = null;
  var io = null;

  /* 서버가 준 열 정의. 저장 payload 와 파일 입출력이 함께 쓴다. */
  var allColumns = [];

  // 검색 조건. 화면을 다시 그려도 유지되도록 모듈에 둔다.
  var criteria = { keyword: '', region: '', visibility: '', booking: '' };
  var filterInputs = null;

  /** 가타카나를 히라가나로 맞춘다. 「センター」와 「せんたー」를 같게 취급하기 위함. */
  function toHiragana(text) {
    return String(text || '').replace(/[ァ-ヶ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0x60);
    });
  }

  A.route('bulk-venues', function (view, params) {
    A.setTitle('会場管理', '会場の所在地情報の一覧編集', [
      el('a.btn.btn--sm', { href: '#/bulk-capacity', text: '定員管理' }),
      el('a.btn.btn--sm', { href: '#/capacity', text: '定員カレンダー' })
    ]);

    criteria = { keyword: '', region: '', visibility: '', booking: '' };

    // 화면을 열 때마다 최신 마스터를 받는다. 표를 캐시해 두면 다른
    // 스태프가 고친 내용을 모르는 채 덮어쓰게 된다.
    A.clear(view).appendChild(A.loading('会場情報を読み込んでいます…'));

    A.api.get('/bulk/venues')
      .then(function (body) {
        if (A.parseHash().name !== 'bulk-venues') return;
        draw(view, body.data);
        focusOn(view, params || {});
      })
      .catch(function (error) { A.fail(view, error); });
  });

  /* ======================================================================
     빠른 검색에서 넘어온 회장 짚어 주기
     --------------------------------------------------------------------
     예전에는 빠른 검색에서 회장을 골라도 이 화면의 **맨 위**에 떨어졌다.
     찾은 회장이 어느 줄인지는 사람이 다시 찾아야 했고, 스무 줄을 훑는
     동안 애초에 무엇을 찾고 있었는지도 흐려졌다.

     거르지 않고 **짚어 준다.** 거르면 그 회장 하나만 남아 「옆 회장과
     비교한다」는 이 표의 쓰임이 사라진다.
     ====================================================================== */

  function focusOn(view, params) {
    if (!params.code) return;

    var row = grid.findRow(function (r) {
      return grid.value(r, 'code') === params.code;
    });

    if (!row) {
      A.toast('クイック検索で選択された会場(' + params.code + ')が一覧表で' +
              '見つかりませんでした。他のスタッフが先ほど削除した可能性があります。', 'warn');
      return;
    }

    // 옛 주소나 손으로 친 주소에는 `field` 가 없을 수 있다. 회장명으로 떨어뜨린다.
    var field = HIGHLIGHT_FIELDS.indexOf(params.field) >= 0 ? params.field : 'name';
    grid.setHighlight({ rowKey: row._key, field: field, query: params.q || '' });

    var banner = A.notice('info',
      '「' + grid.value(row, 'name') + '」の ' + FIELD_LABEL[field] +
      (params.q ? 'にて「' + params.q + '」' : '') + '（該当）で見つかりました。' +
      '一覧表の該当セルをハイライトしています。');

    banner.appendChild(el('button.btn.btn--sm.btn--ghost', {
      type: 'button',
      text: 'ハイライト解除',
      style: 'margin-left:10px;',
      onClick: function () {
        grid.clearHighlight();
        if (banner.parentNode) banner.parentNode.removeChild(banner);
      }
    }));

    // 표 바로 위에 둔다. 알림이 화면 꼭대기에 있으면 표를 보는 동안 안 보인다.
    view.insertBefore(banner, grid.node);
  }

  var HIGHLIGHT_FIELDS = ['code', 'name', 'name_kana'];
  var FIELD_LABEL = { code: '会場コード', name: '会場名', name_kana: 'フリガナ' };

  function draw(view, data) {
    A.clear(view);

    state = { saving: false, view: view };

    var totalChip = el('span.bulk-chip', { text: '会場 0件' });
    var filterChip = el('span.bulk-chip.bulk-chip--info.is-hidden', { text: '' });
    var changedChip = el('span.bulk-chip.bulk-chip--info.is-hidden', { text: '変更 0件' });
    var errorChip = el('span.bulk-chip.bulk-chip--danger.is-hidden', { text: '入力エラー 0件' });
    var resultBox = el('div');

    allColumns = data.columns;

    grid = A.grid.create({
      columns: allColumns,
      variant: 'venues',
      label: '会場管理表',
      // 회장 코드·회장명을 행 번호 옆에 얼려 둔다. 열이 열여섯 개라
      // 오른쪽 끝(후리가나·좌표)을 고칠 때면 어느 회장인지 사라진다.
      stickyColumns: 2,
      fixedHints: [
        '表の何行目かを示します。保存時のエラー位置をこの番号でお知らせします。',
        '「入力エラー N件」修正が必要な箇所あり・「変更あり（未保存）」未保存・「新規（未保存）」新しい行・「保存済」保存完了・「日程未登録」日程なし・「今期終了」過去回終了・「位置情報未設定」地図が不正確・「フリガナ未登録」ひらがな検索不可・「開催予定 N回」今後の開催回数（正常）'
      ],
      onChange: updateSummary,
      rowStatus: rowStatus,
      onCellMenu: openRowMenu,
      // 오류가 걸러진 행에 있으면 grid 가 조건을 푼다. 검색 칸도 비워
      // 화면과 표가 어긋나지 않게 한다.
      onFilterCleared: resetFilterInputs
    });

    io = A.gridIO.attach({
      grid: grid,
      sheet: 'venues',
      label: '会場',
      unit: '件',
      onImported: updateSummary
    });

    var saveButton = el('button.btn.btn--primary', {
      type: 'button',
      text: '会場情報を保存',
      onClick: save
    });

    var toolbar = el('div.bulk-toolbar', {}, [
      el('div.bulk-toolbar__left', {}, [
        el('div.bulk-toolbar__group', {}, [
          el('button.btn.btn--sm', {
            type: 'button', text: '3行追加',
            onClick: function () {
              if (grid.hasFilter()) {
                A.toast('検索条件をクリアしてから行を追加してください。' +
                        '絞り込み中に追加すると、その行がすぐに非表示になります。', 'warn');
                return;
              }
              grid.addRows(3);
            }
          }),
          el('button.btn.btn--sm', {
            type: 'button', text: '選択行を除外',
            title: '表からのみ除外します。登録済みの会場は削除されません。',
            onClick: removeRows
          }),
          el('button.btn.btn--sm.btn--ghost', {
            type: 'button', text: '元に戻す',
            title: 'サーバーのマスターを再読み込みし、表の修正内容を破棄します。',
            onClick: function () { A.go('bulk-venues'); A.render(); }
          })
        ]),
        io.node,
        // 원본 마스터 파일은 한 행이 회장 + 회차 + 정원 16칸이라, 이 표의
        // 「가져오기」로는 받을 수 없다. 반기에 한 번 쓰는 길이므로 탭을
        // 따로 두지 않고 버튼 하나로 둔다. (master-import.js 도입부 참조)
        el('div.bulk-toolbar__group', {}, [
          el('button.btn.btn--sm', {
            type: 'button',
            text: '原本マスターファイル',
            title: '担当者から受け取った会場マスターファイル（会場＋開催日＋定員が1行）を' +
                   'そのまま取り込みます。新しい期を開始する際に使用します。',
            onClick: function () {
              A.masterImport.open({
                onDone: function () { A.go('bulk-venues'); A.render(); }
              });
            }
          })
        ])
      ]),
      el('div.bulk-toolbar__summary', {}, [totalChip, filterChip, changedChip, errorChip]),
      el('div.bulk-toolbar__actions', {}, [saveButton])
    ]);

    state.totalChip = totalChip;
    state.filterChip = filterChip;
    state.changedChip = changedChip;
    state.errorChip = errorChip;
    state.saveButton = saveButton;
    state.resultBox = resultBox;

    // 使い方は「使い方」ボタンへ移した (guide.js)。常時表示すると表がその分狭くなる。

    warnAboutData(view, data.rows);

    view.appendChild(buildFilterCard(data));
    view.appendChild(toolbar);
    view.appendChild(io.noticeBox);
    view.appendChild(grid.node);
    view.appendChild(resultBox);

    io.bindDrop(grid.node);
    grid.setRows(data.rows);
  }

  /* ======================================================================
     들어오자마자 알아야 하는 것
     --------------------------------------------------------------------
     예전 조회 화면이 상단에 띄우던 경고다. 표만 보면 전부 멀쩡해 보이는데,
     이용자 화면에서는 빠져 있는 회장이 있다. 그 어긋남을 여기서 알린다.
     ====================================================================== */

  function warnAboutData(view, rows) {
    var hidden = 0;
    var closed = 0;
    var noKana = 0;

    rows.forEach(function (row) {
      // 후리가나는 빠른 검색이 히라가나로 회장을 찾는 유일한 축이다.
      // 원본 마스터 파일에는 이 열이 없어 새로 들어온 회장은 대개 비어
      // 있는데, 표에서는 오른쪽 끝이라 가로로 밀지 않으면 보이지 않는다.
      if (!String(row.name_kana || '').trim()) noKana += 1;

      var visible = String(row.is_visible) === 'はい';
      if (!visible) { hidden += 1; return; }
      if (!row._is_booking_open) closed += 1;
    });

    if (noKana) {
      view.appendChild(A.notice('info',
        'フリガナが未入力の会場が ' + noKana + '件あります。' +
        'その会場は管理画面のクイック検索でひらがなで検索できません。' +
        '利用者画面には影響ありません。'));
    }

    if (hidden) {
      view.appendChild(A.notice('info',
        '予約画面に表示されない会場が ' + hidden + '件あります。' +
        '利用者には表示されませんが、既存の予約はそのまま維持されます。'));
    }

    // 접수가 끝난 회장은 이용자 화면에서 이미 빠져 있다. 스태프가 그것을
    // 모르면 「왜 목록에 없느냐」는 문의에 답할 수 없으므로 여기서 알린다.
    if (closed) {
      view.appendChild(A.notice('warn',
        '受付締切日が過ぎているか、今後の開催回がない会場が ' + closed + '件' +
        'あります。利用者画面の会場一覧からは外れますが、郵送受付は' +
        '引き続き登録できます。'));
    }
  }

  /* ======================================================================
     검색 · 필터
     --------------------------------------------------------------------
     행을 **버리지 않고 감춘다** (grid.setFilter). 걸러진 배열로 표를 다시
     그리면 편집 중이던 내용이 날아가고 행 번호가 바뀐다 — 검색 칸에 한
     글자 칠 때마다 그러면 표로 쓸 수 없다.

     저장할 때는 **감춘 행도 함께** 보낸다. 거른 상태로 저장했다는 이유로
     일부만 반영되면 무엇이 들어갔는지 아무도 모른다.
     ====================================================================== */

  /** 한 회장에서 검색 대상이 되는 모든 문자열. */
  function haystack(row) {
    return toHiragana([
      grid.value(row, 'code'),
      grid.value(row, 'name'),
      grid.value(row, 'name_kana'),
      grid.value(row, 'area'),
      grid.value(row, 'city'),
      grid.value(row, 'postal_code'),
      grid.value(row, 'address'),
      grid.value(row, 'transit_info'),
      grid.value(row, 'tel')
    ].join(' ')).toLowerCase();
  }

  function matches(row) {
    var keyword = toHiragana(criteria.keyword).toLowerCase().trim();
    if (keyword && haystack(row).indexOf(keyword) === -1) return false;

    // 거르는 축은 地域 이다. 표시용 지역으로 거르면 회장마다 값이 달라
    // 선택지가 회장 수만큼 생겨 거르는 뜻이 없어진다.
    if (criteria.region && grid.value(row, 'area') !== criteria.region) {
      return false;
    }

    // 표의 **현재 셀 값**으로 거른다. 방금 고친 값이 반영되는 편이 자연스럽다.
    var visible = grid.value(row, 'is_visible') === 'はい';
    if (criteria.visibility === 'visible' && !visible) return false;
    if (criteria.visibility === 'hidden' && visible) return false;

    // 접수 상태는 회차에서 나오는 값이라 셀에 없다. 서버가 준 것을 쓴다.
    if (criteria.booking === 'open' && !row._is_booking_open) return false;
    if (criteria.booking === 'closed' && row._is_booking_open) return false;

    return true;
  }

  function applyFilter() {
    var active = Boolean(
      criteria.keyword.trim() || criteria.region ||
      criteria.visibility || criteria.booking
    );
    grid.setFilter(active ? matches : null);
    updateSummary();
  }

  function resetFilterInputs() {
    criteria = { keyword: '', region: '', visibility: '', booking: '' };
    if (!filterInputs) return;
    filterInputs.keyword.value = '';
    filterInputs.region.value = '';
    filterInputs.visibility.value = '';
    filterInputs.booking.value = '';
  }

  function buildFilterCard(data) {
    var keyword = A.input({
      value: criteria.keyword,
      placeholder: '会場名・ひらがな（さんぷる）・コード・地域・住所・電話',
      autocomplete: 'off',
      'data-shortcut': 'search'
    });

    /* 실제 등록된 값에서만 뽑아 없는 선택지를 보여 주지 않는다.
       -------------------------------------------------------------------
       **표가 아니라 응답(`data.rows`)에서 뽑는다.** 예전에는 `grid.rows()`
       를 훑었는데, 이 카드는 `grid.setRows()` 보다 **먼저** 만들어진다.
       그때 표는 비어 있어 뽑히는 값이 하나도 없었고, 드롭다운에 「전체
       地域」한 줄만 남았다. 회장이 20곳인데 거를 방법이 없었다. */
    var regions = [];
    (data.rows || []).forEach(function (row) {
      var key = row.area;
      if (key && regions.indexOf(key) === -1) regions.push(key);
    });
    regions.sort();

    var region = A.select({}, [{ value: '', label: 'すべての地域' }].concat(
      regions.map(function (r) {
        return { value: r, label: r, selected: criteria.region === r };
      })
    ));

    var visibility = A.select({}, [
      { value: '', label: '表示・非表示（すべて）' },
      { value: 'visible', label: '予約画面に表示' },
      { value: 'hidden', label: '非表示' }
    ]);

    var booking = A.select({}, [
      { value: '', label: '受付ステータス（すべて）' },
      { value: 'open', label: '受付中' },
      { value: 'closed', label: '受付締切・日程なし' }
    ]);

    filterInputs = {
      keyword: keyword, region: region,
      visibility: visibility, booking: booking
    };

    // 입력하는 즉시 걸러 준다. 검색 input DOM 을 파괴하지 않아
    // 일본어 IME 입력(うえの)이 중간에 깨지지 않는다.
    function rerender() {
      criteria.keyword = keyword.value;
      criteria.region = region.value;
      criteria.visibility = visibility.value;
      criteria.booking = booking.value;
      applyFilter();
    }

    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); rerender(); }
    });
    region.addEventListener('change', rerender);
    visibility.addEventListener('change', rerender);
    booking.addEventListener('change', rerender);

    var form = el('div.filters.filters--compact', {}, [
      A.field('検索', keyword),
      A.field('地域', region),
      A.field('予約画面', visibility),
      A.field('受付ステータス', booking),
      el('div.filters__actions', {}, [
        el('button.btn.btn--primary', {
          type: 'button', text: '検索',
          onClick: function () { rerender(); }
        }),
        el('button.btn.btn--ghost', {
          type: 'button', text: 'リセット',
          onClick: function () { resetFilterInputs(); applyFilter(); }
        })
      ])
    ]);

    return A.card('検索条件', {
      desc: '漢字が分からなくてもひらがなで検索できます （例: さんぷる → サンプル会館 A）. ' +
            '絞り込みで非表示の会場も、保存時にはあわせてチェックされます。',
      collapsible: true,
      collapseKey: 'bulk-venues-filter',
      body: form
    });
  }

  /* ======================================================================
     행 상태
     --------------------------------------------------------------------
     「일정 없음」을 여기서 알린다. 회차가 0인 회장은 이용자 화면에 아예
     나오지 않는데, 회장 표만 보면 멀쩡해 보인다.
     ====================================================================== */

  function rowStatus(row, changed) {
    if (row._errors.length) {
      return el('span.bulk-row-state.bulk-row-state--error', {
        text: '入力エラー ' + row._errors.length + '件',
        title: row._errors.map(function (e) { return e.message; }).join('\n')
      });
    }
    if (row._result) {
      if (row._result.action === 'CREATED') {
        return el('span.bulk-row-state.bulk-row-state--ok', { text: '保存済' });
      }
      if (row._result.action === 'UPDATED') {
        return el('span.bulk-row-state.bulk-row-state--ok', {
          text: '保存済',
          title: (row._result.changed_fields || []).map(grid.labelOf).join(', ')
        });
      }
    }
    if (grid.isBlank(row)) return el('span.bulk-row-state', { text: '未入力' });
    if (changed) {
      return el('span.bulk-row-state.bulk-row-state--ready', { text: '変更あり（未保存）' });
    }
    if (!row.id) {
      return el('span.bulk-row-state.bulk-row-state--ready', { text: '新規（未保存）' });
    }

    /* 여기서부터는 「손볼 곳이 있다」는 알림이다.
       **한 칸에 하나만 보이므로 순서가 곧 우선순위다.** 이용자에게 미치는
       영향이 큰 것부터 둔다.

         일정 없음  이용자 화면에 **아예 나오지 않는다**
         좌표 없음  나오기는 하는데 지도 위치가 흔들린다
         읽기 없음  이용자와는 무관하다. 관리 화면 검색만 불편하다  */

    var upcomingCount = Number(row._upcoming_count || 0);
    var scheduleCount = Number(row._schedule_count || 0);

    if (!scheduleCount) {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: '日程未登録',
        title: '開催日程が一度も登録されていません。利用者画面に表示されません。'
             + '「定員管理」で開催日を入力してください。'
      });
    }

    if (!upcomingCount) {
      return el('span.bulk-row-state.bulk-row-state--muted', {
        text: '今期終了',
        title: '過去の開催日程（' + scheduleCount + '回）はすべて終了しました。'
             + '今後の開催回がないため、利用者画面には表示されません。'
      });
    }

    // 좌표가 비면 이용자 화면의 지도가 주소 검색으로 떨어진다.
    // 위치가 흔들릴 수 있으므로 담당자가 알고 채워 넣게 표시한다.
    if (!grid.value(row, 'latitude') || !grid.value(row, 'longitude')) {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: '位置情報未設定',
        title: '緯度・経度が未入力です。地図が住所検索で表示され、'
             + '位置が正確でない場合があります。'
      });
    }

    // 읽기가 없으면 그 회장은 히라가나로 찾을 수 없다. 후리가나 열이
    // 오른쪽 끝이라 가로로 밀지 않으면 비어 있는 것이 보이지 않는다.
    if (!grid.value(row, 'name_kana')) {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: 'フリガナ未登録',
        title: 'フリガナが未入力のため、管理画面でひらがな検索が'
             + 'できません。利用者画面への影響はありません。'
      });
    }

    // 손볼 곳이 없으면 앞으로 몇 번 여는지를 보여 준다.
    return el('span.bulk-row-state', { text: '開催予定 ' + upcomingCount + '回' });
  }

  /* ======================================================================
     행 메뉴 (우클릭)
     --------------------------------------------------------------------
     표에서는 할 수 없는 일들이 여기 있다 — **삭제**와 정원으로 건너뛰기.
     예전 조회 화면에만 있던 것이라, 그 화면을 없애면서 옮겨 왔다.
     ====================================================================== */

  function openRowMenu(event, row) {
    if (grid.isBlank(row) || !row.id) return false;

    var name = grid.value(row, 'name') || grid.value(row, 'code');
    var reserved = Number(row._upcoming_reserved || 0);

    A.modal({
      title: name,
      size: 'slim',
      body: [
        el('p.field__hint', {
          style: 'margin:0 0 12px',
          text: 'コード ' + grid.value(row, 'code') +
                ' ・ 今後の開催回 ' + (row._upcoming_count || 0) + '回' +
                ' ・ 今後の予約 ' + reserved + '件'
        })
      ],
      actions: [
        { label: '閉じる' },
        {
          label: 'この会場の定員を表示',
          onClick: function () {
            A.go('bulk-capacity', { hospital_id: Number(row.id) });
          }
        },
        {
          label: '会場削除',
          tone: 'danger',
          onClick: function () { confirmDelete(row, name, reserved); }
        }
      ]
    });
    return true;
  }

  function confirmDelete(row, name, reserved) {
    A.confirm({
      title: name + ' を削除しますか？',
      message: '会場およびその会場の開催回・定員がすべて削除されます。',
      detail: reserved
        ? '今後の予約が ' + reserved + '件あるため削除できません。' +
          '利用者画面で非表示にするには、表の「予約画面表示」を' +
          '「いいえ」に変更して保存してください。'
        : '利用者画面でのみ非表示にする場合は、表の「予約画面表示」を' +
          '「いいえ」に変更する方が安全です。既存の予約は残ります。',
      okLabel: '削除'
    }).then(function (ok) {
      if (!ok) return;
      A.api.del('/hospitals/' + row.id)
        .then(function (body) {
          A.toast(body.message, 'ok');
          A.go('bulk-venues');
          // 이미 그 화면이면 해시가 안 바뀌어 다시 그려지지 않는다.
          A.render();
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    });
  }

  /* ======================================================================
     요약 · 표에서 빼기
     ====================================================================== */

  function updateSummary() {
    if (!state || !grid) return;
    var count = grid.dataRows().length;
    var visible = grid.visibleCount();
    var changed = grid.changedCount();
    var errors = grid.errorCount();

    state.totalChip.textContent = '会場 ' + count + '件';

    var filtered = grid.hasFilter();
    state.filterChip.textContent = '絞り込み ' + visible + ' / ' + count + '件';
    state.filterChip.classList.toggle('is-hidden', !filtered);
    state.filterChip.title = filtered
      ? '非表示の会場も保存時にあわせて検証されます。'
      : '';

    state.changedChip.textContent = '変更 ' + changed + '件';
    state.changedChip.classList.toggle('is-hidden', changed === 0);
    state.errorChip.textContent = '入力エラー ' + errors + '件';
    state.errorChip.classList.toggle('is-hidden', errors === 0);

    state.saveButton.textContent = state.saving ? '保存中…' : '会場情報を保存';
    state.saveButton.disabled = state.saving || !count;
  }

  function removeRows() {
    var picked = grid.selectedRows();
    var registered = picked.filter(function (row) { return row.id; }).length;
    if (!picked.length) {
      A.toast('除外する行のセルを先に選択してください。', 'warn');
      return;
    }

    A.confirm({
      title: picked.length + '行を表から除外しますか？',
      message: registered
        ? 'このうち ' + registered + '件は登録済みの会場です。'
        : 'まだ保存されていない行です。',
      detail: '表から除外するだけです。登録済みの会場は削除されません。'
            + '会場を実際に削除するには、行を右クリックして「会場削除」を選択してください。',
      okLabel: '表から除外'
    }).then(function (yes) {
      if (yes) grid.deleteSelected();
    });
  }

  /* ======================================================================
     저장
     --------------------------------------------------------------------
     저장 전에 **무엇이 바뀌는지 먼저 세어 보여 준다** (dry-run).
     예전에는 「21곳을 검사합니다」만 말했고, 몇 곳이 새로 생기고 몇 곳이
     덮어써지는지는 저장한 뒤에야 알 수 있었다.
     ====================================================================== */

  function payloadRows() {
    // **감춘 행도 함께** 보낸다. 거른 상태로 저장했다는 이유로 일부만
    // 반영되면 무엇이 들어갔는지 아무도 모른다.
    return grid.dataRows().map(function (row, index) {
      var out = { row_no: index + 1, id: row.id || '' };
      // **감춘 열까지** 담는다. 화면에 없다는 이유로 빼면 그 칸이 빈 값으로
      // 저장되어, 켜 두지 않은 사람이 저장할 때마다 후리가나가 지워진다.
      allColumns.forEach(function (column) {
        out[column.key] = grid.value(row, column.key);
      });
      return out;
    });
  }

  function save() {
    if (state.saving) return;

    var payload = payloadRows();
    if (!payload.length) {
      A.toast('保存する会場を1行以上入力してください。', 'warn');
      return;
    }

    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('変更内容を確認しています…'));

    // ① 먼저 저장하지 않고 결과만 받아 본다.
    A.api.post('/bulk/venues?dry_run=true', { rows: payload })
      .then(function (body) {
        A.clear(state.resultBox);
        state.saving = false;
        updateSummary();
        askConfirm(payload, body.data);
      })
      .catch(function (error) {
        state.saving = false;
        updateSummary();
        showFailure(error);
      });
  }

  function askConfirm(payload, preview) {
    A.preview.confirm({
      title: '会場情報を保存しますか？',
      preview: preview,
      unit: 'か所',
      labelOf: grid.labelOf,
      hiddenNote: grid.hasFilter()
        ? '検索で非表示にした会場もあわせて確認しました。'
        : '',
      detail: '1セルでもエラーがある場合は1か所も保存せず、エラー位置を' +
              '表に表示します。この表にない会場は削除されません。'
    }).then(function (yes) {
      if (!yes || state.saving) return;
      commit(payload);
    });
  }

  function commit(payload) {
    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('保存しています…'));

    A.api.post('/bulk/venues', { rows: payload })
      .then(function (body) {
        grid.setResults(body.data.rows, function (row, result) {
          row.id = String(result.id);
        });
        renderResult(body.data);
        A.toast(summaryText(body.data), 'ok');
      })
      .catch(showFailure)
      .then(function () {
        state.saving = false;
        updateSummary();
      });
  }

  function showFailure(error) {
    var errors = (error.body || {}).errors || [];
    if (errors.length) {
      grid.setErrors(errors);
      A.clear(state.resultBox);
      A.toast(errors.length + '件の入力エラーがあります。表でご確認ください。',
              'danger');
    } else {
      A.clear(state.resultBox).appendChild(
        A.notice('danger', error.message || '保存できませんでした。'));
    }
  }

  function summaryText(data) {
    var parts = [];
    if (data.created_count) parts.push('新規 ' + data.created_count + 'か所');
    if (data.updated_count) parts.push('修正 ' + data.updated_count + 'か所');
    if (!parts.length) return '変更がないため取り込みを行いませんでした。';
    return parts.join(' · ') + 'を保存しました。';
  }

  function renderResult(data) {
    var box = A.clear(state.resultBox);

    box.appendChild(el('div.bulk-result__head', {}, [
      el('div', {}, [
        el('h2.bulk-result__title', { text: '会場情報の保存完了' }),
        el('p.bulk-result__desc', {
          text: summaryText(data)
              + (data.unchanged_count ? ' (変更なし ' + data.unchanged_count + 'か所)' : '')
        })
      ]),
      el('a.btn.btn--sm', { href: '#/bulk-capacity', text: '定員管理へ' })
    ]));

    if ((data.warnings || []).length) {
      box.appendChild(el('div.bulk-warn', {}, [
        el('p.bulk-warn__title', {
          text: '保存しましたが、ご確認いただきたい事項が ' + data.warnings.length + '件あります'
        }),
        el('ul.bulk-warn__list', {}, data.warnings.map(function (w) {
          return el('li', {
            text: w.row_no + '行目「' + grid.labelOf(w.field) + '」 — ' + w.message
          });
        }))
      ]));
    }
  }

  /* 아직 저장하지 않은 수정이 사라지는 것을 경고한다. */
  window.addEventListener('beforeunload', function (event) {
    if (!grid || !grid.isDirty()) return;
    if (A.parseHash().name !== 'bulk-venues') return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
