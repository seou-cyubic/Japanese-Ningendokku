/* ==========================================================================
   bulk-exam-options.js — 옵션 검사 관리
   --------------------------------------------------------------------------
   **한 행이 옵션 검사 하나다.** 기본 검진에 추가로 신청할 수 있는 검사다.

   왜 표로 바꿨는가
   ----------------
   예전에는 카드 목록 + 행마다 「수정」 모달이었다. 검사 12건의 타깃 연령을
   한 살씩 올리는 데 모달을 열두 번 열고 열두 번 저장해야 했다.
   CSV 입출력은 별도 드롭다운에 따로 붙어 있어, 「표에서 고치는 것」과
   「파일로 고치는 것」이 아예 다른 화면이었고 검증 규칙도 두 벌이었다.

   회장·정원과 같은 표로 맞췄다. 고치는 창구가 하나여야 규칙이 갈라지지 않는다.

   타깃 조건은 즉시 반영된다
   -------------------------
   여기서 바꾼 성별·연령은 이용자 폼에 **즉시** 반영된다 (BR-13).
   조건에 맞지 않는 검사는 이용자 화면에 아예 나타나지 않으므로, 조건을
   잘못 좁히면 「왜 신청이 안 되냐」는 문의가 바로 늘어난다. 그래서 저장
   전에 무엇이 어떻게 바뀌는지 먼저 보여 준다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var grid = null;
  var state = null;
  var io = null;

  var criteria = { keyword: '', gender: '', status: '' };
  var filterInputs = null;

  A.route('bulk-exam-options', function (view) {
    A.setTitle('オプション検査管理', '基本健診に追加で申し込める検査の管理');

    criteria = { keyword: '', gender: '', status: '' };

    A.clear(view).appendChild(A.loading('オプション検査を読み込んでいます…'));

    A.api.get('/bulk/exam-options')
      .then(function (body) {
        if (A.parseHash().name !== 'bulk-exam-options') return;
        draw(view, body.data);
      })
      .catch(function (error) { A.fail(view, error); });
  });

  function draw(view, data) {
    A.clear(view);

    state = { saving: false };

    var totalChip = el('span.bulk-chip', { text: '検査 0件' });
    var filterChip = el('span.bulk-chip.bulk-chip--info.is-hidden', { text: '' });
    var changedChip = el('span.bulk-chip.bulk-chip--info.is-hidden', { text: '変更 0件' });
    var errorChip = el('span.bulk-chip.bulk-chip--danger.is-hidden', { text: '入力エラー 0件' });
    var resultBox = el('div');

    grid = A.grid.create({
      columns: data.columns,
      variant: 'exam-options',
      label: 'オプション検査管理表',
      fixedHints: [
        '表の何行目かを示します。保存時のエラー位置をこの番号でお知らせします。',
        '「入力エラー N件」修正か所あり・「変更あり（未保存）」未保存・「新規（未保存）」新しい検査・「保存済」保存完了・「年齢設定エラー」誰にも表示されない・「非公開」予約画面に表示されない（右クリックで行メニュー・予約確認）'
      ],
      onChange: updateSummary,
      rowStatus: rowStatus,
      onCellMenu: openRowMenu,
      onFilterCleared: resetFilterInputs
    });

    io = A.gridIO.attach({
      grid: grid,
      sheet: 'exam-options',
      label: 'オプション検査',
      unit: '件',
      onImported: updateSummary
    });

    var saveButton = el('button.btn.btn--primary', {
      type: 'button', text: 'オプション検査を保存', onClick: save
    });

    var toolbar = el('div.bulk-toolbar', {}, [
      el('div.bulk-toolbar__left', {}, [
        el('div.bulk-toolbar__group', {}, [
          el('button.btn.btn--sm', {
            type: 'button', text: '3行追加',
            onClick: function () {
              if (grid.hasFilter()) {
                A.toast('検索条件をクリアしてから行を追加してください。', 'warn');
                return;
              }
              grid.addRows(3);
            }
          }),
          el('button.btn.btn--sm', {
            type: 'button', text: '選択行を除外',
            title: '表からのみ除外します。登録済みの検査は削除されません。',
            onClick: removeRows
          }),
          el('button.btn.btn--sm.btn--ghost', {
            type: 'button', text: '元に戻す',
            onClick: function () { A.go('bulk-exam-options'); A.render(); }
          })
        ]),
        io.node
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

    view.appendChild(buildFilterCard());
    view.appendChild(toolbar);
    view.appendChild(io.noticeBox);
    view.appendChild(grid.node);
    view.appendChild(resultBox);

    io.bindDrop(grid.node);
    grid.setRows(data.rows);
  }

  /* ======================================================================
     검색
     ====================================================================== */

  function matches(row) {
    var keyword = criteria.keyword.trim().toLowerCase();
    if (keyword) {
      var haystack = [
        grid.value(row, 'code'), grid.value(row, 'name'),
        grid.value(row, 'description'), grid.value(row, 'note')
      ].join(' ').toLowerCase();
      if (haystack.indexOf(keyword) === -1) return false;
    }
    if (criteria.gender && grid.value(row, 'target_gender') !== criteria.gender) {
      return false;
    }
    var active = grid.value(row, 'is_active') === 'はい';
    if (criteria.status === 'active' && !active) return false;
    if (criteria.status === 'inactive' && active) return false;
    return true;
  }

  function applyFilter() {
    var active = Boolean(criteria.keyword.trim() || criteria.gender || criteria.status);
    grid.setFilter(active ? matches : null);
    updateSummary();
  }

  function resetFilterInputs() {
    criteria = { keyword: '', gender: '', status: '' };
    if (!filterInputs) return;
    filterInputs.keyword.value = '';
    filterInputs.gender.value = '';
    filterInputs.status.value = '';
  }

  function buildFilterCard() {
    var keyword = A.input({
      placeholder: 'コード・検査名・説明・準備事項',
      autocomplete: 'off',
      'data-shortcut': 'search'
    });

    // 선택지는 서버가 준 열 정의에서 뽑는다. 화면에 적어 두면 성별을
    // 하나 늘릴 때 두 곳을 고쳐야 한다.
    var genderColumn = null;
    grid.columns.forEach(function (column) {
      if (column.key === 'target_gender') genderColumn = column;
    });
    var genderOptions = [{ value: '', label: '対象性別（すべて）' }].concat(
      ((genderColumn && genderColumn.choices) || []).map(function (choice) {
        return { value: choice.value, label: choice.label };
      })
    );

    var gender = A.select({}, genderOptions);
    var status = A.select({}, [
      { value: '', label: '有効/無効（すべて）' },
      { value: 'active', label: '有効' },
      { value: 'inactive', label: '無効' }
    ]);

    filterInputs = { keyword: keyword, gender: gender, status: status };

    function rerender() {
      criteria.keyword = keyword.value;
      criteria.gender = gender.value;
      criteria.status = status.value;
      applyFilter();
    }

    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); rerender(); }
    });
    gender.addEventListener('change', rerender);
    status.addEventListener('change', rerender);

    return A.card('検索条件', {
      desc: '絞り込みで非表示の検査も、保存時にあわせてチェックされます。',
      collapsible: true,
      collapseKey: 'bulk-exam-options-filter',
      body: el('div.filters.filters--compact', {}, [
        A.field('検索', keyword),
        A.field('対象性別', gender),
        A.field('有効/無効', status),
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
      ])
    });
  }

  /* ======================================================================
     행 상태
     --------------------------------------------------------------------
     신청 건수를 여기 둔다. 열로 두면 고칠 수 있는 칸처럼 보이는데,
     이것은 예약에서 세어 낸 값이라 표에서 바꿀 수 있는 것이 아니다.

     상태 칸은 **두 조각**이다.

         [ 오류 2 ] [ 3건 ]
         ↑ 지금 이 행의 상태  ↑ 이 검사를 신청한 예약 수 (더블 클릭)

     예전에는 하나였고 먼저 만나는 상태만 보여 주었다. 그래서 셀을 한 칸만
     고쳐도 「3건」이 사라졌다. 더블 클릭으로 예약을 보러 가는 길이 있다가
     없다가 하면 그런 길이 있다는 것 자체를 아무도 믿지 않는다.
     ====================================================================== */

  function rowStatus(row, changed) {
    return primaryState(row, changed);
  }

  // 신청 건수 확인 및 예약 검색 이동은 행 우클릭 메뉴(openRowMenu)에서 수행한다.

  function openReservations(row, used) {
    if (!used) {
      A.toast('この検査を申し込んだ予約はまだありません。', 'info');
      return;
    }

    function jump() { A.go('reservations', { option_id: row.id }); }

    // 표에 고쳐 둔 것이 있으면 그냥 떠나지 않는다. 저장하지 않은 수정은
    // 화면을 옮기는 순간 사라진다.
    if (!grid.isDirty()) { jump(); return; }

    A.confirm({
      title: '保存されていない変更があります',
      message: '予約検索へ移動すると、現在編集中の内容は破棄されます。',
      okLabel: '破棄して移動',
      tone: 'danger'
    }).then(function (yes) { if (yes) jump(); });
  }

  function primaryState(row, changed) {
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

    // 신청 건수는 `usedChip()` 이 따로 붙인다. 여기서는 「손볼 곳이 있는가」만 본다.

    // 조건이 뒤집힌 검사는 아무에게도 보이지 않는다. 표에서는 숫자 두 개일
    // 뿐이라 눈에 띄지 않으므로 상태 칸에서 짚어 준다.
    var low = Number(grid.value(row, 'target_age_min'));
    var high = Number(grid.value(row, 'target_age_max'));
    if (low && high && low > high) {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: '年齢設定エラー',
        title: '最小年齢が最大年齢を超えています。誰にも表示されません。'
      });
    }

    if (grid.value(row, 'is_active') !== 'はい') {
      return el('span.bulk-row-state.bulk-row-state--warn', {
        text: '非公開',
        title: '予約画面に表示されません。'
      });
    }

    return el('span.bulk-row-state', { text: '—' });
  }

  /* ======================================================================
     행 메뉴 — 표에서는 할 수 없는 일
     ====================================================================== */

  function openRowMenu(event, row) {
    if (grid.isBlank(row) || !row.id) return false;

    var name = grid.value(row, 'name') || grid.value(row, 'code');
    var used = Number(row._used_count || 0);

    var actions = [{ label: '閉じる' }];

    if (used > 0) {
      actions.push({
        label: '予約一覧を見る (' + used + '件)',
        tone: 'primary',
        onClick: function () { openReservations(row, used); }
      });
    }

    actions.push({
      label: '検査削除',
      tone: 'danger',
      onClick: function () { confirmDelete(row, name, used); }
    });

    A.modal({
      title: name,
      size: 'slim',
      body: [
        el('p.field__hint', {
          style: 'margin:0 0 12px',
          text: 'コード ' + grid.value(row, 'code') + ' ・ 申込 ' + used + '件'
        }),
        used > 0
          ? el('p', {
            style: 'font-size:13px;color:var(--a-ink);margin:0 0 8px;',
            text: 'この検査を申し込んだ予約が ' + used + '件あります。「予約一覧を見る」をクリックすると該当の予約一覧を確認できます。'
          })
          : el('p.field__hint', {
            style: 'margin:0 0 8px;',
            text: 'この検査を申し込んだ予約はまだありません。'
          })
      ],
      actions: actions
    });
    return true;
  }

  function confirmDelete(row, name, used) {
    A.confirm({
      title: name + ' を削除しますか？',
      message: 'オプション検査がマスターから削除されます。',
      detail: used
        ? 'この検査を申し込んだ予約が ' + used + '件あるため削除できません。' +
        '新規の申込のみを停止する場合は、表で「予約画面に表示」を「いいえ」に変更して保存してください。'
        : '新規の申込のみを停止したい場合は、表で「予約画面に表示」を「いいえ」にする方が安全です。',
      okLabel: '削除'
    }).then(function (ok) {
      if (!ok) return;
      A.api.del('/bulk/exam-options/' + row.id)
        .then(function (body) {
          A.toast(body.message, 'ok');
          A.go('bulk-exam-options');
          A.render();
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    });
  }

  /* ======================================================================
     요약 · 저장
     ====================================================================== */

  function updateSummary() {
    if (!state || !grid) return;
    var count = grid.dataRows().length;
    var changed = grid.changedCount();
    var errors = grid.errorCount();
    var filtered = grid.hasFilter();

    state.totalChip.textContent = '検査 ' + count + '件';
    state.filterChip.textContent = '絞り込み ' + grid.visibleCount() + ' / ' + count + '件';
    state.filterChip.classList.toggle('is-hidden', !filtered);
    state.changedChip.textContent = '変更 ' + changed + '件';
    state.changedChip.classList.toggle('is-hidden', changed === 0);
    state.errorChip.textContent = '入力エラー ' + errors + '件';
    state.errorChip.classList.toggle('is-hidden', errors === 0);

    state.saveButton.textContent = state.saving ? '保存中…' : 'オプション検査を保存';
    state.saveButton.disabled = state.saving || !count;
  }

  function removeRows() {
    var picked = grid.selectedRows();
    if (!picked.length) {
      A.toast('除外する行のセルを先に選択してください。', 'warn');
      return;
    }
    var registered = picked.filter(function (row) { return row.id; }).length;

    A.confirm({
      title: picked.length + '行を表から除外しますか？',
      message: registered
        ? 'このうち ' + registered + '件は登録済みの検査です。'
        : 'まだ保存されていない行です。',
      detail: '表からのみ除外します。登録済みの検査は削除されません。'
        + '実際に削除するには、行を右クリックして「検査削除」を選択してください。',
      okLabel: '表から除外'
    }).then(function (yes) {
      if (yes) grid.deleteSelected();
    });
  }

  function payloadRows() {
    return grid.dataRows().map(function (row, index) {
      var out = { row_no: index + 1, id: row.id || '' };
      grid.columns.forEach(function (column) {
        out[column.key] = grid.value(row, column.key);
      });
      return out;
    });
  }

  function save() {
    if (state.saving) return;

    var payload = payloadRows();
    if (!payload.length) {
      A.toast('保存する検査を1行以上入力してください。', 'warn');
      return;
    }

    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('変更内容を確認しています…'));

    A.api.post('/bulk/exam-options?dry_run=true', { rows: payload })
      .then(function (body) {
        A.clear(state.resultBox);
        state.saving = false;
        updateSummary();

        A.preview.confirm({
          title: 'オプション検査を保存しますか？',
          preview: body.data,
          unit: '件',
          labelOf: grid.labelOf,
          hiddenNote: grid.hasFilter()
            ? '検索で非表示にした検査もあわせて確認しました。'
            : '',
          detail: '対象条件は利用者画面に即座に反映されます。' +
            'この表にない検査は削除されません。'
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
    state.saving = true;
    updateSummary();
    A.clear(state.resultBox).appendChild(A.loading('保存しています…'));

    A.api.post('/bulk/exam-options', { rows: payload })
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
      A.toast(errors.length + '件の入力エラーがあります。表でご確認ください。', 'danger');
    } else {
      A.clear(state.resultBox).appendChild(
        A.notice('danger', error.message || '保存できませんでした。'));
    }
  }

  function summaryText(data) {
    var parts = [];
    if (data.created_count) parts.push('新規 ' + data.created_count + '件');
    if (data.updated_count) parts.push('修正 ' + data.updated_count + '件');
    if (!parts.length) return '変更がないため取り込みを行いませんでした。';
    return parts.join(' · ') + 'を保存しました。';
  }

  function renderResult(data) {
    var box = A.clear(state.resultBox);

    box.appendChild(el('div.bulk-result__head', {}, [
      el('div', {}, [
        el('h2.bulk-result__title', { text: 'オプション検査保存完了' }),
        el('p.bulk-result__desc', {
          text: summaryText(data)
            + (data.unchanged_count ? ' (変更なし ' + data.unchanged_count + '件)' : '')
        })
      ])
    ]));

    if ((data.warnings || []).length) {
      box.appendChild(el('div.bulk-warn', {}, [
        el('p.bulk-warn__title', {
          text: '保存しましたが、ご確認いただきたい事項が ' + data.warnings.length + '件あります'
        }),
        el('ul.bulk-warn__list', {}, data.warnings.map(function (w) {
          return el('li', { text: w.row_no + '行 — ' + w.message });
        }))
      ]));
    }
  }

  window.addEventListener('beforeunload', function (event) {
    if (!grid || !grid.isDirty()) return;
    if (A.parseHash().name !== 'bulk-exam-options') return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
