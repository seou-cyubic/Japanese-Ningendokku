/* ==========================================================================
   preview.js — 「저장하면 무엇이 바뀌는가」 (공용)
   --------------------------------------------------------------------------
   왜 필요한가
   -----------
   예전에는 저장 확인창이 이렇게 말했다.

       21곳을 검사한 뒤, 고치신 3곳을 저장합니다.

   그런데 담당자가 실제로 걱정하는 것은 다른 것이다. 파일로 90~110번을
   올릴 때, **기존 1~89번이 어떻게 되는지**와 **90~100번이 무엇으로
   덮어써지는지**다. 위 문장은 그 둘 중 어느 것에도 답하지 않는다.
   답은 저장한 뒤의 결과 화면에만 있었고, 그때는 이미 늦다.

   그래서 저장을 두 걸음으로 나눈다.

       ① dry_run=true  — 서버가 전부 계산하고 **되돌린다**
       ② 그 결과를 이 대화상자가 보여 준다
       ③ 사람이 「저장하기」를 누르면 그때 진짜로 저장한다

   무엇을 보여 주는가
   ------------------
       신규 10곳 · 덮어쓰기 11곳 · 변경 없음 0곳
       이 표에 없는 89곳은 손대지 않습니다.
       ⚠ 확인해 주실 것 2건
       [무엇이 바뀌는지 자세히 보기]  ← 코드 · 항목 · 전 → 후

   서버가 세는 이유
   ----------------
   화면이 세면 「화면이 아는 것」만 셀 수 있다. 코드가 겹치는지, 어느 행이
   기존 회장에 붙는지, 정원이 예약 수 아래로 내려가는지는 DB 를 봐야 안다.
   같은 판정을 두 곳에서 하면 확인창의 숫자와 저장 결과가 갈라진다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  // 자세히 보기에 한 번에 그리는 최대 줄 수. 200행 × 15칸이면 3,000줄이라
  // 열자마자 화면이 멎는다. 나머지는 「더 보기」로 이어 그린다.
  var DETAIL_CHUNK = 40;

  /**
   * confirm({ title, preview, unit, labelOf, detail, hiddenNote })
   *   preview  : 서버의 dry-run 응답 (created_count · updated_count …)
   *   unit     : '곳' · '회차' · '건'
   *   labelOf  : 열 키 → 사람이 읽는 이름 (grid.labelOf)
   * → Promise<boolean>
   */
  function confirm(options) {
    var preview = options.preview || {};
    var unit = options.unit || '件';
    var labelOf = options.labelOf || function (key) { return key; };

    var created = preview.created_count || 0;
    var updated = preview.updated_count || 0;
    var unchanged = preview.unchanged_count || 0;
    var untouched = preview.untouched_count || 0;
    var warnings = preview.warnings || [];

    return new Promise(function (resolve) {
      var decided = false;
      function decide(value) {
        if (decided) return;
        decided = true;
        resolve(value);
      }

      A.modal({
        title: options.title || '保存してよろしいですか？',
        size: options.size || 'wide',
        body: buildBody(),
        onClose: function () { decide(false); },
        actions: [
          { label: 'キャンセル', onClick: function () { decide(false); } },
          {
            label: created + updated ? '保存する' : 'そのまま保存する',
            tone: 'primary',
            onClick: function () { decide(true); }
          }
        ]
      });

      function buildBody() {
        var nodes = [];

        /* --- 숫자 세 개 + 손대지 않는 것 ------------------------------- */
        nodes.push(el('div.preview-counts', {}, [
          countBox('新規', created, unit, 'ok'),
          countBox('上書き', updated, unit, updated ? 'warn' : ''),
          countBox('変更なし', unchanged, unit, '')
        ]));

        // 이것이 「1~89 는 어떻게 되는가」에 대한 답이다.
        nodes.push(el('p.preview-untouched', {
          text: untouched
            ? 'この表にない ' + untouched + unit + 'は変更されません。' +
              'そのまま残ります。'
            : '登録されているものはすべてこの表に含まれています。'
        }));

        if (options.hiddenNote) {
          nodes.push(el('p.field__hint', { text: options.hiddenNote }));
        }

        /* --- 확인해 주실 것 --------------------------------------------- */
        if (warnings.length) {
          nodes.push(el('div.preview-warn', {}, [
            el('p.preview-warn__title', {
              text: 'ご確認事項が ' + warnings.length + '件あります'
            }),
            el('ul.preview-warn__list', {}, warnings.slice(0, 12).map(function (w) {
              return el('li', {
                text: w.row_no + '行目「' + labelOf(w.field) + '」 — ' + w.message
              });
            })),
            warnings.length > 12
              ? el('p.field__hint', {
                  text: 'ほか ' + (warnings.length - 12) + '件は保存後の結果画面で' +
                        'すべて表示されます。'
                })
              : null
          ]));
        }

        /* --- 무엇이 바뀌는지 자세히 --------------------------------------- */
        var detailRows = collectChanges(preview.rows || []);
        if (detailRows.length) nodes.push(buildDetail(detailRows));

        if (options.detail) {
          nodes.push(el('p.preview-detail-hint', { text: options.detail }));
        }

        return nodes;
      }

      /** 행 결과에서 「무엇이 무엇으로」만 뽑아 평탄하게 편다. */
      function collectChanges(rows) {
        var out = [];
        rows.forEach(function (row) {
          if (row.action === 'UNCHANGED') return;
          var who = row.code || row.hospital_code || String(row.row_no);
          var when = row.event_date ? ' ' + row.event_date : '';

          if (row.action === 'CREATED') {
            out.push({
              who: who + when,
              name: row.name || row.hospital_name || '',
              action: 'CREATED',
              field: '', before: '', after: ''
            });
            return;
          }
          (row.changes || []).forEach(function (change) {
            out.push({
              who: who + when,
              name: row.name || row.hospital_name || '',
              action: 'UPDATED',
              field: change.label || labelOf(change.field),
              before: change.before,
              after: change.after
            });
          });
        });
        return out;
      }

      function buildDetail(rows) {
        var box = el('details.preview-detail');
        box.appendChild(el('summary', {
          text: '変更内容の詳細 (' + rows.length + '件)'
        }));

        var table = el('table.preview-table');
        table.appendChild(el('thead', {}, el('tr', {}, [
          el('th', { text: '対象' }),
          el('th', { text: '項目' }),
          el('th', { text: '変更前' }),
          el('th', { text: '変更後' })
        ])));

        var tbody = el('tbody');
        var drawn = 0;

        var more = el('button.btn.btn--sm.btn--ghost', {
          type: 'button',
          onClick: function () { drawMore(); }
        });

        function drawMore() {
          var end = Math.min(rows.length, drawn + DETAIL_CHUNK);
          for (var i = drawn; i < end; i++) {
            var row = rows[i];
            tbody.appendChild(el('tr', {}, [
              el('td', {}, [
                el('span.mono', { text: row.who }),
                row.name ? el('span.preview-table__name', { text: row.name }) : null
              ]),
              row.action === 'CREATED'
                ? el('td.preview-table__new', { colSpan: 3, text: '新規登録されます' })
                : el('td', { text: row.field }),
              row.action === 'CREATED' ? null
                : el('td.preview-table__before', { text: row.before }),
              row.action === 'CREATED' ? null
                : el('td.preview-table__after', { text: row.after })
            ]));
          }
          drawn = end;
          more.textContent = 'さらに表示 (' + (rows.length - drawn) + '件)';
          // `hidden` 속성은 단추 CSS(display)에 눌려 무시된다. 「さらに表示 (0件)」가
          // 남지 않도록 표시 자체를 끈다.
          more.hidden = drawn >= rows.length;
          more.style.display = drawn >= rows.length ? 'none' : '';
        }

        table.appendChild(tbody);
        box.appendChild(el('div.preview-table-wrap', {}, table));
        box.appendChild(more);
        drawMore();

        return box;
      }
    });
  }

  function countBox(label, value, unit, tone) {
    return el('div.preview-count' + (tone ? '.preview-count--' + tone : ''), {}, [
      el('span.preview-count__label', { text: label }),
      el('span.preview-count__value', { text: A.fmt.number(value) + unit })
    ]);
  }

  A.preview = { confirm: confirm };
})();
