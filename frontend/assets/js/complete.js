/* ==========================================================================
   complete.js — 예약 5단계 : 예약 완료 (U-17)
   --------------------------------------------------------------------------
   이 화면은 **아무것도 요청하지 않는다.** 예약 확정 API 는 U-16 에서 호출되고,
   그 결과가 sessionStorage 에 담겨 넘어온다.

   왜 여기서 API 를 부르지 않는가
   ------------------------------
   이 화면에서 확정하면 새로고침·뒤로가기·중복 클릭이 전부 「예약 시도」가 된다.
   확정은 되돌릴 수 없는 조작이므로(BR-10) 그 위험을 한 곳(U-16 버튼)에 가둔다.
   여기 도달했다는 것은 이미 서버가 예약번호를 발행했다는 뜻이다.

   완료 후에는 앞 단계의 입력값을 지운다. 그대로 두면 브라우저를 닫지 않은
   다른 사람이 남의 개인정보를 보게 되고, 다음 예약 때 옛 값이 되살아난다.
   ========================================================================== */

(function () {
  'use strict';

  var RESULT_KEY   = 'kenshin.reservationResult';
  var VERIFIED_KEY = 'kenshin.verifiedPerson';
  var PICK_KEY     = 'kenshin.selectedSlot';
  var APPLY_KEY    = 'kenshin.applicantInfo';

  // --- DOM ---------------------------------------------------------------
  var elBody        = document.getElementById('done-body');
  var elLead        = document.getElementById('done-lead');
  var elResNo       = document.getElementById('res-no');
  var elSlot        = document.getElementById('sum-slot');
  var elPerson      = document.getElementById('sum-person');
  var elOption      = document.getElementById('sum-option');
  var elBringList   = document.getElementById('bring-list');
  var elCancelNote  = document.getElementById('cancel-note');

  var elMailWarn    = document.getElementById('mail-warn');
  var elMailWarnTxt = document.getElementById('mail-warn-text');

  var elAlert       = document.getElementById('global-alert');
  var elAlertText   = document.getElementById('global-alert-text');
  var elLive        = document.getElementById('live-status');

  var elPrintBtn    = document.getElementById('print-btn');
  var elCopyBtn     = document.getElementById('copy-btn');
  var elCopyResult  = document.getElementById('copy-result');

  /* ======================================================================
     공통 유틸
     ====================================================================== */

  function showAlert(message) {
    elAlertText.textContent = message;
    elAlert.classList.add('is-visible');
  }

  function announce(text) {
    if (elLive) elLive.textContent = text;
  }

  function readSession(key) {
    try {
      var raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function formatBirth(iso) {
    var p = String(iso).split('-').map(Number);
    return p[0] + '年' + p[1] + '月' + p[2] + '日';
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

  /* ======================================================================
     그리기
     ====================================================================== */

  function render(data) {
    elResNo.textContent = data.reservation_no;
    // 예약번호는 제목에 두지 않는다. 제목은 브라우저 방문 기록에 남고, 번호
    // 하나가 성함·주소·보험증을 여는 열쇠다. 인쇄(PDF 저장)할 때만 파일 이름에
    // 쓰이도록 그동안만 제목에 넣는다.
    var plainTitle = document.title;
    var printTitle = '予約完了 ' + data.reservation_no + '｜健康診断予約';
    window.addEventListener('beforeprint', function () { document.title = printTitle; });
    window.addEventListener('afterprint', function () { document.title = plainTitle; });

    elLead.textContent =
      data.full_name + '様の健康診断のご予約を受け付けました。' +
      '下記の内容をご確認ください。';

    // --- 검진 일시 · 장소 -------------------------------------------------
    var h = data.hospital || {};
    var p = String(data.slot_date).split('-').map(Number);

    row(elSlot, '受診日時',
        p[0] + '年' + p[1] + '月' + p[2] + '日(' + data.weekday + ')  ' +
        data.time_label);
    row(elSlot, '受診会場', h.name);
    row(elSlot, '会場の住所', h.address);
    row(elSlot, 'アクセス', h.access_info);
    row(elSlot, 'お問い合わせ電話', h.tel);

    // --- 신청 내용 --------------------------------------------------------
    row(elPerson, 'お名前', data.full_name);
    row(elPerson, 'フリガナ', data.full_name_kana);
    row(elPerson, '性別', data.gender_label);
    row(elPerson, '生年月日', formatBirth(data.birth_date));
    row(elPerson, 'ご住所',
        (data.postal_code ? '〒 ' + data.postal_code + '  ' : '') +
        [data.address, data.address_detail, data.building]
          .filter(Boolean).join(' '));
    row(elPerson, '携帯電話', data.tel_mobile, '入力なし');
    row(elPerson, '固定電話', data.tel_home, '入力なし');
    row(elPerson, 'メールアドレス', data.email, '入力なし（任意の項目）');

    // --- 옵션 검사 --------------------------------------------------------
    renderOptions(data.options || []);

    // --- 메일 안내 (BR-11) ------------------------------------------------
    if (data.mail_sent) {
      elMailWarn.classList.add('is-ok');
    } else {
      elMailWarn.classList.remove('is-ok');
    }
    elMailWarnTxt.textContent = data.mail_message || '';

    // --- 변경 · 취소 안내 (BR-10 / P-9) -----------------------------------
    // 「기능이 없다」가 아니라 「어떻게 하면 되는지」를 말한다.
    elCancelNote.innerHTML =
      'ご予約の変更・キャンセルは<strong>当サイトでは承っておりません。</strong>' +
      '受診日の<strong>3日前まで</strong>に、下記の予約センターへお電話ください。<br>' +
      '<strong>' + escapeHtml(h.name || '') + '  ' +
      escapeHtml(h.tel || '') + '</strong>';

    // --- 문의처 -----------------------------------------------------------
    setText('contact-tel', data.contact_tel);
    setText('contact-email', data.contact_email);
    setText('contact-hours', data.contact_hours);

    elBody.classList.remove('is-hidden');
    announce('ご予約が完了しました。予約番号は' +
             spellOut(data.reservation_no) + 'です。');
  }

  /* 예약번호를 화면 낭독기가 한 글자씩 또박또박 읽도록 풀어 쓴다.

     예약번호에는 영문 대문자·소문자·숫자가 섞여 있고 **대소문자를 구별한다.**
     글자만 나열하면 낭독기에서 `a` 와 `A` 가 똑같이 들려, 받아 적는 쪽이
     어느 쪽인지 알 수 없다. 그러면 그대로 「조회가 안 된다」가 된다. */
  function spellOut(value) {
    var parts = [];

    for (var i = 0; i < value.length; i += 1) {
      var c = value.charAt(i);

      if (c >= '0' && c <= '9') {
        parts.push(c);
      } else if (c === c.toUpperCase()) {
        parts.push('大文字' + c);
      } else {
        parts.push('小文字' + c.toUpperCase());
      }
    }

    return parts.join(', ');
  }

  function renderOptions(options) {
    elOption.textContent = '';

    if (!options.length) {
      var none = document.createElement('p');
      none.className = 'sumsec__none';
      none.textContent =
        'オプション検査のお申し込みはありません。基本の健診を受診いただきます。';
      elOption.appendChild(none);
      return;
    }

    var ul = document.createElement('ul');
    ul.className = 'optpick';

    options.forEach(function (opt) {
      var li = document.createElement('li');
      li.className = 'optpick__item';
      li.innerHTML =
        '<span class="optpick__check" aria-hidden="true">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M20 6L9 17l-5-5"></path></svg>' +
        '</span>' +
        '<span class="optpick__name"></span>';
      li.querySelector('.optpick__name').textContent = opt.name;
      ul.appendChild(li);
    });

    elOption.appendChild(ul);

    var note = document.createElement('p');
    note.className = 'sumsec__none';
    note.textContent =
      '費用は受診当日に会場でお支払いいただきます。';
    elOption.appendChild(note);

    // 금식 등 준비가 필요한 검사가 있으면 준비물 목록에도 올린다.
    // 옵션 구획까지 다시 올라가 읽게 만들지 않는다.
    var li = document.createElement('li');
    li.className = 'bring__item bring__item--note';
    li.textContent =
      'オプション検査' + options.length + '件をお申し込みいただきました。' +
      '検査によっては前日の絶食などのご準備が必要です。ご案内をご確認ください。';
    elBringList.appendChild(li);
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value || '—';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ======================================================================
     印刷・コピー
     ====================================================================== */

  elPrintBtn.addEventListener('click', function () {
    window.print();
  });

  elCopyBtn.addEventListener('click', function () {
    var value = elResNo.textContent.trim();
    if (!value || value === '—') return;

    function done(ok) {
      elCopyResult.textContent = ok
        ? '予約番号をコピーしました。'
        : 'コピーできませんでした。番号を直接お控えください。';
      announce(elCopyResult.textContent);
    }

    // クリップボードAPIはHTTPSでない場合や権限がないと失敗する。
    // 失敗しても画面の番号はそのまま表示されているため、静かに案内のみ変更する。
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () { done(true); },
                                                function () { done(false); });
    } else {
      done(false);
    }
  });

  /* ======================================================================
     初期化
     ====================================================================== */

  (function init() {
    var data = readSession(RESULT_KEY);

    if (!data || !data.reservation_no) {
      showAlert('表示できるご予約の内容がありません。' +
                'ご予約を進めるには、最初の画面で「予約する」を押してください。');
      announce('ご予約の内容を読み込めませんでした。');
      return;
    }

    render(data);

    // 前段階の入力値をクリアする。完了した予約の個人情報をブラウザに
    // 残しておく理由はない。予約結果自体は再読み込みに備えて残す。
    try {
      sessionStorage.removeItem(VERIFIED_KEY);
      sessionStorage.removeItem(PICK_KEY);
      sessionStorage.removeItem(APPLY_KEY);
    } catch (e) { /* 削除できなくても画面は正常に動作する */ }
  })();

})();
