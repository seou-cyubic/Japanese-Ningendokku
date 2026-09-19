/* ===========================================================================
   bulk-postal.js — 우편 접수 일괄 입력
   --------------------------------------------------------------------------
   Excel/Google Sheets 에서 복사한 TSV 를 그대로 붙여 넣고, 표 안에서 직접
   고친 뒤 전 행을 한 번에 검증·등록한다. 원본 파일이나 개인정보를 브라우저
   저장소에 남기지 않는다.

   파일로도 들고 나갈 수 있다 (CSV · Excel).
     · 내보내기 : 지금 표를 그대로 파일로. **검증하지 않는다.** 형식이 틀린
       값을 Excel 에서 고치려고 꺼내는 것이 가장 흔한 사용법이다
     · 가져오기 : 파일을 표로. **저장하지 않는다.** 사람이 표에서 확인하고
       「예약 적용하기」를 눌러야 예약이 된다
     · 열의 정의(라벨·순서·서식)는 서버(`postal_sheet_service`) 한 곳에만
       둔다. 여기서는 **열 키**로만 주고받는다. 라벨을 계약으로 삼으면
       이름을 다듬는 순간 어제 내보낸 파일을 못 읽는다
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;
  var MAX_ROWS = 200;
  var INITIAL_ROWS = 15;
  var rowSequence = 0;
  var filters = null;
  var draftRows = null;
  var draftDirty = false;
  var draftApplied = false;
  var state = null;
  // 파일 입출력 툴바(grid-io.js). 화면을 그릴 때 만든다.
  var io = null;

  var COLUMNS = [
    { key: 'last_name', label: '姓', width: 96 },
    { key: 'first_name', label: '名', width: 96 },
    { key: 'last_name_kana', label: '姓フリガナ', width: 120 },
    { key: 'first_name_kana', label: '名フリガナ', width: 120 },
    { key: 'middle_name', label: 'ミドルネーム', width: 112 },
    { key: 'middle_name_kana', label: 'ミドルネームフリガナ', width: 145 },
    { key: 'gender', label: '性別', width: 72, tooltip: '性別（男/女、M/Fなど入力可能）' },
    { key: 'birth_date', label: '生年月日', width: 112, tooltip: '生年月日（YYYY-MM-DD形式）' },
    { key: 'insurer_no', label: '保険者番号', width: 112 },
    { key: 'insurance_symbol', label: '保険証記号', width: 112 },
    { key: 'insurance_no', label: '保険証番号', width: 112 },
    { key: 'postal_code', label: '郵便番号', width: 102 },
    { key: 'address', label: '住所', width: 220 },
    { key: 'address_detail', label: '番地', width: 140 },
    { key: 'building', label: 'アパート・マンション名', width: 180 },
    { key: 'tel_mobile', label: '携帯電話', width: 140 },
    { key: 'tel_home', label: '固定電話', width: 140 },
    { key: 'email', label: 'メールアドレス', width: 210 },
    { key: 'wish1_hospital', label: '会場コード/名', width: 180 },
    { key: 'wish1_date', label: '受診日', width: 112 },
    { key: 'wish1_time', label: '開始時刻', width: 94 },
    { key: 'wish2_hospital', label: '会場コード/名', width: 180 },
    { key: 'wish2_date', label: '受診日', width: 112 },
    { key: 'wish2_time', label: '開始時刻', width: 94 },
    { key: 'wish3_hospital', label: '会場コード/名', width: 180 },
    { key: 'wish3_date', label: '受診日', width: 112 },
    { key: 'wish3_time', label: '開始時刻', width: 94 },
    { key: 'option_codes', label: 'オプションコード（;区切り）', width: 180 },
    { key: 'allow_defect', label: '不備許容', width: 90 },
    { key: 'memo', label: 'スタッフメモ', width: 240 }
  ];

  var GROUPS = [
    { label: '申込者', span: 8 },
    { label: '保険証', span: 3 },
    { label: '住所・連絡先', span: 7 },
    { label: '第1希望', span: 3 },
    { label: '第2希望', span: 3 },
    { label: '第3希望', span: 3 },
    { label: 'オプション・メモ', span: 3 }
  ];

  var COLUMN_BY_KEY = {};
  COLUMNS.forEach(function (column, index) {
    COLUMN_BY_KEY[column.key] = { column: column, index: index };
  });

  A.route('postal-bulk', function (view) {
    A.setTitle('郵送受付一括入力', '表への直接入力・Excel貼り付けによる一括登録', [
      el('a.btn.btn--sm', { href: '#/postal', text: '単件入力へ' })
    ]);

    var ready = filters
      ? Promise.resolve()
      : A.api.get('/reservations/filters').then(function (body) { filters = body.data; });

    ready.then(function () {
      if (isCurrentRoute()) draw(view);
    }).catch(function (error) {
      if (isCurrentRoute()) A.fail(view, error);
    });
  });

  function isCurrentRoute() {
    return location.hash.replace(/^#\/?/, '').split('?')[0] === 'postal-bulk';
  }

  function emptyRow() {
    return {
      _key: 'bulk-row-' + (++rowSequence),
      _errors: [],
      _result: null
    };
  }

  function initialRows(count) {
    var rows = [];
    for (var i = 0; i < count; i++) rows.push(emptyRow());
    return rows;
  }

  function clean(value) {
    if (value === null || value === undefined || value === false) return '';
    if (value === true) return 'はい';
    return String(value).replace(/\u00a0/g, ' ').trim();
  }

  function displayValue(row, key) {
    if (key === 'allow_defect') {
      if (row[key] === true) return 'はい';
      if (row[key] === false || row[key] === undefined || row[key] === null) return '';
    }
    return clean(row[key]);
  }

  function isRowBlank(row) {
    return !COLUMNS.some(function (column) {
      return clean(row[column.key]) !== '';
    });
  }

  function nonBlankRows() {
    return (draftRows || []).filter(function (row) { return !isRowBlank(row); });
  }

  function rowByKey(key) {
    return (draftRows || []).find(function (row) { return row._key === key; }) || null;
  }

  function rowErrorsForField(row, key) {
    return (row._errors || []).filter(function (error) {
      if (error.field === key) return true;
      if (error.field === 'wishes' && key.indexOf('wish') === 0) return true;
      return false;
    });
  }

  function draw(view) {
    if (!draftRows) draftRows = initialRows(INITIAL_ROWS);
    A.clear(view);

    io = buildIO();

    state = {
      view: view,
      applying: false,
      applied: draftApplied,
      selection: null,
      anchor: null,
      dragging: false,
      closeDrawer: null,
      globalErrors: []
    };

    // 使い方は「使い方」ボタンへ移した (guide.js)。常時表示すると表がその分狭くなる。

    var totalChip = el('span.bulk-chip', { text: '入力 0件' });
    var errorChip = el('span.bulk-chip.bulk-chip--danger.is-hidden', { text: '入力エラー 0件' });
    var selectionText = el('span.bulk-selection-text', { text: '選択セルなし' });

    var applyButton = el('button.btn.btn--primary', {
      type: 'button',
      text: '予約を適用',
      onClick: applyReservations
    });
    var newButton = el('button.btn.is-hidden', {
      type: 'button',
      text: '新規一括入力を開始',
      onClick: startNewBatch
    });

    // 파일 선택 창은 버튼으로만 연다. input 을 그대로 두면 툴바에서
    // 자리만 차지하고 브라우저마다 다르게 그려진다.
    var toolbar = el('div.bulk-toolbar', {}, [
      el('div.bulk-toolbar__left', {}, [
        el('div.bulk-toolbar__group', {}, [
          el('button.btn.btn--sm', {
            type: 'button', text: '10行追加',
            onClick: function () { addRows(10); }
          }),
          el('button.btn.btn--sm', {
            type: 'button', text: '選択行を削除',
            onClick: deleteSelectedRows
          }),
          el('button.btn.btn--sm.btn--ghost', {
            type: 'button', text: '表全体をクリア',
            onClick: clearAllRows
          })
        ]),
        el('div.bulk-toolbar__group.bulk-toolbar__group--file', {}, [
          el('span.bulk-toolbar__label', { text: 'ファイル' }),
          io.node
        ])
      ]),
      el('div.bulk-toolbar__summary', {}, [totalChip, errorChip, selectionText]),
      el('div.bulk-toolbar__actions', {}, [newButton, applyButton])
    ]);

    var table = buildGrid();
    // 표의 끝에 닿으면 페이지가 이어서 굴러간다 (core.js `chainScroll`).
    var wrap = A.chainScroll(el('div.bulk-grid-wrap', {}, table));
    var ioBox = io.noticeBox;
    var resultBox = el('div.bulk-result');

    state.table = table;
    state.tbody = table.querySelector('tbody');
    state.wrap = wrap;
    state.totalChip = totalChip;
    state.errorChip = errorChip;
    state.selectionText = selectionText;
    state.applyButton = applyButton;
    state.newButton = newButton;
    state.ioBox = ioBox;
    state.resultBox = resultBox;

    // 保存のきまりは画面のいちばん上に出す。表を触る前に知っておく話であり、
    // 使い方の詳細は「使い方」ボタンにまとめてある。
    view.appendChild(el('p.bulk-rule', {
      text: '1セルでもエラーがあれば、データベースには1件も保存しません。' +
            'エラーの位置は表に示します。'
    }));
    view.appendChild(toolbar);
    view.appendChild(ioBox);
    view.appendChild(wrap);
    view.appendChild(resultBox);

    bindGridEvents(table);
    io.bindDrop(wrap);
    renderRows();
    updateSummary();
    if (draftApplied) {
      var appliedRows = draftRows.map(function (row) { return row._result; }).filter(Boolean);
      renderSuccess({ created_count: appliedRows.length, rows: appliedRows });
    }
  }

  function buildGrid() {
    var table = el('table.bulk-grid.bulk-grid--postal', {
      role: 'grid',
      'aria-label': '郵便受付一括入力表'
    });

    var colgroup = el('colgroup');
    [60, 40, 70].forEach(function (width) {
      colgroup.appendChild(el('col', { style: 'width:' + width + 'px' }));
    });
    COLUMNS.forEach(function (column) {
      colgroup.appendChild(el('col', { style: 'width:' + column.width + 'px' }));
    });
    table.appendChild(colgroup);

    var thead = el('thead');
    var groupRow = el('tr.bulk-grid__groups');
    ['修正', '行', 'ステータス'].forEach(function (label) {
      groupRow.appendChild(el('th.bulk-grid__fixed-head', {
        text: label,
        rowSpan: 2,
        scope: 'col'
      }));
    });
    GROUPS.forEach(function (group) {
      groupRow.appendChild(el('th.bulk-grid__group', {
        text: group.label,
        colSpan: group.span,
        scope: 'colgroup'
      }));
    });

    var labelRow = el('tr.bulk-grid__labels');
    COLUMNS.forEach(function (column) {
      labelRow.appendChild(el('th', { text: column.label, scope: 'col', title: column.tooltip || column.label }));
    });

    thead.appendChild(groupRow);
    thead.appendChild(labelRow);
    table.appendChild(thead);
    table.appendChild(el('tbody'));
    return table;
  }

  function renderRows(focus) {
    if (!state || !state.tbody) return;
    var tbody = A.clear(state.tbody);

    draftRows.forEach(function (row, rowIndex) {
      var tr = el('tr', {
        dataset: { rowKey: row._key, rowIndex: String(rowIndex) },
        'class': row._errors.length ? 'has-error' : (row._result ? 'is-applied' : '')
      });

      tr.appendChild(el('td.bulk-grid__edit', {}, el('button.bulk-row-button', {
        type: 'button',
        text: '修正',
        disabled: state.applied,
        onClick: function () { openDrawer(row); }
      })));
      tr.appendChild(el('td.bulk-grid__number', { text: String(rowIndex + 1) }));
      tr.appendChild(el('td.bulk-grid__status', {}, rowStatus(row)));

      COLUMNS.forEach(function (column, columnIndex) {
        var errors = rowErrorsForField(row, column.key);
        var dataset = {
          rowKey: row._key,
          rowIndex: String(rowIndex),
          colIndex: String(columnIndex),
          field: column.key
        };

        var cell = el('td.bulk-cell' + (errors.length ? '.has-error' : ''), {
          contentEditable: state.applied ? 'false' : 'true',
          spellcheck: 'false',
          role: 'gridcell',
          tabIndex: state.applied ? -1 : 0,
          text: displayValue(row, column.key),
          title: errors.map(function (error) { return error.message; }).join('\n'),
          dataset: dataset
        });
        tr.appendChild(cell);
      });
      tbody.appendChild(tr);
    });

    paintSelection();
    if (focus) window.setTimeout(function () { focusCell(focus.row, focus.col); }, 0);
  }

  function rowStatus(row) {
    if (row._result) {
      return el('span.bulk-row-state.bulk-row-state--ok', {
        text: row._result.status === 'PENDING' ? '仮受付（登録済）' : '登録済',
        title: row._result.reservation_no || ''
      });
    }
    if (row._errors.length) {
      return el('span.bulk-row-state.bulk-row-state--error', {
        text: '入力エラー ' + row._errors.length + '件',
        title: row._errors.map(function (error) { return error.message; }).join('\n')
      });
    }
    if (isRowBlank(row)) return el('span.bulk-row-state', { text: '未入力' });
    return el('span.bulk-row-state.bulk-row-state--ready', { text: '入力済（未登録）' });
  }

  function bindGridEvents(table) {
    table.addEventListener('mousedown', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell || state.applied) return;
      var point = cellPoint(cell);
      if (event.shiftKey && state.anchor) {
        setSelection(state.anchor.row, state.anchor.col, point.row, point.col);
      } else {
        state.anchor = point;
        setSelection(point.row, point.col, point.row, point.col);
      }
      state.dragging = true;
    });

    table.addEventListener('mouseover', function (event) {
      if (!state.dragging || !state.anchor || state.applied) return;
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;
      var point = cellPoint(cell);
      setSelection(state.anchor.row, state.anchor.col, point.row, point.col);
    });

    document.addEventListener('mouseup', function () {
      if (state) state.dragging = false;
    });

    table.addEventListener('focusin', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell || state.applied) return;
      var point = cellPoint(cell);
      if (!state.selection || !cell.classList.contains('is-selected')) {
        state.anchor = point;
        setSelection(point.row, point.col, point.row, point.col);
      }
    });

    table.addEventListener('input', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell || state.applied) return;
      var row = rowByKey(cell.dataset.rowKey);
      if (!row) return;
      row[cell.dataset.field] = cell.textContent.replace(/\r?\n/g, ' ');
      clearFieldError(row, cell.dataset.field);
      markDirty();
      updateRowChrome(row);
      updateSummary();
    });

    table.addEventListener('keydown', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell || state.applied || event.isComposing || event.keyCode === 229) return;
      var point = cellPoint(cell);

      if (event.key === 'Tab') {
        event.preventDefault();
        moveFocus(point, event.shiftKey ? -1 : 1, 0, true);
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        moveFocus(point, 0, event.shiftKey ? -1 : 1, true);
        return;
      }
      if (event.key === 'Delete' && state.selection) {
        event.preventDefault();
        clearSelectionValues();
      }
    });

    table.addEventListener('paste', pasteIntoGrid);
    table.addEventListener('copy', copyFromGrid);
    table.addEventListener('cut', function (event) {
      copyFromGrid(event);
      if (!event.defaultPrevented || state.applied) return;
      clearSelectionValues();
    });
  }

  function cellPoint(cell) {
    return { row: Number(cell.dataset.rowIndex), col: Number(cell.dataset.colIndex) };
  }

  function setSelection(r1, c1, r2, c2) {
    state.selection = {
      r1: Math.min(r1, r2),
      c1: Math.min(c1, c2),
      r2: Math.max(r1, r2),
      c2: Math.max(c1, c2)
    };
    paintSelection();
  }

  function paintSelection() {
    if (!state || !state.table) return;
    var selection = state.selection;
    Array.prototype.forEach.call(state.table.querySelectorAll('td.bulk-cell'), function (cell) {
      var point = cellPoint(cell);
      var selected = selection && point.row >= selection.r1 && point.row <= selection.r2 &&
        point.col >= selection.c1 && point.col <= selection.c2;
      cell.classList.toggle('is-selected', Boolean(selected));
    });

    if (!selection) {
      state.selectionText.textContent = '選択中のセルなし';
      return;
    }
    var cellCount = (selection.r2 - selection.r1 + 1) * (selection.c2 - selection.c1 + 1);
    state.selectionText.textContent = (selection.r1 + 1) + '行 ・ ' +
      COLUMNS[selection.c1].label + (cellCount > 1 ? ' 他 ' + (cellCount - 1) + 'セル' : '');
  }

  function focusCell(rowIndex, colIndex) {
    if (!state || state.applied) return;
    if (rowIndex < 0 || colIndex < 0 || colIndex >= COLUMNS.length) return;
    if (rowIndex >= draftRows.length) return;
    var cell = state.table.querySelector(
      'td.bulk-cell[data-row-index="' + rowIndex + '"][data-col-index="' + colIndex + '"]'
    );
    if (!cell) return;
    state.anchor = { row: rowIndex, col: colIndex };
    setSelection(rowIndex, colIndex, rowIndex, colIndex);
    cell.focus();
    placeCaretAtEnd(cell);
    cell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function placeCaretAtEnd(node) {
    if (!window.getSelection || !document.createRange) return;
    var range = document.createRange();
    range.selectNodeContents(node);
    range.collapse(false);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function moveFocus(point, deltaCol, deltaRow, grow) {
    var row = point.row + deltaRow;
    var col = point.col + deltaCol;

    if (deltaCol) {
      if (col >= COLUMNS.length) { col = 0; row += 1; }
      if (col < 0) { col = COLUMNS.length - 1; row -= 1; }
    }

    if (row >= draftRows.length && grow && draftRows.length < MAX_ROWS) {
      draftRows.push(emptyRow());
      renderRows({ row: row, col: col });
      updateSummary();
      return;
    }
    focusCell(Math.max(0, row), col);
  }

  function parseClipboard(text) {
    var rows = [];
    var row = [];
    var cell = '';
    var quoted = false;

    for (var index = 0; index < text.length; index++) {
      var character = text[index];
      if (quoted) {
        if (character === '"' && text[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else if (character === '"') {
          quoted = false;
        } else {
          cell += character;
        }
        continue;
      }

      if (character === '"' && cell === '') {
        quoted = true;
      } else if (character === '\t') {
        row.push(cell);
        cell = '';
      } else if (character === '\r' || character === '\n') {
        if (character === '\r' && text[index + 1] === '\n') index += 1;
        row.push(cell);
        rows.push(row);
        row = [];
        cell = '';
      } else {
        cell += character;
      }
    }
    row.push(cell);
    rows.push(row);

    while (rows.length > 1 && rows[rows.length - 1].every(function (value) { return value === ''; })) {
      rows.pop();
    }
    return rows;
  }

  function pasteIntoGrid(event) {
    var cell = event.target.closest('td.bulk-cell');
    if (!cell || state.applied) return;
    var text = event.clipboardData && event.clipboardData.getData('text/plain');
    if (text === null || text === undefined) return;

    event.preventDefault();
    var matrix = parseClipboard(text);
    var start = cellPoint(cell);
    var width = matrix.reduce(function (max, row) { return Math.max(max, row.length); }, 0);

    if (start.col + width > COLUMNS.length) {
      A.toast('貼り付ける列が表の最終列を超えています。開始セルを左に移動してください。', 'danger');
      return;
    }
    if (start.row + matrix.length > MAX_ROWS) {
      A.toast('一度に入力できる行は最大 ' + MAX_ROWS + '行です。', 'danger');
      return;
    }

    while (draftRows.length < start.row + matrix.length) draftRows.push(emptyRow());
    matrix.forEach(function (values, rowOffset) {
      var row = draftRows[start.row + rowOffset];
      values.forEach(function (value, colOffset) {
        var key = COLUMNS[start.col + colOffset].key;
        row[key] = value;
        clearFieldError(row, key);
      });
    });

    markDirty();
    setSelection(start.row, start.col, start.row + matrix.length - 1, start.col + width - 1);
    renderRows({ row: start.row, col: start.col });
    updateSummary();
    A.toast(matrix.length + '行 × ' + width + '列を貼り付けました。', 'ok');
  }

  function clipboardValue(value) {
    var text = clean(value);
    if (/^[=+\-@]/.test(text)) text = "'" + text;
    if (/["\t\r\n]/.test(text)) text = '"' + text.replace(/"/g, '""') + '"';
    return text;
  }

  function copyFromGrid(event) {
    if (!state.selection || !event.clipboardData) return;
    var selection = state.selection;
    var lines = [];
    for (var rowIndex = selection.r1; rowIndex <= selection.r2; rowIndex++) {
      var values = [];
      for (var colIndex = selection.c1; colIndex <= selection.c2; colIndex++) {
        values.push(clipboardValue(draftRows[rowIndex][COLUMNS[colIndex].key]));
      }
      lines.push(values.join('\t'));
    }
    event.clipboardData.setData('text/plain', lines.join('\r\n'));
    event.preventDefault();
  }

  function clearSelectionValues() {
    if (!state.selection || state.applied) return;
    var selection = state.selection;
    for (var rowIndex = selection.r1; rowIndex <= selection.r2; rowIndex++) {
      for (var colIndex = selection.c1; colIndex <= selection.c2; colIndex++) {
        var key = COLUMNS[colIndex].key;
        draftRows[rowIndex][key] = '';
        clearFieldError(draftRows[rowIndex], key);
      }
    }
    markDirty();
    renderRows({ row: selection.r1, col: selection.c1 });
    updateSummary();
  }

  function addRows(count) {
    if (state.applied) return;
    var addCount = Math.min(count, MAX_ROWS - draftRows.length);
    if (!addCount) {
      A.toast('行は最大 ' + MAX_ROWS + '行まで作成できます。', 'warn');
      return;
    }
    for (var i = 0; i < addCount; i++) draftRows.push(emptyRow());
    renderRows({ row: draftRows.length - addCount, col: 0 });
    updateSummary();
  }

  function selectedRowIndexes() {
    if (!state.selection) return [];
    var rows = [];
    for (var index = state.selection.r1; index <= state.selection.r2; index++) rows.push(index);
    return rows;
  }

  function deleteSelectedRows() {
    if (state.applied) return;
    var indexes = selectedRowIndexes();
    if (!indexes.length) {
      A.toast('削除する行のセルを先に選択してください。', 'warn');
      return;
    }
    if (!window.confirm(indexes.length + '行を表から削除しますか？')) return;
    var remove = {};
    indexes.forEach(function (index) { remove[index] = true; });
    draftRows = draftRows.filter(function (_row, index) { return !remove[index]; });
    if (!draftRows.length) draftRows = initialRows(INITIAL_ROWS);
    state.selection = null;
    state.anchor = null;
    markDirty();
    renderRows();
    updateSummary();
  }

  function clearAllRows() {
    if (state.applied) return;
    if (nonBlankRows().length && !window.confirm('表に入力した内容をすべて削除しますか？')) return;
    draftRows = initialRows(INITIAL_ROWS);
    state.selection = null;
    state.anchor = null;
    state.globalErrors = [];
    draftDirty = false;
    renderRows();
    A.clear(state.resultBox);
    A.clear(state.ioBox);
    updateSummary();
  }

  function clearFieldError(row, key) {
    row._errors = (row._errors || []).filter(function (error) {
      if (error.field === key) return false;
      if (error.field === 'wishes' && key.indexOf('wish') === 0) return false;
      return true;
    });
  }

  function clearAllErrors() {
    draftRows.forEach(function (row) { row._errors = []; });
    state.globalErrors = [];
  }

  function updateRowChrome(row) {
    if (!state || !state.tbody) return;
    var tr = state.tbody.querySelector('tr[data-row-key="' + row._key + '"]');
    if (!tr) return;
    tr.classList.toggle('has-error', Boolean(row._errors.length));
    var status = tr.querySelector('.bulk-grid__status');
    if (status) { A.clear(status).appendChild(rowStatus(row)); }
  }

  function syncCell(row, key) {
    if (!state || !state.table) return;
    var cell = state.table.querySelector(
      'td.bulk-cell[data-row-key="' + row._key + '"][data-field="' + key + '"]'
    );
    if (!cell) return;
    cell.textContent = displayValue(row, key);
    var errors = rowErrorsForField(row, key);
    cell.classList.toggle('has-error', Boolean(errors.length));
    cell.title = errors.map(function (error) { return error.message; }).join('\n');
    updateRowChrome(row);
  }

  function markDirty() {
    if (!state.applied) draftDirty = true;
  }

  function updateSummary() {
    if (!state) return;
    var count = nonBlankRows().length;
    var errorCount = draftRows.reduce(function (sum, row) { return sum + row._errors.length; }, 0) +
      state.globalErrors.length;
    state.totalChip.textContent = '入力 ' + count + '件';
    state.errorChip.textContent = '入力エラー ' + errorCount + '件';
    state.errorChip.classList.toggle('is-hidden', errorCount === 0);
    state.applyButton.textContent = state.applying
      ? '検証・適用中…'
      : (count ? count + '件の予約を適用する' : '予約を適用する');

    state.applyButton.disabled = state.applying || state.applied || !count;
    state.newButton.classList.toggle('is-hidden', !state.applied);

    // 適用中はファイルボタンもロックする。適用が完了した表の取り込みは
    // `canImport` が防ぐ — 書き出しは残しておく。何を登録したか
    // ファイルで保管するほうがむしろ必要だ。
    if (io) io.setBusy(state.applying);
  }

  /* ----------------------------------------------------------------------
     右側詳細編集パネル
     ---------------------------------------------------------------------- */

  function openDrawer(row) {
    if (state.closeDrawer) state.closeDrawer();
    var root = document.getElementById('modal-root');
    var backdrop = el('div.bulk-drawer-backdrop');
    var panel = el('aside.bulk-drawer', {
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': '郵送受付行の詳細修正'
    });

    function close() {
      backdrop.remove();
      document.removeEventListener('keydown', onKey);
      if (state && state.closeDrawer === close) state.closeDrawer = null;
    }
    function onKey(event) {
      if (event.key === 'Escape') close();
    }

    var currentIndex = draftRows.indexOf(row);
    panel.appendChild(el('div.bulk-drawer__head', {}, [
      el('div', {}, [
        el('p.bulk-drawer__eyebrow', { text: (currentIndex + 1) + '行目の詳細入力' }),
        el('h2.bulk-drawer__title', { text: '郵送受付の修正' }),
        el('p.bulk-drawer__desc', { text: 'ここで修正した内容は、入力するとすぐに左の表に反映されます。' })
      ]),
      el('button.bulk-drawer__close', {
        type: 'button', text: '×', 'aria-label': '閉じる', onClick: close
      })
    ]));

    var body = el('div.bulk-drawer__body');
    body.appendChild(drawerSection('① 申込者', applicantFields(row)));
    body.appendChild(drawerSection('② 保険証', insuranceFields(row)));
    body.appendChild(drawerSection('③ 住所・連絡先', contactFields(row)));
    body.appendChild(drawerSection('④ 希望受診日時', wishFields(row)));
    body.appendChild(drawerSection('⑤ オプション検査', optionFields(row)));
    body.appendChild(drawerSection('⑥ メモ・登録方式', memoFields(row)));
    panel.appendChild(body);

    panel.appendChild(el('div.bulk-drawer__foot', {}, [
      el('span', { text: 'すべての変更は表に反映されました。' }),
      el('button.btn.btn--primary', { type: 'button', text: '閉じる', onClick: close })
    ]));

    backdrop.appendChild(panel);
    root.appendChild(backdrop);
    state.closeDrawer = close;
    document.addEventListener('keydown', onKey);

    var first = panel.querySelector('input, select, textarea');
    if (first) first.focus();
  }

  function drawerSection(title, content) {
    return el('section.bulk-drawer__section', {}, [
      el('h3.bulk-drawer__section-title', { text: title }),
      content
    ]);
  }

  function fieldError(row, key) {
    var errors = rowErrorsForField(row, key);
    return errors.length ? errors.map(function (error) { return error.message; }).join(' / ') : '';
  }

  function decorateDrawerField(field, row, key) {
    var message = fieldError(row, key);
    if (message) {
      field.classList.add('has-error');
      field.appendChild(el('p.bulk-field-error', { text: message }));
    }
    return field;
  }

  function drawerInput(row, key, attrs) {
    attrs = Object.assign({ autocomplete: 'off' }, attrs || {});
    var input = A.input(attrs);
    input.value = clean(row[key]);
    input.addEventListener('input', function () {
      row[key] = input.value;
      clearFieldError(row, key);
      input.closest('.field').classList.remove('has-error');
      var error = input.closest('.field').querySelector('.bulk-field-error');
      if (error) error.remove();
      syncCell(row, key);
      markDirty();
      updateSummary();
    });
    return input;
  }

  function drawerText(row, label, key, attrs, options) {
    var input = drawerInput(row, key, attrs);
    return decorateDrawerField(A.field(label, input, options || {}), row, key);
  }

  function applicantFields(row) {
    var gender = A.select({}, [
      { value: '', label: '選択してください' },
      { value: 'M', label: '男性 (M)' },
      { value: 'F', label: '女性 (F)' }
    ]);
    gender.value = clean(row.gender);
    gender.addEventListener('change', function () {
      row.gender = gender.value;
      clearFieldError(row, 'gender');
      syncCell(row, 'gender');
      markDirty();
      updateSummary();
    });

    return el('div.grid.grid--2', {}, [
      drawerText(row, '姓', 'last_name', {}, { required: true }),
      drawerText(row, '名', 'first_name', {}, { required: true }),
      drawerText(row, '姓フリガナ', 'last_name_kana', { placeholder: 'タナカ' }),
      drawerText(row, '名フリガナ', 'first_name_kana', { placeholder: 'タロウ' }),
      drawerText(row, 'ミドルネーム', 'middle_name'),
      drawerText(row, 'ミドルネームフリガナ', 'middle_name_kana'),
      decorateDrawerField(A.field('性別', gender, { required: true }), row, 'gender'),
      drawerText(row, '生年月日', 'birth_date', { type: 'date', birth: true }, { required: true })
    ]);
  }

  function insuranceFields(row) {
    return el('div.grid.grid--3', {}, [
      drawerText(row, '保険者番号', 'insurer_no'),
      drawerText(row, '保険証記号', 'insurance_symbol'),
      drawerText(row, '保険証番号', 'insurance_no')
    ]);
  }

  function contactFields(row) {
    var postal = drawerInput(row, 'postal_code', { placeholder: '101-0021' });
    var address = drawerInput(row, 'address');
    return el('div.grid.grid--2', {}, [
      A.field('住所検索', A.addressSearch(postal, address), { span: 'span-full' }),
      decorateDrawerField(A.field('郵便番号', postal), row, 'postal_code'),
      decorateDrawerField(A.field('住所', address), row, 'address'),
      drawerText(row, '番地', 'address_detail'),
      drawerText(row, 'アパート・マンション名', 'building'),
      drawerText(row, '携帯電話', 'tel_mobile', { placeholder: '090-1234-5678' }),
      drawerText(row, '固定電話', 'tel_home', { placeholder: '03-1234-5678' }),
      drawerText(row, 'メールアドレス', 'email', { type: 'email' }, { span: 'span-full' })
    ]);
  }

  function wishFields(row) {
    var box = el('div.bulk-wishes');
    for (var rank = 1; rank <= 3; rank++) box.appendChild(wishEditor(row, rank));
    return box;
  }

  function hospitalValue(hospital) {
    return hospital.code || hospital.name;
  }

  function hospitalMatches(hospital, value) {
    var normalized = clean(value).toLocaleLowerCase();
    return clean(hospital.code).toLocaleLowerCase() === normalized || clean(hospital.name) === clean(value);
  }

  function wishEditor(row, rank) {
    var hospitalKey = 'wish' + rank + '_hospital';
    var dateKey = 'wish' + rank + '_date';
    var timeKey = 'wish' + rank + '_time';
    var hospital = A.select({}, [{ value: '', label: '会場を選択' }].concat(
      filters.hospitals.map(function (item) {
        return {
          value: hospitalValue(item),
          label: (item.code ? item.code + ' · ' : '') + item.name + (item.is_visible ? '' : ' （Web非表示）')
        };
      })
    ));
    var currentHospital = clean(row[hospitalKey]);
    var matchedHospital = filters.hospitals.find(function (item) {
      return hospitalMatches(item, currentHospital);
    });
    if (currentHospital && !matchedHospital) {
      hospital.appendChild(el('option', { value: currentHospital, text: currentHospital + ' （表の入力値）' }));
    }
    hospital.value = matchedHospital ? hospitalValue(matchedHospital) : currentHospital;

    // 受診日は自由入力ではなく、選んだ会場の開催日から選ぶ。
    // 会場は数日しか開かないので、日付を手で打たせると存在しない日を
    // 書いてしまい、保存時に初めてエラーになる。単件入力(postal.js)と
    // 同じつくりに揃える。
    var dateInput = A.select({}, [{ value: '', label: '会場を先に選択' }]);
    var currentDate = clean(row[dateKey]);
    var timeSelect = A.select({}, [{ value: '', label: '開始時刻を選択' }]);
    var currentTime = clean(row[timeKey]);

    function updateDateOptions() {
      A.clear(dateInput);
      var selected = filters.hospitals.find(function (item) {
        return hospitalMatches(item, hospital.value);
      });
      var schedules = (selected && selected.schedules) || [];

      if (!selected) {
        dateInput.appendChild(el('option', { value: '', text: '会場を先に選択' }));
        dateInput.disabled = true;
      } else if (!schedules.length) {
        dateInput.appendChild(el('option', { value: '', text: '開催日が登録されていません' }));
        dateInput.disabled = true;
      } else {
        dateInput.appendChild(el('option', { value: '', text: '受診日を選択' }));
        schedules.forEach(function (s) {
          dateInput.appendChild(el('option', {
            value: s.event_date,
            text: A.fmt.date(s.event_date) + (s.is_past ? ' （終了）' : '')
          }));
        });
        dateInput.disabled = false;
      }

      // 表に入っている値が候補になければ、消さずに残して見せる。
      if (currentDate && !Array.prototype.some.call(dateInput.options, function (o) {
        return o.value === currentDate;
      })) {
        dateInput.appendChild(el('option', {
          value: currentDate, text: currentDate + ' （表の入力値）'
        }));
      }
      dateInput.value = currentDate;
    }

    function sync(key, value) {
      row[key] = value;
      clearFieldError(row, key);
      syncCell(row, key);
      markDirty();
      updateSummary();
    }

    function addCurrentTime() {
      if (currentTime && !Array.prototype.some.call(timeSelect.options, function (option) {
        return option.value === currentTime;
      })) {
        timeSelect.appendChild(el('option', { value: currentTime, text: currentTime + ' （表の入力値）' }));
      }
      timeSelect.value = currentTime;
    }

    function loadSlots() {
      A.clear(timeSelect).appendChild(el('option', { value: '', text: '開始時刻を選択' }));
      var selectedHospital = filters.hospitals.find(function (item) {
        return hospitalMatches(item, hospital.value);
      });
      if (!selectedHospital || !dateInput.value) {
        addCurrentTime();
        return;
      }
      timeSelect.disabled = true;
      timeSelect.appendChild(el('option', { value: '', text: '読み込み中…', disabled: true }));
      A.api.get('/reservations/slots' + A.query({
        hospital_id: selectedHospital.id,
        date: dateInput.value
      })).then(function (body) {
        if (!timeSelect.isConnected) return;
        A.clear(timeSelect).appendChild(el('option', { value: '', text: '開始時刻を選択' }));
        body.data.forEach(function (slot) {
          var start = String(slot.time_label).split('~')[0];
          timeSelect.appendChild(el('option', {
            value: start,
            text: slot.time_label + ' — ' + (slot.selectable
              ? '残り ' + slot.remaining + '枠'
              : slot.reason + ' （希望として記録可能）')
          }));
        });
        addCurrentTime();
        timeSelect.disabled = false;
      }).catch(function (error) {
        if (!timeSelect.isConnected) return;
        A.clear(timeSelect).appendChild(el('option', { value: currentTime, text: error.message }));
        timeSelect.disabled = false;
      });
    }

    hospital.addEventListener('change', function () {
      // 会場が変われば、その会場の開催日をすぐ出す。前の会場の日付は残さない。
      currentDate = '';
      currentTime = '';
      sync(hospitalKey, hospital.value);
      sync(dateKey, '');
      sync(timeKey, '');
      updateDateOptions();
      loadSlots();
    });
    dateInput.addEventListener('change', function () {
      currentDate = dateInput.value;
      currentTime = '';
      sync(dateKey, currentDate);
      sync(timeKey, '');
      loadSlots();
    });
    timeSelect.addEventListener('change', function () {
      currentTime = timeSelect.value;
      sync(timeKey, currentTime);
    });
    updateDateOptions();   // 開いた時点で、すでに選ばれている会場の開催日を出す
    loadSlots();

    return el('div.bulk-wish', {}, [
      el('strong.bulk-wish__rank', { text: '第' + rank + '希望' }),
      el('div.bulk-wish__fields', {}, [
        decorateDrawerField(A.field('会場', hospital), row, hospitalKey),
        decorateDrawerField(A.field('受診日', dateInput), row, dateKey),
        decorateDrawerField(A.field('開始時刻', timeSelect), row, timeKey)
      ])
    ]);
  }

  function optionFields(row) {
    var selected = {};
    splitOptionCodes(row.option_codes).forEach(function (code) { selected[code.toLocaleLowerCase()] = true; });
    var list = el('div.grid.grid--2');
    filters.exam_options.forEach(function (option) {
      if (!option.is_active) return;
      var control = A.checkbox(option.code + ' · ' + option.name, {
        value: option.code,
        checked: Boolean(selected[option.code.toLocaleLowerCase()])
      });
      control.querySelector('input').addEventListener('change', function () {
        var codes = Array.prototype.map.call(
          list.querySelectorAll('input:checked'), function (input) { return input.value; }
        );
        row.option_codes = codes.join(';');
        clearFieldError(row, 'option_codes');
        syncCell(row, 'option_codes');
        markDirty();
        updateSummary();
      });
      list.appendChild(control);
    });
    var message = fieldError(row, 'option_codes');
    return el('div', {}, [list, message ? el('p.bulk-field-error', { text: message }) : null]);
  }

  function memoFields(row) {
    var memo = A.textarea({ rows: 4, placeholder: '申込書で判読が難しかった箇所など' });
    memo.value = clean(row.memo);
    memo.addEventListener('input', function () {
      row.memo = memo.value;
      clearFieldError(row, 'memo');
      syncCell(row, 'memo');
      markDirty();
      updateSummary();
    });

    var allow = A.checkbox('必須情報が空欄でも不備状態(PENDING)として仮受付', {
      checked: truthy(row.allow_defect)
    });
    allow.querySelector('input').addEventListener('change', function (event) {
      row.allow_defect = event.target.checked;
      clearFieldError(row, 'allow_defect');
      syncCell(row, 'allow_defect');
      markDirty();
      updateSummary();
    });

    return el('div', {}, [
      decorateDrawerField(A.field('スタッフメモ', memo), row, 'memo'),
      el('div.bulk-defect-toggle', {}, [allow]),
      fieldError(row, 'allow_defect') ? el('p.bulk-field-error', { text: fieldError(row, 'allow_defect') }) : null
    ]);
  }

  function truthy(value) {
    if (value === true) return true;
    var normalized = clean(value).toLocaleLowerCase();
    return ['1', 'true', 'yes', 'y', 'はい', '許可'].indexOf(normalized) >= 0;
  }

  function allowDefectValue(value) {
    if (value === true || value === false) return value;
    var normalized = clean(value).toLocaleLowerCase();
    if (!normalized || ['0', 'false', 'no', 'n', 'いいえ', '不許可'].indexOf(normalized) >= 0) {
      return false;
    }
    if (truthy(value)) return true;
    // 不明な貼り付け値はfalseで上書きせずサーバーのセル検証に送信する。
    return value;
  }

  function splitOptionCodes(value) {
    if (Array.isArray(value)) return value.map(clean).filter(Boolean);
    return clean(value).split(/[;,，、\n\r]+/).map(clean).filter(Boolean);
  }

  /* ----------------------------------------------------------------------
     ファイル入出力（CSV・Excel）
     --------------------------------------------------------------------
     書き出し・取り込み・ドラッグ＆ドロップ・「クリアして配置 / 追記」・読み込み結果
     のサマリーはすべて `grid-io.js` が行う。以前はその250行がこのファイル内に
     あり、会場・定員・オプション検査の表に同じボタンを追加したことで **4セット**になる
     ところだった。

     この画面の表は `A.grid` ではなく独自実装である。そのためヘルパーが
     要求する **4つ**だけを備えた薄いラッパーを作成して渡す。

         columns · dataRows() · displayValue(row, col) · setRows(rows)

     列ラベル・順序・ファイル形式はサーバーが決定する。ここでやり取りするのは
     `last_name` のような **列キーをそのまま使用したフラットな行**のみである。
     ---------------------------------------------------------------------- */

  function buildIO() {
    var adapter = {
      columns: COLUMNS,

      dataRows: nonBlankRows,

      // ヘルパーは列オブジェクトを渡し、この画面のdisplayValueは列キーを受け取る。
      displayValue: function (row, column) {
        return displayValue(row, column.key);
      },

      /**
       * 取り込んだ行で表を差し替える。
       *
       * ヘルパーは「クリアして挿入」と「追記」をすでに結合して渡す。
       * ここではそれをこの画面の行形式に変換して格納するだけだ。
       */
      setRows: function (rows, info) {
        draftRows = (rows || []).map(function (values) {
          var row = emptyRow();
          COLUMNS.forEach(function (column) {
            var value = values[column.key];
            var text = (value === null || value === undefined) ? '' : String(value);
            row[column.key] = KANA_KEYS.indexOf(column.key) === -1 ? text : A.toKatakana(text);
          });
          return row;
        });

        // 続けて入力できるように空行を残す。完全に埋まった状態で終わると、値をもう1つ
        // 入力するためにまず「行追加」を押さなければならなくなる。
        var target = Math.min(MAX_ROWS, draftRows.length + 3);
        while (draftRows.length < target) draftRows.push(emptyRow());

        clearAllErrors();
        A.clear(state.resultBox);
        state.selection = null;
        state.anchor = null;
        markDirty();
        // 追記した場合は新しく入った先頭行にカーソルを移動する。
        renderRows({ row: (info && info.kept) || 0, col: 0 });
        updateSummary();
      }
    };

    return A.gridIO.attach({
      grid: adapter,
      exportPath: '/reservations/postal/bulk/export',
      importPath: '/reservations/postal/bulk/import',
      label: '予約',
      unit: '件',
      maxRows: MAX_ROWS,

      // 適用済みの表はこれ以上変更できない。ヘルパーがこの画面の事情を知る必要は
      // ないため、問い合わせがあれば応答する形にしておく。
      canImport: function () {
        if (state && state.applied) {
          A.toast('すでに適用済みの表です。「新規一括入力を開始」を押してから' +
                  '取り込んでください。', 'warn');
          return false;
        }
        return !(state && state.applying);
      },

      onImported: function () { updateSummary(); }
    });
  }

  /* ----------------------------------------------------------------------
     サーバー適用
     ---------------------------------------------------------------------- */

  // 표·드로어·파일 어디서 들어와도 같은 표기가 되도록 한곳에서 바꾼다.
  var KANA_KEYS = ['last_name_kana', 'first_name_kana', 'middle_name_kana'];

  function rowPayload(row, rowNo) {
    var payload = { row_no: rowNo };
    [
      'last_name', 'first_name', 'last_name_kana', 'first_name_kana',
      'middle_name', 'middle_name_kana', 'gender', 'birth_date',
      'insurer_no', 'insurance_symbol', 'insurance_no', 'postal_code',
      'address', 'address_detail', 'building', 'tel_mobile', 'tel_home',
      'email', 'memo'
    ].forEach(function (key) {
      var value = clean(row[key]);
      payload[key] = KANA_KEYS.indexOf(key) === -1 ? value : A.toKatakana(value);
    });

    payload.wishes = [];
    for (var rank = 1; rank <= 3; rank++) {
      var hospital = clean(row['wish' + rank + '_hospital']);
      var date = clean(row['wish' + rank + '_date']);
      var time = clean(row['wish' + rank + '_time']);
      if (hospital || date || time) {
        payload.wishes.push({ rank: rank, hospital: hospital, date: date, time: time });
      }
    }
    payload.option_codes = splitOptionCodes(row.option_codes);
    payload.allow_defect = allowDefectValue(row.allow_defect);
    return payload;
  }

  function collectPayload() {
    var rows = [];
    var rowMap = {};
    draftRows.forEach(function (row, index) {
      if (isRowBlank(row)) return;
      var rowNo = index + 1;
      rows.push(rowPayload(row, rowNo));
      rowMap[rowNo] = row;
    });
    return { rows: rows, map: rowMap };
  }

  function applyReservations() {
    if (state.applying || state.applied) return;
    var collected = collectPayload();
    if (!collected.rows.length) {
      A.toast('適用する予約を1行以上入力してください。', 'warn');
      return;
    }

    A.confirm({
      title: '予約を一括適用しますか？',
      message: collected.rows.length + '件をすべてチェックした後、実際の予約として保存します。',
      detail: '1セルでもエラーがある場合は全体を保存せず、エラー箇所を表に表示します。',
      okLabel: collected.rows.length + '件適用',
      tone: 'primary'
    }).then(function (confirmed) {
      if (!confirmed || state.applying || state.applied) return;
      clearAllErrors();
      state.applying = true;
      state.applyButton.disabled = true;
      updateSummary();
      A.clear(state.resultBox).appendChild(A.loading('入力値と予約定員を確認しています…'));

      A.api.post('/reservations/postal/bulk', { rows: collected.rows })
        .then(function (body) {
          state.applied = true;
          draftApplied = true;
          draftDirty = false;
          body.data.rows.forEach(function (result) {
            var row = collected.map[result.row_no];
            if (row) row._result = result;
          });
          renderRows();
          renderSuccess(body.data);
          if (A.refreshAttentionBadge) A.refreshAttentionBadge();
          A.toast(body.data.created_count + '件の予約を適用しました。', 'ok');
        })
        .catch(function (error) {
          applyServerErrors(error, collected.map);
        })
        .then(function () {
          state.applying = false;
          updateSummary();
        });
    });
  }

  function applyServerErrors(error, rowMap) {
    var body = error.body || {};
    var errors = body.errors || [];

    if (!errors.length && body.fields) {
      errors = body.fields.map(function (field) {
        var matched = String(field.name || '').match(/^rows\.(\d+)\.(.+)$/);
        return matched
          ? { row_no: Number(matched[1]) + 1, field: matched[2], message: field.message }
          : { row_no: 0, field: field.name || 'rows', message: field.message };
      });
    }
    if (!errors.length) errors = [{ row_no: 0, field: 'rows', message: error.message }];

    var first = null;
    errors.forEach(function (item) {
      var row = rowMap[item.row_no];
      if (!row) {
        state.globalErrors.push(item);
        return;
      }
      row._errors.push(item);
      if (!first) first = { row: draftRows.indexOf(row), col: errorColumn(item.field) };
    });

    renderRows(first);

    var box = A.clear(state.resultBox);
    box.appendChild(A.notice(
      'danger',
      '入力エラー ' + errors.length + '件をご確認ください。予約は1件も保存されていません。'
    ));
    box.appendChild(errorList(errors, rowMap));

    updateSummary();
    A.toast('入力エラーがあるため、全体の適用を中断しました。', 'danger');
  }

  /* 何がなぜ間違っているかを一覧で表示する。

     赤いセルとツールチップだけでは不十分である。どのセルが間違っているかは見えるが
     「なぜ」はマウスを1つずつ乗せてみないと分からず、200行まで入る
     画面では事実上読めないのと同じである。

     1行に「行・列名 — 理由」をそのまま記載し、押すとそのセルに移動する。
     担当者が一覧を上から下へ目を通しながら修正できるようにする必要がある。 */
  function errorList(errors, rowMap) {
    var list = el('ul.bulk-errorlist');

    errors.forEach(function (item) {
      var column = COLUMNS[errorColumn(item.field)];
      var where = [];
      if (item.row_no) where.push(item.row_no + '行');
      if (column && item.field !== 'rows') where.push(column.label);

      var line = el('li.bulk-errorlist__item', {}, [
        el('span.bulk-errorlist__where', { text: where.join(' · ') || '全体' }),
        el('span.bulk-errorlist__msg', { text: item.message })
      ]);

      // 該当セルが表に実際に存在する場合のみ移動ボタンのように動作させる。
      var targetRow = rowMap ? rowMap[item.row_no] : null;
      var rowIndex = targetRow ? draftRows.indexOf(targetRow) : -1;

      if (rowIndex >= 0 && column) {
        line.classList.add('is-linked');
        line.setAttribute('role', 'button');
        line.setAttribute('tabindex', '0');
        line.title = 'このセルに移動します。';
        var jump = function () { focusCell(rowIndex, errorColumn(item.field)); };
        line.addEventListener('click', jump);
        line.addEventListener('keydown', function (event) {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            jump();
          }
        });
      }

      list.appendChild(line);
    });

    return list;
  }

  function errorColumn(field) {
    if (COLUMN_BY_KEY[field]) return COLUMN_BY_KEY[field].index;
    var matched = String(field || '').match(/^wishes\.(\d+)\.(hospital|date|time)$/);
    if (matched) {
      var key = 'wish' + (Number(matched[1]) + 1) + '_' + matched[2];
      if (COLUMN_BY_KEY[key]) return COLUMN_BY_KEY[key].index;
    }
    if (field === 'wishes') return COLUMN_BY_KEY.wish1_hospital.index;
    return 0;
  }

  function renderSuccess(data) {
    var box = A.clear(state.resultBox);
    box.appendChild(el('div.bulk-result__head', {}, [
      el('div', {}, [
        el('h2.bulk-result__title', { text: '予約適用完了' }),
        el('p.bulk-result__desc', { text: data.created_count + '件がすべて保存されました。この表は再適用できません。' })
      ]),
      el('button.btn.btn--sm', { type: 'button', text: '新しい表を開始', onClick: startNewBatch })
    ]));

    var wrap = el('div.table-wrap');
    var table = el('table.table');
    var head = el('tr', {}, [
      el('th', { text: '行' }), el('th', { text: '予約番号' }),
      el('th', { text: 'ステータス' }), el('th', { text: '会場' }),
      el('th', { text: '受診日時' }), el('th', { text: '割当' }),
      el('th', { text: '詳細' })
    ]);
    table.appendChild(el('thead', {}, head));
    var tbody = el('tbody');
    data.rows.forEach(function (result) {
      tbody.appendChild(el('tr', {}, [
        el('td', { text: result.row_no }),
        el('td.mono', { text: result.reservation_no }),
        el('td', {}, A.statusBadge(result.status, result.status_label)),
        el('td', { text: result.hospital_name }),
        el('td', { text: result.slot_date + ' ' + result.time_label }),
        el('td', { text: '第' + result.used_choice + '希望' }),
        el('td', {}, el('a.btn.btn--sm', { href: '#/reservation?id=' + result.id, text: '詳細を見る' }))
      ]));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    box.appendChild(wrap);
  }

  function startNewBatch() {
    if (!state.applied && nonBlankRows().length && !window.confirm('現在の表をクリアして新しい一括入力を開始しますか？')) return;
    if (state.closeDrawer) state.closeDrawer();
    draftRows = initialRows(INITIAL_ROWS);
    draftDirty = false;
    draftApplied = false;
    draw(state.view);
  }

  /* ページ終了・別メニュー移動時に未適用の個人情報が失われることを警告する。 */
  window.addEventListener('beforeunload', function (event) {
    if (!draftDirty) return;
    event.preventDefault();
    event.returnValue = '';
  });

  document.addEventListener('click', function (event) {
    if (!isCurrentRoute() || !draftDirty || !state || state.applied) return;
    var link = event.target.closest('a[href^="#/"]');
    if (!link || link.getAttribute('href') === '#/postal-bulk') return;
    if (!window.confirm('適用されていない一括入力があります。他の画面に移動しますか？')) {
      event.preventDefault();
      event.stopPropagation();
    } else {
      draftDirty = false;
    }
  }, true);

})();
