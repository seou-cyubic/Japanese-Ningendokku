/* ==========================================================================
   grid-io.js — 표의 파일 입출력 (공용)
   --------------------------------------------------------------------------
   왜 따로 뺐는가
   --------------
   같은 코드가 `bulk-postal.js` 에만 250줄쯤 들어 있었다. 회장·정원·옵션
   검사 표에도 같은 버튼을 달면 **네 벌**이 된다. 내보내기·가져오기·
   끌어다 놓기·「비우고 넣기 / 이어붙이기」·읽은 결과 요약을 네 곳에서
   각각 고치게 된다.

   무엇을 하는가
   -------------
     · CSV 내보내기 / EXCEL 내보내기 / 가져오기 버튼
     · 표 위로 파일 끌어다 놓기
     · 이미 입력된 표가 있으면 「비우고 넣기 / 이어붙이기」를 묻는다
     · 무엇을 어떻게 읽었는지 요약 — 파일명·시트·인코딩·붙은 열 수·
       건너뛴 빈 행·제목 줄을 못 찾음·버린 열

   무엇을 하지 않는가
   ------------------
   **저장하지 않는다.** 가져오기는 표에 올려 놓기만 하고, 저장은 각 화면의
   저장 버튼이 한다. 파일을 올린 것과 마스터에 넣은 것은 다른 일이다 —
   그 둘을 한 번에 하면 되돌릴 기회가 없다.

   어떤 표에든 붙는다
   ------------------
   표가 `A.grid` 로 만든 것일 필요는 없다. 필요한 것은 **네 가지뿐**이다.

       columns                 [{ key, label }]
       dataRows()              빈 행을 뺀 지금의 행들
       displayValue(row, col)  그 칸을 파일에 적을 글자
       setRows(rows)           행을 통째로 갈아 끼운다

   `A.grid` 는 이 넷을 이미 갖고 있으므로 그대로 넘기면 되고, 자체 표를
   쓰는 화면(우편 접수 일괄 입력)은 같은 모양의 객체를 만들어 넘긴다.
   이 파일이 `A.grid` 를 직접 알면, 그 화면은 영영 이 헬퍼를 못 쓴다.

   쓰는 법
   -------
       var io = A.gridIO.attach({
         grid: grid,
         sheet: 'venues',            // /bulk/<sheet>/export · /import
         label: '회장', unit: '곳',
         onImported: function (count, summary) { updateSummary(); }
       });
       toolbar.appendChild(io.node);   // 버튼 묶음
       view.appendChild(io.noticeBox); // 읽은 결과 요약이 뜨는 자리
       io.bindDrop(grid.node);

   주소가 `/bulk/<sheet>/…` 가 아닌 표는 직접 준다.

       A.gridIO.attach({
         grid: adapter,
         exportPath: '/reservations/postal/bulk/export',
         importPath: '/reservations/postal/bulk/import',
         maxRows: 200,
         canImport: function () { … },   // 지금 가져와도 되는가
         …
       })
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var ACCEPT_EXTENSIONS = /\.(csv|tsv|txt|xlsx|xlsm)$/i;
  var MAX_UPLOAD_BYTES = 2 * 1024 * 1024;   // 서버(sheet_io.MAX_UPLOAD_BYTES)와 같다
  var FORMAT_LABEL = { csv: 'CSV', xlsx: 'Excel' };

  function attach(options) {
    var grid = options.grid;
    var sheet = options.sheet;
    var label = options.label || '行';
    var unit = options.unit || '件';
    var onImported = options.onImported || function () {};
    var maxRows = options.maxRows || A.grid.MAX_ROWS;
    // 지금 가져와도 되는지 물어본다. 「이미 적용한 표」처럼 표마다 다른
    // 사정이 있고, 그것을 이 파일이 알 필요는 없다.
    var canImport = options.canImport || function () { return true; };

    var exportPath = options.exportPath || ('/bulk/' + sheet + '/export');
    var importPath = options.importPath || ('/bulk/' + sheet + '/import');

    // 표가 열을 따로 알려 주면 그것을, 아니면 표가 그리는 열 그대로.
    var columns = options.columns || grid.columns;

    var busy = false;
    var noticeBox = el('div.bulk-io');

    var fileInput = el('input', {
      type: 'file',
      accept: '.csv,.tsv,.txt,.xlsx,.xlsm',
      style: 'display:none',
      onChange: function (event) {
        var file = event.target.files && event.target.files[0];
        // 같은 파일을 다시 고를 수 있게 비운다. 비우지 않으면 두 번째
        // 선택에서 change 가 오지 않아 「눌러도 아무 일이 없다」가 된다.
        event.target.value = '';
        if (file) importFile(file);
      }
    });

    var importButton = el('button.btn.btn--sm', {
      type: 'button',
      text: '取り込み',
      title: 'CSV または Excel(.xlsx) ファイルを表に取り込みます。表の上にドラッグ＆ドロップすることもできます。',
      onClick: function () { fileInput.click(); }
    });

    var csvButton = el('button.btn.btn--sm.btn--csv', {
      type: 'button',
      text: 'CSV 書き出し',
      title: '現在の表を CSV でダウンロードします。Excel でそのまま開けます。',
      onClick: function () { exportSheet('csv'); }
    });

    var xlsxButton = el('button.btn.btn--sm.btn--csv', {
      type: 'button',
      text: 'EXCEL 書き出し',
      title: '現在の表を Excel(.xlsx) ファイルでダウンロードします。',
      onClick: function () { exportSheet('xlsx'); }
    });

    var node = el('div.bulk-toolbar__group', {}, [
      importButton, csvButton, xlsxButton, fileInput
    ]);

    function setBusy(next) {
      busy = Boolean(next);
      [importButton, csvButton, xlsxButton].forEach(function (button) {
        button.disabled = busy;
      });
    }

    /* --- 내보내기 --------------------------------------------------------
       **화면의 표를 그대로** 내보낸다. 서버가 DB 를 다시 읽지 않는다.
       고치던 값을 Excel 로 꺼내 마저 고치는 것이 이 버튼의 쓰임이다.
       그래서 검증도 하지 않는다 — 형식이 틀린 값을 꺼내려는 것이니까. */

    function rowsForFile() {
      return grid.dataRows().map(function (row) {
        var values = {};
        columns.forEach(function (column) {
          // 파일에는 사람이 읽는 말을 담는다 (`F` 가 아니라 「여성만」).
          values[column.key] = grid.displayValue(row, column);
        });
        return values;
      });
    }

    function exportSheet(format) {
      if (busy) return;

      var rows = rowsForFile();
      setBusy(true);

      A.api.download(exportPath + '?format=' + format, { rows: rows })
        .then(function (fileName) {
          A.toast(rows.length
            ? rows.length + unit + 'を ' + FORMAT_LABEL[format] +
              ' ファイルとしてダウンロードしました。(' + fileName + ')'
            : '空のフォーマットをダウンロードしました。見出し行に合わせて入力した後、' +
              '「取り込み」からアップロードしてください。',
            'ok');
        })
        .catch(function (error) { A.toast(error.message, 'danger'); })
        .then(function () { setBusy(false); });
    }

    /* --- 가져오기 -------------------------------------------------------- */

    function importFile(file) {
      if (busy) return;
      if (!canImport()) return;

      // 왕복이 무의미한 두 가지만 여기서 거른다. 형식·인코딩 판정과
      // 제목 줄 대조는 서버가 한다 — 판정이 두 곳에 있으면 갈라진다.
      if (!ACCEPT_EXTENSIONS.test(file.name || '')) {
        A.toast('CSV(.csv) またはExcel(.xlsx)ファイルのみ取り込めます。', 'danger');
        return;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        A.toast('ファイルサイズが大きすぎます。2MB以下にしてください。', 'danger');
        return;
      }

      setBusy(true);
      A.clear(noticeBox).appendChild(A.loading(file.name + ' を読み込んでいます…'));

      A.api.upload(importPath, file)
        .then(function (body) {
          A.clear(noticeBox);
          askMode(body.data);
        })
        .catch(function (error) {
          A.clear(noticeBox).appendChild(A.notice('danger', error.message));
          A.toast(error.message, 'danger');
        })
        .then(function () { setBusy(false); });
    }

    /**
     * 이미 입력된 표가 있으면 어디에 넣을지 묻는다.
     *
     * 여기서 「비운다」는 것은 **화면의 표**다. DB 는 저장을 누르기 전까지
     * 바뀌지 않는다. 예전 문구(「표를 비우고 넣기」)가 DB 를 비우는 것으로
     * 읽혀, 그 말을 문장으로 풀어 둔다.
     */
    function askMode(data) {
      var existing = grid.dataRows().length;
      if (!existing) {
        applyImported(data, 'replace');
        return;
      }

      A.modal({
        title: '取り込んだ表をどこに追加しますか？',
        size: 'slim',
        body: [
          el('p', {
            style: 'margin:0 0 8px;line-height:1.7',
            text: '表にすでに  ' + existing + unit + 'あります。' +
                  'ファイルから読み込んだ  ' + data.rows.length + '行をどのように追加するか選択してください。'
          }),
          el('p.field__hint', {
            text: 'どちらを選択しても画面の表のみが変更されます。' +
                  '保存を押すまでは登録済みの ' + label + ' 情報はそのままです。'
          })
        ],
        actions: [
          { label: 'キャンセル' },
          {
            label: '末尾に追加',
            onClick: function () { applyImported(data, 'append'); }
          },
          {
            label: '表をクリアして追加',
            tone: 'primary',
            onClick: function () { applyImported(data, 'replace'); }
          }
        ]
      });
    }

    function applyImported(data, mode) {
      var kept = mode === 'append' ? grid.dataRows().slice() : [];
      var incoming = data.rows || [];
      var total = kept.length + incoming.length;

      if (total > maxRows) {
        A.toast('表にすでに' + kept.length + '行あるため、' + incoming.length +
                '行をすべて追加できません。(最大 ' + maxRows + '行) ' +
                '表をクリアして追加するか、ファイルを分割してください。', 'danger');
        return;
      }

      // 이어붙일 때 기존 행의 id 를 잃지 않도록 값만 옮겨 담는다.
      var merged = kept.map(function (row) {
        var values = {};
        Object.keys(row).forEach(function (key) {
          if (key.charAt(0) !== '_') values[key] = row[key];
        });
        return values;
      }).concat(incoming);

      // 두 번째 인자는 「어디부터가 새로 들어온 줄인가」다. `A.grid` 는
      // 이것을 무시하고, 자체 표를 쓰는 화면은 커서를 그 줄로 옮긴다.
      grid.setRows(merged, { mode: mode, kept: kept.length });
      renderSummary(data.summary, mode, incoming.length);
      onImported(incoming.length, data.summary);

      A.toast(incoming.length + '行を表に追加しました。内容をご確認の上、' +
              '保存を押してください。', 'ok');
    }

    /** 무엇을 어떻게 읽었는지 그대로 보여 준다. 조용히 넘기면 오해가 남는다. */
    function renderSummary(summary, mode, placed) {
      var box = A.clear(noticeBox);
      if (!summary) return;

      var parts = [summary.file_name];
      if (summary.sheet_name) parts.push('シート「' + summary.sheet_name + '」');
      if (summary.encoding) parts.push(summary.encoding);
      parts.push(placed + '行');
      parts.push('列  ' + summary.matched_columns + '個一致');
      if (summary.blank_rows) parts.push('空行  ' + summary.blank_rows + '行スキップ');
      parts.push(mode === 'append' ? '既存の表の下に追加' : '表をクリアして追加');

      var notes = [];
      if (summary.header_mode === 'POSITIONAL') {
        notes.push('見出し行が見つからなかったため、列の順序通りに追加しました。' +
                   '値が正しいセルに入っているかご確認ください。');
      }
      if (summary.ignored_columns && summary.ignored_columns.length) {
        notes.push('不明な列は追加しませんでした — ' +
                   summary.ignored_columns.join(', '));
      }
      (summary.warnings || []).forEach(function (warning) { notes.push(warning); });

      box.appendChild(A.notice(notes.length ? 'warn' : 'info',
        '取り込みました — ' + parts.join(' · ') +
        '. まだ保存されていません。'));

      if (notes.length) {
        var list = el('ul.bulk-io__notes');
        notes.forEach(function (note) { list.appendChild(el('li', { text: note })); });
        box.appendChild(list);
      }

      box.appendChild(el('button.btn.btn--sm.btn--ghost', {
        type: 'button', text: 'この案内を閉じる',
        onClick: function () { A.clear(box); }
      }));
    }

    /* --- 표 위로 끌어다 놓기 ---------------------------------------------
       버튼을 찾지 않아도 되게 한다. 담당자가 메일로 받은 파일을 그대로
       끌어다 놓는 것이 가장 짧은 길이다. */

    function bindDrop(wrap) {
      if (!wrap) return;
      var depth = 0;

      function hasFile(event) {
        var types = event.dataTransfer && event.dataTransfer.types;
        return Boolean(types && Array.prototype.indexOf.call(types, 'Files') >= 0);
      }

      wrap.addEventListener('dragenter', function (event) {
        if (!hasFile(event)) return;
        event.preventDefault();
        depth += 1;
        wrap.classList.add('is-dropping');
      });

      wrap.addEventListener('dragover', function (event) {
        if (!hasFile(event)) return;
        // 이것을 빼면 브라우저가 기본 동작(파일 열기)을 하고 drop 이 오지 않는다.
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
      });

      wrap.addEventListener('dragleave', function () {
        depth = Math.max(0, depth - 1);
        if (!depth) wrap.classList.remove('is-dropping');
      });

      wrap.addEventListener('drop', function (event) {
        if (!hasFile(event)) return;
        event.preventDefault();
        depth = 0;
        wrap.classList.remove('is-dropping');

        var files = event.dataTransfer.files;
        if (!files || !files.length) return;
        if (files.length > 1) {
          A.toast('ファイルは一度に1つしか取り込めません。', 'warn');
          return;
        }
        importFile(files[0]);
      });
    }

    return {
      node: node,
      noticeBox: noticeBox,
      bindDrop: bindDrop,
      setBusy: setBusy
    };
  }

  A.gridIO = { attach: attach, MAX_UPLOAD_BYTES: MAX_UPLOAD_BYTES };
})();
