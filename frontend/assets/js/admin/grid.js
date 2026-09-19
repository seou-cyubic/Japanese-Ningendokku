/* ==========================================================================
   grid.js — 관리 화면의 엑셀식 표 (공용)
   --------------------------------------------------------------------------
   왜 따로 뺐는가
   --------------
   같은 표 코드가 `bulk-hospitals.js`(1,700줄)와 `bulk-postal.js` 두 벌에
   들어 있었다. 회장 정보 표와 정원 표를 새로 만들면 **네 벌**이 된다.
   셀 선택·붙여넣기·오류 표시·고정 헤더를 네 곳에서 각각 고치게 된다.

   무엇을 하는가
   -------------
     · 셀 편집 (contentEditable)
     · 범위 선택 · Ctrl+C / Ctrl+V — Excel 에서 복사한 블록을 그대로 받는다
     · 키보드 이동 (화살표 · Tab · Enter)
     · 셀 단위 오류 표시 — 서버가 준 (행, 칸) 을 그대로 칠한다
     · 「변경함」 판정 — 불러온 값과 다른 행을 저장 전에 알려 준다
     · 고정 헤더 · 고정 좌측 열 (CSS 는 admin-postal-bulk.css)
     · 데이터 열도 왼쪽에 얼릴 수 있다 (`stickyColumns`)
     · 다시 그려도 스크롤 자리를 잃지 않는다
     · 거르기 — 행을 **버리지 않고 감춘다** (`setFilter`)
     · 골라 넣는 칸 — 코드를 담고 말을 보여 준다 (`kind:'enum'` + `choices`)

   무엇을 하지 않는가
   ------------------
   **서버와 이야기하지 않는다.** 불러오기·저장·검증은 부르는 쪽의 일이다.
   이 파일이 API 를 알면 표마다 다른 규칙이 여기로 스며든다.

   쓰는 법
   -------
       var grid = A.grid.create({
         mount: someNode,
         columns: [{ key, label, width, kind, readonly, group, choices }],
         fixedLabels: ['행', '상태'],
         stickyColumns: 2,                       // 앞 2개 데이터 열도 얼린다
         onChange: function () { ... },
         onFilterCleared: function () { ... },   // 오류 때문에 조건이 풀렸다
         rowStatus: function (row) { return node; }
       });
       grid.setRows(rows);          // [{ key: value, … }]
       grid.rows();                 // 지금 표의 행 (감춘 것 포함)
       grid.setErrors(errors);      // [{ row_no, field, message }]
       grid.changedCount();
       grid.setFilter(fn);          // fn(row) → 보일 것인가. null 이면 해제
       grid.visibleCount();
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  /** 빈 행에도 자리를 남긴다. 꽉 찬 표는 한 줄을 더 넣으려면 버튼부터 눌러야 한다. */
  var SPARE_ROWS = 3;
  var MAX_ROWS = 400;

  var sequence = 0;

  function clean(value) {
    if (value === null || value === undefined || value === false) return '';
    return String(value).replace(/ /g, ' ').trim();
  }

  /** 가타카나를 히라가나로. 「センター」로 적힌 값을 「せんたー」로 찾기 위함.
      **문자 하나를 문자 하나로** 바꾸므로 글자 수가 보존된다 — 히라가나에서
      찾은 자리를 원문에 그대로 쓸 수 있고, 아래의 강조가 그 성질에 기댄다. */
  function toHiragana(text) {
    return String(text || '').replace(/[ァ-ヶ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0x60);
    });
  }

  /* ======================================================================
     한 표
     ====================================================================== */

  function create(options) {
    var columns = options.columns || [];
    var fixedLabels = options.fixedLabels || ['行', 'ステータス'];
    var onChange = options.onChange || function () {};
    var rowStatus = options.rowStatus || function () { return null; };
    var cellDecorator = options.cellDecorator || null;
    var onCellMenu = options.onCellMenu || null;
    var onFilterCleared = options.onFilterCleared || function () {};
    var variant = options.variant || '';

    /* 고정 열 머리글에 붙일 설명. 「상태」 칸에 뜨는 말이 표마다 다르므로
       무엇이 뜰 수 있는지는 부르는 쪽이 안다. */
    var fixedHints = options.fixedHints || [
      '表の何行目かを示します。保存時のエラー位置をこの番号でお知らせします。',
      'この行の現在のステータスを示します。'
    ];

    var byKey = {};
    columns.forEach(function (column, index) {
      byKey[column.key] = { column: column, index: index };
    });

    var rows = [];
    var selection = null;      // { r1, c1, r2, c2 }
    var anchor = null;         // 선택을 시작한 셀
    // 붙여넣기로 행 값을 먼저 바꾼 뒤 다시 그릴 때 켠다. 다시 그리며 포커스가
    // 있던 셀이 DOM 에서 빠지면 브라우저가 focusout 을 보내는데, 그 셀에는
    // **붙여넣기 전의 글자**가 남아 있어 방금 넣은 값을 되덮는다.
    var suppressCommit = false;
    var dirty = false;
    var locked = false;

    /* --- DOM ---------------------------------------------------------- */

    var table = el('table.bulk-grid' + (variant ? '.bulk-grid--' + variant : ''), {
      role: 'grid',
      'aria-label': options.label || '一括管理表'
    });

    var colgroup = el('colgroup');

    /* 고정 열(행 번호 · 상태)의 폭.
       --------------------------------------------------------------------
       가로로 스크롤해도 이 두 칸은 왼쪽에 붙어 있어야 한다. 그러려면 CSS 가
       두 번째 칸의 `left` 를 **첫 칸의 폭만큼** 밀어 줘야 하는데, 그 숫자가
       여기 있는 폭과 어긋나면 두 칸이 겹치거나 사이가 벌어진다.

       예전에는 CSS 에 `left: 46px` 를 손으로 적어 두었다. 폭을 여기서 한 번
       바꾸면 조용히 어긋나는 종류의 중복이라, 폭에서 계산한 값을 표에
       실어 보낸다. CSS 는 그 값을 그대로 쓴다. */
    var FIXED_WIDTHS = [46, 74];
    var fixedLeft = 0;
    FIXED_WIDTHS.slice(0, fixedLabels.length).forEach(function (width, index) {
      colgroup.appendChild(el('col', { style: 'width:' + width + 'px' }));
      table.style.setProperty('--grid-fixed-left-' + (index + 1), fixedLeft + 'px');
      fixedLeft += width;
    });
    columns.forEach(function (column) {
      colgroup.appendChild(el('col', { style: 'width:' + (column.width || 120) + 'px' }));
    });
    table.appendChild(colgroup);

    /* 얼려 있는 데이터 열 (`stickyColumns`)
       --------------------------------------------------------------------
       행 번호·상태만 얼려 있으면, 가로로 밀었을 때 **지금 보는 줄이
       어느 회장인지**를 잃는다. 회장 표도 정원 표도 앞 두 칸이 「회장
       코드·회장명」이므로, 그 둘을 행 번호 옆에 붙여 둔다.

       `left` 는 **앞 칸들의 폭을 더해서** 구한다. CSS 에 숫자를 적어
       두면 열 폭을 바로 잡는 순간 칸이 겹친다 (고정 열이 그랬다).

       그룹 머리글은 여러 칸을 한 칸으로 덮으므로, **그룹 경계에 떨어지지
       않는 수는 그룹 경계로 줄인다.** 그렇게 하지 않으면 머리글만 밀려
       가고 본문은 서 있는 모양이 된다. */
    var stickyCount = Math.max(
      0, Math.min(columns.length, Number(options.stickyColumns) || 0)
    );

    // 그룹 머리글은 열 정의의 `group` 에서 만든다. 화면이 따로 적어 두면
    // 열을 하나 늘릴 때 두 곳을 고쳐야 한다.
    var groups = [];
    columns.forEach(function (column) {
      var name = column.group || '';
      var last = groups[groups.length - 1];
      if (last && last.label === name) last.span += 1;
      else groups.push({ label: name, span: 1 });
    });

    if (stickyCount) {
      var edge = 0;
      for (var g = 0; g < groups.length; g++) {
        if (edge + groups[g].span > stickyCount) break;
        edge += groups[g].span;
      }
      stickyCount = edge;
    }

    var stickyLeft = [];      // 데이터 열 index → left(px)
    var stickyOffset = fixedLeft;
    for (var si = 0; si < stickyCount; si++) {
      stickyLeft.push(stickyOffset);
      stickyOffset += (columns[si].width || 120);
    }
    if (stickyCount) table.classList.add('bulk-grid--has-sticky');

    /** 얼린 칸에 붙일 클래스. 마지막 칸은 얼은 구역의 끝이라 줄을 그어 둔다. */
    function stickyClass(index, span) {
      if (index >= stickyCount) return '';
      return '.is-sticky' + (index + (span || 1) === stickyCount ? '.is-sticky-edge' : '');
    }

    function stickyStyle(index) {
      return index < stickyCount ? 'left:' + stickyLeft[index] + 'px' : null;
    }

    /* 얼린 열의 left 를 실측값으로 보정한다
       ------------------------------------------------------------------
       `box-sizing: border-box` 가 전역으로 걸려 있으면, `<col>` 에 적은
       너비와 브라우저가 실제로 그리는 열 너비가 1~2px 어긋날 수 있다.
       그 차이가 쌓이면 얼린 열의 왼쪽 끝이 앞 열 아래로 파고들어,
       스크롤했을 때 첫 글자가 잘린다.

       해결 : 표가 DOM 에 들어간 뒤 첫 행의 셀 위치를 재고, 그 값으로
       인라인 `left` 와 CSS 변수를 다시 쓴다. `<col>` 너비를 믿지 않고
       브라우저가 실제로 배치한 자리를 쓰므로 어긋남이 없다. */
    var stickyCalibrated = false;

    function calibrateStickyLeft() {
      if (!stickyCount) return;
      var row = tbody.querySelector('tr:not([hidden])');
      if (!row) return;

      var cells = row.children;                     // td 목록
      var fixedCount = fixedLabels.length;          // 행 번호 · 상태

      /* 렌더링된 **셀 너비**를 재서, 그 합으로 left 를 잡는다.
         `<col>` 에 적은 너비는 `box-sizing: border-box` 가 전역으로 걸려
         있으면 실제 렌더링 너비와 1~2px 어긋난다. 그 차이가 쌓이면
         얼린 열의 왼쪽 끝이 앞 열 아래로 파고들어, 스크롤했을 때
         첫 글자가 잘린다.

         `getBoundingClientRect().width` 는 브라우저가 실제로 그린 폭이라
         border-box 여부와 상관없이 정확하다. */
      var offset = 0;
      var debug = [];
      for (var fi = 0; fi < fixedCount; fi++) {
        var w = cells[fi].getBoundingClientRect().width;
        debug.push('fixed[' + fi + '] left=' + Math.round(offset) + ' width=' + w);
        table.style.setProperty(
          '--grid-fixed-left-' + (fi + 1), Math.round(offset) + 'px'
        );
        offset += w;
      }

      /* 얼린 데이터 열 */
      for (var si = 0; si < stickyCount; si++) {
        var w2 = cells[fixedCount + si].getBoundingClientRect().width;
        debug.push('sticky[' + si + '] left=' + Math.round(offset) + ' width=' + w2 + ' (was=' + stickyLeft[si] + ')');
        stickyLeft[si] = Math.round(offset);
        offset += w2;
      }
      console.log('[grid calibrate]', debug.join(' | '));

      /* 이미 그려진 모든 행의 인라인 left 를 다시 쓴다 */
      var allRows = tbody.querySelectorAll('tr');
      for (var ri = 0; ri < allRows.length; ri++) {
        var tds = allRows[ri].children;
        for (var ci = 0; ci < stickyCount; ci++) {
          var td = tds[fixedCount + ci];
          if (td) td.style.left = stickyLeft[ci] + 'px';
        }
      }

      /* 머리글(그룹 · 라벨)도 보정한다 */
      var groupCells = groupRow.children;
      var labelCells = labelRow.children;
      var gi = fixedCount;   // 그룹 행의 자식 인덱스 (고정 열 다음)
      var li = 0;            // 라벨 행 인덱스 (라벨 행에는 고정 열이 없다)
      var dataIdx = 0;
      for (var g = 0; g < groups.length && dataIdx < stickyCount; g++) {
        if (groupCells[gi]) groupCells[gi].style.left = stickyLeft[dataIdx] + 'px';
        for (var s = 0; s < groups[g].span && dataIdx < stickyCount; s++) {
          if (labelCells[li]) labelCells[li].style.left = stickyLeft[dataIdx] + 'px';
          li++;
          dataIdx++;
        }
        gi++;
      }

      stickyCalibrated = true;
    }

    var thead = el('thead');
    var groupRow = el('tr.bulk-grid__groups');
    fixedLabels.forEach(function (label, index) {
      groupRow.appendChild(el('th.bulk-grid__fixed-head', {
        text: label, rowSpan: 2, scope: 'col',
        // 「상태」가 무슨 칸인지 물어보게 두지 않는다. 값 목록을 머리글에
        // 붙여 둔다 — 표마다 뜨는 말이 다르므로 부르는 쪽이 준다.
        title: fixedHints[index] || ''
      }));
    });

    var groupStart = 0;
    groups.forEach(function (group) {
      groupRow.appendChild(el(
        'th.bulk-grid__group' + stickyClass(groupStart, group.span),
        {
          text: group.label, colSpan: group.span, scope: 'colgroup',
          style: stickyStyle(groupStart)
        }
      ));
      groupStart += group.span;
    });

    var labelRow = el('tr.bulk-grid__labels');
    columns.forEach(function (column, index) {
      labelRow.appendChild(el(
        'th' + (column.readonly ? '.is-readonly' : '') + stickyClass(index),
        {
          text: column.label,
          scope: 'col',
          title: column.readonly ? column.label + ' （読み取り専用）' : column.label,
          style: stickyStyle(index)
        }
      ));
    });

    thead.appendChild(groupRow);
    thead.appendChild(labelRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    table.appendChild(tbody);

    // 표의 끝에 닿으면 페이지가 이어서 굴러간다. 커서를 표 밖으로
    // 빼야만 화면 아래를 볼 수 있는 것은 표 탓이 아니다.
    var wrap = A.chainScroll(el('div.bulk-grid-wrap', {}, table));

    /* --- 값 ------------------------------------------------------------ */

    function emptyRow() {
      sequence += 1;
      return { _key: 'grid-row-' + sequence, _errors: [], _result: null };
    }

    function value(row, key) {
      return clean(row[key]);
    }

    /* --- 골라 넣는 칸 (kind: 'enum') --------------------------------------
       저장하는 값은 코드(`ALL`/`M`/`F`)이고 사람이 보는 값은 말
       (`전체`/`남성만`/`여성만`)이다. 셀에는 **말**을 띄우고 행에는
       **코드**를 담는다.

       왜 코드를 그대로 보여 주지 않는가 : 이 표는 담당자가 하루에도 몇 번씩
       읽는 곳이다. `F` 가 여성인지 거짓(false)인지 매번 헷갈린다.

       왜 말을 그대로 저장하지 않는가 : 서버·파일·API 가 전부 코드로 말한다.
       화면에서만 말로 바꾸는 편이 경계가 하나뿐이라 어긋날 곳이 적다. */

    function choicesOf(column) {
      return (column && column.choices) || null;
    }

    /** 코드 → 사람이 읽는 말. 모르는 코드는 그대로 보여 준다(값을 숨기지 않는다). */
    function labelOfValue(column, code) {
      var choices = choicesOf(column);
      if (!choices) return code;
      for (var i = 0; i < choices.length; i++) {
        if (String(choices[i].value) === code) return choices[i].label;
      }
      return code;
    }

    /** 사람이 친 말(또는 코드) → 코드. 아무것에도 안 맞으면 친 그대로 둔다.
        조용히 버리면 「분명 뭘 넣었는데 비어 있다」가 되므로, 틀린 값은
        틀린 채로 남겨 저장할 때 서버가 그 셀을 짚게 한다. */
    function valueOfLabel(column, text) {
      var choices = choicesOf(column);
      if (!choices) return text;
      var needle = String(text).trim().toLowerCase();
      if (!needle) return '';
      for (var i = 0; i < choices.length; i++) {
        if (String(choices[i].label).toLowerCase() === needle) return choices[i].value;
        if (String(choices[i].value).toLowerCase() === needle) return choices[i].value;
      }
      return text;
    }

    /** 셀에 그릴 글자. 코드가 아니라 사람이 읽는 말이다. */
    function displayValue(row, column) {
      return labelOfValue(column, value(row, column.key));
    }

    function isBlank(row) {
      return !columns.some(function (column) {
        return value(row, column.key) !== '';
      });
    }

    function nonBlank() {
      return rows.filter(function (row) { return !isBlank(row); });
    }

    /* --- 거르기 ----------------------------------------------------------
       행을 **버리지 않고 감춘다.**

       `setRows` 로 걸러진 배열을 다시 넣으면 편집 중이던 내용이 날아가고
       행 번호가 바뀐다. 검색 칸에 한 글자 칠 때마다 그러면 표로 쓸 수 없다.
       그래서 `rows` 는 그대로 두고 `_hidden` 만 세운다.

       **저장할 때는 감춘 행도 함께 보낸다.** 「표에 없는 회장은 지우지
       않는다」는 규약이 있어 위험하지는 않지만, 거른 상태로 저장했다는
       이유로 일부만 반영되면 무엇이 들어갔는지 아무도 모른다.

       판정은 `setFilter` 를 부른 그 순간에 한 번만 한다. 셀을 고칠 때마다
       다시 판정하면, 값을 고치는 도중에 그 행이 눈앞에서 사라진다. */

    var filterFn = null;

    function applyFilter() {
      rows.forEach(function (row) {
        if (!filterFn) { row._hidden = false; return; }
        // 빈 여유 행은 거르는 동안 감춘다. 조건에 맞을 리가 없는데
        // 표 끝에 빈 줄만 셋 남으면 「이게 결과인가」로 읽힌다.
        row._hidden = isBlank(row) ? true : !filterFn(row);
      });
    }

    function setFilter(next) {
      filterFn = (typeof next === 'function') ? next : null;
      applyFilter();
      // 감춰진 행에 선택이 걸려 있으면 보이지 않는 곳을 지우게 된다.
      selection = null;
      anchor = null;
      render();
      onChange();
    }

    function isHidden(row) {
      return Boolean(row && row._hidden);
    }

    function visibleRows() {
      return rows.filter(function (row) { return !isHidden(row); });
    }

    function visibleCount() {
      return rows.filter(function (row) {
        return !isHidden(row) && !isBlank(row);
      }).length;
    }

    function pad() {
      var target = Math.min(MAX_ROWS, nonBlank().length + SPARE_ROWS);
      while (rows.length < target) {
        var spare = emptyRow();
        // 거르는 중에 생긴 여유 행은 감춘 채로 둔다. 그렇지 않으면
        // 걸러 놓은 표 끝에 빈 줄이 불쑥 나타난다.
        spare._hidden = Boolean(filterFn);
        rows.push(spare);
      }
    }

    /** 불러온 뒤로 셀이 하나라도 달라졌는가. */
    function isChanged(row) {
      if (!row._origin) return !isBlank(row);
      return columns.some(function (column) {
        return value(row, column.key) !== clean(row._origin[column.key]);
      });
    }

    function changedCount() {
      return rows.filter(function (row) {
        return !isBlank(row) && isChanged(row);
      }).length;
    }

    /* --- 셀에 곁들이는 표시 ----------------------------------------------
       셀 안에는 **값 말고도** 들어가는 것이 있다. 정원 표의 예약 수 뱃지가
       그렇다. 화면에는 작게 떠 있지만 DOM 상으로는 셀의 자식이라,
       `cell.textContent` 로 값을 읽으면 **그것까지 값으로 딸려 들어온다.**

           정원 22 · 예약 15  →  textContent 는 "2215"

       실제로 그 셀을 눌렀다 다른 곳을 누르면 정원이 2215 로 바뀌었다.
       회장 표에 읽기를 곁들였을 때 회장명이 「サンプル会館 Aさんぷる…」로
       바뀌면서 드러났지만, 원인은 그보다 오래된 것이고 정원 표에도 있었다.

       그래서 곁들인 것에 표를 달아 두고, 값을 읽을 때 그것을 뺀다.
       CSS 로 감추는 것으로는 해결되지 않는다 — `textContent` 는 화면이
       아니라 DOM 을 본다.
       ---------------------------------------------------------------------- */

    var DECO_ATTR = 'data-grid-deco';

    function decorate(cell, row, column) {
      if (!cellDecorator) return;

      var from = cell.childNodes.length;
      cellDecorator(cell, row, column);

      // 부르는 쪽이 붙인 것에 표를 단다. 무엇을 붙였는지 이쪽이 알 필요는
      // 없고, 「값이 아니다」는 것만 알면 된다.
      for (var i = from; i < cell.childNodes.length; i += 1) {
        var node = cell.childNodes[i];
        if (node.nodeType === 1) node.setAttribute(DECO_ATTR, '1');
      }
    }

    /** 셀에서 **값만** 읽는다. 곁들인 표시는 값이 아니다. */
    function cellText(cell) {
      if (!cell.querySelector('[' + DECO_ATTR + ']')) return cell.textContent;

      var text = '';
      Array.prototype.forEach.call(cell.childNodes, function (node) {
        if (node.nodeType === 1 && node.hasAttribute(DECO_ATTR)) return;
        text += node.textContent;
      });
      return text;
    }

    /** 셀 글자를 새로 쓴다. 곁들인 표시가 함께 지워지므로 다시 얹는다. */
    function setCellText(cell, text) {
      cell.textContent = text;
      var row = rows[Number(cell.dataset.rowIndex)];
      var entry = byKey[cell.dataset.field];
      if (row && entry) decorate(cell, row, entry.column);
    }

    /* --- 그리기 --------------------------------------------------------- */

    function errorsFor(row, field) {
      return (row._errors || []).filter(function (error) {
        return error.field === field;
      });
    }

    /* 다시 그리면 스크롤이 맨 위로 튄다
       --------------------------------------------------------------------
       `tbody` 를 비우는 순간 표의 높이가 0 이 되고, 브라우저는 스크롤
       위치를 거기에 맞춰 0 으로 깎는다. 행을 도로 채워도 그 값은 돌아오지
       않는다. 셀 하나를 고쳐 다시 그렸을 뿐인데 **보고 있던 줄을 잃는
       것**이 이 표에서 가장 자주 나오던 불평이었다 (마감 우클릭).

       그래서 그리기 전에 자리를 적어 두었다가, 행을 채운 뒤에 되돌린다.
       페이지 스크롤까지 함께 보는 이유는 표가 화면보다 길면 문서 쪽이
       함께 밀리기 때문이다.

       강조(`paintHighlight`)는 일부러 스크롤한다. 되돌리기를 그보다
       **먼저** 해서, 강조가 필요하면 그쪽이 이기게 둔다. */
    function render(focus) {
      var keep = {
        top: wrap.scrollTop,
        left: wrap.scrollLeft,
        pageX: window.pageXOffset,
        pageY: window.pageYOffset
      };

      A.clear(tbody);

      rows.forEach(function (row, rowIndex) {
        var cls = row._errors.length
          ? 'has-error'
          : (row._result ? 'is-applied' : '');
        var tr = el('tr', {
          dataset: { rowKey: row._key, rowIndex: String(rowIndex) },
          'class': cls
        });

        // 거른 행은 DOM 에 남기고 감추기만 한다. 행 번호(rowIndex)가
        // 그대로여야 저장·오류 표시의 좌표가 어긋나지 않는다.
        if (isHidden(row)) tr.hidden = true;

        if (fixedLabels.length >= 1) {
          tr.appendChild(el('td.bulk-grid__number', { text: String(rowIndex + 1) }));
        }
        if (fixedLabels.length >= 2) {
          tr.appendChild(el('td.bulk-grid__status', {}, rowStatus(row, isChanged(row))));
        }

        columns.forEach(function (column, columnIndex) {
          var errors = errorsFor(row, column.key);
          var readonly = Boolean(column.readonly);
          var cell = el(
            'td.bulk-cell'
              + (errors.length ? '.has-error' : '')
              + (readonly ? '.is-readonly' : '')
              + stickyClass(columnIndex),
            {
              contentEditable: readonly ? 'false' : 'true',
              spellcheck: 'false',
              role: 'gridcell',
              tabIndex: 0,
              style: stickyStyle(columnIndex),
              text: displayValue(row, column),
              title: errors.map(function (e) { return e.message; }).join('\n'),
              dataset: {
                rowKey: row._key,
                rowIndex: String(rowIndex),
                colIndex: String(columnIndex),
                field: column.key
              }
            }
          );

          // 셀에 값 말고 더 붙일 것이 있으면 부르는 쪽이 붙인다.
          // 정원 표가 예약 수와 마감 빗금을 여기서 얹는다.
          decorate(cell, row, column);

          tr.appendChild(cell);
        });

        tbody.appendChild(tr);
      });

      wrap.scrollTop = keep.top;
      wrap.scrollLeft = keep.left;
      if (window.pageXOffset !== keep.pageX || window.pageYOffset !== keep.pageY) {
        window.scrollTo(keep.pageX, keep.pageY);
      }

      paintSelection();
      // 표를 다시 그리면 DOM 이 통째로 바뀌므로 강조 자국도 함께 사라진다.
      // 그리는 쪽에서 매번 다시 얹는다 — 부르는 쪽이 챙길 일이 아니다.
      paintHighlight();
      if (focus) {
        window.setTimeout(function () { focusCell(focus.row, focus.col); }, 0);
      }
    }

    /* --- 강조 -----------------------------------------------------------
       빠른 검색에서 「이 회장」을 골라 넘어왔을 때, 스무 줄짜리 표에서 그
       줄을 사람이 다시 찾게 두지 않는다.

           1차 : 그 행과 그 셀      — 어디에 있는가
           2차 : 셀 안의 검색어 부분 — 무엇으로 찾았는가

       2차를 `<mark>` 로 감싼다. 셀은 `contentEditable` 이라 요소를 넣는 것이
       조심스럽지만, 값을 읽는 `cellText()` 는 텍스트만 이어 붙이므로 값은
       바뀌지 않는다. 그래도 **편집이 시작되면 곧바로 지운다** — 타자를 치는
       동안 마크업이 남아 있으면 언젠가 값에 섞인다.
       -------------------------------------------------------------------- */

    var highlight = null;      // { rowKey, field, query }

    function setHighlight(next) {
      highlight = next || null;
      paintHighlight();
    }

    function rowIndexOfKey(key) {
      for (var i = 0; i < rows.length; i++) {
        if (rows[i]._key === key) return i;
      }
      return -1;
    }

    function clearHighlightPaint() {
      var marked = tbody.querySelectorAll('tr.is-hit');
      for (var i = 0; i < marked.length; i++) marked[i].classList.remove('is-hit');

      var cells = tbody.querySelectorAll('td.is-hit-cell');
      for (var j = 0; j < cells.length; j++) {
        var cell = cells[j];
        cell.classList.remove('is-hit-cell');
        var row = rows[Number(cell.dataset.rowIndex)];
        var entry = byKey[cell.dataset.field];
        // `<mark>` 를 걷어 낸다. 글자를 다시 써 넣는 편이 확실하다.
        if (row && entry) setCellText(cell, displayValue(row, entry.column));
      }
    }

    /** 셀 글자 안에서 검색어에 해당하는 부분만 `<mark>` 로 감싼다. */
    function markInside(cell, query) {
      if (!query) return;
      var text = cellText(cell);
      var at = toHiragana(text).toLowerCase()
        .indexOf(toHiragana(query).toLowerCase());
      if (at < 0) return;

      cell.textContent = '';
      cell.appendChild(document.createTextNode(text.slice(0, at)));
      cell.appendChild(el('mark.bulk-hit', { text: text.slice(at, at + query.length) }));
      cell.appendChild(document.createTextNode(text.slice(at + query.length)));

      // 곁들인 표시(정원 표의 예약 수 등)는 글자를 다시 쓰면서 지워졌다.
      var row = rows[Number(cell.dataset.rowIndex)];
      var entry = byKey[cell.dataset.field];
      if (row && entry) decorate(cell, row, entry.column);
    }

    function paintHighlight() {
      clearHighlightPaint();
      if (!highlight) return;

      var index = rowIndexOfKey(highlight.rowKey);
      if (index < 0) return;

      var tr = tbody.querySelector('tr[data-row-index="' + index + '"]');
      if (tr) tr.classList.add('is-hit');

      var entry = byKey[highlight.field];
      var cell = entry ? cellAt(index, entry.index) : null;
      if (!cell) return;

      cell.classList.add('is-hit-cell');
      markInside(cell, highlight.query);
      // 표가 세로로 길다. 강조만 해 두고 스크롤은 사람에게 맡기면
      // 「강조했다는데 안 보인다」가 된다.
      if (cell.scrollIntoView) {
        cell.scrollIntoView({ block: 'center', inline: 'center' });
      }
    }

    /* --- 선택 ----------------------------------------------------------- */

    function cellAt(rowIndex, colIndex) {
      return tbody.querySelector(
        'td.bulk-cell[data-row-index="' + rowIndex + '"]'
        + '[data-col-index="' + colIndex + '"]'
      );
    }

    function focusCell(rowIndex, colIndex) {
      var cell = cellAt(rowIndex, colIndex);
      if (!cell) return;
      cell.focus();
      setSelection({ r1: rowIndex, c1: colIndex, r2: rowIndex, c2: colIndex });
    }

    function setSelection(next) {
      selection = next;
      paintSelection();
    }

    function paintSelection() {
      var cells = tbody.querySelectorAll('td.bulk-cell');
      for (var i = 0; i < cells.length; i++) {
        var cell = cells[i];
        var r = Number(cell.dataset.rowIndex);
        var c = Number(cell.dataset.colIndex);
        var inside = selection
          && r >= Math.min(selection.r1, selection.r2)
          && r <= Math.max(selection.r1, selection.r2)
          && c >= Math.min(selection.c1, selection.c2)
          && c <= Math.max(selection.c1, selection.c2);
        cell.classList.toggle('is-selected', Boolean(inside));
      }
    }

    function selectedRowIndexes() {
      if (!selection) return [];
      var out = [];
      var from = Math.min(selection.r1, selection.r2);
      var to = Math.max(selection.r1, selection.r2);
      for (var i = from; i <= to; i++) {
        // 감춘 행은 고르지 않은 것으로 본다. 범위 선택이 걸러진 줄을
        // 건너뛰며 지나가므로, 보이지 않는 행이 함께 지워지면 안 된다.
        if (isHidden(rows[i])) continue;
        out.push(i);
      }
      return out;
    }

    /* --- 입력 ----------------------------------------------------------- */

    function commit(cell) {
      var row = rows[Number(cell.dataset.rowIndex)];
      if (!row) return;
      var field = cell.dataset.field;
      var entry = byKey[field];
      var column = entry ? entry.column : null;

      // 값만 읽는다. 곁들인 표시(예약 수 등)는 셀의 자식이지 값이 아니다.
      var next = clean(cellText(cell));
      if (column && choicesOf(column)) next = clean(valueOfLabel(column, next));

      if (value(row, field) === next) {
        // 값은 같은데 표기가 다를 수 있다 (`f` 로 쳤고 저장값은 `F`).
        // 셀 글자를 정식 표기로 되돌려, 사람이 본 것과 담긴 것을 맞춘다.
        if (column) {
          var shown = labelOfValue(column, next);
          if (cellText(cell) !== shown) setCellText(cell, shown);
        }
        return;
      }

      row[field] = next;
      if (column && choicesOf(column)) {
        setCellText(cell, labelOfValue(column, next));
      }
      // 값을 고치면 그 셀의 예전 오류는 뜻을 잃는다. 남겨 두면 이미 고친
      // 자리가 계속 붉게 보여, 무엇이 남았는지 알 수 없다.
      row._errors = (row._errors || []).filter(function (e) {
        return e.field !== field;
      });
      row._result = null;
      cell.classList.remove('has-error');
      cell.title = '';
      dirty = true;
      pad();
      onChange();
    }

    tbody.addEventListener('focusin', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;

      // 강조한 행에 손을 대면 자국을 지운다. `<mark>` 를 둔 채로 타자를
      // 치면 마크업이 값에 섞일 수 있고, 무엇보다 이미 찾았으므로 강조가
      // 할 일이 끝났다.
      if (highlight && cell.dataset.rowKey === highlight.rowKey) setHighlight(null);

      var r = Number(cell.dataset.rowIndex);
      var c = Number(cell.dataset.colIndex);
      if (!selection || selection.r1 !== r || selection.c1 !== c) {
        anchor = { row: r, col: c };
        setSelection({ r1: r, c1: c, r2: r, c2: c });
      }

      // 셀에 들어오면 글자를 통째로 고른다. Excel 처럼 **치면 바뀐다.**
      // 캐럿만 두면 「22」 위에서 20 을 쳤을 때 「2022」가 되어, 정원이
      // 조용히 백 배가 된다. 글자 중간을 고치려면 한 번 더 누르면 된다
      // (이미 포커스가 있는 셀은 focusin 이 다시 오지 않는다).
      if (!cell.classList.contains('is-readonly')) selectCellText(cell);
    });

    function selectCellText(cell) {
      var selectionApi = window.getSelection && window.getSelection();
      if (!selectionApi) return;
      var range = document.createRange();
      range.selectNodeContents(cell);
      var deco = cell.querySelector('[' + DECO_ATTR + ']');
      if (deco) range.setEndBefore(deco);
      selectionApi.removeAllRanges();
      selectionApi.addRange(range);
    }

    tbody.addEventListener('focusout', function (event) {
      if (suppressCommit) return;
      var cell = event.target.closest('td.bulk-cell');
      if (cell && !cell.classList.contains('is-readonly')) commit(cell);
    });

    tbody.addEventListener('mousedown', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;
      if (event.shiftKey && anchor) {
        event.preventDefault();
        setSelection({
          r1: anchor.row, c1: anchor.col,
          r2: Number(cell.dataset.rowIndex), c2: Number(cell.dataset.colIndex)
        });
        return;
      }
      anchor = {
        row: Number(cell.dataset.rowIndex),
        col: Number(cell.dataset.colIndex)
      };
      // 아직 포커스가 없는 셀을 누르면, 브라우저가 누른 자리에 캐럿을 놓아
      // focusin 에서 고른 글자를 풀어 버린다. 포커스는 직접 옮긴다.
      if (document.activeElement !== cell && !cell.classList.contains('is-readonly')) {
        event.preventDefault();
        cell.focus();
      }
    });

    if (onCellMenu) {
      tbody.addEventListener('contextmenu', function (event) {
        var cell = event.target.closest('td.bulk-cell');
        if (!cell) return;
        var row = rows[Number(cell.dataset.rowIndex)];
        if (!row) return;
        var handled = onCellMenu(event, row, byKey[cell.dataset.field].column, cell);
        if (handled) event.preventDefault();
      });
    }

    tbody.addEventListener('keydown', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;

      var r = Number(cell.dataset.rowIndex);
      var c = Number(cell.dataset.colIndex);

      /* 세로 이동은 **보이는 행만** 지난다. 거른 행을 그냥 세면 Enter 를
         눌렀는데 아무 데도 가지 않은 것처럼 보인다(감춘 줄에 포커스가 선다). */
      function nextVisibleRow(from, step) {
        var index = from + step;
        while (index >= 0 && index < rows.length && isHidden(rows[index])) {
          index += step;
        }
        // 그 방향에 보이는 행이 없으면 있던 자리에 머문다.
        if (index < 0 || index >= rows.length) return from;
        return index;
      }

      function move(dr, dc) {
        event.preventDefault();
        commit(cell);
        var nextRow = dr === 0 ? r : nextVisibleRow(r, dr > 0 ? 1 : -1);
        var nextCol = Math.max(0, Math.min(columns.length - 1, c + dc));
        focusCell(nextRow, nextCol);
      }

      if (event.key === 'Enter' && !event.shiftKey) { move(1, 0); return; }
      if (event.key === 'Enter' && event.shiftKey) { move(-1, 0); return; }
      if (event.key === 'Tab') { move(0, event.shiftKey ? -1 : 1); return; }
      if (event.key === 'Escape') {
        // 고치던 값을 되돌린다. 「잘못 눌렀다」를 되돌릴 길이 없으면
        // 사람은 표 안에서 편히 움직이지 못한다.
        var back = byKey[cell.dataset.field];
        setCellText(cell, back
          ? displayValue(rows[r], back.column)
          : value(rows[r], cell.dataset.field));
        cell.blur();
        return;
      }
      if (event.key.indexOf('Arrow') === 0 && (event.ctrlKey || event.metaKey)) {
        var map = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
        if (map[event.key]) move(map[event.key][0], map[event.key][1]);
      }
    });

    /* --- 붙여넣기 -------------------------------------------------------
       Excel 에서 복사한 블록은 탭 구분 · 줄바꿈 구분이다. 그대로 받는다.
       담당자가 실제로 하는 일이 「엑셀에서 만들어 붙여넣기」이므로,
       이것이 되지 않으면 표는 반쪽이다. */

    tbody.addEventListener('paste', function (event) {
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;

      var text = (event.clipboardData || window.clipboardData).getData('text/plain');
      if (!text) return;
      if (text.indexOf('\t') === -1 && text.indexOf('\n') === -1) return;  // 한 칸이면 기본 동작

      event.preventDefault();

      /* 거르는 중에는 블록 붙여넣기를 막는다.
         붙여넣기는 **화면에 보이는 줄**이 아니라 행 번호를 따라 내려간다.
         걸러 놓은 표에 20줄을 붙이면, 사람이 보는 다음 줄과 값이 실제로
         들어가는 줄이 어긋난다. 조용히 어긋나느니 막고 이유를 말한다. */
      if (filterFn) {
        A.toast('絞り込み中は貼り付けできません。' +
                '検索条件をクリアしてから貼り付けてください。', 'warn');
        return;
      }

      var matrix = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n')
        .map(function (line) { return line.split('\t'); });

      var startRow = Number(cell.dataset.rowIndex);
      var startCol = Number(cell.dataset.colIndex);

      // 붙여넣기 전에 치던 글자가 있으면 먼저 담는다. 아래에서 다시 그리는
      // 동안은 커밋을 막으므로 여기서 놓치면 사라진다.
      commit(cell);

      while (rows.length < startRow + matrix.length) rows.push(emptyRow());

      matrix.forEach(function (line, dr) {
        var row = rows[startRow + dr];
        line.forEach(function (raw, dc) {
          var column = columns[startCol + dc];
          if (!column || column.readonly) return;
          // Excel 에는 사람이 읽는 말이 들어 있다. 코드로 되돌린다.
          row[column.key] = choicesOf(column)
            ? clean(valueOfLabel(column, raw))
            : clean(raw);
          row._errors = [];
          row._result = null;
        });
      });

      dirty = true;
      suppressCommit = true;
      try {
        pad();
        render();
      } finally {
        suppressCommit = false;
      }
      setSelection({
        r1: startRow, c1: startCol,
        r2: startRow + matrix.length - 1,
        c2: Math.min(columns.length - 1, startCol + matrix[0].length - 1)
      });
      onChange();
    });

    tbody.addEventListener('copy', function (event) {
      if (!selection) return;
      var cell = event.target.closest('td.bulk-cell');
      if (!cell) return;

      var r1 = Math.min(selection.r1, selection.r2);
      var r2 = Math.max(selection.r1, selection.r2);
      var c1 = Math.min(selection.c1, selection.c2);
      var c2 = Math.max(selection.c1, selection.c2);
      if (r1 === r2 && c1 === c2) return;   // 한 칸이면 기본 동작

      event.preventDefault();
      var lines = [];
      for (var r = r1; r <= r2; r++) {
        // 거른 행은 복사에서 뺀다. 화면에 안 보이는 줄이 클립보드에 따라오면
        // Excel 에 붙였을 때 줄 수가 맞지 않는다.
        if (isHidden(rows[r])) continue;
        var line = [];
        for (var c = c1; c <= c2; c++) {
          // 화면에 보이는 말 그대로 복사한다. 다시 붙여넣으면 코드로 돌아간다.
          line.push(displayValue(rows[r], columns[c]));
        }
        lines.push(line.join('\t'));
      }
      event.clipboardData.setData('text/plain', lines.join('\n'));
    });

    /* --- 바깥에서 쓰는 것 ------------------------------------------------ */

    function setRows(incoming) {
      rows = (incoming || []).map(function (values) {
        var row = emptyRow();
        columns.forEach(function (column) {
          var raw = values[column.key];
          row[column.key] = (raw === null || raw === undefined) ? '' : String(raw);
        });
        // 열에 없는 값(id 계열)도 그대로 나른다. 「어느 것을 고치는가」의
        // 열쇠이며, 표에 보이지 않아도 저장할 때 함께 보내야 한다.
        Object.keys(values).forEach(function (key) {
          if (!byKey[key]) row[key] = values[key];
        });
        // 불러온 시점의 값. 「무엇을 고쳤는지」를 저장 전에 보여 주기 위함.
        row._origin = {};
        columns.forEach(function (column) {
          row._origin[column.key] = row[column.key];
        });
        return row;
      });
      dirty = false;
      pad();
      // 새로 불러온 행에도 지금 걸린 조건을 적용한다. 저장 뒤 다시 불러왔을 때
      // 검색 칸에는 조건이 남아 있는데 표만 전부 펼쳐지면 어긋나 보인다.
      applyFilter();
      render();
      // 표가 DOM 에 들어간 뒤 한 프레임 기다려 레이아웃이 끝나면,
      // 실제 열 위치를 재서 sticky left 를 보정한다.
      if (!stickyCalibrated && stickyCount) {
        requestAnimationFrame(calibrateStickyLeft);
      }
      onChange();
    }

    function setErrors(errors) {
      rows.forEach(function (row) { row._errors = []; });
      (errors || []).forEach(function (error) {
        var row = rows[Number(error.row_no) - 1];
        if (row) row._errors.push(error);
      });

      // 오류가 걸러 놓은 행에 있으면 사람은 그것을 볼 수 없다. 「저장이
      // 안 되는데 붉은 칸도 없다」가 되므로, 오류가 있으면 조건을 푼다.
      // 검색 칸을 비우는 것은 부르는 쪽의 일이라 알려만 준다.
      if ((errors || []).length && filterFn) {
        filterFn = null;
        applyFilter();
        onFilterCleared();
        A.toast('エラーのある行を表示するため、検索条件を解除しました。', 'warn');
      }

      render();
      onChange();

      var first = (errors || [])[0];
      if (first) {
        var index = byKey[first.field] ? byKey[first.field].index : 0;
        window.setTimeout(function () {
          focusCell(Number(first.row_no) - 1, index);
        }, 0);
      }
    }

    function setResults(results, keyOf) {
      (results || []).forEach(function (result) {
        var row = rows[Number(result.row_no) - 1];
        if (!row) return;
        row._result = result;
        if (keyOf) keyOf(row, result);
        // 저장된 값이 곧 새 기준이다. 이것을 갱신하지 않으면 저장한 뒤에도
        // 「변경함」이 남아 무엇이 아직 안 됐는지 알 수 없다.
        row._origin = {};
        columns.forEach(function (column) {
          row._origin[column.key] = value(row, column.key);
        });
      });
      dirty = false;
      render();
      onChange();
    }

    function addRows(count) {
      var room = MAX_ROWS - rows.length;
      for (var i = 0; i < Math.min(count, room); i++) rows.push(emptyRow());
      render();
      onChange();
    }

    function deleteSelected() {
      var indexes = selectedRowIndexes();
      if (!indexes.length) return 0;
      var keep = rows.filter(function (_row, index) {
        return indexes.indexOf(index) === -1;
      });
      rows = keep;
      dirty = true;
      selection = null;
      pad();
      render();
      onChange();
      return indexes.length;
    }

    function duplicateSelected(transform) {
      var indexes = selectedRowIndexes().filter(function (index) {
        return rows[index] && !isBlank(rows[index]);
      });
      if (!indexes.length) return 0;

      // 뒤에서부터 끼운다. 앞에서부터 넣으면 아직 처리하지 않은 행의
      // 자리가 밀려, 두 번째 복제본이 엉뚱한 줄 뒤에 붙는다.
      indexes.slice().reverse().forEach(function (index) {
        var source = rows[index];
        var copy = emptyRow();
        columns.forEach(function (column) {
          copy[column.key] = value(source, column.key);
        });
        if (transform) transform(copy, source);
        rows.splice(index + 1, 0, copy);
      });

      dirty = true;
      pad();
      render();
      onChange();
      return indexes.length;
    }

    return {
      node: wrap,
      table: table,

      setRows: setRows,
      setErrors: setErrors,
      setResults: setResults,

      rows: function () { return rows; },
      dataRows: nonBlank,
      selectedRows: function () {
        return selectedRowIndexes()
          .map(function (index) { return rows[index]; })
          .filter(function (row) { return row && !isBlank(row); });
      },

      addRows: addRows,
      deleteSelected: deleteSelected,
      duplicateSelected: duplicateSelected,

      value: value,
      isBlank: isBlank,
      isChanged: isChanged,
      changedCount: changedCount,

      // 강조 — 빠른 검색에서 넘어온 행을 짚어 준다.
      // { rowKey, field, query } · 표를 다시 그려도 유지된다.
      setHighlight: setHighlight,
      clearHighlight: function () { setHighlight(null); },
      /** 조건에 맞는 **첫 행**. 강조할 행을 찾는 데 쓴다. */
      findRow: function (fn) {
        for (var i = 0; i < rows.length; i++) {
          if (fn(rows[i], i)) return rows[i];
        }
        return null;
      },

      // 거르기 — 행을 버리지 않고 감춘다. 저장 payload 에는 감춘 행도 들어간다.
      setFilter: setFilter,
      hasFilter: function () { return Boolean(filterFn); },
      isHidden: isHidden,
      visibleRows: visibleRows,
      visibleCount: visibleCount,

      // 골라 넣는 칸(kind:'enum')의 코드 ↔ 말
      labelOfValue: labelOfValue,
      valueOfLabel: valueOfLabel,
      displayValue: displayValue,
      errorCount: function () {
        return rows.reduce(function (sum, row) {
          return sum + (row._errors ? row._errors.length : 0);
        }, 0);
      },
      isDirty: function () { return dirty; },
      setDirty: function (next) { dirty = Boolean(next); },
      setLocked: function (next) {
        locked = Boolean(next);
        table.classList.toggle('is-locked', locked);
      },
      render: render,
      columns: columns,
      labelOf: function (key) {
        return byKey[key] ? byKey[key].column.label : key;
      }
    };
  }

  A.grid = { create: create, MAX_ROWS: MAX_ROWS };
})();
