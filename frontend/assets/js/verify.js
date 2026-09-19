/* ==========================================================================
   verify.js — 예약 1단계 : 본인 확인 (U-11)
   --------------------------------------------------------------------------
   POST /api/v1/reservations/verify 로 검진 대상자 여부를 판별하고
   세 가지 결과 화면 중 하나를 표시한다.

     ELIGIBLE         → 예약 진행 가능
     ALREADY_RESERVED → 이미 예약 내용이 있음
     NOT_ELIGIBLE     → 검진 대상자가 아님 (문의처 안내)

   성명은 성（姓）·이름（名）을 분리해 받고, 후리가나도 각각 전각 가타카나로 받는다.

   plan.md BR-01 / BR-02 / 자체 피드백 P-7 (오류는 해결 방법을 안내한다)
   ========================================================================== */

(function () {
  'use strict';

  var API_VERIFY = '/api/v1/reservations/verify';
  var STORAGE_KEY = 'kenshin.verifiedPerson';

  // --- DOM ---------------------------------------------------------------
  var form        = document.getElementById('verify-form');
  var submitBtn   = document.getElementById('submit-btn');
  var sectionForm = document.getElementById('step-form');
  var progress    = document.getElementById('progress');

  var panels = {
    ELIGIBLE:         document.getElementById('result-eligible'),
    ALREADY_RESERVED: document.getElementById('result-already'),
    NOT_ELIGIBLE:     document.getElementById('result-not-eligible')
  };

  var globalAlert     = document.getElementById('global-alert');
  var globalAlertText = document.getElementById('global-alert-text');
  var kanaConverted   = document.getElementById('kana-converted');

  // 마지막 판정 결과. 「다시 입력하기」 시 어디로 포커스를 보낼지 정한다.
  var lastStatus = null;

  var el = {
    lastName:       document.getElementById('last-name'),
    firstName:      document.getElementById('first-name'),
    lastNameKana:   document.getElementById('last-name-kana'),
    firstNameKana:  document.getElementById('first-name-kana'),
    middleName:     document.getElementById('middle-name'),
    middleNameKana: document.getElementById('middle-name-kana'),
    genderM:        document.getElementById('gender-m'),
    genderF:        document.getElementById('gender-f'),
    year:           document.getElementById('birth-year'),
    month:          document.getElementById('birth-month'),
    day:            document.getElementById('birth-day'),
    insurerNo:      document.getElementById('insurer-no'),
    symbol:         document.getElementById('insurance-symbol'),
    cardNo:         document.getElementById('insurance-no')
  };

  // 필드 묶음 — 오류 표시 대상 매핑에 사용
  var GROUPS = {
    name:   [el.lastName, el.firstName],
    kana:   [el.lastNameKana, el.firstNameKana],
    middle: [el.middleName, el.middleNameKana],
    gender: [el.genderM, el.genderF],
    birth:  [el.year, el.month, el.day],
    card:   [el.insurerNo, el.symbol, el.cardNo]
  };

  /* ======================================================================
     후리가나 정규화 — 전각 가타카나로 통일
     ----------------------------------------------------------------------
     고령 이용자에게 「전각 가타카나로 다시 입력하세요」라고 되돌려 보내는 대신
     시스템이 알아서 맞춰 준다. (서버에서도 동일하게 처리한다)

       ﾀﾅｶ (반각 가타카나) → タナカ
       たなか (히라가나)    → タナカ
     ====================================================================== */

  // 전각 가타카나 + ー(장음) + ・(중점) + ヽヾ(반복 기호)
  var KATAKANA_ONLY = /^[ァ-ヺ・-ヾ]+$/;

  function normalizeKana(value) {
    if (!value) return '';

    // NFKC : 반각 가타카나 → 전각 (탁점 결합 포함)
    var s = value.normalize('NFKC').replace(/\s+/g, '');

    // 히라가나 → 가타카나 (ぁ U+3041 ~ ゖ U+3096 은 +0x60)
    return s.replace(/[ぁ-ゖ]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) + 0x60);
    });
  }

  function isKatakana(value) {
    return !!value && KATAKANA_ONLY.test(value);
  }

  /**
   * 후리가나 입력란을 전각 가타카나로 변환한다.
   * 입력 도중(IME 조합 중)이 아니라 입력을 마쳤을 때만 실행한다.
   */
  function applyKanaConversion(input) {
    var before = input.value;
    if (!before) return;

    var after = normalizeKana(before);
    if (after === before) return;

    input.value = after;

    // 무엇이 바뀌었는지 알려 준다. 말없이 값이 바뀌면 불안해진다.
    if (kanaConverted) {
      kanaConverted.textContent =
        'ご入力の「' + before + '」を全角カタカナの「' + after + '」に変換しました。';
      kanaConverted.classList.add('is-visible');
    }
  }

  function clearKanaNotice() {
    if (kanaConverted) {
      kanaConverted.textContent = '';
      kanaConverted.classList.remove('is-visible');
    }
  }

  [el.lastNameKana, el.firstNameKana, el.middleNameKana].forEach(function (input) {
    // IME 조합이 끝난 뒤에 변환한다. 조합 중에 건드리면 입력이 깨진다.
    input.addEventListener('blur', function () { applyKanaConversion(this); });
    input.addEventListener('compositionend', function () { applyKanaConversion(this); });
  });

  /* ======================================================================
     생년월일 선택지 생성
     ====================================================================== */

  function fillSelect(select, from, to) {
    var frag = document.createDocumentFragment();
    for (var i = from; i <= to; i++) {
      var opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = String(i);
      frag.appendChild(opt);
    }
    select.appendChild(frag);
  }

  fillSelect(el.month, 1, 12);
  fillSelect(el.day, 1, 31);

  /* 「日」の選択肢を、選んだ年・月に合わせて出し直す。

     31日まで並べたままだと、2月を選んでも30日・31日が選べてしまう。
     選んでから「2月は28日までです」と言われるより、はじめから出さない方が早い。
     年が空のときは、うるう年が決まらないので29日まで出しておく。 */
  /* 생년은 **반각 숫자로 읽는다.** 일본어 IME 가 켜진 채로 치면 「１９７０」이
     들어오는데, 그대로 두면 「西暦4桁で」 오류가 떠서 이용자는 무엇이 틀렸는지
     알 수 없다. 입력 칸의 글자도 IME 입력이 끝난 뒤(blur)에 반각으로 바꿔 둔다. */
  function yearValue() {
    return (el.year.value || '').normalize('NFKC').replace(/\s+/g, '');
  }

  el.year.addEventListener('blur', function () {
    var normalized = yearValue();
    if (normalized !== el.year.value) el.year.value = normalized;
  });

  function refreshDayOptions() {
    var year = yearValue();
    var month = parseInt(el.month.value, 10);
    if (!month) return;

    var last = /^\d{4}$/.test(year)
      ? daysInMonth(parseInt(year, 10), month)
      : (month === 2 ? 29 : daysInMonth(2024, month));

    var kept = el.day.value;
    while (el.day.options.length > 1) el.day.remove(1);
    fillSelect(el.day, 1, last);

    // すでに選んでいた日が月の外に出た場合（3月31日 → 2月）は、その月の末日に寄せる。
    if (kept) el.day.value = parseInt(kept, 10) > last ? String(last) : kept;
  }

  el.year.addEventListener('input', refreshDayOptions);
  el.month.addEventListener('change', refreshDayOptions);

  /* ======================================================================
     오류 표시 유틸
     ====================================================================== */

  /**
   * 필드 오류를 표시한다.
   * @param {string} key      'name' | 'kana' | 'birth' | 'card'
   * @param {string} message  해결 방법을 담은 문장 (빈 문자열이면 오류 해제)
   */
  function setFieldError(key, message) {
    var box = document.getElementById(key + '-error');
    if (!box) return;

    var inputs = GROUPS[key] || [];

    if (message) {
      box.querySelector('span').textContent = message;
      box.classList.add('is-visible');
      inputs.forEach(function (i) { i.setAttribute('aria-invalid', 'true'); });
    } else {
      box.classList.remove('is-visible');
      inputs.forEach(function (i) { i.setAttribute('aria-invalid', 'false'); });
    }
  }

  function clearAllErrors() {
    Object.keys(GROUPS).forEach(function (k) { setFieldError(k, ''); });
    globalAlert.classList.remove('is-visible');
  }

  function showGlobalAlert(message) {
    globalAlertText.textContent = message;
    globalAlert.classList.add('is-visible');
  }

  /* ======================================================================
     입력 검증 (클라이언트)
     서버에서도 동일하게 검증하지만, 왕복 없이 즉시 알려주는 편이 친절하다.
     ====================================================================== */

  function daysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
  }

  function pad2(v) {
    return String(v).length < 2 ? '0' + v : String(v);
  }

  function collectAndValidate() {
    clearAllErrors();

    var ok = true;
    var firstInvalid = null;

    function fail(key, message, input) {
      setFieldError(key, message);
      firstInvalid = firstInvalid || input;
      ok = false;
    }

    // --- 성함 (한자) ---
    var lastName  = el.lastName.value.trim();
    var firstName = el.firstName.value.trim();

    if (!lastName && !firstName) {
      fail('name', 'お名前を姓と名に分けてご入力ください。', el.lastName);
    } else if (!lastName) {
      fail('name', '姓をご入力ください。（例：田中）', el.lastName);
    } else if (!firstName) {
      fail('name', '名をご入力ください。（例：太郎）', el.firstName);
    }

    // --- 후리가나 ---
    // 검증 직전에 한 번 더 변환한다. blur 없이 바로 제출하는 경우가 있다.
    applyKanaConversion(el.lastNameKana);
    applyKanaConversion(el.firstNameKana);

    var lastKana  = normalizeKana(el.lastNameKana.value);
    var firstKana = normalizeKana(el.firstNameKana.value);

    if (!lastKana && !firstKana) {
      fail('kana', 'フリガナは全角カタカナでご入力ください。(例：タナカ / タロウ)',
           el.lastNameKana);
    } else if (!lastKana) {
      fail('kana', '姓のフリガナをご入力ください。（例：タナカ）', el.lastNameKana);
    } else if (!firstKana) {
      fail('kana', '名のフリガナをご入力ください。（例：タロウ）', el.firstNameKana);
    } else if (!isKatakana(lastKana)) {
      fail('kana', '姓のフリガナは全角カタカナのみでご入力ください。漢字や英字は使えません。（例：タナカ）',
           el.lastNameKana);
    } else if (!isKatakana(firstKana)) {
      fail('kana', '名のフリガナは全角カタカナのみでご入力ください。漢字や英字は使えません。（例：タロウ）',
           el.firstNameKana);
    }

    // --- 미들네임 (임의) ---
    // 해당자만 입력하므로 비어 있으면 통과. 입력했다면 후리가나 형식만 검사한다.
    applyKanaConversion(el.middleNameKana);

    var middleName = el.middleName.value.trim();
    var middleKana = normalizeKana(el.middleNameKana.value);

    if (middleKana && !isKatakana(middleKana)) {
      fail('middle',
           'ミドルネームのフリガナは全角カタカナのみでご入力ください。（例：ウィリアム）',
           el.middleNameKana);
    }

    // --- 성별 ---
    var genderInput = document.querySelector('input[name="gender"]:checked');
    if (!genderInput) {
      fail('gender', '性別をお選びください。', el.genderM);
    }

    // --- 생년월일 ---
    var year  = yearValue();
    var month = el.month.value;
    var day   = el.day.value;

    if (!year || !month || !day) {
      fail('birth', '生年月日は年・月・日をすべてお選びください。',
           !year ? el.year : (!month ? el.month : el.day));
    } else if (!/^\d{4}$/.test(year)) {
      fail('birth', '生まれた年を西暦4桁でご入力ください。（例：1970）', el.year);
    } else {
      var y = parseInt(year, 10);
      var m = parseInt(month, 10);
      var d = parseInt(day, 10);
      var thisYear = new Date().getFullYear();

      if (y < 1900 || y > thisYear) {
        fail('birth', '生まれた年をもう一度ご確認ください。', el.year);
      } else if (d > daysInMonth(y, m)) {
        fail('birth', y + '年' + m + '月は' + daysInMonth(y, m) +
                      '日までです。日付をもう一度お選びください。', el.day);
      }
    }

    // --- 건강보험증 ---
    var insurerNo = el.insurerNo.value.trim();
    var symbol    = el.symbol.value.trim();
    var cardNo    = el.cardNo.value.trim();

    if (!insurerNo || !symbol || !cardNo) {
      fail('card', '健康保険証の保険者番号・記号・番号をすべてご入力ください。',
           !insurerNo ? el.insurerNo : (!symbol ? el.symbol : el.cardNo));
    }

    if (!ok) {
      if (firstInvalid) firstInvalid.focus();
      return null;
    }

    return {
      last_name: lastName,
      first_name: firstName,
      last_name_kana: lastKana,
      first_name_kana: firstKana,
      middle_name: middleName,
      middle_name_kana: middleKana,
      gender: genderInput.value,
      birth_date: year + '-' + pad2(month) + '-' + pad2(day),
      insurer_no: insurerNo,
      insurance_symbol: symbol,
      insurance_no: cardNo
    };
  }

  /* ======================================================================
     표시 유틸
     ====================================================================== */

  function formatBirth(iso) {
    var p = String(iso).split('-');
    if (p.length !== 3) return iso;
    return parseInt(p[0], 10) + '年' +
           parseInt(p[1], 10) + '月' +
           parseInt(p[2], 10) + '日';
  }

  function formatGender(code) {
    if (code === 'M') return '男性';
    if (code === 'F') return '女性';
    return '-';
  }

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value || '-';
  }

  /* ======================================================================
     결과 화면 전환
     ====================================================================== */

  function showPanel(status) {
    sectionForm.classList.add('is-hidden');
    if (progress) progress.classList.add('is-hidden');

    Object.keys(panels).forEach(function (key) {
      panels[key].classList.toggle('is-hidden', key !== status);
    });

    window.scrollTo({ top: 0, behavior: 'auto' });

    // 스크린 리더 이용자를 위해 결과 영역으로 포커스를 옮긴다
    var active = panels[status];
    if (active) active.focus();
  }

  function backToForm() {
    Object.keys(panels).forEach(function (key) {
      panels[key].classList.add('is-hidden');
    });
    sectionForm.classList.remove('is-hidden');
    if (progress) progress.classList.remove('is-hidden');

    window.scrollTo({ top: 0, behavior: 'auto' });

    if (lastStatus === 'KANA_MISMATCH') {
      // 고칠 곳이 후리가나임을 이미 알고 있다. 거기로 바로 보낸다.
      setFieldError('kana', '健康保険証に記載の読み方のとおり、もう一度ご入力ください。');
      el.lastNameKana.focus();
      el.lastNameKana.select();
    } else {
      el.lastName.focus();
    }
  }

  /* ======================================================================
     결과 렌더링
     ====================================================================== */

  /**
   * 안내 목록을 그린다. 서버가 결과 종류에 맞는 문구를 내려 준다.
   */
  function renderHints(id, hints) {
    var list = document.getElementById(id);
    if (!list) return;

    list.textContent = '';
    (hints || []).forEach(function (text) {
      var li = document.createElement('li');
      li.textContent = text;
      list.appendChild(li);
    });
  }

  /**
   * 「진행할 수 없음」 계열 결과를 그린다.
   *   NOT_ELIGIBLE  : 명부에 없음
   *   KANA_MISMATCH : 한자는 맞으나 후리가나가 다름
   *   AMBIGUOUS     : 완전 일치가 2명 이상 → 담당자 확인
   *
   * 제목·본문·원인 안내는 모두 서버가 내려 준 값을 쓴다.
   * 결과 종류가 늘어나도 이 함수를 고치지 않아도 된다.
   */
  function renderBlocked(data) {
    setText('ne-title', data.title);
    setText('ne-message', data.message);
    renderHints('ne-hints', data.hints);

    if (data.contact) {
      setText('ne-tel', data.contact.tel);
      setText('ne-email', data.contact.email);
      setText('ne-hours', data.contact.hours);
    }
    showPanel('NOT_ELIGIBLE');
  }

  /* 이미 예약이 있는 경우.

     **예약번호도 예약 내용도 그리지 않는다.** 서버가 애초에 내려 주지 않는다.
     이 화면에 넣는 값(성명·생년월일·보험증)은 가족이나 동거인이라면 알 수 있는
     정보다. 그것만으로 예약번호가 나오면 예약 조회(U-20)가 통째로 열린다.

     그래서 여기서 할 일은 「이제 무엇을 하면 되는지」를 자세히 알리는 것이다.
     화면에서 더 할 수 있는 일이 없는 사람에게 안내가 부족하면 그대로 전화가 된다. */
  function renderAlreadyReserved(data) {
    setText('ar-title', data.title);
    setText('ar-message', data.message);

    var hints = document.getElementById('ar-hints');
    hints.textContent = '';
    (data.hints || []).forEach(function (text) {
      var li = document.createElement('li');
      li.className = 'guide-list__item';
      li.textContent = text;
      hints.appendChild(li);
    });

    if (data.contact) {
      setText('ar-tel', data.contact.tel);
      setText('ar-hours', data.contact.hours);
      setText('ar-email', data.contact.email);
    }

    showPanel('ALREADY_RESERVED');
  }

  function renderEligible(data) {
    setText('ok-title', data.title);
    setText('ok-message', data.message);

    if (data.person) {
      setText('ok-name', data.person.full_name);
      setText('ok-kana', data.person.full_name_kana);
      setText('ok-gender', data.person.gender_label || formatGender(data.person.gender));
      setText('ok-birth', formatBirth(data.person.birth_date));
      setText('ok-card', data.person.insurance_card_no);
    }

    // 다음 단계에서 사용할 본인 확인 결과를 보관한다.
    // (뒤로가기로 돌아와도 다시 입력하지 않도록 — 자체 피드백 P-1)
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        token: data.verify_token,
        person: data.person
      }));
    } catch (e) { /* 저장 실패해도 현재 흐름은 계속된다 */ }

    showPanel('ELIGIBLE');
  }

  /* ======================================================================
     전송
     ====================================================================== */

  function setLoading(isLoading) {
    if (isLoading) {
      submitBtn.classList.add('is-loading');
      submitBtn.setAttribute('aria-busy', 'true');
      submitBtn.querySelector('.btn__label').textContent = '確認しています…';
    } else {
      submitBtn.classList.remove('is-loading');
      submitBtn.removeAttribute('aria-busy');
      submitBtn.querySelector('.btn__label').textContent = '次へ進む';
    }
  }

  /** 서버가 돌려준 필드 오류를 화면의 필드 묶음에 매핑한다. */
  function applyServerFieldErrors(fields) {
    var map = {
      last_name: 'name',
      first_name: 'name',
      last_name_kana: 'kana',
      first_name_kana: 'kana',
      middle_name: 'middle',
      middle_name_kana: 'middle',
      gender: 'gender',
      birth_date: 'birth',
      insurer_no: 'card',
      insurance_symbol: 'card',
      insurance_no: 'card'
    };

    var handled = false;
    (fields || []).forEach(function (f) {
      var key = map[f.name];
      if (key) {
        setFieldError(key, f.message);
        handled = true;
      }
    });
    return handled;
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var payload = collectAndValidate();
    if (!payload) return;

    setLoading(true);

    fetch(API_VERIFY, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.body.success) {
          var body = result.body || {};
          if (!applyServerFieldErrors(body.fields)) {
            showGlobalAlert(
              (body.error && body.error.message) ||
              '処理中に問題が発生しました。しばらくしてからもう一度お試しください。'
            );
          }
          return;
        }

        var data = result.body.data;
        lastStatus = data.status;

        if (data.status === 'ELIGIBLE') {
          renderEligible(data);
        } else if (data.status === 'ALREADY_RESERVED') {
          renderAlreadyReserved(data);
        } else {
          // NOT_ELIGIBLE / KANA_MISMATCH / AMBIGUOUS
          renderBlocked(data);
        }
      })
      .catch(function () {
        showGlobalAlert(
          'インターネットの接続をご確認ください。問題が続く場合はお電話でお問い合わせください。'
        );
      })
      .then(function () {
        setLoading(false);
      });
  });

  /* ======================================================================
     「다시 입력하기」
     ====================================================================== */

  document.querySelectorAll('[data-action="retry"]').forEach(function (btn) {
    btn.addEventListener('click', backToForm);
  });

  /* ======================================================================
     다음 단계
     --------------------------------------------------------------------
     예약은 회장·일시 선택에서 시작하므로, 여기 도달한 사람은 이미 일시를
     고른 상태다. 고른 것을 다시 고르게 하면 자리를 뺏은 것처럼 보이므로
     그 단계를 건너뛰고 정보 입력으로 보낸다.

     고른 일시가 없는 채로 이 화면에 곧장 들어온 경우(주소를 직접 친 경우
     등)만 회장·일시 선택으로 되돌린다.
     ====================================================================== */

  var PICK_KEY = 'kenshin.selectedSlot';

  function readPick() {
    try {
      var raw = sessionStorage.getItem(PICK_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  var picked = readPick();

  /** 'YYYY-MM-DD' → '2026年8月10日(月)' */
  function formatPickedDate(iso) {
    var parts = String(iso || '').split('-');
    if (parts.length !== 3) return iso || '';

    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    var weekday = ['日', '月', '火', '水', '木', '金', '土'][d.getDay()];

    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' +
           d.getDate() + '日(' + weekday + ')';
  }

  var hasPick = !!(picked && picked.hospital && picked.slot);

  // 고른 일시를 입력 화면 위에 띄워 둔다.
  if (hasPick) {
    var heldBox = document.getElementById('held-slot');
    if (heldBox) {
      document.getElementById('held-hospital').textContent = picked.hospital.name || '';
      document.getElementById('held-when').textContent =
        formatPickedDate(picked.date) + '  ' + (picked.slot.time_label || '');
      heldBox.classList.remove('is-hidden');
    }

    var nextLabel = document.getElementById('next-step-label');
    if (nextLabel) nextLabel.textContent = '情報の入力へ進む';
  }

  var nextBtn = document.getElementById('next-step-btn');
  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      // 고른 일시가 있으면 회장·일시 선택을 건너뛴다.
      window.location.href = hasPick ? 'form.html' : 'schedule.html';
    });
  }

  /* ======================================================================
     입력 중에는 해당 필드의 오류를 해제한다 (P-7)
     ====================================================================== */

  Object.keys(GROUPS).forEach(function (key) {
    GROUPS[key].forEach(function (input) {
      input.addEventListener('input', function () {
        setFieldError(key, '');
        if (key === 'kana') clearKanaNotice();
      });
      input.addEventListener('change', function () { setFieldError(key, ''); });
    });
  });

  /* ======================================================================
     생년월일 되묻기 — 명백히 대상 밖일 때만

     검진 대상은 만 40~74세다. 20·30대가 보험증 번호까지 다 적고 나서야
     「대상자를 확인할 수 없습니다」를 보는 것은 시간 낭비다.
     생년월일 세 칸이 채워지는 순간 여기서 먼저 되묻는다.

     「대상이 아닙니다」라고 하지 않는 이유
     ---------------------------------------
     거절로 읽히는데, 실제로는 **생년월일 오타**인 경우가 섞여 있다.
     그래서 입력한 날짜를 그대로 되돌려 보여 준다. 오타면 본인이 알아챈다.
     범위도 「당신은」이 아니라 날짜로 말한다.

     경계는 넉넉히 잡는다
     ---------------------
     최종 판정은 대상자 명부가 한다. 여기서 경계를 조금이라도 잘못 잡으면
     대상자인 분을 막아 버리므로, 서버가 내려주는 여유 범위(screening_*)를
     벗어날 때만 되묻는다. 그 사이는 그냥 통과시켜 명부에 맡긴다.

     규칙은 서버(core/dates.py)에 있다. 여기에 복사해 두면 제도가 바뀌었을 때
     한쪽만 고쳐져 조용히 어긋난다.
     ====================================================================== */

  var API_ELIGIBILITY = '/api/v1/reservations/eligibility';

  var birthCheck        = document.getElementById('birth-check');
  var birthCheckEntered = document.getElementById('birth-check-entered');
  var birthCheckRange   = document.getElementById('birth-check-range');
  var eligibility       = null;

  function ymd(value) {
    var m = String(value).split('-');
    return m.length === 3 ? m[0] + '年' + Number(m[1]) + '月' + Number(m[2]) + '日' : value;
  }

  function enteredBirthDate() {
    var y = yearValue();
    var m = el.month.value;
    var d = el.day.value;
    if (!/^\d{4}$/.test(y) || !m || !d) return null;
    return { y: Number(y), m: Number(m), d: Number(d),
             iso: y + '-' + ('0' + m).slice(-2) + '-' + ('0' + d).slice(-2) };
  }

  function updateBirthCheck() {
    if (!birthCheck || !eligibility) return;

    var picked = enteredBirthDate();
    if (!picked) { hideBirthCheck(); return; }

    // 여유 범위 안이면 아무 말도 하지 않는다. 명부가 판정한다.
    if (picked.iso >= eligibility.screening_from && picked.iso <= eligibility.screening_to) {
      hideBirthCheck();
      return;
    }

    birthCheckEntered.innerHTML =
      '<strong>' + picked.y + '年' + picked.m + '月' + picked.d + '日</strong>とご入力いただいています。';
    birthCheckRange.innerHTML =
      '今年の健康診断は<strong>' + ymd(eligibility.eligible_from) + '～' +
      ymd(eligibility.eligible_to) + '</strong>にお生まれの方が対象です。';
    birthCheck.classList.remove('is-hidden');
    if (submitBtn) submitBtn.disabled = true;
  }

  function hideBirthCheck() {
    birthCheck.classList.add('is-hidden');
    if (submitBtn) submitBtn.disabled = false;
  }

  if (birthCheck) {
    [el.year, el.month, el.day].forEach(function (el) {
      el.addEventListener('input', updateBirthCheck);
      el.addEventListener('change', updateBirthCheck);
    });

    // 범위를 못 받아오면 되묻기를 하지 않는다. 판정은 어차피 명부가 하므로
    // 이 기능이 없다고 해서 예약이 막히면 안 된다.
    fetch(API_ELIGIBILITY)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.success && j.data) { eligibility = j.data; updateBirthCheck(); }
      })
      .catch(function () { /* 조용히 넘어간다 */ });
  }

})();
