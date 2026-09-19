/* ==========================================================================
   reservation-detail.js — A-11 예약 상세 · 수정 (의료 레코드형 레이아웃)
   --------------------------------------------------------------------------
   · 2열 조밀 그리드 의료 레코드 UI
   · [予約情報] & [患者情報] 좌우 대조 뷰
   · [予約票をダウンロード] 오렌지 인쇄/다운로드 버튼
   · [予約完了 ∨] 상태 변경 컨트롤
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  A.route('reservation', function (view, params) {
    var id = Number(params.id);
    if (!id) { A.go('reservations', {}); return; }

    A.setTitle('予約詳細', '', [
      el('a.btn.btn--sm', { href: '#/reservations', text: '一覧へ' })
    ]);

    A.api.get('/reservations/' + id)
      .then(function (body) { draw(view, body.data); })
      .catch(function (error) { A.fail(view, error); });
  });

  function reload(view, id) {
    A.api.get('/reservations/' + id)
      .then(function (body) { draw(view, body.data); })
      .catch(function (error) { A.fail(view, error); });
  }

  function calculateAge(birthDateStr) {
    if (!birthDateStr) return '-';
    var parts = birthDateStr.split('-');
    if (parts.length < 3) return '-';
    var birthYear = parseInt(parts[0], 10);
    var birthMonth = parseInt(parts[1], 10) - 1;
    var birthDay = parseInt(parts[2], 10);
    var today = new Date();
    var age = today.getFullYear() - birthYear;
    var m = today.getMonth() - birthMonth;
    if (m < 0 || (m === 0 && today.getDate() < birthDay)) {
      age--;
    }
    return age > 0 ? age : 0;
  }

  /* ======================================================================
     레코드 뷰 그리기 (Draw)
     ====================================================================== */

  function draw(view, r) {
    A.clear(view);
    A.setTitle('予約詳細', r.reservation_no + ' · ' + r.full_name, [
      el('a.btn.btn--sm', { href: '#/reservations', text: '一覧へ' })
    ]);

    var container = el('div.record-container');

    // 1. 브레드크럼 (Breadcrumb)
    container.appendChild(el('div.record-breadcrumb', {}, [
      el('a', { href: '#/reservations', text: '予約受付一覧' }),
      el('span', { text: ' > ' }),
      el('span', { text: '予約受付詳細 (' + r.reservation_no + ')' })
    ]));

    // 2. 상단 헤더 바 (Top Bar with Action Buttons)
    container.appendChild(buildRecordTopBar(view, r));

    // 3. 경고 및 상태 알림
    if (r.status === 'CANCELLED') {
      container.appendChild(A.notice('danger',
        (r.status_label || 'キャンセル') + 'された予約です。' + A.fmt.datetime(r.cancelled_at) + ' / 理由 — ' +
        A.fmt.or(r.cancel_reason, '記録なし')));
    }
    if (r.has_defect) {
      container.appendChild(A.notice('warn',
        '登録情報不備のご案内: ' + r.defect_note +
        '. 本人確認の上、修正してステータスを「予約確定」に変更してください。'));
    }

    // 4. 메인 2열 그리드 (予約情報 + 患者情報)
    var mainGrid = el('div.record-grid');
    mainGrid.appendChild(buildReservationInfoCard(view, r));
    mainGrid.appendChild(buildPatientInfoCard(view, r));
    container.appendChild(mainGrid);

    // 5. 하단 2열 그리드 (정보 수정 폼 + 연락/발송 이력)
    var subGrid = el('div.record-grid');
    subGrid.appendChild(buildEditableFormCard(view, r));
    subGrid.appendChild(buildHistoryCard(view, r));
    container.appendChild(subGrid);

    view.appendChild(container);
  }

  /* --- 1. 상단 바 (Top Bar) ----------------------------------------------- */

  function buildRecordTopBar(view, r) {
    var titleGroup = el('div.record-top-bar__title', {}, [
      el('h1.record-top-bar__h1', { text: '予約受付詳細' }),
      A.statusBadge(r.status, r.status_label, r.is_holiday),
      el('span.badge.badge--' + (r.channel === 'POSTAL' ? 'info' : 'muted'),
        { text: r.channel_label + ' 受付' })
    ]);

    var actionsGroup = el('div.record-top-bar__actions', {}, [
      // 중요 핵심 기능: 전용 딥 에메랄드 강조 버튼 (Primary Action)
      el('button.record-btn-primary', {
        type: 'button',
        text: '予約票をダウンロード',
        onClick: function () { printReservationReceipt(r); }
      }),
      // 통일된 은은한 보조 액션 버튼들 (Unified Neutral Action Buttons)
      (r.tel_mobile || r.tel_home) ? el('a.record-btn-neutral', {
        href: 'tel:' + (r.tel_mobile || r.tel_home), text: '電話をかける'
      }) : null
    ].filter(Boolean));

    // 검진일 변경 / 확인 메일 재발송 / 취소 버튼
    if (r.status !== 'CANCELLED') {
      actionsGroup.appendChild(el('button.record-btn-neutral', {
        type: 'button',
        text: '受診日変更',
        onClick: function () { openSlotChange(view, r); }
      }));
    }

    // 취소된 예약에는 두지 않는다. 「予約が確定しました」가 다시 나가면
    // 받은 사람은 예약이 살아 있다고 믿고 당일에 온다.
    if (r.email && r.status !== 'CANCELLED') {
      actionsGroup.appendChild(el('button.record-btn-neutral', {
        type: 'button',
        text: '確認メール再送信',
        onClick: function () { resend(view, r); }
      }));
    }

    // 확정·취소는 오른쪽 끝에 나란히 붙인다.
    var decideGroup = el('div.record-top-bar__decide');

    if (r.status === 'PENDING') {
      decideGroup.appendChild(el('button.record-btn-primary', {
        type: 'button',
        text: '予約確定',
        onClick: function () { confirmReservation(view, r); }
      }));
    }

    if (r.status !== 'CANCELLED') {
      decideGroup.appendChild(el('button.record-btn-danger', {
        type: 'button',
        text: '予約キャンセル',
        onClick: function () { openCancel(view, r); }
      }));
    }

    if (decideGroup.children.length) actionsGroup.appendChild(decideGroup);

    return el('div.record-top-bar', {}, [titleGroup, actionsGroup]);
  }

  /* --- 2. 予約情報 (예약 정보 카드) --------------------------------------- */

  function buildReservationInfoCard(view, r) {
    var optionsText = (r.options || []).map(function (o) { return o.name; }).join(', ') || '選択なし';

    var table = el('table.record-table.record-table--res-info', {}, [
      el('tbody', {}, [
        el('tr', {}, [
          el('th', { text: '予約番号' }),
          el('td.record-table__mono.record-table__highlight', {}, [
            el('span', { text: r.reservation_no, style: 'font-weight:700;margin-right:8px;' }),
            el('button.btn.btn--xs', {
              type: 'button',
              text: 'コピー',
              onClick: function () {
                navigator.clipboard.writeText(r.reservation_no).then(function () {
                  A.toast('予約番号をコピーしました。', 'ok');
                });
              }
            })
          ])
        ]),
        el('tr', {}, [
          el('th', { text: '受付日時' }),
          el('td', { text: A.fmt.datetime(r.created_at) + ' (' + r.channel_label + ')' })
        ]),
        el('tr', {}, [
          el('th', { text: '受診日時' }),
          el('td', {}, [
            el('strong', { text: r.slot_date + ' ' + r.time_label }),
            r.status !== 'CANCELLED' ? el('button.btn.btn--xs', {
              type: 'button',
              text: '変更',
              style: 'margin-left:8px',
              onClick: function () { openSlotChange(view, r); }
            }) : null
          ])
        ]),
        el('tr', {}, [
          el('th', { text: '健診区分' }),
          el('td', { text: '健康診断 （人間ドック）' })
        ]),
        el('tr', {}, [
          el('th', { text: '受診会場' }),
          el('td', { text: r.hospital_name })
        ]),
        el('tr', {}, [
          el('th', { text: 'オプション検査' }),
          el('td', {}, [
            el('span', { text: optionsText }),
            r.status !== 'CANCELLED' ? el('button.btn.btn--xs', {
              type: 'button',
              text: '編集',
              style: 'margin-left:8px',
              onClick: function () {
                var chosen = (r.options || []).map(function (o) { return o.id; });
                openOptionEditor(view, r, chosen);
              }
            }) : null
          ])
        ])
      ])
    ]);

    return el('div.record-card', {}, [
      el('div.record-card__header', {}, [
        el('div.record-card__title', {}, [
          el('span', { text: '予約情報' })
        ])
      ]),
      table
    ]);
  }

  /* --- 3. 患者情報 (수검자/환자 정보 카드) --------------------------------- */

  function buildPatientInfoCard(view, r) {
    var age = calculateAge(r.birth_date);
    var fullAddress = (r.postal_code ? '〒' + r.postal_code + ' ' : '') +
      (r.address || '') + ' ' + (r.address_detail || '') + ' ' + (r.building || '');
    var insurance = (r.insurer_no || '-') + ' / ' + (r.insurance_symbol || '-') + ' / ' + (r.insurance_no || '-');

    var table = el('table.record-table', {}, [
      el('tbody', {}, [
        el('tr', {}, [
          el('th', { text: '受診者氏名（漢字）' }),
          el('td.record-table__highlight', { text: r.full_name + (r.middle_name ? ' ' + r.middle_name : '') })
        ]),
        el('tr', {}, [
          el('th', { text: '受診者氏名（カナ）' }),
          el('td', { text: r.full_name_kana })
        ]),
        el('tr', {}, [
          el('th', { text: '生年月日 / 年齢' }),
          el('td', { text: r.birth_date + ' (満 ' + age + '歳)' })
        ]),
        el('tr', {}, [
          el('th', { text: '性別' }),
          el('td', { text: r.gender_label })
        ]),
        el('tr', {}, [
          el('th', { text: '電話番号' }),
          el('td.record-table__mono', {
            text: r.tel_primary + (r.tel_home ? ' (固定電話: ' + r.tel_home + ')' : '')
          })
        ]),
        el('tr', {}, [
          el('th', { text: 'メールアドレス' }),
          el('td', { text: r.email || '未登録' })
        ]),
        el('tr', {}, [
          el('th', { text: '住所' }),
          el('td', { text: fullAddress.trim() || '未登録' })
        ]),
        el('tr', {}, [
          el('th', { text: '保険証番号' }),
          el('td.record-table__mono', { text: insurance })
        ])
      ])
    ]);

    return el('div.record-card', {}, [
      el('div.record-card__header', {}, [
        el('div.record-card__title', {}, [
          el('span', { text: '受診者情報' })
        ])
      ]),
      table
    ]);
  }

  /* --- 4. 정보 수정 폼 카드 ----------------------------------------------- */

  function buildEditableFormCard(view, r) {
    var f = {};

    f.last_name = A.input({ value: r.last_name });
    f.first_name = A.input({ value: r.first_name });
    f.last_name_kana = A.attachKana(A.input({ value: r.last_name_kana }));
    f.first_name_kana = A.attachKana(A.input({ value: r.first_name_kana }));
    f.middle_name = A.input({ value: r.middle_name });
    f.middle_name_kana = A.attachKana(A.input({ value: r.middle_name_kana }));
    f.gender = A.select({}, [
      { value: 'M', label: '男性', selected: r.gender === 'M' },
      { value: 'F', label: '女性', selected: r.gender === 'F' }
    ]);
    f.birth_date = A.input({ type: 'date', birth: true, value: r.birth_date });
    f.insurer_no = A.input({ value: r.insurer_no });
    f.insurance_symbol = A.input({ value: r.insurance_symbol });
    f.insurance_no = A.input({ value: r.insurance_no });

    f.postal_code = A.input({ value: r.postal_code, placeholder: '101-0021' });
    f.address = A.input({ value: r.address });
    f.address_detail = A.input({ value: r.address_detail });
    f.building = A.input({ value: r.building });
    f.tel_mobile = A.input({ value: r.tel_mobile, placeholder: '090-1234-5678' });
    f.tel_home = A.input({ value: r.tel_home, placeholder: '03-1234-5678' });
    f.email = A.input({ value: r.email, type: 'email' });
    f.memo = A.textarea({ value: r.memo, rows: 3, placeholder: '利用者には表示されないスタッフ用メモです' });

    /* この欄でキャンセルには**できない**。取消は理由の記録が要るので
       専用のボタンから行う。そのため選択肢は確定と仮予約の2つだけだった。

       ところがキャンセル済みの予約を開くと、どちらにも当てはまらず
       ブラウザが先頭の「確定（CONFIRMED）」を表示してしまい、
       画面上は確定に見えるのに直せない、という状態になっていた。
       キャンセル済みのときだけ、その旨の選択肢を出して選んでおく。
       （このとき入力欄と保存ボタンはまとめて使用不可にしている） */
    var statusOptions = [
      { value: 'CONFIRMED', label: '予約確定（CONFIRMED）', selected: r.status === 'CONFIRMED' },
      { value: 'PENDING', label: '仮受付（PENDING - 要確認）', selected: r.status === 'PENDING' }
    ];
    if (r.status === 'CANCELLED') {
      statusOptions.unshift({
        value: 'CANCELLED', label: (r.status_label || 'キャンセル') + '（CANCELLED）', selected: true
      });
    }
    f.status = A.select({}, statusOptions);
    f.defect_note = A.input({ value: r.defect_note, placeholder: '未入力項目の理由' });
    var defectBox = A.checkbox('登録情報不備（不備あり）', { checked: r.has_defect });

    var disabled = r.status === 'CANCELLED';
    if (disabled) {
      Object.keys(f).forEach(function (key) { f[key].disabled = true; });
      defectBox.querySelector('input').disabled = true;
    }

    /* 전화번호 입력 칸 옆의 「걸기」 버튼.
       상세 화면에서 스태프가 하는 일은 결국 이 번호로 전화를 거는 것이다.
       번호를 눈으로 읽어 다이얼을 누르게 하면 그 자리에서 오타가 난다. */
    function telRow(input) {
      return el('div.tel-row', {}, input);
    }

    var hasAnyTel = Boolean((f.tel_mobile && f.tel_mobile.value && f.tel_mobile.value.trim()) ||
      (f.tel_home && f.tel_home.value && f.tel_home.value.trim()));

    function makeField(label, inputNode, key, opts) {
      opts = opts || {};
      var isDefect = false;
      if (r.has_defect && key) {
        var val = (f[key] && f[key].value) ? String(f[key].value).trim() : '';
        var note = (r.defect_note || '').toLowerCase();
        var keyLabel = label.toLowerCase();
        var isNoteMatch = note.indexOf(keyLabel) >= 0 || note.indexOf(key) >= 0;

        var isEssentialEmpty = false;
        if (key === 'tel_mobile' || key === 'tel_home') {
          isEssentialEmpty = !hasAnyTel;
        } else if (['last_name', 'first_name', 'last_name_kana', 'first_name_kana', 'birth_date', 'gender', 'insurer_no', 'insurance_symbol', 'insurance_no', 'postal_code', 'address', 'address_detail'].indexOf(key) !== -1) {
          isEssentialEmpty = !val;
        }

        if (isNoteMatch || isEssentialEmpty) {
          isDefect = true;
        }
      }

      if (isDefect && inputNode) {
        var targetInput = (inputNode.tagName === 'INPUT' || inputNode.tagName === 'SELECT')
          ? inputNode
          : (inputNode.querySelector ? inputNode.querySelector('input, select') : inputNode);
        if (targetInput) {
          targetInput.style.backgroundColor = '#FEF9C3';
          targetInput.style.borderColor = '#F59E0B';
          targetInput.style.borderWidth = '2px';
        }
      }

      var labelText = label;
      if (isDefect) {
        labelText = el('span', {}, [
          label,
          el('span', {
            style: 'background:#FEF3C7;color:#D97706;border:1px solid #F59E0B;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700;margin-left:6px;',
            text: '登録情報不備'
          })
        ]);
      }

      return A.field(labelText, inputNode, opts);
    }

    var saveBtn = el('button.btn.btn--primary', {
      type: 'button',
      text: '変更内容を保存',
      disabled: disabled,
      onClick: function () { save(view, r, f, defectBox, saveBtn); }
    });

    var dirtyMark = el('span.form-bar__dirty.is-hidden', {
      text: '保存されていない変更があります'
    });

    var bar = el('div.form-bar', { style: 'margin-top:24px;padding-top:16px;border-top:1px solid var(--a-line);' }, [dirtyMark, el('div.form-bar__right', {}, saveBtn)]);

    if (!disabled) {
      var watch = Object.keys(f).map(function (k) { return f[k]; })
        .concat([defectBox.querySelector('input')]);

      watch.forEach(function (node) {
        if (!node) return;
        ['input', 'change'].forEach(function (evt) {
          node.addEventListener(evt, function () {
            dirtyMark.classList.remove('is-hidden');
          });
        });
      });
    }

    var bodyNode = el('div', { style: 'padding:16px' }, [
      A.notice('warn',
        '受診者の本人確認情報です。誤字・脱字の訂正目的にのみご使用ください — ' +
        '実際に別の方の予約である場合は、この予約をキャンセルして新規に受付してください。'),
      /* 1. 성함 및 건강보험증 그룹 */
      el('div.grid.grid--4', { style: 'margin-top:12px' }, [
        makeField('姓（漢字）', f.last_name, 'last_name', { required: true }),
        makeField('名（漢字）', f.first_name, 'first_name', { required: true }),
        makeField('姓（フリガナ）', f.last_name_kana, 'last_name_kana'),
        makeField('名（フリガナ）', f.first_name_kana, 'first_name_kana'),
        makeField('ミドルネーム', f.middle_name, 'middle_name'),
        makeField('ミドルネーム（フリガナ）', f.middle_name_kana, 'middle_name_kana'),
        makeField('性別', f.gender, 'gender'),
        makeField('生年月日', f.birth_date, 'birth_date'),
        makeField('保険者番号', f.insurer_no, 'insurer_no'),
        makeField('保険証記号', f.insurance_symbol, 'insurance_symbol'),
        makeField('保険証番号', f.insurance_no, 'insurance_no')
      ]),

      /* 구분선 1 (보험증 <-> 주소 섹션 사이) */
      el('hr', { style: 'margin:16px 0;border:0;border-top:1px solid #CBD5E1;' }),

      /* 2. 주소 그룹 */
      el('div.grid.grid--4', {}, [
        disabled
          ? null
          : A.field('住所検索', A.addressSearch(f.postal_code, f.address),
            { span: 'span-full' }),
        makeField('郵便番号', f.postal_code, 'postal_code'),
        makeField('住所', f.address, 'address', { span: 'span-3' }),
        makeField('番地', f.address_detail, 'address_detail', { span: 'span-2' }),
        makeField('建物名・部屋番号', f.building, 'building', { span: 'span-2' })
      ]),

      /* 구분선 2 (주소 <-> 연락처/예약상태 섹션 사이) */
      el('hr', { style: 'margin:16px 0;border:0;border-top:1px solid #CBD5E1;' }),

      /* 3. 연락처 및 예약 상태 그룹 */
      el('div.grid.grid--4', {}, [
        makeField('携帯電話', telRow(f.tel_mobile, r.tel_mobile), 'tel_mobile', { span: 'span-2' }),
        makeField('固定電話', telRow(f.tel_home, r.tel_home), 'tel_home', { span: 'span-2' }),
        makeField('メールアドレス', f.email, 'email', {
          span: 'span-2',
          hint: r.email ? '' : '未登録 — 確認・リマインドメールを送信できません。'
        }),
        makeField('予約ステータス', f.status, 'status', { span: 'span-2' })
      ]),

      /* 4. 불비 및 스태프 메모 그룹 */
      el('div.grid.grid--4', { style: 'margin-top:12px' }, [
        el('div.field', { style: 'justify-content:flex-end' }, defectBox),
        A.field('登録情報不備の理由', f.defect_note, { span: 'span-3' }),
        A.field('スタッフメモ', f.memo, { span: 'span-full' })
      ]),
      bar
    ]);

    return el('div.record-card', {}, [
      el('div.record-card__header', {}, [
        el('div.record-card__title', {}, [
          el('span', { text: '受診者情報の修正' })
        ])
      ]),
      bodyNode
    ]);
  }

  /* --- 5. 히스토리 & 연락 이력 카드 --------------------------------------- */

  function buildHistoryCard(view, r) {
    var contactsBody = r.contacts.length
      ? el('ul.timeline', {}, r.contacts.map(function (c) {
        return el('li.timeline__item' +
          (c.result === 'CONNECTED' ? '.timeline__item--ok' : '.timeline__item--no'), {}, [
          el('div.timeline__head', {}, [
            el('strong', { text: c.method_label + ' · ' + c.result_label }),
            el('span.timeline__when', { text: A.fmt.datetime(c.contacted_at) }),
            el('span.timeline__when', { text: c.admin_name })
          ]),
          c.memo ? el('p.timeline__memo', { text: c.memo }) : null
        ]);
      }))
      : el('p.field__hint', { text: '連絡履歴はありません。' });

    var contactCard = el('div', { style: 'padding:16px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px' }, [
        el('strong', { text: '連絡履歴（累計 ' + r.contact_count + '回）' }),
        el('button.btn.btn--sm', {
          type: 'button',
          text: '連絡記録追加',
          onClick: function () { openContact(view, r); }
        })
      ]),
      contactsBody,
      el('hr', { style: 'margin:16px 0;border:0;border-top:1px solid var(--a-line);' }),
      el('strong', { text: '確認メール送信履歴' }),
      A.table({
        columns: [
          { label: '種別', render: function (m) { return m.template_label; } },
          {
            label: '結果',
            render: function (m) {
              var tone = { SUCCESS: 'ok', FAILED: 'danger', SKIPPED: 'muted' }[m.status];
              return el('span.badge.badge--' + tone, { text: m.status_label });
            }
          },
          { label: '日時', dim: true, render: function (m) { return A.fmt.datetime(m.sent_at); } }
        ],
        rows: r.mails,
        empty: { title: '', desc: '送信履歴はありません。' }
      })
    ]);

    return el('div.record-card', {}, [
      el('div.record-card__header', {}, [
        el('div.record-card__title', {}, [
          el('span', { text: '連絡・メール送信履歴' })
        ])
      ]),
      contactCard
    ]);
  }



  /* --- 6. 예약표 인쇄/PDF 미리보기 기능 ---------------------------------- */

  function printReservationReceipt(r) {
    var printWin = window.open('', '_blank', 'width=850,height=950');
    if (!printWin) {
      A.toast('ポップアップブロックを解除してください。', 'warn');
      return;
    }
    var optionsText = (r.options || []).map(function (o) { return o.name; }).join(', ') || 'なし';
    var age = calculateAge(r.birth_date);
    var addressStr = (r.postal_code ? '〒' + r.postal_code + ' ' : '') +
      (r.address || '') + ' ' + (r.address_detail || '') + ' ' + (r.building || '');

    var html = [
      '<!DOCTYPE html>',
      '<html><head><meta charset="UTF-8"><title>受診予約票 - ' + r.reservation_no + '</title>',
      '<style>',
      'body { font-family: "Meiryo", "メイリオ", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif; padding: 40px; color: #152220; background: #fff; }',
      '.receipt-header { border-bottom: 3px solid #0B6E5B; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; }',
      '.org-name { font-size: 14px; color: #4A5A57; }',
      '.title { font-size: 26px; font-weight: 700; color: #0B6E5B; margin-top: 4px; }',
      '.resno { font-size: 20px; font-weight: 700; font-family: "Meiryo", "メイリオ", sans-serif; }',
      'h3 { font-size: 16px; border-left: 4px solid #0B6E5B; padding-left: 8px; margin: 24px 0 12px; }',
      'table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }',
      'th, td { border: 1px solid #C8D6D2; padding: 10px 14px; font-size: 14px; text-align: left; }',
      'th { background: #F2F7F5; width: 25%; font-weight: 600; color: #354542; }',
      '.footer { margin-top: 50px; padding-top: 20px; border-top: 1px solid #D8E3E0; text-align: center; font-size: 13px; color: #6B7A77; }',
      '@media print { body { padding: 20px; } }',
      '</style></head><body>',
      '<div class="receipt-header">',
      '  <div>',
      '    <div class="org-name">医療法人 Sample Group</div>',
      '    <div class="title">受診予約票</div>',
      '  </div>',
      '  <div class="resno">予約番号: ' + r.reservation_no + '</div>',
      '</div>',
      '<h3>■ 予約情報</h3>',
      '<table>',
      '  <tr><th>健診機関</th><td><strong>' + r.hospital_name + '</strong></td></tr>',
      '  <tr><th>受診日時</th><td><strong>' + r.slot_date + ' ' + r.time_label + '</strong></td></tr>',
      '  <tr><th>健診区分</th><td>健康診断 （人間ドック）</td></tr>',
      '  <tr><th>選択オプション</th><td>' + optionsText + '</td></tr>',
      '  <tr><th>受付日時</th><td>' + A.fmt.datetime(r.created_at) + ' (' + r.channel_label + ')</td></tr>',
      '</table>',
      '<h3>■ 受診者情報</h3>',
      '<table>',
      '  <tr><th>受診者氏名</th><td><strong>' + r.full_name + '</strong> (' + r.full_name_kana + ')</td></tr>',
      '  <tr><th>生年月日 / 年齢</th><td>' + r.birth_date + ' (満 ' + age + '歳) / ' + r.gender_label + '</td></tr>',
      '  <tr><th>連絡先</th><td>' + r.tel_primary + (r.tel_home ? ' / ' + r.tel_home : '') + '</td></tr>',
      '  <tr><th>メールアドレス</th><td>' + (r.email || '未登録') + '</td></tr>',
      '  <tr><th>住所</th><td>' + addressStr + '</td></tr>',
      '  <tr><th>健康保険証番号</th><td>' + r.insurer_no + ' - ' + r.insurance_symbol + ' - ' + r.insurance_no + '</td></tr>',
      '</table>',
      '<div class="footer">本予約票を受診日当日にご持参の上、受付窓口にご提出ください。<br>医療法人 Sample Group 健診センター・お問い合わせ: 03-1234-5678</div>',
      '<script>window.onload = function() { window.print(); };</script>',
      '</body></html>'
    ].join('');

    printWin.document.write(html);
    printWin.document.close();
  }

  /* --- 7. 저장 및 기타 조작 함수들 ----------------------------------------- */

  function save(view, r, f, defectBox, button) {
    var dirtyCard = button.closest('.record-card');
    var dirty = dirtyCard ? dirtyCard.querySelector('.form-bar__dirty') : null;
    if (dirty) dirty.classList.add('is-hidden');

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
      status: f.status.value,
      has_defect: defectBox.querySelector('input').checked,
      defect_note: f.defect_note.value.trim(),
      memo: f.memo.value
    };

    button.disabled = true;
    button.textContent = '保存中…';

    A.api.put('/reservations/' + r.id, payload)
      .then(function (body) {
        A.toast(body.message || '保存しました。', 'ok');
        draw(view, body.data);
        if (A.refreshAttentionBadge) A.refreshAttentionBadge();
      })
      .catch(function (error) {
        A.toast(error.message, 'danger');
        button.disabled = false;
        button.textContent = '変更を保存';
      });
  }

  function openOptionEditor(view, r, chosen) {
    A.api.get('/reservations/filters').then(function (body) {
      var boxes = [];
      var list = el('div', { style: 'display:grid;gap:8px' });

      body.data.exam_options.forEach(function (option) {
        var box = A.checkbox(
          option.name + (option.is_active ? '' : ' （無効）'),
          { checked: chosen.indexOf(option.id) !== -1, value: String(option.id) }
        );
        boxes.push({ id: option.id, input: box.querySelector('input') });
        list.appendChild(box);
      });

      A.modal({
        title: 'オプション検査変更',
        body: [
          A.notice('info', '申込書に記載されたオプション項目を選択してください。'),
          list
        ],
        actions: [
          { label: 'キャンセル' },
          {
            label: '保存',
            tone: 'primary',
            onClick: function () {
              var ids = boxes.filter(function (b) { return b.input.checked; })
                .map(function (b) { return b.id; });

              return A.api.put('/reservations/' + r.id, {
                postal_code: r.postal_code,
                address: r.address,
                address_detail: r.address_detail,
                building: r.building,
                tel_mobile: r.tel_mobile,
                tel_home: r.tel_home,
                email: r.email,
                memo: r.memo,
                defect_note: r.defect_note,
                option_ids: ids
              }).then(function (res) {
                A.toast('オプション検査を保存しました。', 'ok');
                draw(view, res.data);
              }).catch(function (error) {
                A.toast(error.message, 'danger');
                throw error;
              });
            }
          }
        ]
      });
    }).catch(function (error) { A.toast(error.message, 'danger'); });
  }

  function openContact(view, r) {
    var method = A.select({}, [
      { value: 'TEL', label: '電話' },
      { value: 'MAIL', label: 'メール' }
    ]);
    var result = A.select({}, [
      { value: 'NO_ANSWER', label: '応答なし' },
      { value: 'CONNECTED', label: '連絡完了' }
    ]);
    var memo = A.textarea({
      rows: 4,
      placeholder: '例：1回目の電話は不在、14時頃に再度電話予定'
    });

    A.modal({
      title: '連絡記録追加',
      body: [
        el('div.grid.grid--2', {}, [
          A.field('連絡手段', method),
          A.field('結果', result)
        ]),
        A.field('メモ', memo)
      ],
      actions: [
        { label: 'キャンセル' },
        {
          label: '記録を保存',
          tone: 'primary',
          onClick: function () {
            return A.api.post('/reservations/' + r.id + '/contacts', {
              method: method.value,
              result: result.value,
              memo: memo.value.trim()
            }).then(function () {
              A.toast('連絡記録を保存しました。', 'ok');
              reload(view, r.id);
            }).catch(function (error) {
              A.toast(error.message, 'danger');
              throw error;
            });
          }
        }
      ]
    });
  }

  function openCancel(view, r) {
    // 취소는 두 가지로 나눠 **열(cancel_type)에 기록**한다. 통계도 이 값으로 센다.
    // 사유 글에서 말을 찾아 가르지 않는다 — 「当日は本人が来られず…」처럼
    // 事前 취소의 사유에도 「当日」이 들어갈 수 있기 때문이다.
    var cancelType = A.select({}, [
      { value: 'ADVANCE', label: '事前キャンセル（患者都合・電話受付）' },
      { value: 'SAME_DAY', label: '当日キャンセル（連絡不通・応答なし）' }
    ]);
    var reason = A.textarea({
      rows: 3,
      placeholder: '例：患者本人からの電話連絡によるキャンセル'
    });

    cancelType.addEventListener('change', function () {
      if (cancelType.value === 'SAME_DAY') {
        reason.placeholder = '例：3回連絡後も応答なし、連絡不通のため当日キャンセル';
      } else {
        reason.placeholder = '例：患者本人からの電話連絡によるキャンセル';
      }
    });

    A.modal({
      title: '予約キャンセル',
      size: 'slim',
      body: [
        el('p', {
          style: 'margin:0 0 10px;line-height:1.7',
          text: r.reservation_no + ' · ' + r.full_name + ' 様 / ' +
            A.fmt.date(r.slot_date) + ' ' + r.time_label
        }),
        A.notice('warn', 'キャンセルすると、その枠はすぐに再度受付可能になります。'),
        A.field('キャンセル区分', cancelType, {
          required: true,
          hint: '統計では2種類を分けて集計します。'
        }),
        A.field('キャンセル理由', reason, { hint: '操作ログに記録されます。' })
      ],
      actions: [
        { label: '戻る' },
        {
          label: 'キャンセル処理',
          tone: 'danger',
          onClick: function () {
            // 사유를 적지 않았을 때만 종류에 맞는 문장을 넣어 둔다.
            // 앞에 【当日キャンセル】을 덧붙이지는 않는다 — 종류는 열에 남고,
            // 목록·통계도 그 열을 보므로 사유까지 꾸밀 필요가 없다.
            var detail = reason.value.trim();
            var finalReason = detail || (cancelType.value === 'SAME_DAY'
              ? '連絡不通のため当日キャンセル'
              : '患者電話受付による事前キャンセル');

            return A.api.post('/reservations/' + r.id + '/cancel', {
              reason: finalReason,
              cancel_type: cancelType.value
            }).then(function (body) {
              A.toast(body.message, 'ok');
              draw(view, body.data);
              if (A.refreshAttentionBadge) A.refreshAttentionBadge();
            }).catch(function (error) {
              A.toast(error.message, 'danger');
              throw error;
            });
          }
        }
      ]
    });
  }

  function confirmReservation(view, r) {
    var payload = {
      postal_code: r.postal_code,
      address: r.address,
      address_detail: r.address_detail,
      building: r.building,
      tel_mobile: r.tel_mobile,
      tel_home: r.tel_home,
      email: r.email,
      memo: r.memo,
      defect_note: r.defect_note,
      status: 'CONFIRMED'
    };

    function doConfirm() {
      A.api.put('/reservations/' + r.id, payload)
        .then(function (body) {
          A.toast(body.message || '予約を確定しました。', 'ok');
          draw(view, body.data);
          if (A.refreshAttentionBadge) A.refreshAttentionBadge();
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    }

    if (!r.has_defect) { doConfirm(); return; }

    A.confirm({
      title: '登録情報不備が残っています',
      message: r.defect_note || '未入力の項目があります。',
      detail: 'このまま確定すると登録情報不備の表示も解除されます。本人確認が完了しているかご確認ください。',
      okLabel: '確認のうえ予約確定',
      tone: 'primary'
    }).then(function (ok) {
      if (!ok) return;
      payload.has_defect = false;
      doConfirm();
    });
  }

  function resend(view, r) {
    // 누르는 즉시 이용자에게 메일이 나간다. 다른 대외 조작(일시 변경·취소)과
    // 같이 한 번 묻는다.
    A.confirm({
      title: '確認メールを再送信しますか？',
      message: r.email + ' 宛てに予約完了案内メールを送信します。',
      okLabel: '送信する',
      tone: 'primary'
    }).then(function (ok) {
      if (!ok) return;
      A.api.post('/reservations/' + r.id + '/resend-mail?template_key=RESERVE_COMPLETE')
        .then(function (body) {
          // 요청이 처리돼도 실제로 나가지 않았을 수 있다(발송 설정 없음 등).
          A.toast(body.message, body.delivered ? 'ok' : 'warn');
          reload(view, r.id);
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    });
  }

  /* ==========================================================================
     검진 일시 변경
     --------------------------------------------------------------------------
     회장을 바꾸면 **날짜가 따라와야 한다.**

     회장마다 여는 날이 다르다. 예전에는 회장만 바뀌고 날짜는 그대로여서,
     고르는 즉시 「이 날짜에는 접수 시간이 없습니다」가 떴다. 그 회장이 언제
     여는지는 이 화면 어디에도 없으므로, 스태프는 달력을 하루씩 눌러 가며
     찾아야 했다.

     그래서 회장을 바꾸면 **고를 수 있는 가장 이른 개최일**로 날짜를 옮긴다.
     지금 날짜가 새 회장에서도 열리는 날이면 그대로 둔다 — 그것도 「고를 수
     있는 날」이고, 회장별로 같은 날을 견주어 보는 것이 이 화면의 흔한 쓰임이다.
     ========================================================================== */

  /** 접수가 열려 있는 날 → 지나지 않은 날 → 아무 날. 각각 이른 순. */
  function pickEventDate(schedules, keep) {
    var dates = (schedules || []).slice().sort(function (a, b) {
      return a.event_date < b.event_date ? -1 : (a.event_date > b.event_date ? 1 : 0);
    });
    if (!dates.length) return '';

    var open = dates.filter(function (s) { return s.is_booking_open; });
    var ahead = dates.filter(function (s) { return !s.is_past; });
    var pool = open.length ? open : (ahead.length ? ahead : dates);

    // 지금 날짜가 그 회장에서도 고를 수 있는 날이면 옮기지 않는다.
    var stay = pool.some(function (s) { return s.event_date === keep; });
    return stay ? keep : pool[0].event_date;
  }

  function openSlotChange(view, r) {
    var hospitalSelect = A.select({}, []);
    /* 검진일은 **고르는 것**이지 적는 것이 아니다.
       -------------------------------------------------------------------
       예전에는 빈 <input type="date"> 였다. 회장은 며칠만 여는 순회 검진
       회장이라 담당자가 「이 회장이 언제 열더라」를 외우고 있어야 했고,
       모르면 정원 관리 화면을 따로 열어 찾아야 했다. 날짜를 잘못 짚으면
       「이 날짜에는 접수 시간이 없습니다」만 뜨고, 그래서 **언제 여는지는
       끝내 알려 주지 않았다.**

       회장별 개최일은 `/reservations/filters` 가 이미 함께 준다. 그것을
       그대로 목록으로 낸다. 지난 회차·마감된 회차도 감추지 않고 이유를
       붙인다 — 시간대 목록(`available_slots`)이 이미 그렇게 하고 있다.
       목록에서 사라지면 「신청서에 적힌 날이 없다」며 헤매기 때문이다. */
    var dateSelect = A.select({}, []);
    var slotBox = el('div.slot-pick');
    var picked = { slot_id: null };
    var schedulesByHospital = {};

    var dialog = A.modal({
      title: '受診日時の変更',
      body: [
        A.notice('info', '新しい枠を確保してから元の枠を返却します。'),
        el('div.grid.grid--2', {}, [
          A.field('会場', hospitalSelect),
          A.field('受診日', dateSelect)
        ]),
        el('p.field__label', { text: '時間帯', style: 'margin-top:14px' }),
        slotBox
      ],
      actions: [
        { label: 'キャンセル' },
        {
          label: 'この時間に変更',
          tone: 'primary',
          onClick: function () {
            if (!picked.slot_id) {
              A.toast('時間帯を選択してください。', 'warn');
              return Promise.reject(new Error('no slot'));
            }
            /* 옮기기 **전에** 안내 메일을 보낼지 묻는다.
               -------------------------------------------------------------
               담당자는 전화로 새 날짜를 먼저 합의하고 그 결과를 화면에
               반영한다. 그래서 메일은 「갑자기 바뀌었습니다」가 아니라
               **합의한 내용을 남기는 확인용**이고, 자동으로 나가면 안 된다.
               통화 중에 「메일도 보내 드릴까요」를 묻고 답을 받는 자리다.

               이메일이 없으면 물을 것도 없다 — 전화가 유일한 길이다. */
            function saveWith(notify) {
              return A.api.put('/reservations/' + r.id, {
                postal_code: r.postal_code,
                address: r.address,
                address_detail: r.address_detail,
                building: r.building,
                tel_mobile: r.tel_mobile,
                tel_home: r.tel_home,
                email: r.email,
                memo: r.memo,
                defect_note: r.defect_note,
                slot_id: picked.slot_id,
                notify_change: !!notify
              }).then(function (body) {
                A.toast(body.message, 'ok');
                draw(view, body.data);
              }).catch(function (error) {
                A.toast(error.message, 'danger');
                throw error;
              });
            }

            if (!r.email) return saveWith(false);

            /* × · Escape 는 **그만두기**다.
               「보내지 않음」과 다르다 — 그쪽은 옮기기는 하고 메일만 안
               보내는 것이고, 닫는 것은 옮기는 것 자체를 그만두려는 뜻이다.
               둘을 같게 두면 창을 닫았을 뿐인데 예약이 옮겨진다. */
            return A.confirm({
              title: '変更案内メールを送信しますか？',
              message: '受診日時を変更します。変更後の日時を記載した案内メールを '
                + r.email + ' 宛てに送信できます。',
              detail: 'お電話でお伝え済みの場合は、確認用として残ります。'
                + '送信しなくても日時は変更されます。'
                + 'ウィンドウを閉じると日時は変更されません。',
              okLabel: '送信する',
              cancelLabel: '送信しない',
              closeValue: null,
              tone: 'primary'
            }).then(function (answer) {
              if (answer === null) {
                A.toast('キャンセルしました。受診日時はそのままです。', 'warn');
                return Promise.reject(new Error('dismissed'));
              }
              return saveWith(answer);
            });
          }
        }
      ]
    });

    A.api.get('/reservations/filters').then(function (body) {
      body.data.hospitals.forEach(function (h) {
        schedulesByHospital[String(h.id)] = h.schedules || [];
        hospitalSelect.appendChild(el('option', {
          value: String(h.id), text: h.name, selected: h.id === r.hospital_id
        }));
      });
      fillDates(r.slot_date);
      loadSlots();
    });

    /** 지금 고른 회장의 개최일을 날짜 목록에 채운다. */
    function fillDates(preferred) {
      A.clear(dateSelect);

      var list = schedulesByHospital[hospitalSelect.value] || [];
      if (!list.length) {
        dateSelect.appendChild(el('option', {
          value: '', text: '開催予定がありません'
        }));
        dateSelect.disabled = true;
        return;
      }
      dateSelect.disabled = false;

      // 지금 예약된 날이 이 회장의 날이면 그것을, 아니면 고를 수 있는
      // 첫 회차를 편다. 회장을 바꾸자마자 못 고르는 날이 잡혀 있으면
      // 담당자가 목록을 한 번 더 눌러야 한다.
      var openDates = list.filter(function (sc) { return canPick(sc); });
      var fallback = openDates.length ? openDates[0].event_date : list[0].event_date;
      var target = preferred && list.some(function (sc) {
        return sc.event_date === preferred;
      }) ? preferred : fallback;

      list.forEach(function (sc) {
        dateSelect.appendChild(el('option', {
          value: sc.event_date,
          text: sc.event_date + ' (' + sc.weekday + ')' + noteOf(sc),
          selected: sc.event_date === target
        }));
      });
    }

    function canPick(sc) {
      return !sc.is_past && sc.is_booking_open !== false;
    }

    /* 못 고르는 날도 목록에 남기되 **왜** 못 고르는지 적는다.
       지금 예약이 잡혀 있는 날이 이미 지났을 수 있으므로 지우지 않는다. */
    function noteOf(sc) {
      if (sc.is_past) return ' — 開催日経過';
      if (sc.is_booking_open === false) return ' — 受付締切';
      return '';
    }

    function loadSlots() {
      A.clear(slotBox);
      picked.slot_id = null;

      // 개최일이 없는 회장이면 부를 날짜가 없다. 빈 date 로 부르면 422 다.
      if (!dateSelect.value) {
        slotBox.appendChild(el('p.field__hint', {
          text: 'この会場は今後の開催予定がありません。「定員管理」で開催日を登録してください。'
        }));
        return;
      }

      slotBox.appendChild(el('p.field__hint', { text: '読み込み中…' }));

      A.api.get('/reservations/slots' + A.query({
        hospital_id: hospitalSelect.value,
        date: dateSelect.value
      })).then(function (body) {
        A.clear(slotBox);

        if (!body.data.length) {
          slotBox.appendChild(el('p.field__hint', {
            text: 'この日付には受付時間がありません。'
          }));
          return;
        }

        body.data.forEach(function (slot) {
          var button = el('button.slot-pick__btn', {
            type: 'button',
            disabled: !slot.selectable,
            'aria-pressed': 'false',
            title: slot.reason || '',
            onClick: function () {
              Array.prototype.forEach.call(
                slotBox.querySelectorAll('.slot-pick__btn'),
                function (b) { b.setAttribute('aria-pressed', 'false'); }
              );
              button.setAttribute('aria-pressed', 'true');
              picked.slot_id = slot.slot_id;
            }
          }, [
            el('span', { text: slot.time_label }),
            el('span.rest', {
              text: slot.selectable
                ? '残り ' + slot.remaining + ' / ' + slot.capacity
                : slot.reason
            })
          ]);
          slotBox.appendChild(button);
        });
      }).catch(function (error) {
        A.clear(slotBox).appendChild(el('p.field__error', { text: error.message }));
      });
    }

    // 회장이 바뀌면 그 회장의 개최일로 목록을 다시 짠 뒤 시간대를 부른다.
    hospitalSelect.addEventListener('change', function () {
      fillDates(null);
      loadSlots();
    });
    dateSelect.addEventListener('change', loadSlots);
    return dialog;
  }

})();
