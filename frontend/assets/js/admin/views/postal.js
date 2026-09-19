/* ==========================================================================
   postal.js — A-13 우편 접수 입력
   --------------------------------------------------------------------------
   하루 30건을 처리하는 화면이다. 설계 기준은 **속도** 하나다.

     · 마법사 금지. 1페이지 단일 폼으로 위에서 아래로 훑는다 (자체 피드백 M-1)
     · Tab 만으로 전 항목을 지나간다. 마우스로 옮겨 잡을 일이 없어야 한다
     · 「저장 후 연속 입력」 — 저장하면 폼이 비워지고 첫 칸에 커서가 간다
     · 희망 일시를 제1~제3까지 받는다. 제1희망이 만석이면 시스템이 다음으로
       내려가고, 무엇을 왜 건너뛰었는지 알려 준다 (자체 피드백 M-2)
     · 필수 항목이 비어 있으면 기본은 거절. 다만 「불비 상태로 임시 접수」를
       한 번 더 누르면 등록된다. 종이는 이미 도착해 있고, 되돌려 보낼 곳이 없다
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var filters = null;
  var sessionHistory = [];

  A.route('postal', function (view) {
    A.setTitle('郵送受付入力', '紙の申込書の内容をそのまま入力', [
      el('a.btn.btn--sm', { href: '#/reservations', text: '予約検索' })
    ]);

    var ready = filters
      ? Promise.resolve()
      : A.api.get('/reservations/filters').then(function (body) { filters = body.data; });

    ready
      .then(function () { draw(view); })
      .catch(function (error) { A.fail(view, error); });
  });

  function draw(view) {
    A.clear(view);

    var f = {};
    var wishes = [];        // 희망 슬롯 3개
    var optionBoxes = [];

    // 메인 2열 레이아웃 컨테이너 (좌측: 폼, 우측: 실시간 대조 패널)
    var container = el('div.postal-layout', {
      style: 'display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:20px;align-items:start'
    });

    var mainCol = el('div', { style: 'display:flex;flex-direction:column;gap:16px' });
    var sideCol = el('div', { style: 'display:flex;flex-direction:column;gap:16px;position:sticky;top:80px' });

    container.appendChild(mainCol);
    container.appendChild(sideCol);
    view.appendChild(container);

    /* ==================================================================
       ① 수검자 명부 대조 정보
       ================================================================== */

    f.last_name = A.input({ id: 'p-last', autocomplete: 'off' });
    f.first_name = A.input({ autocomplete: 'off' });
    // 히라가나·반각으로 쳐도 칸을 벗어날 때 전각 가타카나로 바꾼다.
    f.last_name_kana = A.attachKana(A.input({ placeholder: 'タナカ', autocomplete: 'off' }));
    f.first_name_kana = A.attachKana(A.input({ placeholder: 'タロウ', autocomplete: 'off' }));
    f.middle_name = A.input({ autocomplete: 'off' });
    f.middle_name_kana = A.attachKana(A.input({ autocomplete: 'off' }));
    f.gender = A.select({}, [
      { value: 'M', label: '男性' },
      { value: 'F', label: '女性' }
    ]);
    f.birth_date = A.input({ type: 'date', birth: true });

    f.insurer_no = A.input({ placeholder: '123', autocomplete: 'off' });
    f.insurance_symbol = A.input({ placeholder: 'abcd', autocomplete: 'off' });
    f.insurance_no = A.input({ placeholder: '12345', autocomplete: 'off' });

    function sectionCard(title, options) {
      options = options || {};
      var headNode = el('div.card__head', {
        style: 'background:#D9E7E4;border-bottom:1px solid #C5DDD8;padding:12px 18px;border-radius:8px 8px 0 0;'
      }, [
        el('div', { style: 'flex:1;min-width:0;' }, [
          el('h2.card__title', {
            style: 'color:#0A3A31;font-size:15px;font-weight:700;margin:0;',
            text: title
          }),
          options.desc ? el('p.card__desc', { style: 'margin:3px 0 0;color:#3A6158;font-size:12px;', text: options.desc }) : null
        ])
      ]);
      return A.card(headNode, {
        body: options.body
      });
    }

    mainCol.appendChild(sectionCard('① 受診者名簿照合情報', {
      desc: '「*」は確定に必要な項目です。未入力でも「不備のまま仮受付」で登録できます。',
      body: el('div.grid.grid--4', {}, [
        A.field('姓（漢字）', f.last_name, { required: true }),
        A.field('名（漢字）', f.first_name, { required: true }),
        A.field('姓（フリガナ）', f.last_name_kana, { hint: '全角カタカナ' }),
        A.field('名（フリガナ）', f.first_name_kana, { hint: '全角カタカナ' }),
        A.field('ミドルネーム', f.middle_name, { hint: '外国籍の方専用・該当者のみ' }),
        A.field('ミドルネーム（フリガナ）', f.middle_name_kana),
        A.field('性別', f.gender, { required: true }),
        A.field('生年月日', f.birth_date, { required: true, hint: '西暦で入力（8桁の数字でも可）' }),
        A.field('保険者番号', f.insurer_no, { required: true }),
        A.field('保険証記号', f.insurance_symbol, { required: true }),
        A.field('保険証番号', f.insurance_no, { required: true })
      ])
    }));

    /* ==================================================================
       ② 주소 · 연락처
       ================================================================== */

    f.postal_code = A.input({ placeholder: '101-0021' });
    f.address = A.input();
    f.address_detail = A.input({ placeholder: '1-2-3' });
    f.building = A.input();
    f.tel_mobile = A.input({ placeholder: '090-1234-5678' });
    f.tel_home = A.input({ placeholder: '03-1234-5678' });
    f.email = A.input({ type: 'email' });

    mainCol.appendChild(sectionCard('② 住所・連絡先', {
      desc: '電話番号は携帯電話・固定電話の少なくとも1つが必要です。',
      body: el('div.grid.grid--4', {}, [
        // 종이 신청서의 한자 주소를 손으로 치는 것이 이 화면에서 가장 오래
        // 걸리고 가장 자주 틀리는 일이다. 찾아서 넣게 한다. (core.js)
        A.field('住所検索', A.addressSearch(f.postal_code, f.address), { span: 'span-full' }),
        A.field('郵便番号', f.postal_code, { required: true }),
        A.field('住所', f.address, { span: 'span-3', required: true }),
        A.field('番地', f.address_detail, { span: 'span-2', required: true }),
        A.field('建物名・部屋番号', f.building, { span: 'span-2' }),
        // 둘 다 * 를 붙이면 둘 다 필요한 것으로 읽힌다. 한쪽에만 안내를 둔다.
        A.field('携帯電話', f.tel_mobile, { span: 'span-2', hint: '携帯電話・固定電話のどちらか1つは必須です。' }),
        A.field('固定電話', f.tel_home, { span: 'span-2' }),
        A.field('メールアドレス', f.email, {
          span: 'span-2',
          hint: 'ない場合は空欄にしてください。確認メールは登録がある場合のみ送信されます。'
        })
      ])
    }));

    /* ==================================================================
       ③ 희망 일시 (제1~제3)
       ================================================================== */

    var wishBox = el('div');
    for (var rank = 1; rank <= 3; rank++) {
      wishBox.appendChild(buildWish(rank, wishes, updateLiveVerification));
    }

    mainCol.appendChild(sectionCard('③ 希望受診日時', {
      desc: '第1希望が満員の場合は、第2・第3希望へ自動的に移行します。',
      body: [
        A.notice('info',
          '郵送であっても定員を超えて受け付けることはできません。' +
          '希望日時を複数入力しておくと、スタッフが再度電話する必要がなくなります。'),
        wishBox
      ]
    }));

    /* ==================================================================
       ④ 옵션 검사
       ================================================================== */

    var optionList = el('div.grid.grid--3');
    filters.exam_options.forEach(function (option) {
      if (!option.is_active) return;
      var box = A.checkbox(option.name, { value: String(option.id) });
      var chk = box.querySelector('input');
      chk.addEventListener('change', updateLiveVerification);
      optionBoxes.push({ id: option.id, name: option.name, input: chk });
      optionList.appendChild(box);
    });

    mainCol.appendChild(sectionCard('④ オプション検査', {
      desc: '年齢・性別の条件は強制しません。申込書に記載された通りにご入力ください。',
      body: optionList
    }));

    /* ==================================================================
       ⑤ 메모 · 등록
       ================================================================== */

    f.memo = A.textarea({ rows: 2, placeholder: '申込書で判読が難しかった箇所など' });

    var submitBtn = el('button.btn.btn--primary', {
      type: 'button', text: '登録して次の件を入力',
      onClick: function () { submit(false); }
    });

    var defectBtn = el('button.btn', {
      type: 'button', text: '登録情報不備のまま仮受付',
      title: '必須項目が未入力でも登録します。後から電話で確認して入力します。',
      onClick: function () { submit(true); }
    });

    var resultBox = el('div');

    mainCol.appendChild(sectionCard('⑤ メモ・特記事項', {
      body: [
        A.field('スタッフメモ', f.memo),
        el('div', { style: 'display:flex;gap:8px;margin-top:14px' }, [
          submitBtn, defectBtn,
          el('button.btn.btn--ghost', {
            type: 'button', text: '入力内容をクリア',
            onClick: function () {
              reset(f, wishes, optionBoxes);
              updateLiveVerification();
            }
          })
        ]),
        resultBox
      ]
    }));

    /* ==================================================================
       우측 사이드바: 실시간 대조 & 이력 카드
       ================================================================== */

    // 실시간 대조 카드 (Live Verification)
    var liveCardHead = el('div.card__head', {
      style: 'display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:linear-gradient(135deg, #0A3A31 0%, #104C40 100%);color:#ffffff;border-radius:8px 8px 0 0;'
    }, [
      el('div.card__title', {
        style: 'font-size:16px;font-weight:700;color:#ffffff;display:flex;align-items:center;gap:8px',
        text: 'リアルタイム照合'
      }),
      el('span.badge', {
        style: 'background:rgba(255,255,255,0.2);color:#ffffff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:12px;letter-spacing:0.5px;',
        text: 'Live Verification'
      })
    ]);

    var liveDatalist = el('div', {
      style: 'padding:22px 24px;display:flex;flex-direction:column;gap:14px;font-size:14px;background:#ffffff;'
    });

    var liveStatusBadge = el('span.badge', {
      style: 'background:#FEF3C7;color:#D97706;font-size:12px;font-weight:700;padding:4px 10px;border-radius:6px;',
      text: '作成中'
    });

    var liveFooter = el('div', {
      style: 'padding:14px 20px;background:var(--a-bg-sub);border-top:1px solid var(--a-line-2);display:flex;align-items:center;justify-content:space-between;font-size:13px;'
    }, [
      el('span', { style: 'color:var(--a-ink-sub);font-weight:600;', text: 'リアルタイム書類照合' }),
      liveStatusBadge
    ]);

    var liveCard = el('div.card', {
      style: 'border:2px solid #0F4B40;background:#fff;border-radius:10px;box-shadow:0 4px 16px rgba(10,58,49,0.12);overflow:hidden;'
    }, [liveCardHead, liveDatalist, liveFooter]);

    sideCol.appendChild(liveCard);

    /* ==================================================================
       실시간 대조 업데이트 함수
       ================================================================== */
    function updateLiveVerification() {
      A.clear(liveDatalist);

      var lastName = f.last_name.value.trim();
      var middleName = f.middle_name.value.trim();
      var firstName = f.first_name.value.trim();
      var nameHanjiParts = [lastName, middleName, firstName].filter(Boolean);
      var nameHanji = nameHanjiParts.length ? nameHanjiParts.join(' ') : '未入力';

      var lastNameKana = f.last_name_kana.value.trim();
      var middleNameKana = f.middle_name_kana.value.trim();
      var firstNameKana = f.first_name_kana.value.trim();
      var nameKanaParts = [lastNameKana, middleNameKana, firstNameKana].filter(Boolean);
      var nameKana = nameKanaParts.length ? nameKanaParts.join(' ') : '未入力';

      var birth = f.birth_date.value || '未選択';
      var genderText = f.gender.value === 'F' ? '女性' : (f.gender.value === 'M' ? '男性' : '未選択');
      var birthGender = birth + ' / ' + genderText;

      var mob = f.tel_mobile.value.trim();
      var home = f.tel_home.value.trim();
      var telParts = [mob, home].filter(Boolean);
      var tel = telParts.length ? telParts.join(' / ') : '未入力';

      var postalCode = f.postal_code.value.trim();
      var address = f.address.value.trim();
      var addressDetail = f.address_detail.value.trim();
      var building = f.building.value.trim();
      var addrParts = [address, addressDetail, building].filter(Boolean);
      var addrMain = addrParts.length ? addrParts.join(' ') : '';
      var addr = addrMain;
      if (postalCode && addrMain) {
        addr = '〒' + postalCode + ' ' + addrMain;
      } else if (postalCode && !addrMain) {
        addr = '〒' + postalCode;
      } else if (!addrMain) {
        addr = '未入力';
      }

      // --- 건강보험증 번호 결합 (보험자 번호 / 보험증 기호 / 보험증 번호) ---
      var cardParts = [
        f.insurer_no.value.trim(),
        f.insurance_symbol.value.trim(),
        f.insurance_no.value.trim()
      ].filter(Boolean);
      var cardStr = cardParts.length ? cardParts.join(' / ') : '未入力';

      // 희망 일시
      var wishTexts = wishes.map(function (w, idx) {
        if (w.label) return '第' + (idx + 1) + '希望: ' + w.label;
        return null;
      }).filter(Boolean);
      var wishStr = wishTexts.length ? wishTexts.join(', ') : '未選択';

      // 선택 옵션
      var selectedOptions = optionBoxes
        .filter(function (o) { return o.input.checked; })
        .map(function (o) { return o.name; });
      var optionStr = selectedOptions.length ? selectedOptions.join(', ') : 'なし';

      var rows = [
        ['お名前（漢字）', nameHanji, Boolean(lastName || firstName)],
        ['お名前（フリガナ）', nameKana, Boolean(lastNameKana || firstNameKana)],
        ['生年月日 / 性別', birthGender, Boolean(f.birth_date.value)],
        ['連絡先', tel, Boolean(mob || home)],
        ['住所', addr, Boolean(postalCode || addrMain)],
        ['健康保険証', cardStr, Boolean(cardParts.length)],
        ['希望日時', wishStr, Boolean(wishTexts.length)],
        ['選択オプション', optionStr, Boolean(selectedOptions.length)]
      ];

      var filledCount = rows.filter(function (r) { return r[2]; }).length;
      if (filledCount >= 6) {
        liveStatusBadge.textContent = '検証完了 (' + filledCount + '/8)';
        liveStatusBadge.style.background = '#ECFDF3';
        liveStatusBadge.style.color = '#027A48';
      } else {
        liveStatusBadge.textContent = '入力中 (' + filledCount + '/8)';
        liveStatusBadge.style.background = '#FEF3C7';
        liveStatusBadge.style.color = '#D97706';
      }

      rows.forEach(function (r, index) {
        var isMissing = r[1] === '未入力' || r[1] === '未選択';
        var isLast = index === rows.length - 1;

        var rowEl = el('div', {
          style: 'display:grid;grid-template-columns:120px 1fr;gap:12px;align-items:start;' +
                 (isLast ? '' : 'padding-bottom:12px;border-bottom:1px dashed var(--a-line-2);')
        }, [
          el('span', { style: 'color:var(--a-ink-sub);font-size:13px;font-weight:700;', text: r[0] }),
          el('span', {
            style: isMissing
              ? 'color:#9CA3AF;font-size:13px;font-weight:600;font-style:italic;'
              : 'color:#0A3A31;font-size:14px;font-weight:700;line-height:1.4;'
          }, [r[1]])
        ]);
        liveDatalist.appendChild(rowEl);
      });
    }

    // Attach input event listeners for real-time reactivity
    Object.keys(f).forEach(function (key) {
      if (f[key]) {
        f[key].addEventListener('input', updateLiveVerification);
        f[key].addEventListener('change', updateLiveVerification);
      }
    });

    updateLiveVerification();

    /* ==================================================================
       제출
       ================================================================== */

    function submit(allowDefect) {
      var payload = {
        last_name: f.last_name.value.trim(),
        first_name: f.first_name.value.trim(),
        last_name_kana: f.last_name_kana.value.trim(),
        first_name_kana: f.first_name_kana.value.trim(),
        middle_name: f.middle_name.value.trim(),
        middle_name_kana: f.middle_name_kana.value.trim(),
        gender: f.gender.value,
        birth_date: f.birth_date.value,
        insurer_no: f.insurer_no.value.trim(),
        insurance_symbol: f.insurance_symbol.value.trim(),
        insurance_no: f.insurance_no.value.trim(),
        postal_code: f.postal_code.value.trim(),
        address: f.address.value.trim(),
        address_detail: f.address_detail.value.trim(),
        building: f.building.value.trim(),
        tel_mobile: f.tel_mobile.value.trim(),
        tel_home: f.tel_home.value.trim(),
        email: f.email.value.trim(),
        slot_ids: wishes.map(function (w) { return w.slotId; }).filter(Boolean),
        option_ids: optionBoxes.filter(function (o) { return o.input.checked; })
                               .map(function (o) { return o.id; }),
        allow_defect: allowDefect,
        memo: f.memo.value
      };

      // 서버가 다시 검증하지만, 왕복 없이 잡을 수 있는 것은 여기서 잡는다
      var missing = [];
      if (!payload.last_name) missing.push({ label: '姓（漢字）', nodes: [f.last_name] });
      if (!payload.first_name) missing.push({ label: '名（漢字）', nodes: [f.first_name] });
      if (!payload.birth_date) missing.push({ label: '生年月日', nodes: [f.birth_date] });
      if (!payload.slot_ids.length) {
        missing.push({ label: '希望受診日時（第1希望）', nodes: wishes[0] ? wishes[0].inputs : [] });
      }

      showMissing(missing);
      if (missing.length) return;

      submitBtn.disabled = defectBtn.disabled = true;

      A.api.post('/reservations/postal', payload)
        .then(function (body) {
          var d = body.data;
          A.toast(d.message, d.has_defect ? 'warn' : 'ok');
          showResult(resultBox, d);
          // sessionHistory.unshift(d);
          // renderSessionHistory();
          reset(f, wishes, optionBoxes);
          showMissing([]);
          updateLiveVerification();
          if (A.refreshAttentionBadge) A.refreshAttentionBadge();
        })
        .catch(function (error) {
          // 같은 문장을 화면 안 띠로도 띄우면 두 번 읽게 된다. 알림 한 곳에만 둔다.
          A.toast(error.message, 'danger');
        })
        .then(function () {
          submitBtn.disabled = defectBtn.disabled = false;
        });
    }

    f.last_name.focus();
  }

  /* ======================================================================
     입력이 빠졌을 때

     예전에는 「◯◯ を入力してください。」 한 줄을 주의(노랑)로 띄웠다. 빠진
     항목이 여럿일 때 무엇을 고쳐야 하는지 알기 어려웠다. 알림은 다른 오류와
     같은 자리(오른쪽 아래)에 붉게 띄우고, 빠진 항목을 모두 적는다.
     문구는 서버가 불비를 돌려줄 때와 같은 모양으로 맞춘다.
     ====================================================================== */

  function showMissing(missing) {
    if (!missing.length) return;

    A.toast('次の項目が未入力です — ' + missing.map(function (item) {
      return item.label;
    }).join(', ') + '. ご入力のうえ、もう一度「登録」を押してください。', 'danger');

    var first = (missing[0].nodes || [])[0];
    if (first) {
      first.scrollIntoView({ block: 'center' });
      first.focus();
    }
  }

  /* ======================================================================
     희망 일시 한 줄
     ====================================================================== */

  function buildWish(rank, wishes, onChange) {
    var state = { slotId: null, label: null };
    wishes.push(state);

    var hospital = A.select({}, [{ value: '', label: '会場選択' }].concat(
      filters.hospitals
        .filter(function (h) { return h.is_visible; })
        .map(function (h) { return { value: String(h.id), label: h.name }; })
    ));

    var dateInput = A.select({ style: 'min-width:150px', disabled: true }, [{ value: '', label: '日付選択' }]);
    var slotSelect = A.select({ disabled: true }, [{ value: '', label: '時間選択' }]);

    function updateDateOptions() {
      var prevDate = dateInput.value;
      A.clear(dateInput);
      dateInput.appendChild(el('option', { value: '', text: '日付選択' }));
      
      var selectedHospId = hospital.value ? Number(hospital.value) : null;
      var selectedHosp = null;
      for (var i = 0; i < filters.hospitals.length; i++) {
        if (filters.hospitals[i].id === selectedHospId) {
          selectedHosp = filters.hospitals[i];
          break;
        }
      }

      if (selectedHosp && selectedHosp.schedules && selectedHosp.schedules.length > 0) {
        selectedHosp.schedules.forEach(function (s) {
          var opt = el('option', {
            value: s.event_date,
            text: A.fmt.date(s.event_date) + (s.is_past ? ' （終了）' : '')
          });
          if (s.event_date === prevDate) {
            opt.selected = true;
          }
          dateInput.appendChild(opt);
        });
        dateInput.disabled = false;
      } else {
        dateInput.disabled = true;
      }
      loadSlots();
    }

    function loadSlots() {
      state.slotId = null;
      state.label = null;
      A.clear(slotSelect);
      slotSelect.appendChild(el('option', { value: '', text: '時間選択' }));
      if (onChange) onChange();

      if (!hospital.value || !dateInput.value) {
        slotSelect.disabled = true;
        return;
      }

      slotSelect.disabled = true;
      slotSelect.appendChild(el('option', { value: '', text: '読み込み中…' }));

      A.api.get('/reservations/slots' + A.query({
        hospital_id: hospital.value, date: dateInput.value
      })).then(function (body) {
        A.clear(slotSelect);
        slotSelect.appendChild(el('option', { value: '', text: '時間選択' }));

        if (!body.data.length) {
          slotSelect.appendChild(el('option', {
            value: '', text: 'この日付には受付時間がありません', disabled: true
          }));
          return;
        }

        body.data.forEach(function (slot) {
          slotSelect.appendChild(el('option', {
            value: String(slot.slot_id),
            disabled: !slot.selectable,
            text: slot.time_label + ' — ' +
                  (slot.selectable
                    ? '残り ' + slot.remaining + '名 / 定員 ' + slot.capacity + '名'
                    : slot.reason)
          }));
        });

        slotSelect.disabled = false;
      }).catch(function (error) {
        A.clear(slotSelect);
        slotSelect.appendChild(el('option', { value: '', text: error.message }));
      });
    }

    hospital.addEventListener('change', updateDateOptions);
    hospital.addEventListener('input', updateDateOptions);
    dateInput.addEventListener('change', loadSlots);
    dateInput.addEventListener('input', loadSlots);
    slotSelect.addEventListener('change', function () {
      state.slotId = slotSelect.value ? Number(slotSelect.value) : null;
      var selectedOpt = slotSelect.options[slotSelect.selectedIndex];
      var hospOpt = hospital.options[hospital.selectedIndex];
      state.label = (slotSelect.value && selectedOpt)
        ? ((hospOpt ? hospOpt.text + ' ' : '') + dateInput.value + ' ' + selectedOpt.text.split(' — ')[0])
        : null;
      if (onChange) onChange();
    });

    state.reset = function () {
      hospital.value = '';
      A.clear(dateInput).appendChild(el('option', { value: '', text: '日付選択' }));
      dateInput.disabled = true;
      A.clear(slotSelect).appendChild(el('option', { value: '', text: '時間選択' }));
      slotSelect.disabled = true;
      state.slotId = null;
      state.label = null;
    };

    // 저장할 때 「제1희망이 비었다」를 이 줄에서 바로 보여 주기 위해 칸을 기억한다.
    state.inputs = [hospital, dateInput, slotSelect];

    return el('div.wish', {}, [
      el('span.wish__rank', {}, [
        '第' + rank + '希望',
        rank === 1 ? el('span.req', { text: '*' }) : null
      ]),
      el('div.wish__body', {
        style: 'display:grid;grid-template-columns:minmax(160px,1fr) 160px minmax(200px,1.4fr);gap:8px'
      }, [hospital, dateInput, slotSelect])
    ]);
  }

  /* ======================================================================
     등록 결과
     ====================================================================== */

  function showResult(box, d) {
    A.clear(box);

    var lines = [
      el('div.resno-box', { style: 'margin:14px 0 0' }, [
        el('div', {}, [
          el('div.resno-box__no', { text: d.reservation_no }),
          el('div.resno-box__meta', {
            text: d.hospital_name + ' · ' + A.fmt.date(d.slot_date) + ' ' + d.time_label +
                  ' (第' + d.used_choice + '希望)'
          })
        ]),
        A.statusBadge(d.status, d.status_label),
        el('div.resno-box__right', {}, [
          el('a.btn.btn--sm', { href: '#/reservation?id=' + d.id, text: '詳細' })
        ])
      ])
    ];

    if (d.skipped && d.skipped.length) {
      lines.push(A.notice('warn',
        'スキップされた希望 — ' + d.skipped.join(' / ')));
    }

    if (d.has_defect) {
      lines.push(A.notice('danger',
        '仮受付です。未入力の項目(' + d.defect_note + ')をご本人に確認のうえ、' +
        '予約詳細から「確定」に変更してください。'));
    }

    lines.forEach(function (line) { box.appendChild(line); });
  }

  /* ======================================================================
     초기화 — 저장 후 연속 입력
     ====================================================================== */

  function reset(f, wishes, optionBoxes) {
    Object.keys(f).forEach(function (key) {
      if (f[key].tagName === 'SELECT') f[key].selectedIndex = 0;
      else f[key].value = '';
    });
    wishes.forEach(function (w) { if (w.reset) w.reset(); });
    optionBoxes.forEach(function (o) { o.input.checked = false; });
    f.last_name.focus();
  }

})();

