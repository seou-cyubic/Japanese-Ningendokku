/* ==========================================================================
   apply.js — 예약 3단계 : 신청자 정보 입력 (U-14)
   --------------------------------------------------------------------------
   여기서 새로 받는 것은 주소 · 연락처 · 옵션 검사뿐이다.
   성명 · 성별 · 생년월일 · 보험증은 U-11 에서, 회장 · 일시는 U-12 에서
   이미 확정됐으므로 읽기 전용으로 보여 주기만 한다.

   필수 판정은 plan.md BR-05 를 따른다.
     우편번호 / 주소 / 번지  → 필수
     휴대전화 · 유선전화     → 둘 중 최소 1개 필수
     아파트·맨션명 / 이메일 / 옵션 검사 → 임의

   이메일은 임의지만 미입력 시 확인 메일·리마인드 메일을 받을 수 없으므로
   그 결과를 폼에서 명확히 경고한다. (BR-11 · 문의 감소 시책의 핵심)

     GET /api/v1/exam-options?gender=M&birth_date=YYYY-MM-DD
   ========================================================================== */

(function () {
  'use strict';

  var API_OPTIONS  = '/api/v1/exam-options';
  var VERIFIED_KEY = 'kenshin.verifiedPerson';
  var PICK_KEY     = 'kenshin.selectedSlot';
  var APPLY_KEY    = 'kenshin.applicantInfo';

  var WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];

  // --- DOM ---------------------------------------------------------------
  var elForm        = document.getElementById('apply-form');

  var elOptionLead  = document.getElementById('option-lead');
  var elOptionList  = document.getElementById('option-list');

  var elMailWarn    = document.getElementById('mail-warn');
  var elMailWarnTxt = document.getElementById('mail-warn-text');

  var elErrSum      = document.getElementById('error-summary');
  var elErrSumList  = document.getElementById('error-summary-list');

  var elAlert       = document.getElementById('global-alert');
  var elAlertText   = document.getElementById('global-alert-text');
  var elLive        = document.getElementById('live-status');

  var $ = function (id) { return document.getElementById(id); };

  // --- 상태 --------------------------------------------------------------
  var verified = null;   // { token, person }
  var picked = null;     // { hospital, date, slot }

  // 이전에 고른 옵션 검사 id. 목록은 API 로 비동기로 그려지므로,
  // 되살릴 값을 미리 읽어 두었다가 그릴 때 체크한다.
  var savedOptionIds = [];

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

  /** 전각 숫자·기호를 반각으로 낮춘다. 스마트폰 IME 로 전각이 섞여 들어온다. */
  function toHalfWidth(s) {
    return String(s || '').replace(/[！-～]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0);
    }).replace(/　/g, ' ');
  }

  function digitsOf(s) {
    return toHalfWidth(s).replace(/[^0-9]/g, '');
  }

  /* ======================================================================
     ① 앞 단계 완료 여부
     확정된 내용 자체는 이 화면에 두지 않는다. 전체 확인은 U-16 의 몫이다.
     여기서는 앞 단계를 건너뛴 경우만 안내한다.
     ====================================================================== */

  function checkPrevSteps() {
    verified = readSession(VERIFIED_KEY);
    picked = readSession(PICK_KEY);

    var missing = [];
    if (!verified || !verified.person) missing.push('本人確認');
    if (!picked || !picked.hospital || !picked.slot) missing.push('会場・日時の選択');

    if (missing.length) {
      showAlert(missing.join('と') + 'がまだ終わっていません。' +
                '「前の画面へ戻る」から済ませてください。');
    }
  }

  /* ======================================================================
     ② 옵션 검사 — 성별·연령 조건에 맞는 것만 받아 온다 (BR-13)
     ====================================================================== */

  function loadOptions() {
    if (!verified || !verified.person) {
      elOptionLead.textContent =
        '本人確認が終わると、お申し込みいただけるオプション検査が表示されます。';
      return;
    }

    var p = verified.person;
    var url = API_OPTIONS +
      '?gender=' + encodeURIComponent(p.gender) +
      '&birth_date=' + encodeURIComponent(p.birth_date);

    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.success) throw new Error('オプション検査を読み込めませんでした。');
        renderOptions(body.data);
      })
      .catch(function () {
        elOptionLead.textContent =
          'オプション検査の一覧を読み込めませんでした。オプションなしでもご予約は進められます。';
      });
  }

  function renderOptions(data) {
    if (!data.options.length) {
      elOptionLead.textContent = 'ただいまお申し込みいただけるオプション検査はありません。';
      return;
    }

    // 「왜 내가 받던 검사가 없냐」는 문의를 미리 막기 위해 거른 근거를 밝힌다
    elOptionLead.textContent =
      '満' + data.age + '歳' + data.gender_label +
      'の方がお申し込みいただける検査です。必要なものだけお選びください。';

    elOptionList.textContent = '';

    data.options.forEach(function (opt) {
      var label = document.createElement('label');
      label.className = 'opt';

      label.innerHTML =
        '<input type="checkbox" name="exam_option">' +
        '<span class="opt__box">' +
          '<span class="opt__check" aria-hidden="true">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M20 6L9 17l-5-5"></path></svg>' +
          '</span>' +
          '<span class="opt__body">' +
            '<span class="opt__name"></span>' +
            '<span class="opt__desc"></span>' +
          '</span>' +
        '</span>';

      var input = label.querySelector('input');
      input.value = String(opt.id);
      input.setAttribute('data-code', opt.code);
      input.setAttribute('data-name', opt.name);
      // 「수정」으로 돌아온 경우 이전 선택을 되살린다
      input.checked = savedOptionIds.indexOf(opt.id) !== -1;

      label.querySelector('.opt__name').textContent = opt.name;
      label.querySelector('.opt__desc').textContent = opt.description;

      // 금식 등 당일 준비가 필요한 검사는 고르기 전에 알린다
      if (opt.note) {
        var note = document.createElement('span');
        note.className = 'opt__note';
        note.textContent = 'ご準備・' + opt.note;
        label.querySelector('.opt__body').appendChild(note);
      }

      input.addEventListener('change', function () {
        announce(opt.name + (input.checked ? 'を選びました。' : 'の選択を解除しました。'));
      });

      elOptionList.appendChild(label);
    });
  }

  /* ======================================================================
     ③ 검증
     「무엇이 잘못됐는지」가 아니라 「어떻게 고치면 되는지」를 쓴다. (P-7)
     ====================================================================== */

  function setError(fieldId, errorId, message) {
    var err = $(errorId);
    var input = $(fieldId);
    if (message) {
      err.querySelector('span').textContent = message;
      err.classList.add('is-visible');
      if (input) input.setAttribute('aria-invalid', 'true');
    } else {
      err.classList.remove('is-visible');
      if (input) input.removeAttribute('aria-invalid');
    }
  }

  /* ----------------------------------------------------------------------
     전화번호 — 휴대전화·유선전화 모두 세 칸에 나눠 받는다.

     휴대전화 : 앞자리를 **목록에서 고른다.** 일본 휴대전화 번호의 앞 3자리는
                090 / 080 / 070 세 가지뿐이라, 손으로 치게 하면 오타만 생긴다.
                뒤 두 칸은 각각 4자리 고정 → 합계 11자리.

     유선전화 : 앞자리를 목록으로 만들지 않는다. 일본 고정전화의 시외국번은
                2~5자리로 제각각이고 전국에 500개가 넘어, 목록에서 자기 번호를
                찾는 편이 더 어렵다. 대신 세 조각의 **합이 10자리**인 것은
                공통이므로 그것으로 검증한다.

                    03  - 1234 - 5678   (2+4+4)
                    045 - 123  - 4567   (3+3+4)
                    0123- 45   - 6789   (4+2+4)
     ---------------------------------------------------------------------- */

  var TEL = {
    mobile: {
      parts: ['tel-mobile', 'tel-mobile2', 'tel-mobile3'],
      max: [3, 4, 4],
      total: 11,
      // 앞자리가 <select> 라 자동 넘김·붙여넣기 대상에서 뺀다
      firstIsSelect: true,
      errorId: 'err-tel-mobile',
      label: '携帯電話番号',
      hint: '携帯電話番号を3つの欄にすべてご入力ください。' +
            '先頭の番号をお選びのうえ、中間と下を4桁ずつご入力ください。（例：090 - 1234 - 5678）'
    },
    home: {
      parts: ['tel-home', 'tel-home2', 'tel-home3'],
      max: [5, 4, 4],
      total: 10,
      firstIsSelect: false,
      errorId: 'err-tel-home',
      label: '固定電話番号',
      hint: '固定電話番号を3つの欄にすべてご入力ください。' +
            '市外局番からご入力ください。合わせて10桁です。（例：03 - 1234 - 5678）'
    }
  };

  /** 세 칸을 이어 붙인 숫자만. 비어 있으면 빈 문자열. */
  function telDigits(kind) {
    return TEL[kind].parts.map(function (id) {
      return digitsOf($(id).value);
    }).join('');
  }

  /** 서버로 보낼 값. 한 칸이라도 비면 「입력하지 않음」으로 본다. */
  function telValue(kind) {
    var parts = TEL[kind].parts.map(function (id) { return digitsOf($(id).value); });
    return parts.every(Boolean) ? parts.join('-') : '';
  }

  /** 저장된 값을 세 칸에 되살린다. */
  function setTelValue(kind, value) {
    var cfg = TEL[kind];
    var parts = String(value || '').split('-');

    if (parts.length !== 3) {
      // 하이픈 없이 저장된 경우. 휴대전화만 자릿수가 고정이라 나눌 수 있다.
      var d = digitsOf(value);
      parts = (kind === 'mobile' && d.length === 11)
        ? [d.slice(0, 3), d.slice(3, 7), d.slice(7)]
        : ['', '', ''];
    }

    cfg.parts.forEach(function (id, i) { $(id).value = parts[i] || ''; });
  }

  function validate() {
    var errors = [];

    // --- 주소 (검색해서 고른 값) -----------------------------------------
    // 우편번호와 주소는 이용자가 직접 적지 않는다. 검색 결과를 고르면 함께
    // 채워지므로, 「골랐는가」 하나만 보면 둘 다 검증된다.
    var p1 = digitsOf($('postal1').value);
    var p2 = digitsOf($('postal2').value);
    var addr = $('address').value.trim();

    if (p1.length !== 3 || p2.length !== 4 || !addr) {
      setError('addr-query', 'err-postal',
        '住所を検索してお選びください。お住まいの市区町村名、または郵便番号を入力し' +
        '「住所を検索」を押すと一覧が表示されます。');
      errors.push({ id: 'addr-query', label: 'ご住所' });
    } else {
      setError('addr-query', 'err-postal', '');
    }
    setError('address', 'err-address', '');

    // --- 번지 -----------------------------------------------------------
    if (!$('address-detail').value.trim()) {
      setError('address-detail', 'err-address-detail',
        '番地をご入力ください。数字のみで構いません。（例：1-2-3）');
      errors.push({ id: 'address-detail', label: '番地' });
    } else {
      setError('address-detail', 'err-address-detail', '');
    }

    // --- 전화번호 : 둘 중 최소 1개 (BR-05) -------------------------------
    var mobile = telDigits('mobile');
    var home = telDigits('home');

    setError('tel-mobile', 'err-tel-mobile', '');
    setError('tel-home', 'err-tel-home', '');

    if (!mobile && !home) {
      setError('tel-mobile', 'err-tel-mobile',
        '携帯電話と固定電話のいずれかをご入力ください。ご連絡がつかないとご予約を確定できません。');
      errors.push({ id: 'tel-mobile', label: '電話番号' });
    } else {
      // 세 칸의 합이 정해진 자릿수여야 한다. 한 칸이라도 덜 채우면 여기서 걸린다.
      ['mobile', 'home'].forEach(function (kind) {
        var cfg = TEL[kind];
        var digits = telDigits(kind);
        if (digits && digits.length !== cfg.total) {
          setError(cfg.parts[0], cfg.errorId, cfg.hint);
          errors.push({ id: cfg.parts[0], label: cfg.label });
        }
      });
    }

    // --- 이메일 (임의) ---------------------------------------------------
    var email = toHalfWidth($('email').value).trim();
    if (email && !isValidEmail(email)) {
      setError('email', 'err-email',
        'メールアドレスの形式をご確認ください。（例：example@example.jp）');
      errors.push({ id: 'email', label: 'メールアドレス' });
    } else {
      setError('email', 'err-email', '');
    }

    return errors;
  }

  function showErrorSummary(errors) {
    elErrSumList.textContent = '';

    if (!errors.length) {
      elErrSum.classList.remove('is-visible');
      return;
    }

    errors.forEach(function (e) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = '#' + e.id;
      a.textContent = e.label + '　— この項目へ移動';
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        var target = $(e.id);
        target.focus();
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      li.appendChild(a);
      elErrSumList.appendChild(li);
    });

    elErrSum.classList.add('is-visible');
    elErrSum.focus();
    elErrSum.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /* ======================================================================
     ④ 이메일
     ====================================================================== */

  /* 형식 검사.

     **HTML 표준(WHATWG)이 `<input type="email">` 에 쓰는 정규식 그대로**다.
     브라우저가 그 칸을 검사할 때 쓰는 식이므로, 화면과 브라우저가 서로 다른
     답을 내놓는 일이 없다. 이메일 문법(RFC 5322)은 정규식으로 정확히
     표현하기에 너무 복잡해서 직접 짜면 반드시 틀린다.

     최종 판정은 서버가 한다(backend/app/core/email_utils.py).
     여기서 막는 것은 「보내기 전에 알려 주기」 위해서다. */
  var EMAIL_RE = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;

  function isValidEmail(value) {
    // 점이 하나도 없는 도메인(`a@b`)은 실수로 보고 막는다.
    // 사내망 주소로는 확인 메일을 보낼 수 없다.
    return EMAIL_RE.test(value) && value.split('@')[1].indexOf('.') !== -1;
  }

  /* 흔한 오타 도메인. **막지 않고 되묻는다.**
     `gmail.co` 는 실제로 존재하는 도메인이라 막을 근거가 없다.
     다만 열에 아홉은 `gmail.com` を入力しようとしたものなので一度確認する。 */
  var TYPO_DOMAINS = {
    'gmail.co':      'gmail.com',
    'gmail.con':     'gmail.com',
    'gmail.cpm':     'gmail.com',
    'gmial.com':     'gmail.com',
    'gmai.com':      'gmail.com',
    'yahoo.co.j':    'yahoo.co.jp',
    'yaho.co.jp':    'yahoo.co.jp',
    'ezweb.ne.j':    'ezweb.ne.jp',
    'docomo.ne.j':   'docomo.ne.jp',
    'i.softbank.j':  'i.softbank.jp',
    'outlook.co':    'outlook.com',
    'hotmail.co':    'hotmail.com',
    'icloud.co':     'icloud.com'
  };

  function typoSuggestion(value) {
    var at = value.lastIndexOf('@');
    if (at < 0) return '';

    var domain = value.slice(at + 1).toLowerCase();
    var fixed = TYPO_DOMAINS[domain];
    return fixed ? value.slice(0, at + 1) + fixed : '';
  }

  /* ---------------------------------------------------------------------
     未入力警告 (BR-11)
     --------------------------------------------------------------------- */

  function updateMailWarn() {
    var email = toHalfWidth($('email').value).trim();

    if (email) {
      elMailWarn.classList.add('is-ok');

      // 誤入力と思われるドメインの場合は修正候補を提案する。
      // エラーにせず確認する — 実際に存在するドメインの可能性がある。
      var suggested = typoSuggestion(email);
      if (suggested) {
        elMailWarn.classList.remove('is-ok');
        elMailWarnTxt.textContent = '';

        elMailWarnTxt.appendChild(document.createTextNode('もしかして'));

        var fix = document.createElement('button');
        fix.type = 'button';
        fix.className = 'mail-fix';
        fix.textContent = suggested;
        fix.addEventListener('click', function () {
          $('email').value = suggested;
          setError('email', 'err-email', '');
          updateMailWarn();
          $('email').focus();
        });
        elMailWarnTxt.appendChild(fix);

        elMailWarnTxt.appendChild(document.createTextNode(
          'ではありませんか。そうであれば押して直してください。' +
          '違う場合はそのままで構いません。'
        ));
        return;
      }

      elMailWarnTxt.innerHTML =
        'このアドレスへ<strong>予約確認メール</strong>と<strong>受診前日のリマインドメール</strong>をお送りします。' +
        'お間違いがないか、もう一度ご確認ください。';
    } else {
      elMailWarn.classList.remove('is-ok');
      elMailWarnTxt.innerHTML =
        'メールアドレスのご入力がない場合、<strong>予約確認メール</strong>と' +
        '<strong>受診前日のリマインドメール</strong>をお受け取りいただけません。' +
        '予約番号は次の画面にのみ表示されますので、必ずお控えください。';
    }
  }

  /* ======================================================================
     ⑤ 入力補助
     ====================================================================== */

  // 電話番号は全角で入力されても半角に変換する
  /* 電話番号の3枠 — 数字のみを残し、可能な箇所では次の枠へ移動する。
     枠を分けたことで生じる「タブを3回押さなければならない」負担を軽減する。 */
  ['mobile', 'home'].forEach(function (kind) {
    var cfg = TEL[kind];

    cfg.parts.forEach(function (id, i) {
      var el = $(id);
      var max = cfg.max[i];

      // 携帯電話の先頭番号は <select> だ。選択すると次の欄へ移動する。
      if (i === 0 && cfg.firstIsSelect) {
        el.addEventListener('change', function () {
          setError(cfg.parts[0], cfg.errorId, '');
          if (this.value) $(cfg.parts[1]).focus();
        });
        return;
      }

      el.addEventListener('input', function () {
        this.value = digitsOf(this.value).slice(0, max);
        setError(cfg.parts[0], cfg.errorId, '');

        // 固定電話の最初の欄（市外局番）は2〜5桁と様々なため、自動で移動しない。
        // 移動してしまうと、「03」と入力した人が「0312」になってしまう。
        var fixedWidth = !(kind === 'home' && i === 0);
        if (fixedWidth && this.value.length === max && i < cfg.parts.length - 1) {
          $(cfg.parts[i + 1]).focus();
        }
      });

      // 空の欄で削除を押すと前の欄に戻る。
      // これがないと、誤入力した前の桁を直す方法がマウスしかなくなる。
      el.addEventListener('keydown', function (e) {
        if (e.key !== 'Backspace' || this.value || i === 0) return;
        var prev = $(cfg.parts[i - 1]);
        if (prev.tagName === 'SELECT') return;   // リストは削除するものがない
        e.preventDefault();
        prev.focus();
        prev.value = prev.value.slice(0, -1);
      });

      // 「090-1234-5678」をそのまま貼り付けると3つの欄に振り分ける。
      el.addEventListener('paste', function (e) {
        var text = (e.clipboardData || window.clipboardData).getData('text');
        var d = digitsOf(text);
        if (d.length !== cfg.total) return;   // 形式が異なる場合はデフォルト動作に任せる

        e.preventDefault();

        if (kind === 'mobile') {
          setTelValue('mobile', d.slice(0, 3) + '-' + d.slice(3, 7) + '-' + d.slice(7));
        } else {
          // 固定電話は先頭2つの区切りが特定できない。
          // 下4桁のみ確実なため、残りは前の欄に入れて利用者に分けてもらう。
          setTelValue('home', d.slice(0, d.length - 8) + '-' +
                              d.slice(d.length - 8, d.length - 4) + '-' +
                              d.slice(d.length - 4));
        }
        $(cfg.parts[2]).focus();
      });
    });
  });

  $('email').addEventListener('blur', function () {
    this.value = toHalfWidth(this.value).trim();
    updateMailWarn();
  });

  $('email').addEventListener('input', updateMailWarn);

  /* ======================================================================
     ⑥ 送信
     ====================================================================== */

  elForm.addEventListener('submit', function (ev) {
    ev.preventDefault();

    var errors = validate();
    showErrorSummary(errors);

    if (errors.length) {
      announce('未入力の項目が' + errors.length + '件あります。');
      return;
    }

    saveDraft();
    submitted = true;   // 正常な送信なので離脱警告は出さない
    window.location.href = 'confirm.html';
  });

  /* ----------------------------------------------------------------------
     入力中の内容をそのままセッションに保存する。

     以前はこの保存が**送信成功時に一度だけ**だった。そのため住所・電話・
     メールをすべて入力したあと「名前を見直そう」と前の画面に戻ると、
     一度も保存されていないため、戻ったときにすべて空欄になっていた。

     いまは入力が変わるたびに保存する。下の restore() が戻ったときに復元する。
     （検証は送信時のみなので、途中の値もそのまま保存する。）
     ---------------------------------------------------------------------- */
  function collectOptions() {
    return Array.prototype.map.call(
      document.querySelectorAll('input[name="exam_option"]:checked'),
      function (input) {
        return {
          id: Number(input.value),
          code: input.getAttribute('data-code'),
          name: input.getAttribute('data-name')
        };
      }
    );
  }

  function saveDraft() {
    var payload = {
      postal_code: digitsOf($('postal1').value) + '-' + digitsOf($('postal2').value),
      address: $('address').value.trim(),
      address_detail: $('address-detail').value.trim(),
      building: $('building').value.trim(),
      tel_mobile: telValue('mobile'),
      tel_home: telValue('home'),
      email: toHalfWidth($('email').value).trim(),
      options: collectOptions()
    };
    try {
      sessionStorage.setItem(APPLY_KEY, JSON.stringify(payload));
    } catch (e) { /* 保存に失敗しても現在の処理は継続する */ }
  }

  // 入力・選択が変わるたびに保存する。フォーム内のイベントは上位に伝播するため、
  // フォーム1つに登録すればすべての項目を拾える。
  elForm.addEventListener('input', saveDraft);
  elForm.addEventListener('change', saveDraft);

  // 再読み込み・タブを閉じるなど、セッションごと失われる離脱には一度確認する。
  var submitted = false;
  window.addEventListener('beforeunload', function (ev) {
    if (submitted) return;
    var hasInput = $('address').value.trim() || $('email').value.trim() ||
                   telDigits('mobile') || telDigits('home') ||
                   collectOptions().length;
    if (!hasInput) return;
    ev.preventDefault();
    ev.returnValue = '';
  });

  /* ======================================================================
     開始
     ====================================================================== */

  checkPrevSteps();

  // オプション一覧は非同期で描画される。復元する選択項目をあらかじめ読み込んでおく。
  (function readSavedOptions() {
    var saved = readSession(APPLY_KEY);
    savedOptionIds = ((saved && saved.options) || []).map(function (o) {
      return o.id;
    });
  })();

  loadOptions();
  updateMailWarn();

  // 前のステップで保存した入力値があれば復元する。
  // 「修正」で確認画面から戻ってきた際に、最初から再入力させてはいけない。
  var restored = (function restore() {
    var saved = readSession(APPLY_KEY);
    if (!saved) return null;

    var postal = String(saved.postal_code || '').split('-');
    $('postal1').value = postal[0] || '';
    $('postal2').value = postal[1] || '';
    $('address').value = saved.address || '';
    $('address-detail').value = saved.address_detail || '';
    $('building').value = saved.building || '';
    setTelValue('mobile', saved.tel_mobile);
    setTelValue('home', saved.tel_home);
    $('email').value = saved.email || '';
    updateMailWarn();
    return saved;
  })();

  /* ======================================================================
     U-16 「修正」で戻った場合 — 該当セクションへ誘導する
     form.html#sec-address / #sec-contact / #sec-option
     住所がそのまま開くと「押したのにどこを直せばいいのか」を再度探すことになる。
     ====================================================================== */

  (function focusSection() {
    var hash = (location.hash || '').replace('#', '');
    var SECTIONS = {
      'sec-address': 'addr-query',
      'sec-contact': 'tel-mobile',
      'sec-option': null      // オプションは非同期で描画されるためフォーカスを合わせない
    };

    if (!(hash in SECTIONS)) return;

    var section = $(hash);
    if (!section) return;

    // オプション一覧が描画される時間を待ってから移動する
    window.setTimeout(function () {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      section.classList.add('is-target');

      var firstField = SECTIONS[hash];
      if (firstField && $(firstField)) $(firstField).focus({ preventScroll: true });

      announce(section.querySelector('.formsec__head').textContent.trim() +
               'の項目へ移動しました。');

      // 強調は一時的に留める。表示し続けるとエラー表示のように見える。
      window.setTimeout(function () {
        section.classList.remove('is-target');
      }, 2400);
    }, hash === 'sec-option' ? 500 : 150);

    // 復元する値がないのに「修正」でアクセスしたなら、前の段階が途切れたということだ
    if (!restored) {
      showAlert('ご入力の内容を読み込めませんでした。もう一度ご入力ください。');
    }
  })();

})();
