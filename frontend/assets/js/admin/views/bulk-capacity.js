/* ==========================================================================
   bulk-capacity.js — 정원 관리
   --------------------------------------------------------------------------
   **한 행이 개최 회차 하나다.** 날짜와 그 날의 시간대 정원만 다룬다.
   회장 코드·이름은 읽기 전용으로 붙고, 주소·좌표·교통편은 **없다.**

   이 화면이 답해야 하는 첫 질문
   -----------------------------
       「회장 A 의 8/28 · 8/29 · 8/30 정원을 보고 고친다」

   그래서 상단에 회장 선택이 있고, 고르면 그 회장의 회차만 남는다.
   예전 표에서는 이 질문에 답하려면 주소·좌표 열 스무 개를 지나쳐야 했다.

   셀에 「3 / 22」를 적는 이유
   --------------------------
   정원 옆에 예약 수가 나란히 있으면, **정원을 3 아래로 못 내리는 이유가
   셀 안에 보인다.** 저장을 눌러 거절당한 뒤에 알게 되는 것보다 낫다.

   빈 칸과 0 은 다르다
   -------------------
       빈 칸 → 그 시간대를 **열지 않는다** (점심시간 등)
       0     → 자리는 있으나 정원이 없다 → 화면에 만석으로 뜬다

   마감은 우클릭으로 **표시**하고 「정원 저장」으로 **적용**한다
   ------------------------------------------------------------
   예전에는 우클릭하는 순간 서버로 나갔다. 되돌리려면 한 번 더 우클릭해야
   했고, 그 사이에 이용자 화면은 이미 마감으로 바뀌어 있었다. 표의 다른
   값은 전부 저장을 눌러야 반영되는데 **마감만 손이 닿는 즉시** 나가니,
   손이 미끄러진 것과 결정한 것을 구별할 방법이 없었다.

   그래서 우클릭은 표에 표시만 남긴다. 실제 적용은 「정원 저장」이며,
   저장 전에는 「되돌리기」로 통째로 버릴 수 있다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var grid = null;
  var state = null;
  var data = null;
  var io = null;

  A.route('bulk-capacity', function (view, params) {
    A.setTitle('定員管理', '開催回ごとの時間帯別定員の一括編集', [
      el('a.btn.btn--sm', { href: '#/bulk-venues', text: '会場管理' }),
      el('a.btn.btn--sm', { href: '#/capacity', text: 'カレンダー表示' })
    ]);

    A.clear(view).appendChild(A.loading('定員を読み込んでいます…'));

    var query = params.hospital_id ? '?hospital_id=' + params.hospital_id : '';
    A.api.get('/bulk/capacity' + query)
      .then(function (body) {
        if (A.parseHash().name !== 'bulk-capacity') return;
        data = body.data;
        draw(view, params.hospital_id ? Number(params.hospital_id) : 0);
      })
      .catch(function (error) { A.fail(view, error); });
  });

  function draw(view, hospitalId) {
    A.clear(view);
    // pendingClosed : 「schedule_id|시간대」 → 저장하면 되어야 할 마감 여부.
    // 서버의 값(`data.closed`)과 같아지면 항목 자체를 지운다 — 두 번 눌러
    // 제자리로 돌아온 것은 「바꾼 것」이 아니다.
    state = { saving: false, hospitalId: hospitalId, pendingClosed: {} };

    var totalChip = el('span.bulk-chip', { text: '開催回 0件' });
    var changedChip = el('span.bulk-chip.bulk-chip--info.is-hidden', { text: '変更 0件' });
    var errorChip = el('span.bulk-chip.bulk-chip--danger.is-hidden', { text: '入力エラー 0件' });
    var resultBox = el('div');

    grid = A.grid.create({
      columns: data.columns,
      variant: 'capacity',
      label: '定員管理表',
      // 회장 코드·회장명을 행 번호 옆에 얼려 둔다. 시간대가 열여섯 칸이라
      // 오후 칸을 볼 즈음이면 어느 회장의 어느 회차인지 사라진다.
      stickyColumns: 2,
      fixedHints: [
        '表の何行目かを示します。保存時のエラー位置をこの番号でお知らせします。',
        '「入力エラー N件」修正か所あり・「変更あり（未保存）」未保存・「締切 N枠（未保存）」右クリックでマークした締切（保存時に適用）・「新規（未保存）」新規開催回・「保存済」保存完了・「時間枠未設定」定員が1枠もなく利用者画面にこの日付が表示されない・「定員設定済」正常'
      ],
      onChange: updateSummary,
      rowStatus: rowStatus,
      cellDecorator: decorate,
      onCellMenu: toggleClosed,
      onFilterCleared: function () { /* 이 화면은 회장 콤보로만 좁힌다 */ }
    });

    io = A.gridIO.attach({
      grid: grid,
      sheet: 'capacity',
      label: '定員',
      unit: '件',
      onImported: updateSummary
    });

    var saveButton = el('button.btn.btn--primary', {
      type: 'button', text: '定員保存', onClick: save
    });

    state.totalChip = totalChip;
    state.changedChip = changedChip;
    state.errorChip = errorChip;
    state.saveButton = saveButton;
    state.resultBox = resultBox;

    // 使い方は「使い方」ボタンへ移した (guide.js)。常時表示すると表がその分狭くなる。
    // 右クリックの締切は、セルのツールチップと「使い方」の先頭で案内する。

    view.appendChild(venuePicker(view));
    view.appendChild(toolbar(saveButton, [totalChip, changedChip, errorChip]));
    view.appendChild(io.noticeBox);
    view.appendChild(grid.node);
    view.appendChild(resultBox);

    io.bindDrop(grid.node);
    grid.setRows(data.rows);
  }

  /* --- 회장 고르기 --------------------------------------------------------
     이 화면의 첫 질문이 「어느 회장의 정원인가」이므로 맨 위에 둔다. */

  function venuePicker(view) {
    var options = [{ value: '', label: 'すべての会場 (' + data.rows.length + '開催回)' }];
    (data.hospitals || []).forEach(function (h) {
      options.push({
        value: String(h.id),
        label: h.code + '  ' + h.name + '  (' + h.schedule_count + '開催回)',
        selected: h.id === state.hospitalId
      });
    });

    var select = A.select({ style: 'min-width:340px' }, options);
    select.addEventListener('change', function () {
      if (isDirty()) {
        A.confirm({
          title: '保存されていない変更があります',
          message: '会場を変更すると、今修正した内容が失われます。'
            + (pendingCount()
              ? ' マークした締切 ' + pendingCount() + '枠も一緒に失われます。'
              : ''),
          okLabel: '破棄して移動',
          tone: 'danger'
        }).then(function (yes) {
          if (yes) go(select.value);
          else select.value = state.hospitalId ? String(state.hospitalId) : '';
        });
        return;
      }
      go(select.value);
    });

    function go(value) {
      A.go('bulk-capacity', value ? { hospital_id: Number(value) } : {});
    }

    // 설명을 입력칸 안에 두면 그만큼 칸이 길어져, 옆 버튼이 설명 줄에 맞춰
    // 아래로 내려간다. 설명은 줄 밖으로 빼서 버튼과 고르는 칸의 줄을 맞춘다.
    return A.card('会場選択', {
      body: [
        el('div.filters.filters--single', {}, [
          A.field('会場', select),
          el('div.filters__actions', {}, [
            el('button.btn.btn--ghost', {
              type: 'button', text: 'すべて表示',
              onClick: function () { if (!isDirty()) go(''); }
            })
          ])
        ]),
        el('p.field__hint', {
          style: 'margin:8px 0 0;',
          text: '選択すると、その会場の開催回のみが表に残ります。'
        })
      ]
    });
  }

  function toolbar(saveButton, chips) {
    return el('div.bulk-toolbar', {}, [
      el('div.bulk-toolbar__left', {}, [
        el('div.bulk-toolbar__group', {}, [
          el('button.btn.btn--sm', {
            type: 'button', text: '3行追加',
            title: '新しい開催回を追加します。会場コードと開催日を入力してください。',
            onClick: function () { grid.addRows(3); }
          }),
          el('button.btn.btn--sm', {
            type: 'button', text: '開催回を複製',
            title: '選択した開催回を時間枠ごと複製します。開催日のみ新しく入力してください。',
            onClick: duplicate
          }),
          el('button.btn.btn--sm', {
            type: 'button', text: '選択行を削除',
            title: '表上でのみ削除します。登録済みの開催回は削除されません。',
            onClick: removeRows
          }),
          el('button.btn.btn--sm.btn--ghost', {
            type: 'button', text: '元に戻す',
            onClick: function () {
              A.go('bulk-capacity',
                state.hospitalId ? { hospital_id: state.hospitalId } : {});
              A.render();
            }
          })
        ]),
        io.node
      ]),
      el('div.bulk-toolbar__summary', {}, chips),
      el('div.bulk-toolbar__actions', {}, [saveButton])
    ]);
  }

  /* --- 셀 꾸미기 ----------------------------------------------------------
     정원 칸에 예약 수와 마감 표시를 얹는다. 값 자체는 정원이고, 예약 수는
     읽기 전용이므로 편집 대상이 아니라는 것이 보여야 한다. */

  function decorate(cell, row, column) {
    if (column.kind !== 'capacity') return;

    var sid = row.schedule_id;
    if (!sid) return;

    var taken = ((data.reserved || {})[sid] || {})[column.key] || 0;
    var saved = savedClosed(sid, column.key);
    var closed = effectiveClosed(sid, column.key);

    if (taken) {
      cell.appendChild(el('span.cap-taken', {
        text: String(taken),
        title: '予約済み人数 ' + taken + '名。定員をこれ以下に減らすことはできません。',
        contentEditable: 'false'
      }));
    }
    // 마감이 아닌 칸에도 조작을 적어 둔다. 우클릭은 눈에 보이지 않는 기능이라
    // 「할 수 있다」를 칸 자체가 말해 주어야 처음 쓰는 사람이 찾는다.
    cell.title = '右クリックでこの時間帯を締め切り／解除できます。';
    if (closed) {
      cell.classList.add('is-closed-cell');
      cell.title = 'この時間帯は締め切られています。右クリックで解除できます。';
    }
    // 아직 저장하지 않은 표시는 **저장된 마감과 달라 보여야 한다.**
    // 같아 보이면 이미 적용됐다고 읽고 저장을 누르지 않는다.
    if (closed !== saved) {
      cell.classList.add('is-closed-pending');
      cell.title = closed
        ? '「定員保存」を押すと、この時間帯が締め切られます。（適用前）'
        : '「定員保存」を押すと、この時間帯の締切が解除されます。（適用前）';
    }
  }

  /* --- 마감 표시 (우클릭) --------------------------------------------------
     정원과 **별개의 상태**다. 정원 0 으로 대신하면 해제할 때 원래 정원을
     잃으므로, 저장 경로도 따로 둔다.

     다만 **표시와 적용은 나눈다.** 우클릭은 표에 자국만 남기고, 서버로
     나가는 것은 「정원 저장」이다. 표의 다른 값과 같은 규칙이라야
     「저장을 눌렀던가」를 매번 되짚지 않는다. */

  function closedKey(scheduleId, cell) {
    return String(scheduleId) + '|' + cell;
  }

  /** 서버에 저장되어 있는 마감 여부. */
  function savedClosed(scheduleId, cell) {
    return ((data.closed || {})[scheduleId] || []).indexOf(cell) !== -1;
  }

  /** 지금 표에 보이는 마감 여부 — 표시해 둔 것이 있으면 그것이 이긴다. */
  function effectiveClosed(scheduleId, cell) {
    var pending = state && state.pendingClosed;
    var key = closedKey(scheduleId, cell);
    if (pending && Object.prototype.hasOwnProperty.call(pending, key)) {
      return pending[key];
    }
    return savedClosed(scheduleId, cell);
  }

  function pendingItems() {
    var pending = (state && state.pendingClosed) || {};
    return Object.keys(pending).map(function (key) {
      var at = key.indexOf('|');
      return {
        schedule_id: Number(key.slice(0, at)),
        cell: key.slice(at + 1),
        closed: pending[key]
      };
    });
  }

  function pendingCount() {
    return pendingItems().length;
  }

  /** 이 회차에 표시해 둔 칸이 몇 개인가. 행 상태에 적는다. */
  function pendingCountOf(scheduleId) {
    if (!scheduleId) return 0;
    var prefix = closedKey(scheduleId, '');
    return Object.keys((state && state.pendingClosed) || {})
      .filter(function (key) { return key.indexOf(prefix) === 0; })
      .length;
  }

  function toggleClosed(event, row, column) {
    if (column.kind !== 'capacity') return false;
    if (!row.schedule_id) {
      A.toast('先にこの開催回を保存してください。', 'warn');
      return true;
    }
    if (!grid.value(row, column.key)) {
      A.toast('受付枠がない時間帯のため、締め切ることはできません。', 'warn');
      return true;
    }
    if (state.saving) {
      A.toast('保存中は締切を変更できません。', 'warn');
      return true;
    }

    var sid = row.schedule_id;
    var key = closedKey(sid, column.key);
    var next = !effectiveClosed(sid, column.key);

    if (next === savedClosed(sid, column.key)) delete state.pendingClosed[key];
    else state.pendingClosed[key] = next;

    grid.render();
    updateSummary();

    A.toast(
      (next ? '締切にする枠としてマークしました。' : '締切を解除する枠としてマークしました。')
      + ' 「定員を保存」をクリックすると反映されます。',
      'ok'
    );
    return true;
  }

  /* --- 행 조작 ------------------------------------------------------------ */

  function duplicate() {
    var count = grid.duplicateSelected(function (copy) {
      // 개최일만 비운다. 같은 회장은 대개 같은 시간표로 열기 때문에,
      // 그 칸을 채우는 것이 다음에 할 일이 되게 한다.
      copy.event_date = '';
      copy.booking_close_date = '';
      copy.schedule_id = '';
    });
    if (!count) {
      A.toast('複製する開催回のセルを先に選択してください。', 'warn');
      return;
    }
    A.toast('開催回 ' + count + '件を複製しました。開催日を入力してください。', 'ok');
  }

  function removeRows() {
    var picked = grid.selectedRows();
    if (!picked.length) {
      A.toast('削除する行のセルを先に選択してください。', 'warn');
      return;
    }
    var registered = picked.filter(function (row) { return row.schedule_id; }).length;

    A.confirm({
      title: picked.length + '行を表から除外しますか？',
      message: registered
        ? 'このうち ' + registered + '件は登録済みの開催回です。'
        : 'まだ保存されていない行です。',
      detail: '表からのみ削除します。登録済みの開催回は削除されません。'
        + '開催回を実際に削除するには、会場管理画面でその会場を開いてください — '
        + '予約が入っている開催回はそこでも削除できません。',
      okLabel: '表から削除'
    }).then(function (yes) {
      if (yes) grid.deleteSelected();
    });
  }

  /* --- 행 상태 ------------------------------------------------------------ */

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
          title: (row._result.changed_fields || []).join(', ')
        });
      }
    }
    if (grid.isBlank(row)) return el('span.bulk-row-state', { text: '未入力' });

    // 마감 표시만 있는 행도 「아직 저장 안 함」이다. 셀의 빗금은 가로로
    // 밀어야 보이지만 상태 칸은 늘 왼쪽에 있으므로, 여기에도 적어 둔다.
    var waiting = pendingCountOf(row.schedule_id);
    if (changed || waiting) {
      return el('span.bulk-row-state.bulk-row-state--ready', {
        text: changed ? '変更あり（未保存）' : '締切 ' + waiting + '枠（未保存）',
        title: waiting
          ? '締切マークした ' + waiting + '枠がまだ保存されていません。'
          + '「定員を保存」をクリックすると反映されます。'
          : ''
      });
    }
    if (!row.schedule_id) {
      return el('span.bulk-row-state.bulk-row-state--ready', { text: '新規（未保存）' });
    }

    // 시간표가 비어 있는 회차는 이용자 화면에 그 날짜가 뜨지 않는다.
    // 표만 보면 멀쩡해 보이므로 여기서 알린다.
    var filled = grid.columns.some(function (column) {
      return column.kind === 'capacity' && grid.value(row, column.key);
    });
    if (!filled) {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: '時間枠未設定',
        title: '定員が1枠もないため、利用者画面にこの日付が表示されません。'
      });
    }
    return el('span.bulk-row-state', { text: '定員設定済' });
  }

  function updateSummary() {
    if (!state || !grid) return;
    var count = grid.dataRows().length;
    var changed = grid.changedCount();
    var errors = grid.errorCount();

    var venues = {};
    grid.dataRows().forEach(function (row) {
      var code = grid.value(row, 'hospital_code');
      if (code) venues[code.toLocaleLowerCase()] = true;
    });

    var waiting = pendingCount();

    state.totalChip.textContent =
      '開催回 ' + count + '件・会場 ' + Object.keys(venues).length + 'か所';
    // 「변경 0건 · …」을 적지 않는다. 표시만 해 둔 상태에서 그 줄이 길어지면
    // 도구 막대가 두 줄로 접히고, 표가 통째로 아래로 밀린다.
    var marks = [];
    if (changed) marks.push('変更 ' + changed + '件');
    if (waiting) marks.push('締切 ' + waiting + '枠（未保存）');
    state.changedChip.textContent = marks.join(' · ');
    state.changedChip.classList.toggle('is-hidden', marks.length === 0);
    state.errorChip.textContent = '入力エラー ' + errors + '件';
    state.errorChip.classList.toggle('is-hidden', errors === 0);

    state.saveButton.textContent = state.saving ? '保存中…' : '定員を保存';
    state.saveButton.disabled = state.saving || !count;
  }

  /* --- 저장 --------------------------------------------------------------- */

  function save() {
    if (state.saving) return;

    var payload = grid.dataRows().map(function (row, index) {
      var out = { row_no: index + 1, schedule_id: row.schedule_id || '' };
      grid.columns.forEach(function (column) {
        out[column.key] = grid.value(row, column.key);
      });
      return out;
    });

    if (!payload.length) {
      A.toast('保存する開催回を1行以上入力してください。', 'warn');
      return;
    }

    // ① 먼저 저장하지 않고 결과만 받아 본다.
    //
    //    정원 표에서 가장 무서운 것은 **자리가 없어지는 것**이다. 시간대 열이
    //    빠진 파일을 올리면 그 칸이 「열지 않음」이 되는데, 예전에는 그 사실이
    //    저장한 뒤에야 드러났다. 서버가 미리 세어 경고로 돌려준다.
    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('変更内容を確認しています…'));

    A.api.post('/bulk/capacity?dry_run=true', { rows: payload })
      .then(function (body) {
        A.clear(state.resultBox);
        state.saving = false;
        updateSummary();

        A.preview.confirm({
          title: '定員を保存しますか？',
          preview: body.data,
          unit: '件',
          labelOf: grid.labelOf,
          detail: '空欄は「その時間帯を受付なし」として保存されます。'
            + 'この表にない開催回は削除されません。'
            + pendingDetail()
        }).then(function (yes) {
          if (yes) commit(payload);
        });
      })
      .catch(function (error) {
        state.saving = false;
        updateSummary();
        showFailure(error);
      });
  }

  function commit(payload) {
    if (state.saving) return;
    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('保存しています…'));

    A.api.post('/bulk/capacity', { rows: payload })
      .then(function (body) {
        grid.setResults(body.data.rows, function (row, result) {
          row.schedule_id = String(result.schedule_id);
          row.hospital_id = String(result.hospital_id);
        });
        // 마감은 정원 뒤에 보낸다. 회차가 이번 저장에서 처음 만들어졌다면
        // 그 전에는 붙일 `schedule_id` 가 없다.
        return applyPendingClosed().then(function (closedResult) {
          renderResult(body.data, closedResult);
          A.toast(summaryText(body.data, closedResult), 'ok');
        });
      })
      .catch(showFailure)
      .then(function () {
        state.saving = false;
        updateSummary();
      });
  }

  /* --- 표시해 둔 마감을 실제로 적용한다 -------------------------------------
     한 칸씩 순서대로 보낸다. 한꺼번에 던지면 조작 로그의 순서가 눌린
     순서와 어긋나고, 한 칸이 거절됐을 때 어느 칸인지 짚기 어렵다.

     **한 칸이 실패해도 나머지는 계속한다.** 예약이 들어와 마감이 거절되는
     것은 그 칸만의 사정이며, 다른 칸까지 되돌릴 이유가 없다. 실패한 칸은
     표시를 남겨 두어 다시 저장할 수 있게 한다. */

  function applyPendingClosed() {
    var items = pendingItems();
    var done = { closed: 0, opened: 0, failed: [] };
    if (!items.length) return Promise.resolve(done);
    if (!data.closed) data.closed = {};

    return items.reduce(function (chain, item) {
      return chain.then(function () {
        return A.api.post('/bulk/capacity/closed', {
          schedule_id: item.schedule_id,
          cell: item.cell,
          closed: item.closed
        }).then(function (body) {
          var list = (data.closed[item.schedule_id] || []).slice();
          if (body.data.is_closed) {
            if (list.indexOf(item.cell) === -1) list.push(item.cell);
            done.closed += 1;
          } else {
            list = list.filter(function (k) { return k !== item.cell; });
            done.opened += 1;
          }
          data.closed[item.schedule_id] = list;
          delete state.pendingClosed[closedKey(item.schedule_id, item.cell)];
        }).catch(function (error) {
          done.failed.push({
            cell: item.cell,
            closed: item.closed,
            message: error.message || '変更できませんでした。'
          });
        });
      });
    }, Promise.resolve()).then(function () {
      grid.render();
      return done;
    });
  }

  /** 저장 직전에 「마감도 함께 적용된다」를 알린다. */
  function pendingDetail() {
    var items = pendingItems();
    if (!items.length) return '';

    var closing = items.filter(function (i) { return i.closed; }).length;
    var opening = items.length - closing;
    var parts = [];
    if (closing) parts.push('締切 ' + closing + '枠');
    if (opening) parts.push('締切解除 ' + opening + '枠');
    return ' マークした ' + parts.join(' · ') + 'もあわせて適用されます。';
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

  function summaryText(result, closedResult) {
    var closed = closedResult || { closed: 0, opened: 0, failed: [] };
    var parts = [];
    if (result.created_count) parts.push('新規 ' + result.created_count + '件');
    if (result.updated_count) parts.push('修正 ' + result.updated_count + '件');
    if (closed.closed) parts.push('締切 ' + closed.closed + '枠');
    if (closed.opened) parts.push('締切解除 ' + closed.opened + '枠');
    if (!parts.length) return '変更がないため取り込みを行いませんでした。';

    var text = parts.join(' · ') + 'を保存しました。';
    if (closed.failed.length) {
      text += ' 締切 ' + closed.failed.length + 'セルは適用できませんでした。';
    }
    return text;
  }

  function renderResult(result, closedResult) {
    var closed = closedResult || { closed: 0, opened: 0, failed: [] };
    var box = A.clear(state.resultBox);

    box.appendChild(el('div.bulk-result__head', {}, [
      el('div', {}, [
        el('h2.bulk-result__title', { text: '定員の保存完了' }),
        el('p.bulk-result__desc', {
          text: summaryText(result, closed)
            + (result.unchanged_count
              ? ' (変更なし ' + result.unchanged_count + '件)' : '')
        })
      ]),
      el('a.btn.btn--sm', { href: '#/bulk-venues', text: '会場管理へ' })
    ]));

    // 정원은 저장됐는데 마감만 거절된 경우다. 표에는 표시가 남아 있으므로
    // 무엇이 남았는지 여기서 짚어 준다.
    if (closed.failed.length) {
      box.appendChild(el('div.bulk-warn', {}, [
        el('p.bulk-warn__title', {
          text: '締切 ' + closed.failed.length + '件は適用できませんでした '
            + '（表に表示が残っています）'
        }),
        el('ul.bulk-warn__list', {}, closed.failed.map(function (f) {
          return el('li', {
            text: f.cell + ' — ' + (f.closed ? '締切' : '締切解除')
              + ' : ' + f.message
          });
        }))
      ]));
    }

    if ((result.warnings || []).length) {
      box.appendChild(el('div.bulk-warn', {}, [
        el('p.bulk-warn__title', {
          text: '保存しましたが、ご確認いただきたい事項が ' + result.warnings.length + '件あります'
        }),
        el('ul.bulk-warn__list', {}, result.warnings.map(function (w) {
          return el('li', {
            text: w.row_no + '行目「' + grid.labelOf(w.field) + '」 — ' + w.message
          });
        }))
      ]));
    }
  }

  /** 표의 값이든 마감 표시든, 아직 서버에 없는 것이 하나라도 있는가. */
  function isDirty() {
    return Boolean(grid && grid.isDirty()) || pendingCount() > 0;
  }

  window.addEventListener('beforeunload', function (event) {
    if (!isDirty()) return;
    if (A.parseHash().name !== 'bulk-capacity') return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
