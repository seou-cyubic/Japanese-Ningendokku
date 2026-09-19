/* ==========================================================================
   confirm.js — 예약 4단계 : 입력 내용 확인 (U-16)
   --------------------------------------------------------------------------
   앞의 세 단계에서 모은 값을 한 화면에 전부 펼친다. 여기서 새로 입력받는 것은
   없다. 각 묶음에 「수정」을 달아 그 값을 입력했던 자리로 되돌려 보낸다.

     신청하시는 분   → verify.html          (U-11)
     검진 회장 · 일시 → schedule.html        (U-12)
     주소            → form.html#sec-address (U-14)
     연락처          → form.html#sec-contact (U-14)
     옵션 검사       → form.html#sec-option  (U-14)

   확정 직전에 이메일 미입력과 「웹에서 변경·취소 불가」를 한 번 더 알린다.
   여기서 걸러 내지 못한 착오는 전부 전화 문의가 된다. (BR-10 / BR-11)
   ========================================================================== */

(function () {
  'use strict';

  var API_RESERVE  = '/api/v1/reservations';

  var VERIFIED_KEY = 'kenshin.verifiedPerson';
  var PICK_KEY     = 'kenshin.selectedSlot';
  var APPLY_KEY    = 'kenshin.applicantInfo';
  var RESULT_KEY   = 'kenshin.reservationResult';

  var WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];

  // 확정 요청 중인지. 두 번 눌러 예약이 두 건 생기는 사고를 막는다.
  var submitting = false;

  // --- DOM ---------------------------------------------------------------
  var elPerson      = document.getElementById('sum-person');
  var elSlot        = document.getElementById('sum-slot');
  var elAddress     = document.getElementById('sum-address');
  var elContact     = document.getElementById('sum-contact');
  var elOption      = document.getElementById('sum-option');

  var elMailWarn    = document.getElementById('mail-warn');
  var elMailWarnTxt = document.getElementById('mail-warn-text');

  var elConfirmBtn  = document.getElementById('confirm-btn');
  var elAlert       = document.getElementById('global-alert');
  var elAlertText   = document.getElementById('global-alert-text');
  var elLive        = document.getElementById('live-status');

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

  /** '2026-08-10' → '2026年8月10日（月）' */
  function formatDateLong(iso) {
    var p = String(iso).split('-').map(Number);
    var wd = WEEKDAY[new Date(p[0], p[1] - 1, p[2]).getDay()];
    return p[0] + '年' + p[1] + '月' + p[2] + '日（' + wd + '）';
  }

  /** '1975-12-15' → '1975年12月15日' */
  function formatBirth(iso) {
    var p = String(iso).split('-').map(Number);
    return p[0] + '年' + p[1] + '月' + p[2] + '日';
  }

  /**
   * 확인 항목 한 줄.
   * 값이 비어 있으면 「입력하지 않으셨습니다」로 명시한다.
   * 빈 줄을 그냥 지워 버리면 「입력했는데 안 보인다」와 구별되지 않는다.
   */
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
     ① 신청하시는 분 (U-11)
     ====================================================================== */

  function renderPerson(verified) {
    if (!verified || !verified.person) {
      row(elPerson, '状態', '', '本人確認がまだ終わっていません');
      return false;
    }

    var p = verified.person;
    var name = p.full_name || (p.last_name + ' ' + p.first_name);
    var kana = p.full_name_kana || (p.last_name_kana + ' ' + p.first_name_kana);

    row(elPerson, 'お名前', name);
    row(elPerson, 'フリガナ', kana);
    if (p.middle_name) row(elPerson, 'ミドルネーム', p.middle_name);
    row(elPerson, '性別', p.gender_label || (p.gender === 'F' ? '女性' : '男性'));
    row(elPerson, '生年月日', formatBirth(p.birth_date));
    row(elPerson, '健康保険証', p.insurance_card_no);
    return true;
  }

  /* ======================================================================
     ② 검진 회장 · 일시 (U-12)
     ====================================================================== */

  function renderSlot(picked) {
    if (!picked || !picked.hospital || !picked.slot) {
      row(elSlot, '状態', '', '会場と日時がまだ選ばれていません');
      return false;
    }

    var h = picked.hospital;
    row(elSlot, '会場', h.name);
    row(elSlot, '受診日時', formatDateLong(picked.date) + '  ' + picked.slot.time_label);
    row(elSlot, '会場の住所', h.address);
    row(elSlot, 'アクセス', h.access_info);
    row(elSlot, 'お問い合わせ電話', h.tel);
    return true;
  }

  /* ======================================================================
     ③④⑤ 주소 · 연락처 · 옵션 검사 (U-14)
     ====================================================================== */

  function renderAddress(info) {
    if (!info) {
      row(elAddress, '状態', '', 'ご住所がまだ入力されていません');
      return false;
    }

    row(elAddress, '郵便番号', info.postal_code ? '〒 ' + info.postal_code : '');
    row(elAddress, 'ご住所', info.address);
    row(elAddress, '番地', info.address_detail);
    row(elAddress, 'アパート・マンション名', info.building, '入力なし（任意の項目）');
    return !!(info.postal_code && info.address && info.address_detail);
  }

  function renderContact(info) {
    if (!info) {
      row(elContact, '状態', '', 'ご連絡先がまだ入力されていません');
      updateMailWarn('');
      return false;
    }

    row(elContact, '携帯電話', info.tel_mobile, '入力なし');
    row(elContact, '固定電話', info.tel_home, '入力なし');
    row(elContact, 'メールアドレス', info.email, '入力なし（任意の項目）');

    updateMailWarn(info.email);
    return !!(info.tel_mobile || info.tel_home);
  }

  function updateMailWarn(email) {
    if (email) {
      elMailWarn.classList.add('is-ok');
      elMailWarnTxt.innerHTML =
        'ご予約が確定しましたら<strong>' + escapeHtml(email) + '</strong>へ' +
        '予約番号を記載した確認メールをお送りします。' +
        'お間違いがないか、最後にご確認ください。';
    } else {
      elMailWarn.classList.remove('is-ok');
      elMailWarnTxt.innerHTML =
        'メールアドレスのご入力がないため、<strong>確認メールとリマインドメールをお受け取りいただけません。</strong>' +
        '予約番号は次の画面にのみ表示されますので、<strong>必ずお控えください</strong>。';
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderOptions(info) {
    elOption.textContent = '';

    var options = (info && info.options) || [];

    if (!options.length) {
      var none = document.createElement('p');
      none.className = 'sumsec__none';
      none.textContent =
        'オプション検査は選ばれていません。基本の健診は予定どおり受診いただけます。';
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
      'オプション検査' + options.length + '件を選ばれました。' +
      '費用は受診当日に会場でお支払いいただきます。';
    elOption.appendChild(note);
  }

  /* ======================================================================
     確定
     ====================================================================== */

  function clearAlert() {
    elAlert.classList.remove('is-visible');
    elAlertText.textContent = '';
  }

  function setBusy(busy) {
    submitting = busy;
    elConfirmBtn.disabled = busy;
    elConfirmBtn.setAttribute('aria-busy', busy ? 'true' : 'false');
    elConfirmBtn.querySelector('span').textContent =
      busy ? 'ご予約を受け付けています…' : 'この内容で予約する';
  }

  /**
   * 予約を受け付けられない場合の案内。
   * 文面はサーバーが決定する。結果の種類が増えてもこの画面は修正しない。
   * ただし「次にどこへ進むべきか」は画面が把握しているため、ここで追加する。
   */
  function handleRefusal(error) {
    var code = error.code || '';
    var message = error.message || 'ただいまご予約を受け付けられません。';

    if (error.hints && error.hints.length) {
      message += ' ' + error.hints.join(' ');
    }

    showAlert(message);
    announce(message);
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // 満員・締切は他の時間を選べば解決する。その場で戻す。
    if (code === 'SLOT_FULL' || code === 'SLOT_CLOSED' || code === 'SLOT_PAST') {
      elConfirmBtn.disabled = true;
      addRecovery('別の日時を選ぶ', 'schedule.html');
    }

    // 本人確認の有効期限切れは最初からやり直す必要がある。
    if (code === 'VERIFY_REQUIRED') {
      elConfirmBtn.disabled = true;
      addRecovery('本人確認をやり直す', 'verify.html');
    }
  }

  /** 案内文の下に次のアクションボタンを配置する。行き止まりを作らない。 */
  function addRecovery(label, href) {
    if (document.getElementById('recovery-link')) return;

    var link = document.createElement('a');
    link.id = 'recovery-link';
    link.className = 'btn btn--primary';
    link.href = href;
    link.textContent = label;
    link.style.marginTop = 'var(--sp-2)';

    elAlert.parentNode.insertBefore(link, elAlert.nextSibling);
  }

  elConfirmBtn.addEventListener('click', function () {
    if (submitting) return;

    var verified = readSession(VERIFIED_KEY);
    var picked = readSession(PICK_KEY);
    var info = readSession(APPLY_KEY);

    if (!verified || !verified.token || !picked || !picked.slot || !info) {
      showAlert('ご予約に必要な内容がそろっていません。' +
                '各項目の「修正」からご確認ください。');
      return;
    }

    clearAlert();
    setBusy(true);
    announce('ご予約を受け付けています。少々お待ちください。');

    var payload = {
      verify_token: verified.token,
      slot_id: picked.slot.slot_id,
      postal_code: info.postal_code || '',
      address: info.address || '',
      address_detail: info.address_detail || '',
      building: info.building || '',
      tel_mobile: info.tel_mobile || '',
      tel_home: info.tel_home || '',
      email: info.email || '',
      options: (info.options || []).map(function (o) { return { id: o.id }; })
    };

    fetch(API_RESERVE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (res) {
        if (res.status === 200 && res.body.success) {
          try {
            sessionStorage.setItem(RESULT_KEY, JSON.stringify(res.body.data));
          } catch (e) { /* 保存に失敗しても次の画面で案内を表示する */ }

          window.location.href = 'complete.html';
          return;
        }

        setBusy(false);

        if (res.status === 422 && res.body.fields) {
          // 入力値自体に誤りがある場合。どの項目かを明示する。
          var names = res.body.fields.map(function (f) { return f.message; });
          showAlert('ご入力の内容をご確認ください。' + names.join(' '));
          window.scrollTo({ top: 0, behavior: 'smooth' });
          return;
        }

        handleRefusal(res.body.error || {});
      })
      .catch(function () {
        setBusy(false);
        // 通信が切断された場合、サーバー側で既に確定している可能性がある。
        // 「「もう一度押してください」と案内すると重複予約になる恐れがあるため、
        // 必ず確認から行うよう案内する。
        showAlert('通信が不安定なため、結果を確認できませんでした。' +
                  'ご予約が受け付けられている可能性がありますので、もう一度お試しになる前に' +
                  'お問い合わせ先までご確認ください。');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
  });

  /* ======================================================================
     初期化
     ====================================================================== */

  // 완료 화면에서 브라우저 「뒤로」로 돌아오면 페이지가 bfcache 에서 **그대로**
  // 살아난다. 스크립트가 다시 돌지 않아 「ご予約を受け付けています…」로 잠긴
  // 단추가 그대로 남는다. 캐시에서 살아났으면 새로 읽어 아래 판정을 다시 한다.
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) window.location.reload();
  });

  (function init() {
    var verified = readSession(VERIFIED_KEY);
    var picked = readSession(PICK_KEY);
    var info = readSession(APPLY_KEY);

    // 予約を終えたあとに戻ってきた場合。完了画面が入力セッションを消すため、
    // 下の判定は「まだ何もしていない」ように見えるが、実際にはすでに終わっている。
    // 結果マーカーが残っていればそのように案内する — 予約したばかりの人に
    // 「本人確認がまだ終わっていません」とは言わない。
    var result = readSession(RESULT_KEY);
    if (result && result.reservation_no && !verified && !picked && !info) {
      showAlert('ご予約はすでに完了しています。予約番号 ' + result.reservation_no +
                ' — 内容は「予約完了の画面」でご確認いただけます。');
      announce('ご予約は完了しています。');
      elConfirmBtn.disabled = true;
      addRecovery('予約完了の画面を見る', 'complete.html');
      return;
    }

    var ok = [];
    ok.push(renderPerson(verified));
    ok.push(renderSlot(picked));
    ok.push(renderAddress(info));
    ok.push(renderContact(info));
    renderOptions(info);

    // 未入力項目がある場合は確定ボタンを無効化する。
    // ここで通過させるとサーバー側でエラーとなり、利用者が理由の分からないまま戻される。
    if (ok.indexOf(false) !== -1) {
      elConfirmBtn.disabled = true;
      showAlert('まだ入力されていない項目があります。' +
                '各項目の「修正」からご入力ください。');
      announce('未入力の項目があるため、ご予約に進めません。');
    }
  })();

})();
