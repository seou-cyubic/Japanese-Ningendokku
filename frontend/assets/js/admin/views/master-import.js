/* ==========================================================================
   master-import.js — 원본 마스터 파일 가져오기 (모달)
   --------------------------------------------------------------------------
   담당자에게 받은 **원본 회장 마스터 파일을 그대로 넣는다.** 그것 하나만 한다.

   왜 탭이 아니라 버튼인가
   -----------------------
   예전에는 「마스터 파일 가져오기」가 독립된 탭이었다. 그런데 이 일은
   **반기에 한 번**뿐이고, 나머지 시간에는 메뉴 자리만 차지했다.

   그렇다고 없앨 수도 없었다. 원본 파일의 한 행이 이렇게 생겼기 때문이다.

       会場番号 会場名 地域 住所 緯度 経度 │ 開催日 予約終了 │ 9:30~10:00 … 計
       └──────── 회장(장소) ────────┘ └── 회차 ──┘ └─── 정원 16칸 ───┘

   한 행이 **hospitals + hospital_schedules + 정원 그리드 세 곳에 동시에**
   쓴다. 탭별 「가져오기」는 자기 표의 열만 알기 때문에 이것을 대신할 수 없다.
   특히 정원 표의 가져오기는 **회장이 이미 있어야** 동작한다. 이 길을 없애면
   담당자가 Excel 에서 파일을 손으로 둘로 쪼개 두 번 올려야 한다.

   그래서 기능은 남기고 자리만 옮겼다 — 「회장 관리」의 가져오기 메뉴 안이다.
   검증·저장 로직(`/hospitals/bulk/import`, `/hospitals/bulk`)은 예전 그대로다.

   넣기 전에 보여 준다
   -------------------
   「넣고 나서 확인」은 되돌릴 수 없는 일에 대해 너무 늦다.
   파일 → 무엇이 들어갈지 표 → 「이대로 넣기」 순서를 지킨다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  /**
   * open({ onDone: function () {} })
   * 마스터를 넣은 뒤 부르는 쪽이 표를 다시 불러오게 한다.
   */
  function open(options) {
    var opts = options || {};
    var busy = false;

    var body = el('div');
    var dialog = null;

    var fileInput = el('input', {
      type: 'file',
      accept: '.csv,.xlsx,.xls',
      style: 'display:none',
      onChange: function (event) {
        var file = event.target.files && event.target.files[0];
        event.target.value = '';
        if (file) upload(file);
      }
    });

    var zone = el('div.import-drop', {
      tabIndex: 0,
      role: 'button',
      'aria-label': 'マスターファイルのアップロード',
      onClick: function () { fileInput.click(); },
      onKeydown: function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          fileInput.click();
        }
      }
    }, [
      el('p.import-drop__lead', { text: '会場マスターファイルをここにドラッグ＆ドロップしてください' }),
      el('p.import-drop__sub', { text: 'またはクリックしてファイルを選択してください ・ .xlsx ・ .csv' }),
      fileInput
    ]);

    ['dragenter', 'dragover'].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add('is-dropping');
      });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.remove('is-dropping');
      });
    });
    zone.addEventListener('drop', function (event) {
      var file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) upload(file);
    });

    reset();

    dialog = A.modal({
      title: '原本マスターファイルの取り込み',
      body: body,
      actions: [{ label: '閉じる' }]
    });

    function reset() {
      A.clear(body);

      body.appendChild(A.notice('info',
        '担当者から受け取った会場マスターファイル（.xlsx ・ .csv）を修正せずにそのまま' +
        'アップロードしてください。同じ会場番号が複数行にある場合は、その会場が複数日' +
        '開催されるものとして読み込みます。取り込む前に、何が登録されるかを一覧で表示します。'));

      body.appendChild(A.notice('warn',
        'この機能は新しい期のマスターを初めて登録するためのものです。' +
        '既に登録されている会場を修正する場合は、「会場管理」一覧と「定員管理」一覧を' +
        'ご利用ください — そちらの方が修正しやすく、同じ会場の住所が食い違うこともありません。'));

      body.appendChild(zone);
    }

    function upload(file) {
      if (busy) return;
      busy = true;

      A.clear(body).appendChild(A.loading(file.name + ' を読み込んでいます…'));

      A.api.upload('/hospitals/bulk/import', file)
        .then(function (res) { renderPreview(file.name, res.data); })
        .catch(function (error) {
          A.clear(body).appendChild(
            A.notice('danger', error.message || 'ファイルを読み込めませんでした。'));
          body.appendChild(retryButton());
        })
        .then(function () { busy = false; });
    }

    function retryButton() {
      return el('button.btn.btn--sm', {
        type: 'button', text: '別のファイルを選択',
        onClick: function () { reset(); }
      });
    }

    /* --- 미리 보기 ------------------------------------------------------ */

    function renderPreview(fileName, data) {
      var rows = data.rows || [];

      var venues = {};
      rows.forEach(function (row) {
        var code = String(row.code || '').trim().toLocaleLowerCase();
        if (code) venues[code] = true;
      });

      A.clear(body);

      body.appendChild(el('div.bulk-result__head', {}, [
        el('div', {}, [
          el('h2.bulk-result__title', { text: fileName }),
          el('p.bulk-result__desc', {
            text: '会場 ' + Object.keys(venues).length + 'か所 ・ 開催回 '
                + rows.length + '件を読み込みました。まだ取り込んでいません。'
          })
        ]),
        el('button.btn.btn--primary', {
          type: 'button', text: 'このまま取り込む',
          onClick: function () { apply(rows); }
        })
      ]));

      var summary = data.summary || {};
      if (summary.blank_rows) {
        body.appendChild(A.notice('warn',
          '空行 ' + summary.blank_rows + '行をスキップしました。'));
      }

      body.appendChild(previewTable(rows));
      body.appendChild(retryButton());
    }

    function previewTable(rows) {
      // 앞의 몇 행만. 전부 그리면 스무 열 × 수십 행이라 읽을 것이 없어진다.
      var shown = rows.slice(0, 12);
      var wrap = el('div.table-wrap');
      var table = el('table.table');

      table.appendChild(el('thead', {}, el('tr', {}, [
        el('th', { text: '会場コード' }),
        el('th', { text: '会場名' }),
        el('th', { text: '開催日' }),
        el('th', { text: '受付締切日' }),
        el('th', { text: '時間帯' }),
        el('th', { text: '定員' })
      ])));

      var tbody = el('tbody');
      shown.forEach(function (row) {
        var cells = 0;
        var total = 0;
        Object.keys(row).forEach(function (key) {
          if (/^\d{1,2}:\d{2}[~～]\d{1,2}:\d{2}$/.test(key)) {
            var value = Number(row[key]);
            if (value > 0) { cells += 1; total += value; }
          }
        });
        tbody.appendChild(el('tr', {}, [
          el('td.mono', { text: row.code || '' }),
          el('td', { text: row.name || '' }),
          el('td.mono', { text: row.event_date || '' }),
          el('td.mono', { text: row.booking_close_date || '' }),
          el('td', { text: cells ? cells + '枠' : '—' }),
          el('td', { text: total ? String(total) : '—' })
        ]));
      });
      table.appendChild(tbody);
      wrap.appendChild(table);

      var box = el('div', {}, [wrap]);
      if (rows.length > shown.length) {
        box.appendChild(el('p.field__hint', {
          text: '先頭 ' + shown.length + '行のみ表示しています。'
              + '残りの ' + (rows.length - shown.length) + '行もあわせて取り込まれます。'
        }));
      }
      return box;
    }

    /* --- 넣기 ------------------------------------------------------------ */

    function apply(rows) {
      if (busy) return;

      A.confirm({
        title: 'このファイルをマスターに取り込みますか？',
        message: rows.length + '件の開催回を取り込みます。',
        detail: '同一の会場コード・開催日がすでに存在する場合は、その開催回を更新します。'
              + 'このファイルに含まれない会場・開催回は削除されません。'
              + '1セルでもエラーがある場合は取り込みを行いません。',
        okLabel: '取り込む',
        tone: 'primary'
      }).then(function (yes) {
        if (!yes || busy) return;

        busy = true;
        A.clear(body).appendChild(A.loading('マスターに取り込んでいます…'));

        var payload = rows.map(function (row, index) {
          var copy = {};
          Object.keys(row).forEach(function (key) { copy[key] = row[key]; });
          copy.row_no = index + 1;
          return copy;
        });

        A.api.post('/hospitals/bulk', { rows: payload })
          .then(function (res) { renderResult(res.data); })
          .catch(function (error) {
            var errors = (error.body || {}).errors || [];
            A.clear(body).appendChild(errorList(errors, error));
            body.appendChild(retryButton());
          })
          .then(function () { busy = false; });
      });
    }

    function errorList(errors, error) {
      if (!errors.length) {
        return A.notice('danger', error.message || '取り込めませんでした。');
      }
      return el('div.bulk-errorlist', {}, [
        el('p.bulk-warn__title', {
          text: 'ファイルに修正が必要なか所が ' + errors.length + 'か所あります'
        }),
        el('p.field__hint', {
          text: '1件も取り込まれていません。ファイルを修正して再度アップロードしてください。'
        }),
        el('ul.bulk-warn__list', {}, errors.slice(0, 30).map(function (e) {
          return el('li', { text: e.row_no + '行目「' + e.field + '」 — ' + e.message });
        }))
      ]);
    }

    function renderResult(data) {
      A.clear(body);

      var parts = [];
      if (data.created_count) parts.push('新規 ' + data.created_count + '件');
      if (data.updated_count) parts.push('修正 ' + data.updated_count + '件');
      var summary = parts.length
        ? parts.join(' · ') + 'を取り込みました。'
        : '変更がないため取り込みを行いませんでした。';

      body.appendChild(el('div.bulk-result__head', {}, [
        el('div', {}, [
          el('h2.bulk-result__title', { text: '取り込み完了' }),
          el('p.bulk-result__desc', {
            text: summary
                + (data.unchanged_count ? ' (変更なし ' + data.unchanged_count + '件)' : '')
          })
        ])
      ]));

      body.appendChild(el('p.field__hint', {
        text: '住所・座標・アクセスを続けて編集する場合は、この画面を閉じて一覧から行ってください。' +
              '開催日と定員は「定員管理」で設定します。'
      }));

      body.appendChild(el('button.btn.btn--primary', {
        type: 'button', text: '閉じて一覧を更新',
        onClick: function () {
          if (dialog) dialog.close();
          if (opts.onDone) opts.onDone();
        }
      }));
    }
  }

  A.masterImport = { open: open };
})();
