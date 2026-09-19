/* ==========================================================================
   lookup.js — 예약 확인 (U-20)
   --------------------------------------------------------------------------
   받는 것은 **예약번호 하나뿐**이다. 생년월일도 성함도 묻지 않는다.
   예약번호는 무작위 12자이고 대소문자를 구별하므로 그 자체가 열쇠다.
   반대로 성함·생년월일은 가족이라면 아는 값이라 열쇠가 되지 못한다.

   이 화면은 **읽기 전용**이다. 고칠 수 있는 것이 하나도 없다.
   변경·취소는 웹에서 할 수 없고(BR-10) 전화로만 접수한다.
   그래서 「못 한다」로 끝내지 않고 **어디로 전화하면 되는지**를 크게 보여 준다.
   없는 기능을 찾게 만드는 것 자체가 문의의 근원이기 때문이다. (P-9)

       POST /api/v1/lookup   {"reservation_no": "..."}

   조회는 POST 로 보낸다. 예약번호는 성함·생년월일·주소·보험증번호까지
   전부 여는 유일한 열쇠인데, 쿼리스트링에 실으면 접근 로그와 브라우저
   히스토리에 그대로 남기 때문이다. 메일의 조회 링크로 들어온 경우에도
   조회가 끝나면 주소창에서 번호를 지운다.
   ========================================================================== */

(function () {
  'use strict';

  var API = '/api/v1/lookup';
  var RESNO_LENGTH = 12;

  // 예약번호에 쓰이는 문자. 서버와 같은 기준이다.
  // (backend/app/core/reservation_no.py)
  var RESNO_RE = /^[A-Za-z0-9]{12}$/;

  var elInputStep  = document.getElementById('step-input');
  var elResultStep = document.getElementById('step-result');

  var elForm    = document.getElementById('lookup-form');
  var elResNo   = document.getElementById('res-no');
  var elCount   = document.getElementById('resno-count');
  var elSubmit  = document.getElementById('submit-btn');

  var elAlert     = document.getElementById('global-alert');
  var elAlertText = document.getElementById('global-alert-text');
  var elLive      = document.getElementById('live-status');

  /* ======================================================================
     공통
     ====================================================================== */

  function announce(text) {
    if (elLive) elLive.textContent = text;
  }

  function showAlert(message, hints) {
    elAlertText.textContent = '';

    var p = document.createElement('span');
    p.textContent = message;
    elAlertText.appendChild(p);

    if (hints && hints.length) {
      var ul = document.createElement('ul');
      ul.className = 'alert__hints';
      hints.forEach(function (h) {
        var li = document.createElement('li');
        li.textContent = h;
        ul.appendChild(li);
      });
      elAlertText.appendChild(ul);
    }

    elAlert.classList.add('is-visible');
    elAlert.scrollIntoView({ behavior: 'smooth', block: 'center' });
    announce(message);
  }

  function clearAlert() {
    elAlert.classList.remove('is-visible');
  }

  function setFieldError(message) {
    var box = document.getElementById('err-res-no');
    box.querySelector('span').textContent = message || '';
    box.classList.toggle('is-visible', !!message);
    elResNo.setAttribute('aria-invalid', message ? 'true' : 'false');
  }

  function row(dl, key, value, emptyText) {
    var wrap = document.createElement('div');
    wrap.className = 'datalist__row';

    var k = document.createElement('dt');
    k.className = 'datalist__key';
    k.textContent = key;

    var v = document.createElement('dd');
    v.className = 'datalist__val';

    if (value) {
      v.textContent = value;
    } else {
      v.className += ' datalist__val--empty';
      v.textContent = emptyText || '入力なし';
    }

    wrap.appendChild(k);
    wrap.appendChild(v);
    dl.appendChild(wrap);
  }

  function formatBirth(iso) {
    var p = String(iso).split('-').map(Number);
    return p[0] + '年' + p[1] + '月' + p[2] + '日';
  }

  /* ======================================================================
     입력 보조
     ====================================================================== */

  /* 남은 글자 수를 보여 준다.
     12자를 옮겨 적는 동안 「몇 자까지 적었지」를 세지 않아도 되게 한다. */
  function updateCount() {
    var n = elResNo.value.length;

    if (!n) {
      elCount.textContent = '';
      elCount.className = 'resno-count';
      return;
    }

    if (n === RESNO_LENGTH) {
      elCount.textContent = '12桁すべてご入力いただきました。';
      elCount.className = 'resno-count is-ok';
    } else {
      elCount.textContent = n + ' / ' + RESNO_LENGTH + '桁';
      elCount.className = 'resno-count';
    }
  }

  /* 붙여넣기·손입력에서 흔한 군더더기를 걷어낸다.

     **대소문자는 절대 바꾸지 않는다.** 예약번호는 대소문자를 구별한다.
     여기서 `toUpperCase()` 같은 것을 하면 맞는 번호를 틀리게 만든다. */
  function tidy(value) {
    return String(value)
      // 전각으로 들어온 영숫자를 반각으로 (일본어 입력기에서 흔하다)
      .replace(/[Ａ-Ｚａ-ｚ０-９]/g, function (c) {
        return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
      })
      // 공백·하이픈은 이 번호에 없다. 메일에서 줄바꿈째 복사한 경우를 받아 준다.
      .replace(/[\s\-–—‐]/g, '');
  }

  elResNo.addEventListener('input', function () {
    var cleaned = tidy(this.value).slice(0, RESNO_LENGTH);
    if (cleaned !== this.value) this.value = cleaned;
    setFieldError('');
    clearAlert();
    updateCount();
  });

  /* ======================================================================
     조회
     ====================================================================== */

  function setLoading(on) {
    elSubmit.disabled = on;
    elSubmit.querySelector('.btn__label').textContent =
      on ? '確認しています…' : '予約内容を確認する';
  }

  function validate() {
    var value = elResNo.value;

    if (!value) {
      setFieldError('予約番号をご入力ください。');
      return null;
    }
    if (!RESNO_RE.test(value)) {
      setFieldError(
        '予約番号は英字と数字を組み合わせた12桁です。' +
        'お受け取りになった番号をそのままご確認ください。'
      );
      return null;
    }

    setFieldError('');
    return value;
  }

  elForm.addEventListener('submit', function (e) {
    e.preventDefault();
    clearAlert();

    var value = validate();
    if (!value) {
      elResNo.focus();
      return;
    }

    setLoading(true);

    fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reservation_no: value })
    })
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) {
            var err = body.error || {};
            var e2 = new Error(err.message || 'ご予約が見つかりませんでした。');
            e2.hints = err.hints || [];
            e2.contact = err.contact || null;
            throw e2;
          }
          return body.data;
        });
      })
      .then(render)
      .catch(function (err) {
        if (err.contact) applyContact(err.contact);
        showAlert(
          err.message || '通信に失敗しました。しばらくしてからもう一度お試しください。',
          err.hints
        );
      })
      .then(function () { setLoading(false); });
  });

  function applyContact(contact) {
    var tel = document.getElementById('in-tel');
    var hours = document.getElementById('in-hours');
    if (tel && contact.tel) tel.textContent = contact.tel;
    if (hours && contact.hours) hours.textContent = contact.hours;
  }

  /* ======================================================================
     결과 그리기 — 읽기 전용
     ====================================================================== */

  function render(d) {
    document.getElementById('rs-no').textContent = d.reservation_no;

    /* 상태 배지.

       휴진일 때는 「예약 확정」이 아니라 「일정 변경 예정」으로 바꾼다.
       예약 자체는 살아 있으므로 「취소」로 내리면 안 된다 — 예약이
       없어진 줄 알고 다시 신청하시는 분이 생긴다. */
    var status = document.getElementById('rs-status');
    if (d.is_holiday) {
      status.textContent = '日程変更の予定';
      status.className = 'rs-status rs-status--holiday';
    } else {
      status.textContent = d.status_label;
      status.className = 'rs-status rs-status--' + d.status.toLowerCase();
    }

    /* 휴진 안내.

       전화가 닿기 전에 스스로 확인하러 오시는 분이 있다. 그분이
       「예약 확정」만 보고 그 날 회장에 오시는 것을 막는 것이 이 배너의
       할 일이다. 무엇을 하시면 되는지(기다리기 / 안 오면 전화)까지 적는다. */
    var alarm = document.getElementById('rs-holiday');
    alarm.classList.toggle('is-hidden', !d.is_holiday);
    if (d.is_holiday) {
      var htel = document.getElementById('rs-holiday-tel');
      htel.textContent = d.contact_tel;
      htel.href = 'tel:' + String(d.contact_tel).replace(/[^0-9+]/g, '');
      document.getElementById('rs-holiday-hours').textContent = d.contact_hours || '';
    }

    document.getElementById('rs-lead').textContent =
      d.full_name + '様のご予約内容です。(' + d.channel_label + ')';

    // --- 검진 일시 · 장소 -------------------------------------------------
    var slot = document.getElementById('rs-slot');
    slot.textContent = '';
    var h = d.hospital || {};
    var sd = String(d.slot_date).split('-').map(Number);

    /* 휴진이면 날짜에 취소선을 긋는다.

       배너를 지나쳐 표만 보시는 분이 있다. 「10월 13일」이 멀쩡히 적혀
       있으면 그 날로 읽힌다. 지우지는 않는다 — 원래 어느 날이었는지
       모르면 전화로 이야기할 때 서로 다른 날을 말하게 된다. */
    var when = sd[0] + '年' + sd[1] + '月' + sd[2] + '日('
             + d.weekday + ')  ' + d.time_label;
    row(slot, '受診日時', when);
    if (d.is_holiday) {
      // row() 는 dt·dd 를 .datalist__row 로 한 번 감싼다. 감싼 것을 통째로
      // 건드리면 항목 이름까지 지워지므로 안쪽 dd 만 다시 그린다.
      var dd = slot.lastElementChild.querySelector('dd');
      dd.textContent = '';
      var struck = document.createElement('s');
      struck.textContent = when;
      dd.appendChild(struck);
      var tag = document.createElement('em');
      tag.className = 'holiday-tag';
      tag.textContent = '休診';
      dd.appendChild(tag);
    }
    row(slot, '受診会場', h.name);
    row(slot, '会場の住所', h.address);
    row(slot, 'アクセス', h.access_info);
    row(slot, 'お問い合わせ電話', h.tel);

    // --- 신청 내용 --------------------------------------------------------
    var person = document.getElementById('rs-person');
    person.textContent = '';

    row(person, 'お名前', d.full_name);
    row(person, 'フリガナ', d.full_name_kana);
    row(person, '性別', d.gender_label);
    row(person, '生年月日', formatBirth(d.birth_date));
    row(person, 'ご住所',
        (d.postal_code ? '〒 ' + d.postal_code + '  ' : '') +
        [d.address, d.address_detail, d.building].filter(Boolean).join(' '));
    row(person, '携帯電話', d.tel_mobile);
    row(person, '固定電話', d.tel_home);
    row(person, 'メールアドレス', d.email, 'ご登録なし');

    // --- 옵션 검사 --------------------------------------------------------
    renderOptions(d.options || []);

    // --- 변경 · 취소 안내 --------------------------------------------------
    document.getElementById('rs-change-notice').textContent = d.change_notice;

    // 회장 이름 및 주소는 항상 표시
    document.getElementById('rs-hospital-name').textContent = h.name || '';
    var addrEl = document.getElementById('rs-hospital-address');
    if (addrEl) {
      addrEl.textContent = h.address || '';
    }

    // 회장 전화와 예약 센터 전화가 같으면 전화번호만 숨긴다.
    var venueTel = h.tel || '';
    var venueTelEl = document.getElementById('rs-hospital-tel');
    if (venueTel && venueTel !== d.contact_tel) {
      setTel('rs-hospital-tel', venueTel);
      if (venueTelEl) venueTelEl.style.display = '';
    } else {
      if (venueTelEl) venueTelEl.style.display = 'none';
    }

    setTel('rs-contact-tel', d.contact_tel);
    document.getElementById('rs-contact-hours').textContent = d.contact_hours || '';

    // 언제까지 볼 수 있는지. 「어제는 보였는데」가 문의가 되지 않게 미리 알린다.
    document.getElementById('rs-viewable').textContent =
      d.status === 'CANCELLED'
        ? ''
        : '※ このご予約の内容は、受診後(' + d.viewable_until +
          ')は照会できなくなります。必要な場合はこの画面を印刷してください。';

    // 이메일 버튼 상태
    var emailBtn = document.getElementById('email-btn');
    var emailError = document.getElementById('email-error-msg');
    if (d.email) {
      emailBtn.disabled = false;
      emailError.style.display = 'none';
      emailBtn.dataset.resNo = d.reservation_no;
    } else {
      emailBtn.disabled = true;
      emailError.style.display = '';
      emailBtn.dataset.resNo = '';
    }

    elInputStep.classList.add('is-hidden');
    elResultStep.classList.remove('is-hidden');
    elResultStep.focus();
    window.scrollTo({ top: 0, behavior: 'smooth' });

    announce(d.full_name + '様のご予約内容を表示しました。' + d.status_label + '。');
  }

  /** 전화번호는 눌러서 걸 수 있게 한다. 이 화면의 목적지가 전화이기 때문이다. */
  function setTel(id, value) {
    var el = document.getElementById(id);
    if (!el) return;

    el.textContent = value || '';
    if (value) {
      el.setAttribute('href', 'tel:' + value.replace(/[^0-9+]/g, ''));
    } else {
      el.removeAttribute('href');
    }
  }

  function renderOptions(options) {
    var box = document.getElementById('rs-option');
    box.textContent = '';

    if (!options.length) {
      var none = document.createElement('p');
      none.className = 'sumsec__none';
      none.textContent =
        'オプション検査のお申し込みはありません。基本の健診を受診いただきます。';
      box.appendChild(none);
      return;
    }

    var ul = document.createElement('ul');
    ul.className = 'optpick';

    options.forEach(function (opt) {
      var li = document.createElement('li');
      li.className = 'optpick__item';

      var check = document.createElement('span');
      check.className = 'optpick__check';
      check.setAttribute('aria-hidden', 'true');
      check.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M20 6L9 17l-5-5"></path></svg>';

      var name = document.createElement('span');
      name.className = 'optpick__name';
      name.textContent = opt.name;

      li.appendChild(check);
      li.appendChild(name);
      ul.appendChild(li);
    });

    box.appendChild(ul);
  }

  /* ======================================================================
     결과 화면의 조작
     ====================================================================== */

  document.getElementById('print-btn').addEventListener('click', function () {
    window.print();
  });

  document.getElementById('email-btn').addEventListener('click', function () {
    var btn = this;
    var resNo = btn.dataset.resNo;
    if (!resNo) return;

    btn.disabled = true;
    var originalText = btn.innerHTML;
    btn.textContent = '送信中...';

    fetch(API + '/send-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reservation_no: resNo })
    })
    .then(function(res) {
      return res.json().then(function(body) {
        if (!res.ok) throw new Error((body.error && body.error.message) || 'メールの送信に失敗しました。再度お試しください。');
        if (body.data && body.data.delivered === false) {
          alert('ただいま確認メールをお送りできませんでした。お手数ですが、この画面を印刷するか、' +
                '予約番号をお控えください。');
          return;
        }
        alert('登録されたメールアドレスに確認リンクを送信しました。');
      });
    })
    .catch(function(err) {
      alert(err.message);
    })
    .finally(function() {
      btn.innerHTML = originalText;
      btn.disabled = false;
    });
  });

  document.getElementById('again-btn').addEventListener('click', function () {
    elResultStep.classList.add('is-hidden');
    elInputStep.classList.remove('is-hidden');

    elResNo.value = '';
    setFieldError('');
    clearAlert();
    updateCount();

    window.scrollTo({ top: 0, behavior: 'smooth' });
    elResNo.focus();
  });

  /* ======================================================================
     시작
     ====================================================================== */

  updateCount();
  
  var params = new URLSearchParams(window.location.search);
  var initialResNo = params.get('reservation_no');
  if (initialResNo) {
    elResNo.value = initialResNo;
    // 메일의 조회 링크로 들어온 경우다. 번호를 주소창에 남겨 두면
    // 브라우저 히스토리와 Referer 헤더를 타고 밖으로 새어 나간다.
    // 값을 입력칸으로 옮겼으니 주소에서는 지운다.
    if (window.history && window.history.replaceState) {
      params.delete('reservation_no');
      var rest = params.toString();
      window.history.replaceState(
        null, '', window.location.pathname + (rest ? '?' + rest : '')
      );
    }
    elSubmit.click();
  } else {
    elResNo.focus();
  }
})();
