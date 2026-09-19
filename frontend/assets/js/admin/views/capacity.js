/* ==========================================================================
   capacity.js — A-22 정원 관리 캘린더
   --------------------------------------------------------------------------
   20개 회장 × 시간대를 하나씩 만지는 것은 불가능하다 (자체 피드백 M-5).
   회장은 1년에 하루만 열지만, 그 하루의 시간표는 8칸이고 회장마다 다르다.
   그래서 이 화면은 두 층으로 만든다.

     달력 : 누른 날 하나, 또는 Ctrl+클릭으로 담은 여러 날을 한 번에 휴진 처리
     시간표 : 고른 하루의 12슬롯을 개별 조정

   **이미 예약된 인원보다 낮은 정원으로는 내릴 수 없다** (BR-09 / M-6).
   서버가 거부하며, 거부된 항목은 이유와 함께 그대로 보여 준다.
   조용히 넘기면 스태프는 바뀐 줄 알고 넘어간다.

   변경은 이용자 예약 화면에 즉시 반영된다. 어느 자리가 다시 열렸는지
   조작 직후에 알려 준다 (자체 피드백 M-7).
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var hospitals = null;

  /* Ctrl+클릭으로 담은 날짜 { 'YYYY-MM-DD': true }.
     -------------------------------------------------------------------
     **회장이 바뀔 때만 비운다.** 예전에는 `draw()` 가 매번 비웠는데,
     달을 넘기는 것도 날짜를 펴는 것도 전부 `draw()` 를 지나므로 「다음 달 →」
     한 번에 담아 둔 날이 통째로 사라졌다.

     하필 그것이 이 기능이 가장 필요한 상황이다. 한 회장이 여러 날 열 때
     그 날들은 9월·11월·이듬해 2월처럼 **여러 달에 흩어져 있다.** 같은 달
     안에서만 담을 수 있으면 「여러 날 한꺼번에 휴진」이 이름만 남는다. */
  var marked = {};

  /* 열쇠는 **회장 + 날짜**다. 날짜만으로 담으면 달력에 함께 그려지는 다른
     회장의 개최일을 담았을 때 그 날이 **지금 보는 회장**에 걸린다. 휴진은
     날짜가 아니라 「그 회장의 그 날」을 닫는 일이다. */
  function markKey(hospitalId, iso) { return hospitalId + '|' + iso; }

  /** 담은 날을 비운다. 휴진을 걸고 난 뒤. */
  function clearMarks() { marked = {}; }

  A.route('capacity', function (view, params) {
    var ready = hospitals
      ? Promise.resolve()
      : A.api.get('/hospitals').then(function (body) { hospitals = body.data; });

    ready
      .then(function () {
        if (!hospitals.length) {
          A.setTitle('定員カレンダー', '登録済みの会場なし');
          A.clear(view).appendChild(el('div.empty', {}, [
            el('p.empty__title', { text: '登録された会場がありません' }),
            el('p', { text: '先に会場を登録してください。' })
          ]));
          return;
        }
        var hospitalId = Number(params.hospital_id) || hospitals[0].id;
        var hospital = hospitals.filter(function (h) { return h.id === hospitalId; })[0] || hospitals[0];
        A.setTitle('定員カレンダー', '会場ごとの定員の確認・変更');

        // 주소로 달을 지정하지 않았다면 **이번 달**을 편다.
        //
        // 회장은 1년에 며칠만 열어, 개최월을 펴 주는 편이 그 회장만 볼 때는
        // 친절하다. 그런데 담당자는 대개 「오늘 무슨 일인가」를 보러 온다.
        // 회장을 고를 때마다 달력이 제멋대로 다른 달로 튀면 지금 어느 달을
        // 보고 있는지부터 다시 읽어야 한다.
        //
        // 이번 달을 펴도 빈 달력이 되지 않는다 — 그 달에 여는 **다른 회장**의
        // 개최일을 함께 그리기 때문이다 (hospitalOn / otherVenueCell).
        // 이 회장의 다음 회차로 건너뛰려면 위의 「개최 회차」 칩을 쓴다.
        var month = params.month || A.fmt.month(new Date());
        load(view, hospitalId, month, params.date || '');
      })
      .catch(function (error) { A.fail(view, error); });
  });

  function load(view, hospitalId, month, targetDate) {
    A.clear(view).appendChild(A.loading('定員状況を読み込み中です…'));

    A.api.get('/hospitals/' + hospitalId + '/capacity' +
              A.query({ month: month, date: targetDate }))
      .then(function (body) { draw(view, body.data); })
      .catch(function (error) { A.fail(view, error); });
  }

  /** 고친 뒤 다시 그린다.
   *
   *  회장 목록도 함께 버린다. 달력은 **다른 회장의 개최일**을 그 목록의
   *  `schedules[]` 에서 꺼내 그리는데(hospitalOn), 그 사본은 화면에 처음
   *  들어올 때 한 번 받아 놓은 것이다. 휴진을 걸거나 풀어도 그 사본은
   *  옛 값 그대로라, 회장을 바꾸는 순간 방금 푼 날이 아직 빨갛게 보인다.
   *  실제로 그랬다. */
  function reload(view, data) {
    clearMarks();
    hospitals = null;
    A.api.get('/hospitals')
      .then(function (body) { hospitals = body.data; })
      .catch(function () { /* 못 받아도 그 회장 달력은 그린다 */ })
      .then(function () {
        load(view, data.hospital_id, data.month, data.selected_date || '');
      });
  }

  /* ======================================================================
     그리기
     ====================================================================== */

  function draw(view, data) {
    A.clear(view);
    // 담아 둔 날짜는 **지우지 않는다** (marked 선언부 참조).
    // 지금 펴 놓은 날. Ctrl+클릭을 하나도 안 했을 때 휴진 버튼이 걸릴 대상이다.
    openedDate = data.selected_date || '';
    openedHospitalId = data.hospital_id;
    openedHospitalName = ((hospitals || []).filter(function (h) {
      return h.id === data.hospital_id;
    })[0] || {}).name || '';

    view.appendChild(toolbar(view, data));
    var chips = scheduleChips(data);
    if (chips) view.appendChild(chips);

    var cols = el('div.cap-cols');
    cols.appendChild(calendarCard(view, data));
    cols.appendChild(dayCard(view, data));
    view.appendChild(cols);
  }

  /* ------------------------------------------------------------------
     회차 바로가기
     ------------------------------------------------------------------
     회장이 9월·11월·이듬해 2월에 열면, 달력만으로는 「← 이전 달」을
     다섯 번 눌러야 다음 회차에 닿는다. 열리는 날은 애초에 몇 개뿐이므로
     전부 늘어놓고 한 번에 건너뛰게 한다.
     ------------------------------------------------------------------ */

  function scheduleChips(data) {
    var list = data.schedules || [];
    if (list.length < 2) return null;   // 하나뿐이면 달력이 이미 그 달이다

    return A.card('開催回 ' + list.length + '件', {
      body: el('div.cap-chips', {}, list.map(function (s) {
        var current = s.event_date === data.selected_date;
        return el('button.cap-chip' + (current ? '.is-current' : '')
                  + (s.is_past ? '.is-past' : ''), {
          type: 'button',
          text: s.event_date + ' (' + s.weekday + ')',
          title: (s.is_past ? '過去の開催回 ・ ' : '')
               + 'スロット ' + s.slot_count + '枠・定員 ' + s.capacity
               + ' ・ 予約 ' + s.reserved,
          'aria-current': current ? 'true' : null,
          onClick: function () {
            A.go('capacity', {
              hospital_id: data.hospital_id,
              month: s.event_date.slice(0, 7),
              date: s.event_date
            });
          }
        });
      }))
    });
  }

  /** 가타카나를 히라가나로 맞춘다. 「センター」와 「せんたー」를 같게 취급하기 위함. */
  function toHiragana(text) {
    return String(text || '').replace(/[ァ-ヶ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0x60);
    });
  }

  /* 회장 1곳이 여러 날 연다. `event_date`(대표 회차) 하나로는 그 회장이
     언제 여는지를 다 말할 수 없어, 회차 목록을 본다. */
  function schedulesOf(h) {
    return (h && h.schedules) || [];
  }

  /** 한 회장에서 검색 대상이 되는 모든 문자열을 이어 붙인다. */
  function haystack(h) {
    return toHiragana([
      h.name, h.code, h.region, h.area, h.city, h.address, h.tel,
      h.access_info, h.postal_code,
      schedulesOf(h).map(function (s) { return s.event_date; }).join(' '),
      // 읽기(후리가나)는 **서버가 준다** (`name_kana`). 예전에는 이 파일이
      // 회장 20곳의 읽기를 들고 있었는데, 담당자가 「회장 관리」 표에서
      // 고쳐도 이 사본은 바뀌지 않았다.
      h.name_kana || ''
    ].join(' ')).toLowerCase();
  }

  function toolbar(view, data) {
    var areas = [];
    (hospitals || []).forEach(function (h) {
      var sp = h.area || h.region || '';
      if (sp && areas.indexOf(sp) === -1) {
        areas.push(sp);
      }
    });
    areas.sort();

    var curHosp = (hospitals || []).filter(function (h) { return h.id === data.hospital_id; })[0];

    var kwInput = A.input({
      value: '',
      placeholder: '会場名・ひらがな（さんぷる）・コード・地域・住所',
      autocomplete: 'off'
    });

    var spSelect = A.select({}, [{ value: '', label: 'すべての地域' }].concat(
      areas.map(function (sp) {
        return { value: sp, label: sp, selected: curHosp ? (curHosp.area === sp || curHosp.region === sp) : false };
      })
    ));

    var hospSelect = A.select({
      style: 'font-weight:600;width:100%;'
    }, []);

    function matches(h, query) {
      return !query || haystack(h).indexOf(query) !== -1;
    }

    function inArea(h, sp) {
      return !sp || h.area === sp || h.region === sp;
    }

    /* 고른 地域 에 없으면 조건을 「전체」로 푼다
       --------------------------------------------------------------------
       담당자는 地域 을 골라 둔 채로 다음 회장을 찾는다. 찾는 회장이 옆
       地域 에 있으면 「검색 결과 없음」만 뜨는데, **회장이 없어서가
       아니라 걸러져서 없는 것**이라는 사실이 화면에 없다. 그러면 이름을
       잘못 쳤다고 여기고 같은 말을 다시 친다.

       그래서 지금 地域 에는 없고 다른 地域 에는 있을 때, 조건을
       「전체」로 바꾸고 그 회장을 보여 준다. 사람이 원한 것은 地域 이
       아니라 그 회장이다.

       **검색어가 있을 때만** 푼다. 검색어 없이 地域 만 고른 것은
       「이 地域 을 본다」는 뜻이며, 그 안이 비어 있다는 것 자체가
       답이다. */
    function updateHospOptions() {
      var rawQuery = toHiragana(kwInput.value).trim().toLowerCase();
      var selSp = spSelect.value;

      var filtered = (hospitals || []).filter(function (h) {
        return inArea(h, selSp) && matches(h, rawQuery);
      });

      if (selSp && rawQuery && !filtered.length) {
        var anywhere = (hospitals || []).filter(function (h) {
          return matches(h, rawQuery);
        });
        if (anywhere.length) {
          spSelect.value = '';
          filtered = anywhere;
          A.toast('「' + selSp + '」にはないため、地域を「すべて」に変更しました。'
                  + '他の地域で ' + anywhere.length + '件見つかりました。', 'ok');
        }
      }

      hospSelect.innerHTML = '';
      if (!filtered.length) {
        hospSelect.appendChild(el('option', { value: '', text: '検索結果なし' }));
        return;
      }

      /* 지금 보고 있는 회장이 후보에 남아 있으면 그것을 고른 채로 둔다.
         남아 있지 않으면 **첫 후보**를 고른다.
         -------------------------------------------------------------------
         예전에는 「지금 회장」만 골랐다. 그래서 「西区民」을 쳐서 후보가 한
         곳으로 좁혀져도 드롭다운의 값은 원래 회장 그대로였고, 「검색」을
         누르면 **찾던 곳이 아니라 보고 있던 곳으로** 갔다. 검색이 목록만
         줄이고 아무 데도 데려다주지 않았다. */
      var stillThere = filtered.some(function (h) { return h.id === data.hospital_id; });

      filtered.forEach(function (h, index) {
        var opt = el('option', {
          value: String(h.id),
          text: h.name + (h.is_visible ? '' : ' （非表示）')
        });
        if (stillThere ? h.id === data.hospital_id : index === 0) {
          opt.selected = true;
        }
        hospSelect.appendChild(opt);
      });
    }

    kwInput.addEventListener('input', updateHospOptions);
    spSelect.addEventListener('change', updateHospOptions);

    /* 회장을 바꿀 때 **이 달에 안 여는 회장이면 그 회장이 여는 날로 간다.**
       -------------------------------------------------------------------
       두 요구가 부딪힌다.

         · 회장을 하나씩 넘겨 볼 때 달력이 매번 다른 달로 튀면, 지금 어느
           달을 보고 있는지부터 다시 읽어야 한다. 「10월에 누가 여나」를
           보려던 흐름이 끊긴다.
         · 그런데 「サンプル会館 A」를 **찾아서** 왔는데 그 회장이 안 여는
           9월 달력에 그대로 남으면, 찾은 보람이 없다. 빈 달력만 본다.

       그래서 조건을 붙인다 — **지금 보는 달에 그 회장의 회차가 있으면
       그대로 두고, 없으면 여는 달로 옮긴다.** 넘겨 볼 때는 안 튀고,
       찾아왔을 때는 데려다준다.

       고르는 회차는 「앞으로 열 첫 회차」다. 없으면 마지막 회차를 편다 —
       지난 회차라도 빈 달력보다는 낫고, 「이 회장은 이제 안 연다」가 그
       자리에서 읽힌다. */
    function monthForHospital(hId) {
      var target = (hospitals || []).filter(function (h) {
        return h.id === Number(hId);
      })[0];
      var list = (target && target.schedules) ? target.schedules.slice() : [];
      if (!list.length) return { month: data.month, date: '' };

      list.sort(function (a, b) {
        return a.event_date < b.event_date ? -1 : 1;
      });

      // 지금 보는 달에 이미 회차가 있으면 달력을 흔들지 않는다.
      var here = list.filter(function (sc) {
        return sc.event_date.slice(0, 7) === data.month;
      })[0];
      if (here) return { month: data.month, date: here.event_date };

      var upcoming = list.filter(function (sc) { return !sc.is_past; })[0];
      var pick = upcoming || list[list.length - 1];
      return { month: pick.event_date.slice(0, 7), date: pick.event_date };
    }

    function goToHospital(hId) {
      // 회장이 바뀌면 담은 날을 버린다. 남의 회장 날짜를 들고 넘어가면
      // 그 날들이 새 회장의 휴진 대상이 된다.
      clearMarks();
      var to = monthForHospital(hId);
      A.go('capacity', {
        hospital_id: Number(hId), month: to.month, date: to.date
      });
    }

    hospSelect.addEventListener('change', function () {
      if (hospSelect.value && Number(hospSelect.value) !== data.hospital_id) {
        goToHospital(hospSelect.value);
      }
    });

    updateHospOptions();

    kwInput.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        if (hospSelect.value) { goToHospital(hospSelect.value); }
      }
    });

    var form = el('div.filters.filters--capacity', {}, [
      A.field('検索', kwInput),
      A.field('地域', spSelect),
      A.field('会場選択', hospSelect),
      el('div.filters__actions', {}, [
        el('button.btn.btn--primary', {
          type: 'button', text: '検索',
          onClick: function () {
            if (!hospSelect.value) {
              A.toast('該当する会場がありません。検索キーワードをクリアして再度お試しください。', 'warn');
              return;
            }
            if (Number(hospSelect.value) === data.hospital_id) {
              // 이미 그 회장을 보고 있다. 아무 일도 안 일어나면 「검색이
              // 안 되네」로 읽히므로 그렇지 않다는 것을 알린다.
              A.toast('すでにこの会場のカレンダーを表示しています。', 'ok');
              return;
            }
            goToHospital(hospSelect.value);
          }
        }),
        el('button.btn.btn--ghost', {
          type: 'button', text: 'リセット',
          onClick: function () {
            kwInput.value = '';
            spSelect.value = '';
            updateHospOptions();
          }
        })
      ])
    ]);

    var headerNode = el('div', {
      style: 'display:flex;align-items:center;justify-content:space-between;width:100%;flex-wrap:wrap;gap:12px;'
    }, [
      el('div', {}, [
        el('strong', {
          style: 'font-size:16px;font-weight:700;color:var(--a-ink);display:block;',
          text: '検索条件'
        }),
        el('p', {
          style: 'margin:2px 0 0;font-size:12px;color:var(--a-ink-sub);font-weight:normal;',
          text: '漢字が分からなくてもひらがなで検索できます （例: さんぷる → サンプル会館 A）'
        })
      ])
    ]);

    return A.card(headerNode, {
      body: form
    });
  }

  /* --- 달력 --------------------------------------------------------------- */

  function calendarCard(view, data) {
    var byDate = {};
    data.days.forEach(function (d) { byDate[d.date] = d; });

    var p = data.month.split('-').map(Number);
    var curYear = p[0];
    var curMonth = p[1];
    var first = new Date(curYear, curMonth - 1, 1);
    var lastDay = new Date(curYear, curMonth, 0).getDate();
    var lead = first.getDay();

    function move(delta) {
      var d = new Date(curYear, curMonth - 1 + delta, 1);
      A.go('capacity', { hospital_id: data.hospital_id, month: A.fmt.month(d) });
    }

    var nowYear = new Date().getFullYear();
    var yearOptions = [];
    for (var y = nowYear - 2; y <= nowYear + 3; y++) {
      yearOptions.push({ value: String(y), label: y + '年', selected: y === curYear });
    }
    var yearSelect = A.select({
      style: 'font-weight:700;font-size:17px;color:#0A3A31;padding:6px 30px 6px 14px;min-width:128px;border-radius:6px;min-height:38px;border:1.5px solid var(--a-line-strong);'
    }, yearOptions);

    var monthOptions = [];
    for (var m = 1; m <= 12; m++) {
      var mVal = m < 10 ? '0' + m : String(m);
      monthOptions.push({ value: mVal, label: m + '月', selected: m === curMonth });
    }
    var monthSelect = A.select({
      style: 'font-weight:700;font-size:17px;color:#0A3A31;padding:6px 30px 6px 14px;min-width:100px;border-radius:6px;min-height:38px;border:1.5px solid var(--a-line-strong);'
    }, monthOptions);

    function onYearMonthChange() {
      var ym = yearSelect.value + '-' + monthSelect.value;
      A.go('capacity', { hospital_id: data.hospital_id, month: ym });
    }

    yearSelect.addEventListener('change', onYearMonthChange);
    monthSelect.addEventListener('change', onYearMonthChange);

    var monthNavNode = el('div', {
      style: 'display:inline-flex;align-items:center;justify-content:center;gap:8px;flex-wrap:nowrap;'
    }, [
      /* 화살표만 둔다. 연·월 드롭다운이 바로 옆에 있어 「달을 넘긴다」는
         것이 자리로 읽힌다. 글자를 빼면 회장명이 들어갈 폭이 난다.
         눈으로 못 읽는 사람을 위해 aria-label 은 남긴다. */
      el('button.btn', {
        type: 'button', text: '←',
        title: '前の月',
        'aria-label': '前の月',
        style: 'min-height:38px;padding:0 14px;font-size:15px;font-weight:500;',
        onClick: function () { move(-1); }
      }),
      yearSelect,
      monthSelect,
      el('button.btn', {
        type: 'button', text: '→',
        title: '次の月',
        'aria-label': '次の月',
        style: 'min-height:38px;padding:0 14px;font-size:15px;font-weight:500;',
        onClick: function () { move(1); }
      }),
      /* 채움(btn--primary)을 뺀다. 하는 일은 달 이동 보조인데 카드에서
         제일 강한 요소가 되어 회장명보다 먼저 눈에 들어왔다. */
      el('button.btn', {
        type: 'button', text: '今日へ移動',
        style: 'min-height:38px;padding:0 16px;font-size:14px;font-weight:500;',
        onClick: function () {
          A.go('capacity', {
            hospital_id: data.hospital_id, month: A.fmt.month(new Date())
          });
        }
      })
    ]);

    /* 달력 머리 = 「어느 회장의 · 어느 달」.
       -------------------------------------------------------------------
       회장명은 원래 「검색 조건」 카드 머리의 초록 칩에 있었다. 달력과 다른
       카드라 격자를 보는 동안 눈에 들어오지 않았고, 바로 옆 회장 드롭다운이
       같은 이름을 이미 적고 있어 중복이기도 했다.

       초록 배경·테두리는 뺐다. 그 표현은 상태나 경고에 쓰는 것이고 이건
       **제목**이다. 굵기만으로 충분하다. 「검색 조건」 카드의 초록도 이제
       「검색」 버튼 하나로 정리된다. */
    var titleHosp = (hospitals || []).filter(function (h) {
      return h.id === data.hospital_id;
    })[0];

    /* 이 화면의 첫 질문은 「지금 어느 회장을 보고 있는가」다.
       -------------------------------------------------------------------
       달력의 숫자는 회장이 바뀌어도 비슷하게 생겼다. 회장을 잘못 본 채
       휴진을 걸면 되돌리기 번거로운 사고가 된다. 그래서 이 줄은 카드에서
       **가장 강한 요소**여야 한다.

       세 가지를 겹쳐 쓴다 — 크기(22px), 브랜드 초록, 왼쪽 굵은 색면.
       하나만으로는 옆의 달 이동 버튼 덩어리에 묻힌다. 회장 코드를 뒤에
       작게 붙이는 것은, 이름이 길어 잘려도 회장을 특정할 수 있게 하기
       위해서다(회장명은 「サンプル市民総合文化センター（サンプルホール）」처럼 길다). */
    var venueTitleNode = titleHosp ? el('div', {
      // 연초록 면 위에 올린다. 왼쪽 굵은 선만으로는 그 줄이 「제목」이라는
      // 것은 말해도 「무엇을 보고 있나」로 눈이 먼저 가지는 않았다.
      style: 'display:inline-flex;align-items:center;gap:10px;min-width:0;'
           + 'background:#F0FDF4;border-radius:8px;padding:6px 14px 6px 0;'
           + 'overflow:hidden;'
    }, [
      el('span', {
        style: 'width:5px;align-self:stretch;min-height:30px;'
             + 'background:var(--c-primary, #0B6E5B);flex:none;'
      }),
      el('span', { style: 'min-width:0;display:flex;align-items:baseline;gap:8px;' }, [
        el('strong', {
          style: 'font-size:var(--a-fs-xl);font-weight:700;line-height:1.25;'
               + 'color:var(--c-primary, #0B6E5B);'
               + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;',
            text: shortVenueName(titleHosp.name),
          title: titleHosp.name
        }),
        el('span', {
          style: 'font-size:var(--a-fs-sm);font-weight:700;color:var(--a-ink-weak);flex:none;',
          text: titleHosp.code || ''
        })
      ])
    ]) : null;

    var cardHeaderNode = el('div', {
      style: 'width:100%;padding:2px 0;display:flex;align-items:center;'
           + 'justify-content:space-between;gap:16px;flex-wrap:wrap;'
    }, [
      el('div', { style: 'min-width:0;display:flex;flex-direction:column;gap:4px;' }, [
        venueTitleNode,
        el('p', {
          style: 'margin:0;font-size:var(--a-fs-sm);color:var(--a-ink-sub);font-weight:normal;',
          text: '日付をクリックするとその日のスケジュールが開き、下の休診ボタンの対象になります。'
        })
      ].filter(Boolean)),
      monthNavNode
    ]);

    var grid = el('div.cal');
    ['日', '月', '火', '水', '木', '金', '土'].forEach(function (label, index) {
      grid.appendChild(el('div.cal__dow' +
        (index === 0 ? '.cal__dow--sun' : (index === 6 ? '.cal__dow--sat' : '')),
        { text: label }));
    });

    for (var i = 0; i < lead; i++) grid.appendChild(el('div.day.day--empty'));

    for (var day = 1; day <= lastDay; day++) {
      grid.appendChild(dayCell(view, data, byDate, p, day));
    }

    var bulkBar = bulkActions(view, data);

    return A.card(cardHeaderNode, {
      body: [
        el('p.field__hint', {
          style: 'margin-bottom:8px',
          text: 'マスの数字は「予約 / 定員」です。複数日を一括で休診にするには ' +
                'Ctrl（またはShift）を押しながらクリックして選択してください。'
        }),
        calLegend(),
        grid,
        bulkBar
      ]
    });
  }

  /* --- 칸 모양 읽는 법 -----------------------------------------------------
     달력은 테두리와 빗금으로 세 가지를 말한다. 그런데 **그 규칙을 아무 데도
     적어 두지 않았다.** 점선이 다른 회장이라는 것도, 빨간 테두리가 휴진이라는
     것도 눌러 보고 알아내야 했다. 칸 자체에 적을 자리가 없으므로 위에 한 줄
     둔다. */

  function calLegend() {
    function item(state, label) {
      return el('span', {
        style: 'display:inline-flex;align-items:center;gap:5px;'
      }, [stateDot(state), el('span', { text: label })]);
    }

    /* 칸이 쓰는 색 그대로를 적는다 (`dayState`). 색 하나에 뜻 하나다.
       칸 안의 **글자**가 남의 회장인지 내 회장인지를 따로 말한다 —
       이름이 적혀 있으면 다른 회장, 숫자면 이 회장이다. */
    return el('div', {
      style: 'display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:10px;'
           + 'font-size:12px;color:var(--a-ink-sub);'
    }, [
      item('open',   '受付中'),
      item('over',   '受付終了'),
      item('closed', '休診（全時間帯締切）'),
      el('span', {
        style: 'color:var(--a-ink-weak);',
        text: '・ 会場名が表示されている日は他の会場の開催日です'
      })
    ]);
  }

  /* ------------------------------------------------------------------
     다른 회장의 개최일
     ------------------------------------------------------------------
     한 회장만 보면 달력이 거의 비어 있다. 그 달에 다른 회장이 열면 그
     자리에 이름을 적고, 누르면 그 회장으로 넘어간다.

     이 값은 이미 받아 둔 회장 목록에서 꺼낸다. 달을 넘길 때마다 조회를
     더 하지 않는다.
     ------------------------------------------------------------------ */

  /** iso 날짜에 여는 **다른** 회장. 없으면 null. */
  function hospitalOn(iso, currentId) {
    if (!hospitals) return null;   // 목록이 아직 안 왔을 때
    for (var i = 0; i < hospitals.length; i++) {
      var h = hospitals[i];
      if (h.id === currentId) continue;
      var list = schedulesOf(h);
      for (var j = 0; j < list.length; j++) {
        if (list[j].event_date === iso) return { hospital: h, schedule: list[j] };
      }
    }
    return null;
  }

  /** 다른 회장의 개최일 칸. 지금 회장의 칸과 눈에 띄게 달라야 한다. */
  function otherVenueCell(hit, iso, day, dow) {
    var h = hit.hospital;
    var sc = hit.schedule;
    // 회장을 바꿔도 휴진 표시가 유지되어야 한다. 이 값이 없으면 방금
    // 빨갛던 날이 다른 회장에서 볼 때 평범한 칸으로 돌아간다.
    return el('button.day.day--other.day--st-' + dayState(sc)
              + (marked[markKey(h.id, iso)] ? '.is-marked' : ''), {
      type: 'button',
      title: h.name + (h.region ? ' \u00b7 ' + h.region : '')
           + ' \u00b7 予約 ' + (sc.reserved || 0) + ' / 定員 ' + (sc.capacity || 0)
           + (sc.is_all_closed ? ' ・ 休診' : ''),
      dataset: { date: iso },
      style: 'opacity:.72;',
      onClick: function (ev) {
        /* Ctrl+클릭은 「담기」다. **다른 회장의 날도 담게 둔다.**
           예전에는 Ctrl 을 봐주지 않아 그냥 회장을 갈아탔고, 담으려던
           사람은 「왜 안 담기지」가 아니라 「왜 튕겼지」를 겪었다.

           담긴 날은 그 회장에 걸린다 — 지금 보는 회장이 아니라. 휴진은
           날짜가 아니라 **그 회장의 그 날**을 닫는 일이기 때문이다.
           어느 회장의 날인지는 확인 대화상자에 회장명과 함께 나온다. */
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
          toggleMark(this, iso, h.id, h.name);
          return;
        }
        A.go('capacity', { hospital_id: h.id, month: iso.slice(0, 7), date: iso });
      }
    }, [
      el('span.day__num' + dowClass(dow), { text: String(day) }),
      // 다른 회장 칸에는 **이름**을 적는다. 숫자는 내 회장의 것이 아니라
      // 「누가 여는 날인가」가 먼저다. 예약 수는 title 로 남는다.
      el('span.day__chip', {}, [
        stateDot(dayState(sc)),
        el('span.day__chip-text', { text: shortVenueName(h.name) })
      ])
    ]);
  }

  function dayCell(view, data, byDate, ym, day) {
    var iso = ym[0] + '-' + pad(ym[1]) + '-' + pad(day);
    var info = byDate[iso];
    var dow = new Date(ym[0], ym[1] - 1, day).getDay();

    // 슬롯이 없는 날 = 이 회장은 열지 않는 날.
    // 그렇다고 「아무 일도 없는 날」은 아니다. 다른 회장이 열면 그 사실을
    // 적어 준다. 이것이 없으면 달을 넘길 때마다 빈 달력만 나온다.
    if (!info) {
      var other = hospitalOn(iso, data.hospital_id);
      if (other) return otherVenueCell(other, iso, day, dow);

      /* 여는 회장이 없는 날. **숫자만 남긴다.**
         한 달 31칸 가운데 스물 몇 칸이 여기에 해당한다. 예전에는 이 칸도
         테두리 있는 상자에 「접수 없음」을 적어, 화면의 대부분을 「볼 것이
         없다」는 말이 차지했다. */
      return el('div.day.day--none', {}, [
        el('span.day__num' + dowClass(dow), { text: String(day) })
      ]);
    }

    var full = info.remaining <= 0;
    var state = dayState(scheduleOfDay(data, info));

    var cell = el('button.day.day--own.day--st-' + state
                  + (full ? '.day--full' : ''), {
      type: 'button',
      'aria-pressed': data.selected_date === iso ? 'true' : 'false',
      dataset: { date: iso },
      title: '予約 ' + info.reserved + ' / 定員 ' + info.capacity
           + (info.closed_slots
               ? (info.is_all_closed
                   ? ' ・ 休診'
                   : ' · ' + info.closed_slots + '枠締切')
               : ''),
      style: 'position:relative;',
      onClick: function (ev) {
        // Ctrl/Shift = 여러 날을 한꺼번에 담을 때.
        // 그냥 누르면 시간표를 펴고, 그 날이 곧 휴진 버튼의 대상이 된다.
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
          toggleMark(cell, iso, data.hospital_id, openedHospitalName);
          return;
        }
        A.go('capacity', {
          hospital_id: data.hospital_id, month: data.month, date: iso
        });
      }
    }, [
      el('span.day__num' + dowClass(dow), { text: String(day) }),
      // 점 + 「예약/정원」. 가동률 퍼센트와 막대는 뺐다 — 정원이 161 인데
      // 예약이 4 면 언제나 2% 라, 한 자리를 차지하고 아무 말도 하지 않았다.
      el('span.day__chip', {}, [
        stateDot(state),
        el('span.day__chip-text', {
          text: info.reserved + '/' + info.capacity
        })
      ]),
      /* 「N개 마감」은 뺐다. 칸에서 알아야 할 것은 「이 날 여는가 · 얼마나
         찼는가」까지이고, 어느 시간대가 닫혔는지는 눌러서 오른쪽 시간표로
         본다. 세 줄이 되면 칸이 다시 빽빽해진다. 요약은 title 에 남는다. */
      null
    ].filter(Boolean));

    if (marked[markKey(data.hospital_id, iso)]) cell.classList.add('is-marked');
    return cell;
  }

  /* 칸의 상태는 셋뿐이다. **글자 없이 색으로만** 말한다.
     -------------------------------------------------------------------
       휴진    빨강 — 그 날 전 시간대가 닫혀 있다
       종료    회색 — 개최일이 지났거나 접수 마감일이 지났다. 할 일이 없다
       접수 중 초록 — 지금 예약을 받고 있다

     배지에 「접·종·휴」 글자를 넣어 봤지만, 칸이 좁아 회장명이 더 잘리고
     글자 셋을 읽는 것보다 색 하나를 보는 편이 빨랐다. 색만으로는 색각
     이상이 있는 사람이 못 가르므로, **배경색을 함께 바꿔** 신호를 둘로
     둔다 (`.day--st-*`). */
  function dayState(sc) {
    if (!sc) return 'none';
    if (sc.is_all_closed) return 'closed';
    if (sc.is_past || sc.is_booking_open === false) return 'over';
    return 'open';
  }

  /* 달력 칸에 적을 회장명. **괄호 별칭을 뗀다.**
     -------------------------------------------------------------------
     마스터의 회장명에는 같은 이름을 가나로 다시 적은 별칭이 붙어 있다.

       サンプル市民総合文化センター（サンプルホール）
       サンプル生涯学習センター（サンプルプラザ）

     괄호 안은 앞과 같은 곳을 가리키므로, 좁은 칸에서는 **앞쪽만 있으면
     회장이 특정된다.** 괄호까지 넣으면 이름이 두 배가 되어 어느 쪽도
     다 안 보인다. 전체 이름은 칸의 title 에 그대로 남는다. */
  function shortVenueName(name) {
    return String(name || '')
      .replace(/[（(][^）)]*[）)]/g, '')
      .trim();
  }

  /** 상태 점. 칸 안에서 회장명·숫자 앞에 붙는다. */
  function stateDot(state) {
    return el('span.day__dot.day__dot--' + state, { 'aria-hidden': 'true' });
  }

  /** `days[]` 에는 접수 마감 여부가 없다. 같은 회차를 `schedules[]` 에서 찾는다. */
  function scheduleOfDay(data, info) {
    if (!info) return null;
    var list = data.schedules || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === info.schedule_id) return list[i];
    }
    return info;
  }

  function dowClass(dow) {
    return dow === 0 ? '.day__num--sun' : (dow === 6 ? '.day__num--sat' : '');
  }

  function toggleMark(cell, iso, hospitalId, hospitalName) {
    var key = markKey(hospitalId, iso);
    if (marked[key]) {
      delete marked[key];
      cell.classList.remove('is-marked');
    } else {
      marked[key] = {
        date: iso, hospital_id: hospitalId, hospital_name: hospitalName || ''
      };
      cell.classList.add('is-marked');
    }
    updateBulkLabel();
  }

  var bulkLabelNode = null;

  // 일괄 조작 버튼들. 대상이 하나도 없으면 잠근다.
  var bulkButtons = [];

  // 지금 열어 둔 날짜. Ctrl+클릭을 하나도 안 했을 때 이 날이 대상이 된다.
  var openedDate = '';
  // 펴 놓은 날이 어느 회장의 날인지. 담은 것이 없을 때 그 회장에 건다.
  var openedHospitalId = null;
  var openedHospitalName = '';

  /** 일괄 조작이 걸릴 날짜들.
   *
   *  Ctrl+클릭으로 담은 날이 있으면 그것들, 없으면 **지금 열어 둔 날 하나**다.
   *
   *  체크를 해야만 버튼이 켜지던 것을 고친 것이다. 날짜를 눌러 시간표를
   *  펼쳐 놓고 「이 날 휴진」을 하려는 것이 자연스러운 흐름인데, 칸 귀퉁이의
   *  14px 짜리 ☐ 를 따로 눌러야만 버튼이 켜졌다. 그 표시를 못 찾으면
   *  휴진을 걸 방법 자체를 알 수 없다. */
  function bulkTargets() {
    var keys = Object.keys(marked);
    if (keys.length) {
      return keys.map(function (k) { return marked[k]; });
    }
    // 담은 것이 없으면 지금 펴 놓은 날 하나. 그 날은 지금 보는 회장의 것이다.
    return (openedDate && openedHospitalId)
      ? [{ date: openedDate, hospital_id: openedHospitalId,
           hospital_name: openedHospitalName }]
      : [];
  }

  /** 담은 것을 회장별로 묶는다. 휴진 요청은 회장마다 따로 나간다. */
  function targetsByHospital() {
    var groups = {};
    bulkTargets().forEach(function (t) {
      if (!groups[t.hospital_id]) {
        groups[t.hospital_id] = {
          hospital_id: t.hospital_id, hospital_name: t.hospital_name, dates: []
        };
      }
      groups[t.hospital_id].dates.push(t.date);
    });
    return Object.keys(groups).map(function (k) { return groups[k]; });
  }

  function updateBulkLabel() {
    if (!bulkLabelNode) return;

    var marks = Object.keys(marked).length;
    var targets = bulkTargets();

    /* 무엇에 걸리는지를 **눈에 띄게** 보여 준다.
       휴진 설정은 그 날 전 시간대를 한 번에 닫는 조작이라 되돌리기 번거롭다.
       「몇 일을 고쳤는지」가 작은 회색 글씨면 확인하지 않고 누르게 된다.

       담은 날과 열어 둔 날은 문구를 달리한다. 「1일 선택됨」이라고만 하면
       내가 고른 적이 없는데 왜 켜졌는지 알 수 없다. */
    /* 담은 날이 **지금 보고 있는 달 밖에** 있을 수 있다. 달을 넘겨도
       담은 날이 남기 때문이다. 화면에 안 보이는 날을 닫으려 하는 것이므로
       「3일 선택됨」만 적으면 무엇을 닫는지 모른 채 누르게 된다. */
    bulkLabelNode.textContent = marks
      ? marks + '日選択中' + monthBreakdown()
      : (openedDate ? A.fmt.date(openedDate) + ' に適用されます' : '選択中の日付なし');
    bulkLabelNode.className = 'bulk-count' + (targets.length ? ' is-on' : '');

    // 대상이 없으면 조작 버튼을 잠근다.
    // 눌러 보고 나서 「먼저 고르세요」를 듣는 것보다 눌리지 않는 편이 낫다.
    bulkButtons.forEach(function (b) { b.disabled = !targets.length; });
  }

  /** 담은 날짜를 달별로 센다. 한 달에 다 모여 있으면 붙이지 않는다. */
  function monthBreakdown() {
    var byMonth = {};
    Object.keys(marked).forEach(function (k) {
      var m = marked[k].date.slice(0, 7);
      byMonth[m] = (byMonth[m] || 0) + 1;
    });

    var months = Object.keys(byMonth).sort();
    if (months.length < 2) return '';

    return ' (' + months.map(function (m) {
      return Number(m.slice(5, 7)) + '月' + byMonth[m];
    }).join(' · ') + ')';
  }

  /* --- 날짜 일괄 조작 ------------------------------------------------------
     **휴진만 남는다.** 정원 증감(＋N명 / −N명)은 뺐다 — 같은 값을 정원
     일괄 관리 표에서도 고칠 수 있으므로 편집 창구가 둘이 되고, 두 곳의
     검증이 갈라진다.

     휴진은 다르다. 정원이 아니라 **상태**를 바꾸는 일이고, 「이 날과 이
     날을 닫는다」는 달력에서 날짜를 골라 하는 편이 표에서 열 열여섯 개를
     끄는 것보다 하려는 일에 가깝다. */

  function bulkActions(view, data) {
    bulkLabelNode = el('span.bulk-count');
    bulkButtons = [];

    function dates() {
      var groups = targetsByHospital();
      if (!groups.length) {
        A.toast('まずカレンダーで日付を選択してください。', 'warn');
        return null;
      }
      return groups;
    }

    /* 담은 날이 **여러 회장에 걸쳐** 있을 수 있다. 회장마다 API 가 따로이고,
       예약 영향도 회장별로 세야 한다. 그래서 묶어서 회장 수만큼 보낸다. */
    function holiday(closed) {
      var groups = dates();
      if (!groups) return;

      // 닫을 때만 먼저 세어 본다. 다시 여는 길에는 할 일이 남지 않는다.
      var ask = closed
        ? Promise.all(groups.map(function (g) {
            return askImpact(g.hospital_id, g.dates).then(function (im) {
              return { group: g, impact: im };
            });
          }))
        : Promise.resolve(null);

      ask.then(function (impacts) {
        var msg = holidayMessage(closed, groups);
        return A.confirm({
          title: msg.title,
          message: msg.message,
          detail: closed ? impactDetail(mergeImpacts(impacts)) : '',
          okLabel: closed ? '休診設定' : '休診解除',
          tone: closed ? 'danger' : 'primary',
          size: 'wide'
        }).then(function (ok) {
          if (!ok) return;

          return Promise.all(groups.map(function (g) {
            return A.api.post('/hospitals/' + g.hospital_id + '/holidays',
                              { dates: g.dates, closed: closed })
              .then(function (body) { return { group: g, body: body }; });
          })).then(function (results) {
            // 화면 갱신은 한 번만. 결과는 회장별로 합쳐 알린다.
            var last = results[results.length - 1];
            afterUpdate(view, data, last.body.data, closed ? '休診設定' : '休診解除');

            if (!closed) return;
            // 서버가 세어 준 값을 우선한다. 물어본 뒤에 예약이 들어왔을 수 있다.
            results.forEach(function (r) {
              contactNotice(r.group.hospital_id, r.group.dates, r.body.data.impact);
            });
          }).catch(function (error) { A.toast(error.message, 'danger'); });
        });
      });
    }

    /** 회장별 영향을 하나로 합친다. 하나라도 못 셌으면 못 센 것으로 본다. */
    function mergeImpacts(list) {
      if (!list || !list.length) return null;
      var total = 0, without = 0;
      for (var i = 0; i < list.length; i++) {
        if (!list[i].impact) return null;
        total += list[i].impact.total || 0;
        without += list[i].impact.without_email || 0;
      }
      return { total: total, without_email: without };
    }

    // 휴진은 되돌리기 번거로운 조작이다. 버튼이 작으면 그만큼 가볍게 눌린다.
    function act(cls, label, onClick) {
      var b = el('button.btn' + cls, {
        type: 'button', text: label, onClick: onClick,
        style: 'min-height:38px;padding:0 18px;font-size:14px;font-weight:500;'
      });
      bulkButtons.push(b);
      return b;
    }

    var node = el('div', {
      style: 'margin-top:14px;padding-top:14px;border-top:1px solid var(--a-line-2)'
    }, [
      el('div', { style: 'display:flex;align-items:center;gap:8px;flex-wrap:wrap' }, [
        el('strong', { text: '日付一括操作', style: 'font-size:var(--a-fs-md)' }),
        bulkLabelNode
      ]),
      el('div', { style: 'display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap' }, [
        act('.btn--danger', '休診日に設定', function () { holiday(true); }),
        act('', '休診解除', function () { holiday(false); }),
        el('span.pager__spacer'),
        el('button.btn.btn--ghost', {
          type: 'button', text: '選択解除',
          style: 'min-height:38px;padding:0 16px;font-size:14px;',
          onClick: function () {
            clearMarks();
            Array.prototype.forEach.call(
              view.querySelectorAll('.day.is-marked'),
              function (c) { c.classList.remove('is-marked'); }
            );
            updateBulkLabel();
          }
        })
      ])
    ]);

    updateBulkLabel();
    return node;
  }

  /* --- 하루 시간표 --------------------------------------------------------- */

  /* --- 그 날의 시간표 ------------------------------------------------------
     **읽기 전용이다.** 정원을 고치는 곳은 「정원 관리」 표 하나이며,
     여기서도 고칠 수 있게 두면 같은 값에 편집 창구가 둘이 된다.

     이 화면에 남는 것은 표에서 하기 어려운 일 — **날짜 단위 휴진**과,
     달력으로 「언제 여는가」를 보는 일이다. */

  function dayCard(view, data) {
    if (!data.selected_date) {
      return A.card('時間帯別定員', {
        body: el('p.field__hint', { text: 'カレンダーから日付を選択してください。' })
      });
    }

    /* **보기 전용 목록이다.** 예전에는 네 열짜리 표였다 —
       시간대 / 예약·정원 / 남은 좌석 / 접수.

       셋째 열은 둘째에서 뺄셈만 한 값이고, 넷째는 정원이 남았는지로
       정해지므로 둘째만 봐도 안다. 실질은 두 열이었다. 머리글 줄을 없애고
       한 줄에 담되, 「접수 중 / 마감」 **글자는 남긴다** — 점 색만으로는
       무엇이 닫힌 것인지 확신이 서지 않는다. */
    var body = el('div.slot-list');

    var sumRes = 0;
    var sumCap = 0;
    var allClosed = data.slots.length > 0;

    /* 회차 자체가 끝났으면 **시간대도 「접수 중」일 수 없다.**
       -------------------------------------------------------------------
       예전에는 달력 칸이 회색(접수 마감일이 지남)인데 오른쪽 시간표는
       「접수 중」이라고 적었다. 판정 기준이 서로 달랐기 때문이다 —
       칸은 `is_booking_open`(회차의 접수 마감일), 줄은 `slot.is_closed`
       (그 칸을 손으로 닫았는지)를 보았다. 둘 다 「지금 예약을 받는가」를
       말하므로 회차 쪽이 닫혀 있으면 줄도 닫힌 것으로 덮는다. */
    var schedOver = dayState(scheduleOfDay(data, {
      schedule_id: data.selected_schedule_id
    })) === 'over';

    data.slots.forEach(function (slot) {
      sumRes += slot.reserved;
      sumCap += slot.capacity;
      if (!slot.is_closed) allClosed = false;

      var off = slot.is_closed || schedOver;
      var label = slot.is_closed ? '締切' : (schedOver ? '受付終了' : '受付中');

      body.appendChild(el('div.slot-line' + (off ? '.is-closed' : ''), {}, [
        /* 시간대 마감은 **회색**이다. 달력의 빨강은 「그 날 전체가 닫힘」을
           뜻하므로, 시간대 몇 개가 닫힌 것과 색을 나누어야 한다. */
        stateDot(off ? 'over' : 'open'),
        el('span.slot-line__time', { text: slot.time_label }),
        el('span.slot-line__num', {
          text: slot.reserved + ' / ' + slot.capacity
        }),
        el('span.slot-line__state', { text: label })
      ]));
    });

    body.appendChild(el('div.slot-total', {
      style: 'margin-top:12px;padding-top:10px;display:flex;align-items:center;'
           + 'justify-content:space-between;border-top:1px solid var(--a-line);'
    }, [
      el('span', {
        style: 'color:var(--a-ink-sub);font-size:var(--a-fs-sm);',
        text: 'この日の合計'
      }),
      el('strong', {
        style: 'color:var(--a-ink);font-size:var(--a-fs-sm);font-weight:700;',
        text: '予約 ' + sumRes + ' / 定員 ' + sumCap
      })
    ]));

    /* 예전에는 여기에 초록 안내 박스(「이 회장의 정원 표 열기」)가 있었다.
       머리에 「정원 관리」 버튼을 두면서 **같은 곳으로 가는 길이 둘**이
       되었으므로 뺐다. 안내 한 줄은 목록 아래에 남는다. */

    // 날짜 단위 휴진은 여기 남는다. 표에서 열 열여섯 개를 한꺼번에 끄는
    // 것보다, 달력에서 그 날을 눌러 닫는 편이 하려는 일에 가깝다.
    var holidayBtn = el('button.btn.btn--sm', {
      type: 'button',
      text: allClosed ? 'この日の受付再開' : 'この日の終日休診',
      title: allClosed
        ? 'この日のすべての時間帯の受付を再開します。'
        : 'この日のすべての時間帯を締め切ります。定員はそのまま残ります。',
      onClick: function () {
        var closing = !allClosed;
        var list = [data.selected_date];

        // 달력의 [휴진일로 설정] 과 결과가 같다. 경고도 같아야 한다.
        var ask = closing ? askImpact(data.hospital_id, list)
                          : Promise.resolve(null);

        ask.then(function (impact) {
          return A.confirm({
            title: closing ? 'この日を休診にしますか？' : 'この日の受付を再開しますか？',
            message: A.fmt.date(data.selected_date) + ' の時間帯 '
                   + data.slots.length + '枠を '
                   + (closing ? 'すべて締め切ります。' : 'すべて再開します。'),
            detail: closing
              ? impactDetail(impact) + ' 定員はそのまま残ります。'
              : '定員はそのまま残ります。締切は定員とは別のステータスであるため、'
                + '解除すると元の定員に戻ります。',
            okLabel: closing ? '休診にする' : '受付再開',
            tone: closing ? 'danger' : 'primary'
          }).then(function (yes) {
            if (!yes) return;
            holidayBtn.disabled = true;
            return A.api.post('/hospitals/' + data.hospital_id + '/holidays', {
              dates: list,
              closed: closing
            })
              .then(function (res) {
                afterUpdate(view, data, res.data, closing ? '休診設定' : '受付再開');
                if (closing) contactNotice(data.hospital_id, list, res.data.impact || impact);
              })
              .catch(function (error) { A.toast(error.message, 'danger'); })
              .then(function () { holidayBtn.disabled = false; });
          });
        });
      }
    });

    /* 회장명을 여기에도 적는다.
       담당자가 숫자를 읽는 자리는 이 패널인데, 회장명은 화면 **왼쪽 위 끝**
       초록 칩에만 있었다. 시선이 오른쪽 아래에 있는 동안 「이게 어느 회장
       시간표더라」가 확인되지 않는다. */
    var panelHosp = (hospitals || []).filter(function (h) {
      return h.id === data.hospital_id;
    })[0];

    /* 머리는 「언제 · 어디」 두 줄이다. 카드 제목 자리에 날짜를 크게 두고
       그 아래 회장명을 초록으로 적는다 — 왼쪽 달력 제목과 같은 색이라
       두 화면이 같은 회장을 보고 있다는 것이 이어진다. */
    var d = new Date(data.selected_date + 'T00:00:00');
    var headNode = el('div', {}, [
      el('div', { style: 'display:flex;align-items:baseline;gap:8px;' }, [
        el('strong', {
          style: 'font-size:var(--a-fs-xl);font-weight:700;color:var(--a-ink);',
          text: (d.getMonth() + 1) + '月' + d.getDate() + '日'
        }),
        el('span', {
          style: 'font-size:var(--a-fs-sm);color:var(--a-ink-sub);',
          text: ['日', '月', '火', '水', '木', '金', '土'][d.getDay()]
        })
      ]),
      panelHosp ? el('div', {
        style: 'font-size:var(--a-fs-sm);font-weight:700;'
             + 'color:var(--c-primary, #0B6E5B);margin-top:2px;',
        text: shortVenueName(panelHosp.name),
        title: panelHosp.name
      }) : null
    ].filter(Boolean));

    /* 정원은 여기서 못 고친다. 고치러 갈 길만 둔다 — 「정원 관리」 표가
       유일한 편집 창구다. 휴진은 이 화면에 남는 단 하나의 조작이다. */
    var toTableBtn = el('button.btn.btn--primary', {
      type: 'button',
      text: '定員管理',
      title: 'この会場の定員表を開きます。',
      style: 'flex:1;min-height:34px;',
      onClick: function () {
        A.go('bulk-capacity', { hospital_id: data.hospital_id });
      }
    });
    holidayBtn.style.flex = '1';
    holidayBtn.style.minHeight = '34px';

    var actions = el('div', {
      style: 'display:flex;gap:6px;margin-bottom:11px;'
    }, [toTableBtn, holidayBtn]);

    return A.card(headNode, {
      body: [actions, body, el('p.field__hint', {
        style: 'margin:9px 0 0;',
        text: '閲覧専用です。定員は「定員管理」表で変更してください。'
      })]
    });
  }

  /* --- 조작 결과 ----------------------------------------------------------- */


  /* ------------------------------------------------------------------
     휴진 경고
     ------------------------------------------------------------------
     슬롯을 닫아도 예약은 지워지지 않는다. 아무 말도 하지 않으면 그 사람들은
     그 날 그대로 회장에 온다. 닫기 **전에** 규모를 알려, 담당자가 「몇 명에게
     연락해야 하는 일인가」를 알고 누르게 한다.

     이메일이 빈 사람은 전화 말고 닿을 길이 없어 따로 센다.
     ------------------------------------------------------------------ */

  /** 그 날짜들의 예약 건수를 물어본다. 실패해도 조작은 막지 않는다. */
  function askImpact(hospitalId, list) {
    // A.query() 는 배열을 쉼표로 이어 붙여 `dates=a%2Cb` 를 만든다.
    // FastAPI 의 list[date] 는 같은 이름을 반복해 넘겨야 받는다.
    var qs = list.map(function (d) {
      return 'dates=' + encodeURIComponent(d);
    }).join('&');

    return A.api.get('/hospitals/' + hospitalId + '/reservation-impact?' + qs)
      .then(function (body) { return body.data; })
      .catch(function () { return null; });   // null = 「세지 못했다」
  }

  /** 확인 대화상자에 덧붙일 줄. 못 셌으면 그렇다고 적는다. */
  function impactDetail(impact) {
    if (!impact) {
      // 0 건과 「확인하지 못했다」를 같은 문장으로 적으면, 128명이 걸린 날을
      // 비었다고 믿고 닫는다.
      return 'この日の予約件数を確認できませんでした。'
           + '締め切る前に予約一覧で直接ご確認ください。';
    }
    if (!impact.total) {
      return 'この日付に受付済みの予約はありません。';
    }
    var line = 'すでに受け付けた予約 ' + impact.total + '件はキャンセルされません。'
             + '連絡しないと、当日会場に来場されます。';
    if (impact.without_email) {
      line += ' そのうち ' + impact.without_email
            + '件はメールアドレスがないため、電話でのみ連絡可能です。';
    }
    return line;
  }

  /** 닫은 뒤, 할 일이 남았음을 화면에 남긴다. */
  function contactNotice(hospitalId, list, impact) {
    if (!impact || !impact.total) return;

    // 토스트 한 줄은 몇 초 뒤 사라져, 할 일이 남았다는 사실 자체가 남지 않는다.
    A.modal({
      title: '連絡が必要です',
      body: [
        A.notice('warn',
          '休診で締め切りましたが、予約 ' + impact.total + '件はそのまま残っています。'
          + (impact.without_email
              ? 'メールアドレスがない ' + impact.without_email + '件はまずお電話をおかけください。'
              : '')),
        el('p', {
          style: 'margin:12px 0 0;line-height:1.8;color:var(--a-ink-sub)',
          text: '対象日 — ' + list.join(', ')
        })
      ],
      actions: [
        {
          label: '予約一覧で確認',
          tone: 'primary',
          onClick: function () {
            // status 를 걸지 않는다. 불비(PENDING) 예약자도 본인은
            // 예약했다고 생각하고 그 날 온다.
            A.go('reservations', {
              hospital_id: hospitalId,
              date_from: list[0],
              date_to: list[list.length - 1]
            });
          }
        },
        { label: '後で' }
      ]
    });
  }

  /** 달력 쪽 휴진 대화상자의 제목·본문.
   *
   *  시간표 쪽은 자기 문장을 따로 쓴다 — 거기서는 날짜가 하나로 정해져
   *  있어 「2026-10-13 의 시간대 8칸」처럼 그 날을 이름으로 부를 수 있다.
   *  달력은 여러 날이 담길 수 있어 「선택한 N일」로만 말할 수 있다.
   *  경고(예약 건수)는 두 길이 같은 것을 쓴다 — impactDetail(). */
  /* 담은 날이 여러 회장에 걸치면 **회장마다 몇 일인지** 적는다.
     「3일」만 적으면 어느 회장 것이 섞였는지 모른 채 누르게 된다. */
  /* 닫는 날을 **날짜로** 적는다.
     -------------------------------------------------------------------
     예전에는 「선택한 1일의 모든 시간대를 마감합니다」였다. 되돌리기
     번거로운 조작인데 정작 **어느 날인지가 없다.** 담은 날이 화면 밖에
     있을 수도 있어(달을 넘겨도 담은 것이 남는다) 세어 준 숫자만으로는
     맞는지 확인할 길이 없었다.

     세 날까지는 그대로 늘어놓고, 그보다 많으면 회장별로 앞 둘만 적고
     나머지는 수로 줄인다. */
  function holidayMessage(closed, groups) {
    var all = [];
    groups.forEach(function (g) {
      g.dates.forEach(function (d) { all.push(d); });
    });
    all.sort();

    var verb = closed ? '締め切ります。' : '受付を再開します。';
    var head;

    if (groups.length === 1 && all.length <= 3) {
      head = all.map(dateWithWeekday).join(', ') + ' のすべての時間帯を ' + verb;
    } else {
      head = '以下の ' + all.length + '日のすべての時間帯を ' + verb;
      head += '\n\n' + groups.map(function (g) {
        var ds = g.dates.slice().sort();
        var shown = ds.slice(0, 2).map(dateWithWeekday).join(', ');
        if (ds.length > 2) shown += ' ほか ' + (ds.length - 2) + '日';
        return (groups.length > 1
                 ? '· ' + (g.hospital_name || '会場 ' + g.hospital_id) + ' — '
                 : '· ') + shown;
      }).join('\n');
    }

    return {
      title: closed ? '休診日に設定しますか？' : '休診日を解除しますか？',
      message: head
    };
  }

  /** `2026-10-13` → `2026-10-13 (화)`. 요일이 있어야 「그 날이 맞나」가 선다. */
  function dateWithWeekday(iso) {
    var d = new Date(iso + 'T00:00:00');
    if (isNaN(d.getTime())) return iso;
    return iso + ' (' + ['日', '月', '火', '水', '木', '金', '土'][d.getDay()] + ')';
  }

  function afterUpdate(view, data, result, label) {
    A.toast(result.message, result.blocked.length ? 'warn' : 'ok');

    if (result.blocked.length) {
      // 거부된 항목은 조용히 넘기지 않는다. 바뀐 줄 알고 넘어가면
      // 다음에 「왜 정원이 그대로냐」는 문의가 된다.
      A.modal({
        title: label + ' — 変更できなかった項目',
        body: [
          A.notice('warn',
            'すでに予約されている人数を下回る定員には変更できません。' +
            '先に予約をキャンセルするか、定員をそれ以上に設定してください。'),
          el('ul', { style: 'margin:0;padding-left:18px;line-height:1.9' },
            result.blocked.map(function (line) {
              return el('li', { text: line });
            }))
        ],
        actions: [{ label: '確認', tone: 'primary' }]
      });
    }

    reload(view, data);
    if (A.refreshAttentionBadge) A.refreshAttentionBadge();
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

})();
