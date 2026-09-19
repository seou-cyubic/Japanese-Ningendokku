/* ==========================================================================
   mail-templates.js — A-40 메일 문구 편집 · 발송 이력
   --------------------------------------------------------------------------
   L3(시스템 관리자) 전용.

   「확인 메일 문구를 바꾸려면 매번 개발자를 불러야 한다」를 없애기 위한
   화면이다 (자체 피드백 M-11). 치환 변수 목록을 옆에 붙여 두고,
   눌러서 본문에 끼워 넣을 수 있게 한다.

   **저장하기 전에 미리 볼 수 있어야 한다.** 저장한 뒤에야 결과를 알 수 있으면
   잘못된 문구가 이미 이용자에게 나간 뒤다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  A.route('mail-templates', function (view, params) {
    A.setTitle('メール文面', '予約完了メール / リマインドメール / 送信履歴管理');

    A.api.get('/mail-templates')
      .then(function (body) { draw(view, body.data, params); })
      .catch(function (error) { A.fail(view, error); });
  });

  function draw(view, data, params) {
    A.clear(view);

    var active = params.key || data.templates[0].template_key;

    // --- 템플릿 선택 탭 ---------------------------------------------------
    var tabs = el('div.chips', { style: 'margin-bottom:14px' });
    data.templates.forEach(function (template) {
      tabs.appendChild(el('button.chip', {
        type: 'button',
        text: template.label,
        'aria-pressed': template.template_key === active ? 'true' : 'false',
        onClick: function () { A.go('mail-templates', { key: template.template_key }); }
      }));
    });
    tabs.appendChild(el('button.chip', {
      type: 'button',
      text: '送信履歴',
      'aria-pressed': active === 'logs' ? 'true' : 'false',
      onClick: function () { A.go('mail-templates', { key: 'logs' }); }
    }));
    view.appendChild(tabs);

    if (active === 'logs') { drawLogs(view, 1, params.status || ''); return; }

    var template = data.templates.filter(function (t) {
      return t.template_key === active;
    })[0] || data.templates[0];

    drawEditor(view, template, data.variables);
  }

  /* ======================================================================
     편집
     ====================================================================== */

  function drawEditor(view, template, variables) {
    var subject = A.input({ value: template.subject });
    var body = A.textarea({
      value: template.body,
      rows: 22,
      'class': 'textarea textarea--code'
    });

    var previewBox = el('div.preview', {}, [
      el('p.field__hint', { text: '「プレビュー」を押すと、実際の予約1件の値で確認できます。' })
    ]);

    var saveBtn = el('button.btn.btn--sm.btn--primary', {
      type: 'button', text: '保存',
      onClick: function () {
        saveBtn.disabled = true;
        A.api.put('/mail-templates/' + template.template_key, {
          subject: subject.value, body: body.value
        }).then(function (res) {
          A.toast(res.message, 'ok');
          template.updated_by = res.data.updated_by;
          template.updated_at = res.data.updated_at;
        }).catch(function (error) {
          A.toast(error.message, 'danger');
        }).then(function () { saveBtn.disabled = false; });
      }
    });

    var previewBtn = el('button.btn.btn--sm', {
      type: 'button', text: 'プレビュー',
      onClick: function () {
        A.clear(previewBox).appendChild(A.loading('置換中…'));
        A.api.post('/mail-templates/' + template.template_key + '/preview', {
          subject: subject.value, body: body.value
        }).then(function (res) {
          A.clear(previewBox);
          previewBox.appendChild(el('p.preview__subject', { text: res.data.subject }));
          previewBox.appendChild(el('pre.preview__body', { text: res.data.body }));
          if (res.data.sample_reservation_no) {
            previewBox.appendChild(el('p.field__hint', {
              style: 'margin-top:10px',
              text: '予約番号 ' + res.data.sample_reservation_no + ' の値で置換しました。'
            }));
          }

          /* 「변경 전」은 예약 한 건에서 끌어낼 수 없어 미리 보기에서만
             지어낸 값을 넣는다. 그렇다고 적어 두지 않으면 담당자가
             이 날짜를 진짜로 읽는다. 「변경 후」는 그 예약의 실제 일시다. */
          if (template.template_key === 'SCHEDULE_CHANGED') {
            previewBox.appendChild(el('p.field__hint', {
              style: 'margin-top:4px',
              text: '「変更後」がこの予約の実際の日時で、' +
                    '「変更前」はプレビュー用のダミー値です（実際の日 −7日）。' +
                    '送信時は日時を変更する直前の値が入ります。'
            }));
          }
        }).catch(function (error) {
          A.clear(previewBox).appendChild(el('p.field__error', { text: error.message }));
        });
      }
    });

    var cols = el('div.mail-cols');

    cols.appendChild(el('div', {}, [
      A.card(template.label, {
        desc: template.timing +
              ' ・ 最終更新 ' + A.fmt.datetime(template.updated_at) +
              (template.updated_by ? ' (' + template.updated_by + ')' : ''),
        tools: [previewBtn, saveBtn],
        body: [
          A.notice('warn',
            'この文面は全利用者に送信される対外文書です。' +
            '予約変更・キャンセルの手順案内を本文から削除しないでください。 ' +
            'Web上でご自身でキャンセルできない旨をメールで案内しないと、' +
            'そのままお問い合わせ電話につながります。'),
          A.field('件名', subject),
          el('div', { style: 'margin-top:12px' },
            A.field('本文', body, { hint: '{{変数}} は送信時に実際の値に置換されます。' }))
        ]
      }),
      A.card('プレビュー', { body: previewBox })
    ]));

    // --- 치환 변수 --------------------------------------------------------
    var list = el('ul.varlist');
    variables.forEach(function (variable) {
      list.appendChild(el('li.varlist__item', {}, [
        el('button.varlist__name', {
          type: 'button',
          text: variable.name,
          title: '本文のカーソル位置に挿入',
          onClick: function () { insertAtCursor(body, variable.name); }
        }),
        el('span.varlist__desc', { text: variable.desc })
      ]));
    });

    cols.appendChild(A.card('置換変数', {
      desc: 'クリックすると本文に挿入できます。',
      body: [
        list,
        el('p.field__hint', {
          style: 'margin-top:10px',
          text: '一覧にない名前を使用すると置換されず、{{そのまま}} 送信されます。' +
                '自動で削除しないのは、入力ミスに気づけるようにするためです。'
        })
      ]
    }));

    view.appendChild(cols);
  }

  /** 커서 자리에 변수명을 끼워 넣는다. 맨 뒤에 붙이면 다시 옮겨야 한다. */
  function insertAtCursor(textarea, text) {
    var start = textarea.selectionStart;
    var end = textarea.selectionEnd;
    var value = textarea.value;

    textarea.value = value.slice(0, start) + text + value.slice(end);
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = start + text.length;
  }

  /* ======================================================================
     발송 이력
     ====================================================================== */

  function drawLogs(view, page, initialStatus) {
    page = page || 1;

    var slot = el('div');
    slot.appendChild(A.loading());
    view.appendChild(slot);

    var status = A.select({}, [
      { value: '', label: 'すべての結果' },
      { value: 'SUCCESS', label: '送信完了' },
      { value: 'FAILED', label: '送信失敗' },
      { value: 'SKIPPED', label: '送信なし' }
    ]);
    // 대시보드의 「메일 발송 실패」 카드에서 넘어온 경우, 그 필터를 그대로
    // 걸어 둔다. 실패한 건을 보러 온 사람에게 전체 목록을 주면 다시 걸러야 한다.
    if (initialStatus) status.value = initialStatus;

    var keyword = A.input({ placeholder: '予約番号またはメールアドレス' });
    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); fetchLogs(1); }
    });

    function fetchLogs(nextPage) {
      A.clear(slot).appendChild(A.loading());

      A.api.get('/mail-templates/logs' + A.query({
        status: status.value, keyword: keyword.value.trim(),
        page: nextPage, size: 30
      })).then(function (body) {
        A.clear(slot);

        var card = A.card('送信履歴', {
          desc: A.fmt.number(body.data.total) + '件',
          flush: true,
          body: A.table({
            columns: [
              { label: '予約番号', mono: true, render: function (m) {
                  if (!m.reservation_no) return '';
                  return el('button', {
                    type: 'button',
                    title: '予約番号をコピー',
                    style: 'background:none;border:none;padding:0;font:inherit;color:inherit;cursor:pointer;text-decoration:underline;text-underline-offset:2px;display:inline-flex;align-items:center;gap:4px',
                    onClick: function () {
                      navigator.clipboard.writeText(m.reservation_no).then(function () {
                        A.toast('予約番号 ' + m.reservation_no + ' をコピーしました。', 'ok');
                      }).catch(function () {
                        A.toast('コピーに失敗しました。', 'danger');
                      });
                    }
                  }, [
                    m.reservation_no,
                    A.icon('copy', { size: 14, style: 'opacity:0.5;flex-shrink:0' })
                  ]);
                }
              },
              { label: '種別', render: function (m) { return m.template_label; } },
              { label: '宛先', render: function (m) { return m.to_email; } },
              { label: '件名', wrap: true, dim: true, render: function (m) { return m.subject; } },
              {
                label: '結果', width: '96px',
                render: function (m) {
                  var tone = { SUCCESS: 'ok', FAILED: 'danger', SKIPPED: 'muted' }[m.status];
                  return el('span.badge.badge--' + tone, { text: m.status_label });
                }
              },
              { label: '備考', wrap: true, dim: true,
                render: function (m) { return m.error_message; } },
              { label: '日時', dim: true,
                render: function (m) { return A.fmt.datetime(m.sent_at); } },
              {
                label: '', width: '80px',
                render: function (m) {
                  if (!m.reservation_id) return '';
                  return el('a.btn.btn--sm', {
                    href: '#/reservation?id=' + m.reservation_id, text: '予約'
                  });
                }
              }
            ],
            rows: body.data.items,
            empty: { title: '送信履歴がありません', desc: '' }
          })
        });

        var foot = A.pager(body.data.page, body.data.size, body.data.total, fetchLogs);
        if (foot) card.appendChild(foot);

        slot.appendChild(card);
      }).catch(function (error) {
        A.clear(slot);
        A.fail(slot, error);
      });
    }

    view.insertBefore(A.card('検索条件', {
      body: el('div.filters', {}, [
        A.field('検索', keyword),
        A.field('結果', status),
        el('div.filters__actions', {}, [
          el('button.btn.btn--primary', {
            type: 'button', text: '検索',
            onClick: function () { fetchLogs(1); }
          }),
          el('button.btn.btn--ghost', {
            type: 'button', text: 'リセット',
            onClick: function () {
              keyword.value = '';
              status.value = '';
              fetchLogs(1);
            }
          })
        ])
      ])
    }), slot);



    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); fetchLogs(1); }
    });

    fetchLogs(page);
  }

})();
