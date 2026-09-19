/* ==========================================================================
   datepicker.js — 日本語ネイティブカレンダーピッカー
   --------------------------------------------------------------------------
   OS/ブラウザ言語設定（韓国語等）に関わらず、常に日本語（年/月/日/曜日）で
   カレンダーを表示するカスタムピッカーコンポーネント。
   ========================================================================== */

(function () {
  'use strict';

  var WEEKDAYS_JA = ['日', '月', '火', '水', '木', '金', '土'];
  var activePicker = null;

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /** 手で入力した日付を 'YYYY-MM-DD' にそろえる。読めなければ ''。
      19650220 / 1965/2/20 / 1965.2.20 / 1965-2-20 / 1965年2月20日 / 全角数字 */
  function normalizeDate(text) {
    var s = String(text || '').trim().replace(/[０-９／．－]/g, function (c) {
      return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
    });
    var m = s.match(/^(\d{4})(\d{2})(\d{2})$/) ||
            s.match(/^(\d{4})\s*[-\/.年]\s*(\d{1,2})\s*[-\/.月]\s*(\d{1,2})\s*日?$/);
    if (!m) return '';
    var y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
    var dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return '';
    return y + '-' + pad2(mo) + '-' + pad2(d);
  }

  /** その年・その月の末日。2月なら28、うるう年なら29。 */
  function lastDayOf(y, m) { return new Date(y, m, 0).getDate(); }

  /** 打ち込んでいる途中の文字を「ありえる日付」だけに直す。

     この欄は数字を続けて打てる（19650220）。何も直さないと 1950-50-50 の
     ような日付が最後まで残り、保存の段階で初めて弾かれる。
     打っているそばから 月は1〜12、日はその月の末日までに収め、
     4桁・6桁のところで「-」を入れる。

     ・月の1桁目に2〜9 → 05 のように0を補う（5月と打てる）
     ・日の1桁目に4〜9 → 06 のように0を補う
     ・2桁そろって範囲を越えたら、端（12月・末日）に寄せる */
  function maskDate(raw) {
    var digits = String(raw || '')
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/\D/g, '')
      .slice(0, 8);

    var y = digits.slice(0, 4);
    var mo = digits.slice(4, 6);
    var d = digits.slice(6, 8);

    if (mo.length === 1 && Number(mo) > 1) mo = '0' + mo;
    if (mo.length === 2) mo = pad2(Math.min(12, Math.max(1, Number(mo))));

    if (d.length === 1 && Number(d) > 3) d = '0' + d;
    if (d.length === 2) {
      var last = (y.length === 4 && mo.length === 2) ? lastDayOf(Number(y), Number(mo)) : 31;
      d = pad2(Math.min(last, Math.max(1, Number(d))));
    }

    return y + (mo ? '-' + mo : '') + (d ? '-' + d : '');
  }

  /** 和暦。境目の年は両方を出す（1989 → 昭和64/平成元）。 */
  function eraLabel(y) {
    function n(k) { return k === 1 ? '元' : String(k); }
    if (y >= 2019) return (y === 2019 ? '平成31/' : '') + '令和' + n(y - 2018);
    if (y >= 1989) return (y === 1989 ? '昭和64/' : '') + '平成' + n(y - 1988);
    if (y >= 1926) return (y === 1926 ? '大正15/' : '') + '昭和' + n(y - 1925);
    if (y >= 1912) return (y === 1912 ? '明治45/' : '') + '大正' + n(y - 1911);
    return '明治' + n(y - 1867);
  }

  /** 日本標準時の「きょう」を 'YYYY-MM-DD' で。core.js があればそれを使う。 */
  function jstToday() {
    if (window.Admin && window.Admin.fmt && window.Admin.fmt.today) {
      return window.Admin.fmt.today();
    }
    var parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Tokyo',
      year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date());
    var got = {};
    for (var i = 0; i < parts.length; i++) got[parts[i].type] = parts[i].value;
    return got.year + '-' + got.month + '-' + got.day;
  }

  function createCalendarPopup(inputEl) {
    // すでに同じ入力欄のカレンダーが開いていれば、作り直さない。
    // focusin と click の両方から呼ばれるため、以前は同じ欄で2回作られ、
    // 1つ目の「外側クリックで閉じる」リスナーが残って2つ目を閉じていた。
    // その結果、日付をクリックしても値が入らず閉じるだけになっていた。
    if (activePicker && activePicker._inputEl === inputEl) return;
    if (activePicker) {
      // 前のカレンダーは、document に付けたリスナーごと片付ける。
      if (activePicker._close) activePicker._close();
      else activePicker.remove();
      activePicker = null;
    }

    // 入力欄が空のときに開く月も、日本の「きょう」に合わせる。
    // 生年月日の欄（data-date-kind="birth"）は、空のとき「きょう」で開くと
    // 1960年代まで数百回めくることになる。対象（満40～74歳）の真ん中の年の
    // 1月で開き、「今日」ボタンも出さない。
    var isBirth = inputEl.getAttribute('data-date-kind') === 'birth';
    var thisYear = Number(jstToday().slice(0, 4));
    var yearRange = isBirth ? [thisYear - 100, thisYear] : [thisYear - 10, thisYear + 5];
    var initial = isBirth ? (thisYear - 57) + '-01-01' : jstToday();
    var typedInitial = normalizeDate(inputEl.value);
    if (typedInitial) initial = typedInitial;
    var initialParts = initial.split('-').map(Number);
    var currentDate = new Date(initialParts[0], initialParts[1] - 1, initialParts[2]);

    var viewYear = currentDate.getFullYear();
    var viewMonth = currentDate.getMonth(); // 0-indexed

    var popup = document.createElement('div');
    popup.className = 'ja-datepicker-popup';
    popup.style.cssText = [
      'position: absolute',
      'z-index: 99999',
      'background: #ffffff',
      'border: 1px solid #CBD5E1',
      'border-radius: 10px',
      'box-shadow: 0 10px 25px -5px rgba(0,0,0,0.15), 0 8px 10px -6px rgba(0,0,0,0.1)',
      'padding: 16px',
      'width: ' + (isBirth ? '300px' : '280px'),
      'font-family: var(--font-base)',
      'color: #1E293B',
      'user-select: none',
      'animation: jaFadeIn 0.15s ease-out'
    ].join(';');

    function renderMonth() {
      popup.innerHTML = '';

      // --- Header (年月 & 前月/次月ボタン) ---
      var header = document.createElement('div');
      header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;';

      // 年・月は選択で一気に移れるようにする。前月/次月だけだと、遠い日付
      // （生年月日など）に届くまで何百回も押すことになる。
      var title = document.createElement('div');
      title.style.cssText = 'display:flex;align-items:center;gap:6px;';
      var selStyle = 'border:1px solid #E2E8F0;border-radius:6px;padding:3px 4px;font:inherit;font-size:14px;font-weight:700;color:#0F172A;background:#fff;cursor:pointer;';

      var yearSel = document.createElement('select');
      yearSel.setAttribute('aria-label', '年');
      yearSel.style.cssText = selStyle;
      var yFrom = Math.min(yearRange[0], viewYear), yTo = Math.max(yearRange[1], viewYear);
      for (var yy = yFrom; yy <= yTo; yy++) {
        var yOpt = document.createElement('option');
        yOpt.value = String(yy);
        yOpt.textContent = yy + '年' + (isBirth ? '（' + eraLabel(yy) + '）' : '');
        if (yy === viewYear) yOpt.selected = true;
        yearSel.appendChild(yOpt);
      }
      yearSel.onchange = function () {
        viewYear = Number(yearSel.value);
        renderMonth();
        var again = popup.querySelector('select[aria-label="年"]');
        if (again) again.focus();
      };

      var monthSel = document.createElement('select');
      monthSel.setAttribute('aria-label', '月');
      monthSel.style.cssText = selStyle;
      for (var mi = 0; mi < 12; mi++) {
        var mOpt = document.createElement('option');
        mOpt.value = String(mi);
        mOpt.textContent = (mi + 1) + '月';
        if (mi === viewMonth) mOpt.selected = true;
        monthSel.appendChild(mOpt);
      }
      monthSel.onchange = function () {
        viewMonth = Number(monthSel.value);
        renderMonth();
        var again = popup.querySelector('select[aria-label="月"]');
        if (again) again.focus();
      };

      title.appendChild(yearSel);
      title.appendChild(monthSel);

      var btnPrev = document.createElement('button');
      btnPrev.type = 'button';
      btnPrev.innerHTML = '‹';
      btnPrev.style.cssText = 'background:none;border:1px solid #E2E8F0;border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:18px;line-height:1;color:#64748B;display:flex;align-items:center;justify-content:center;';
      btnPrev.onmousedown = function (e) { e.preventDefault(); };
      btnPrev.onclick = function (e) {
        e.stopPropagation();
        viewMonth--;
        if (viewMonth < 0) {
          viewMonth = 11;
          viewYear--;
        }
        renderMonth();
      };

      var btnNext = document.createElement('button');
      btnNext.type = 'button';
      btnNext.innerHTML = '›';
      btnNext.style.cssText = 'background:none;border:1px solid #E2E8F0;border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:18px;line-height:1;color:#64748B;display:flex;align-items:center;justify-content:center;';
      btnNext.onmousedown = function (e) { e.preventDefault(); };
      btnNext.onclick = function (e) {
        e.stopPropagation();
        viewMonth++;
        if (viewMonth > 11) {
          viewMonth = 0;
          viewYear++;
        }
        renderMonth();
      };

      var navBtns = document.createElement('div');
      navBtns.style.cssText = 'display:flex;gap:6px;';
      navBtns.appendChild(btnPrev);
      navBtns.appendChild(btnNext);

      header.appendChild(title);
      header.appendChild(navBtns);
      popup.appendChild(header);

      // --- Weekday Row ---
      var weekGrid = document.createElement('div');
      weekGrid.style.cssText = 'display:grid;grid-template-columns:repeat(7, 1fr);gap:4px;text-align:center;font-size:12px;font-weight:700;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #F1F5F9;';

      WEEKDAYS_JA.forEach(function (wd, idx) {
        var wdEl = document.createElement('div');
        wdEl.textContent = wd;
        if (idx === 0) wdEl.style.color = '#EF4444'; // 日曜日 赤
        else if (idx === 6) wdEl.style.color = '#3B82F6'; // 土曜日 青
        else wdEl.style.color = '#64748B';
        weekGrid.appendChild(wdEl);
      });
      popup.appendChild(weekGrid);

      // --- Days Grid ---
      var daysGrid = document.createElement('div');
      daysGrid.style.cssText = 'display:grid;grid-template-columns:repeat(7, 1fr);gap:4px;text-align:center;font-size:13px;';

      var firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay();
      var daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      var prevMonthDays = new Date(viewYear, viewMonth, 0).getDate();

      // Leading days from prev month
      for (var i = firstDayOfWeek - 1; i >= 0; i--) {
        var prevDay = document.createElement('div');
        prevDay.style.cssText = 'padding:6px 0;color:#CBD5E1;font-size:12px;';
        prevDay.textContent = String(prevMonthDays - i);
        daysGrid.appendChild(prevDay);
      }

      // 「きょう」は日本標準時で決める。`toISOString()` は世界標準時の
      // ため、日本の午前0時〜9時のあいだ前日を返していた。
      var todayStr = jstToday();
      var selectedVal = normalizeDate(inputEl.value) || inputEl.value;

      for (var d = 1; d <= daysInMonth; d++) {
        (function (dayNum) {
          var dayCell = document.createElement('div');
          var mm = String(viewMonth + 1).padStart(2, '0');
          var dd = String(dayNum).padStart(2, '0');
          var dateStr = viewYear + '-' + mm + '-' + dd;

          var isSelected = (dateStr === selectedVal);
          var isToday = (dateStr === todayStr);

          var dayOfWeek = new Date(viewYear, viewMonth, dayNum).getDay();

          dayCell.style.cssText = [
            'padding: 6px 0',
            'border-radius: 6px',
            'cursor: pointer',
            'font-weight: ' + (isSelected || isToday ? '700' : '500'),
            'background: ' + (isSelected ? '#0A3A31' : 'none'),
            'color: ' + (isSelected ? '#ffffff' : (dayOfWeek === 0 ? '#EF4444' : (dayOfWeek === 6 ? '#2563EB' : '#1E293B'))),
            isToday && !isSelected ? 'border: 1px solid #0A3A31' : 'border: 1px solid transparent'
          ].join(';');

          dayCell.textContent = String(dayNum);

          dayCell.onmouseenter = function () {
            if (!isSelected) dayCell.style.background = '#F1F5F9';
          };
          dayCell.onmouseleave = function () {
            if (!isSelected) dayCell.style.background = 'none';
          };

          dayCell.onmousedown = function (e) { e.preventDefault(); };
          dayCell.onclick = function (e) {
            e.stopPropagation();
            inputEl.value = dateStr;
            inputEl.dispatchEvent(new Event('change', { bubbles: true }));
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            closePopup();
          };

          daysGrid.appendChild(dayCell);
        })(d);
      }

      popup.appendChild(daysGrid);

      // --- Footer Buttons (クリア & 今日) ---
      var footer = document.createElement('div');
      footer.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid #F1F5F9;font-size:12.5px;';

      var btnClear = document.createElement('button');
      btnClear.type = 'button';
      btnClear.textContent = 'クリア';
      btnClear.style.cssText = 'background:none;border:none;color:#64748B;cursor:pointer;padding:4px 8px;font-weight:600;';
      btnClear.onmousedown = function (e) { e.preventDefault(); };
      btnClear.onclick = function (e) {
        e.stopPropagation();
        inputEl.value = '';
        inputEl.dispatchEvent(new Event('change', { bubbles: true }));
        inputEl.dispatchEvent(new Event('input', { bubbles: true }));
        closePopup();
      };

      var btnToday = document.createElement('button');
      btnToday.type = 'button';
      btnToday.textContent = '今日';
      btnToday.style.cssText = 'background:#F0FDF4;border:1px solid #BBF7D0;color:#0A3A31;border-radius:6px;cursor:pointer;padding:4px 12px;font-weight:700;';
      btnToday.onmousedown = function (e) { e.preventDefault(); };
      btnToday.onclick = function (e) {
        e.stopPropagation();
        inputEl.value = todayStr;
        inputEl.dispatchEvent(new Event('change', { bubbles: true }));
        inputEl.dispatchEvent(new Event('input', { bubbles: true }));
        closePopup();
      };

      footer.appendChild(btnClear);
      if (!isBirth) footer.appendChild(btnToday);
      popup.appendChild(footer);
    }

    renderMonth();

    // Position popup
    var rect = inputEl.getBoundingClientRect();
    popup.style.top = (window.scrollY + rect.bottom + 4) + 'px';
    popup.style.left = (window.scrollX + rect.left) + 'px';

    document.body.appendChild(popup);
    popup._inputEl = inputEl;
    activePicker = popup;

    // 開いたまま日付を打ち込んだら、その月に表示を移す。
    function onType() {
      var typed = normalizeDate(inputEl.value);
      if (!typed) return;
      var p = typed.split('-').map(Number);
      viewYear = p[0];
      viewMonth = p[1] - 1;
      renderMonth();
    }
    inputEl.addEventListener('input', onType);

    function onDocClick(e) {
      if (popup && !popup.contains(e.target) && e.target !== inputEl) {
        closePopup();
      }
    }

    function closePopup() {
      inputEl.removeEventListener('input', onType);
      popup.remove();
      if (activePicker === popup) activePicker = null;
      document.removeEventListener('mousedown', onDocClick);
    }
    popup._close = closePopup;

    setTimeout(function () {
      document.addEventListener('mousedown', onDocClick);
    }, 10);
  }

  // Global binding for all date inputs
  document.addEventListener('focusin', function (e) {
    var t = e.target;
    var isDate = t && t.tagName === 'INPUT'
      && (t.type === 'date' || t.getAttribute('data-date') === '1');
    if (isDate) {
      // Prevent OS datepicker popup from opening if possible
      t.addEventListener('click', function (ev) {
        ev.preventDefault();
        createCalendarPopup(t);
      }, { once: true });
      createCalendarPopup(t);
    }
  });

  // 打っている間に、ありえない日付にならないよう直す。
  // 途中の文字を書き換えている最中（カーソルが末尾にない）は触らない。
  // せっかく直した位置にカーソルが飛んでしまうためである。
  document.addEventListener('input', function (e) {
    var t = e.target;
    if (!(t && t.tagName === 'INPUT' && t.getAttribute('data-date') === '1')) return;
    if (t.selectionStart !== null && t.selectionStart !== t.value.length) return;

    var masked = maskDate(t.value);
    if (masked !== t.value) {
      t.value = masked;
      try { t.setSelectionRange(masked.length, masked.length); } catch (err) { /* 無視 */ }
    }
  });

  // 欄を離れたとき、手で打った日付を 'YYYY-MM-DD' にそろえる。
  // 「19650220」のまま保存されると、サーバーが日付として読めずに弾く。
  document.addEventListener('focusout', function (e) {
    var t = e.target;
    if (!(t && t.tagName === 'INPUT' && t.getAttribute('data-date') === '1')) return;
    var v = normalizeDate(t.value);
    if (v && v !== t.value) {
      t.value = v;
      t.dispatchEvent(new Event('input', { bubbles: true }));
      t.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    // 4-2-2桁そろっていない（1965-02 など）。消さずに残し、足りないことだけ伝える。
    if (!v && t.value.trim() && window.Admin && window.Admin.toast) {
      window.Admin.toast('日付は西暦8桁でご入力ください。（例：1965-02-20）', 'warn');
    }
  });

  window.JaDatePicker = {
    attach: createCalendarPopup
  };
})();