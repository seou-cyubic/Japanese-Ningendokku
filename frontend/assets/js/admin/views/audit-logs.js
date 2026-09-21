/* ==========================================================================
   audit-logs.js — A-60 조작 로그
   --------------------------------------------------------------------------
   L3(시스템 관리자) 전용.

   이 화면이 답해야 하는 질문은 하나다 — **「이 예약, 누가 언제 이렇게 만들었나?」**
   그래서 행을 눌러 펼치면 변경 전후를 그대로 보여 준다.
   요약만 남기면 정작 필요할 때 확인할 수 없다.

   검진 시각이 지난 예약은 자동으로 삭제되므로(RESERVATION_PURGE),
   그 뒤에는 이 화면이 유일한 추적 수단이다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var filters = null;

  A.route('audit-logs', function (view, params) {
    A.setTitle('操作ログ', '管理画面で行われた全操作の記録', [
      el('button.btn.btn--sm.btn--csv', {
        type: 'button',
        text: 'CSV 書き出し',
        onClick: function () { exportCurrentAuditLogs(params); }
      })
    ]);

    var ready = filters
      ? Promise.resolve()
      : A.api.get('/audit-logs/filters').then(function (body) { filters = body.data; });

    ready
      .then(function () { load(view, params); })
      .catch(function (error) { A.fail(view, error); });
  });

  function load(view, params) {
    var criteria = {
      keyword: params.keyword || '',
      action: params.action || '',
      admin_user_id: params.admin_user_id || '',
      from: params.from || '',
      to: params.to || '',
      log_id_from: params.log_id_from || '',
      log_id_to: params.log_id_to || '',
      page: Number(params.page || 1),
      size: 40
    };

    A.clear(view);
    view.appendChild(batchCard(view));
    view.appendChild(filterCard(criteria));

    var slot = el('div');
    slot.appendChild(A.loading());
    view.appendChild(slot);

    A.api.get('/audit-logs' + A.query(criteria))
      .then(function (body) {
        A.clear(slot).appendChild(resultCard(body.data, criteria));
      })
      .catch(function (error) {
        A.clear(slot);
        A.fail(slot, error);
      });
  }

  /* ======================================================================
     일괄 저장 되돌리기
     --------------------------------------------------------------------
     아래 목록에서는 회장 21곳이 21줄로 나란히 보일 뿐이라, **어디부터
     어디까지가 한 번의 저장이었는지** 알 수 없다. 「아까 그 저장을
     되돌리고 싶다」에 답하려면 그 경계가 보여야 한다.

     되돌리기는 그 자체가 되돌릴 수 없는 조작이다. 그래서 **반드시
     미리보기를 먼저** 보여 준다 — 무엇이 무엇으로 돌아가는지, 어느 행이
     왜 건너뛰어지는지.
     ====================================================================== */

  function batchCard(view) {
    var box = el('div');
    box.appendChild(A.loading('直近の一括保存を読み込んでいます…'));

    var card = A.card('一括保存を元に戻す', {
      desc: '表で「保存」を1回押した内容をまとめて元に戻します。' +
        '元に戻した後も履歴は削除されません。',
      collapsible: true,
      collapseKey: 'audit-batches',
      body: box
    });

    A.api.get('/audit-logs/batches?limit=20')
      .then(function (body) { renderBatches(view, box, body.data || []); })
      .catch(function () {
        A.clear(box).appendChild(A.notice('warn',
          '一括保存一覧を読み込めませんでした。'));
      });

    return card;
  }

  function renderBatches(view, box, batches) {
    A.clear(box);

    if (!batches.length) {
      box.appendChild(el('p.field__hint', {
        text: '元に戻せる一括保存はまだありません。' +
          '会場・定員・オプション検査の表で保存するとここに蓄積されます。'
      }));
      return;
    }

    box.appendChild(A.table({
      columns: [
        {
          label: '日時', width: '150px',
          render: function (b) { return A.fmt.datetime(b.created_at); }
        },
        { label: '内容', render: function (b) { return cleanBulkLabel(b.title); } },
        {
          label: '操作者', width: '120px',
          render: function (b) { return b.admin_name; }
        },
        {
          label: '件数', align: 'right', width: '70px',
          render: function (b) { return b.row_count + '件'; }
        },
        {
          label: '', width: '130px',
          render: function (b) {
            if (b.is_reverted) {
              return el('span.badge.badge--muted', { text: '元に戻し済み' });
            }
            if (!b.row_count) {
              return el('span.dim', { text: '元に戻す対象なし' });
            }
            return el('button.btn.btn--sm', {
              type: 'button', text: '元に戻す',
              onClick: function () { openRevert(view, b); }
            });
          }
        }
      ],
      rows: batches,
      empty: { title: '一括保存がありません', desc: '' }
    }));
  }

  function openRevert(view, batch) {
    A.api.get('/audit-logs/batches/' + batch.batch_id)
      .then(function (body) { showRevertPlan(view, batch, body.data); })
      .catch(function (error) { A.toast(error.message, 'danger'); });
  }

  function showRevertPlan(view, batch, plan) {
    var restorable = plan.restorable_count;
    var skipped = plan.skipped_count;

    var planTitleText = cleanBulkLabelText(plan.title);
    var body = [
      el('p', {
        style: 'margin:0 0 10px;line-height:1.7',
        text: A.fmt.datetime(batch.created_at) + ' · ' + batch.admin_name +
          ' さんが保存した「' + planTitleText + '」を元に戻します。'
      }),
      el('div.preview-counts', {}, [
        el('div.preview-count.preview-count--warn', {}, [
          el('span.preview-count__label', { text: '元に戻します' }),
          el('span.preview-count__value', { text: restorable + '件' })
        ]),
        el('div.preview-count', {}, [
          el('span.preview-count__label', { text: 'スキップします' }),
          el('span.preview-count__value', { text: skipped + '件' })
        ])
      ])
    ];

    // 건너뛰는 것은 이유가 반드시 보여야 한다. 조용히 빼면 「되돌렸는데
    // 그대로다」가 되고, 그때는 원인을 찾을 길이 없다.
    var skips = plan.items.filter(function (i) { return i.plan === 'SKIP'; });
    if (skips.length) {
      body.push(el('div.preview-warn', {}, [
        el('p.preview-warn__title', {
          text: skips.length + '件は元に戻しません'
        }),
        el('ul.preview-warn__list', {}, skips.slice(0, 10).map(function (i) {
          return el('li', { text: i.target_label + ' — ' + i.reason });
        }))
      ]));
    }

    var doing = plan.items.filter(function (i) { return i.plan !== 'SKIP'; });
    if (doing.length) body.push(revertDetail(doing));

    body.push(el('p.field__hint', {
      text: '元に戻す操作も操作ログに記録されます。元の記録は削除されません。' +
        '同じ保存を2回元に戻すことはできません。'
    }));

    A.modal({
      title: 'この保存を元に戻しますか？',
      size: 'wide',
      body: body,
      actions: [
        { label: 'キャンセル' },
        {
          label: restorable ? '元に戻す' : '元に戻す対象がありません',
          tone: 'danger',
          onClick: restorable
            ? function () { runRevert(view, batch); }
            : null
        }
      ]
    });
  }

  function revertDetail(items) {
    var box = el('details.preview-detail');
    box.appendChild(el('summary', {
      text: '変更内容の詳細 (' + items.length + '件)'
    }));

    var table = el('table.preview-table');
    table.appendChild(el('thead', {}, el('tr', {}, [
      el('th', { text: '対象' }),
      el('th', { text: '項目' }),
      el('th', { text: '現在' }),
      el('th', { text: '戻す値' })
    ])));

    var tbody = el('tbody');
    items.forEach(function (item) {
      (item.changes || []).forEach(function (change, index) {
        var label = change.label || change.field || '';
        if (KEY_LABELS[label]) {
          label = KEY_LABELS[label];
        } else if (change.field && KEY_LABELS[change.field]) {
          label = KEY_LABELS[change.field];
        }

        tbody.appendChild(el('tr', {}, [
          el('td', {}, index === 0
            ? [el('span.mono', { text: item.target_label })]
            : []),
          el('td', { text: label }),
          el('td.preview-table__before', { text: change.before }),
          el('td.preview-table__after', { text: change.after })
        ]));
      });
    });
    table.appendChild(tbody);

    box.appendChild(el('div.preview-table-wrap', {}, table));
    return box;
  }

  function runRevert(view, batch) {
    A.api.post('/audit-logs/batches/' + batch.batch_id + '/revert')
      .then(function (body) {
        A.toast(body.message, 'ok');
        A.render();   // 목록과 되돌리기 카드를 함께 다시 그린다
      })
      .catch(function (error) { A.toast(error.message, 'danger'); });
  }

  /* 삭제 복원 — 삭제 로그 한 건에서 삭제 전 내용으로 다시 등록한다.
     일괄 저장 되돌리기와 달리 batch 가 없어 로그 행에서 직접 실행한다. */
  function restoreDeleted(log) {
    var hasSchedules = log.action === 'HOSPITAL_DELETE' &&
      log.before_json && Array.isArray(log.before_json.schedules) &&
      log.before_json.schedules.length;
    A.confirm({
      title: '削除を元に戻す',
      message: '「' + log.target_label + '」を削除前の内容で登録し直します。',
      detail: log.action === 'HOSPITAL_DELETE'
        ? (hasSchedules
            ? '開催日程 ' + log.before_json.schedules.length + '件と定員も復元されます。'
            : 'この削除の記録には開催日程がないため、会場情報のみ復元されます（日程・定員は再登録が必要です）。')
        : '',
      okLabel: '元に戻す',
      tone: 'primary'
    }).then(function (ok) {
      if (!ok) return;
      A.api.post('/audit-logs/' + log.id + '/restore')
        .then(function (body) {
          A.toast(body.message, 'ok');
          A.render();
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    });
  }

  function exportCurrentAuditLogs(params) {
    openExportModal(params);
  }

  function openExportModal(params) {
    params = params || {};

    // 現在の画面の入力値があれば優先し、無ければURLパラメータを使用
    var curKw = document.getElementById('f-keyword') ? document.getElementById('f-keyword').value.trim() : (params.keyword || '');
    var curAct = document.getElementById('f-action') ? document.getElementById('f-action').value : (params.action || '');
    var curAdmin = document.getElementById('f-admin') ? document.getElementById('f-admin').value : (params.admin_user_id || '');
    var curFrom = document.getElementById('f-from') ? document.getElementById('f-from').value : (params.from || '');
    var curTo = document.getElementById('f-to') ? document.getElementById('f-to').value : (params.to || '');
    var curIdFrom = document.getElementById('f-log-id-from') ? document.getElementById('f-log-id-from').value.trim() : (params.log_id_from || '');
    var curIdTo = document.getElementById('f-log-id-to') ? document.getElementById('f-log-id-to').value.trim() : (params.log_id_to || '');

    var dateFrom = A.input({ id: 'exp-from', type: 'date', value: curFrom });
    var dateTo = A.input({ id: 'exp-to', type: 'date', value: curTo });

    var idFrom = A.input({
      id: 'exp-id-from',
      type: 'number',
      value: curIdFrom,
      placeholder: '例: 100',
      style: 'width:100%;'
    });
    var idTo = A.input({
      id: 'exp-id-to',
      type: 'number',
      value: curIdTo,
      placeholder: '例: 250',
      style: 'width:100%;'
    });

    var keyword = A.input({
      id: 'exp-keyword',
      value: curKw,
      placeholder: '予約番号・会場名・担当者・変更内容など'
    });

    var actionSelect = A.select({ id: 'exp-action' }, [{ value: '', label: 'すべての操作' }].concat(
      (filters && filters.actions ? filters.actions : []).map(function (a) {
        return { value: a.value, label: a.label, selected: curAct === a.value };
      })
    ));

    var adminSelect = A.select({ id: 'exp-admin' }, [{ value: '', label: 'すべての担当者' }].concat(
      (filters && filters.admins ? filters.admins : []).map(function (a) {
        return {
          value: String(a.id),
          label: a.name + ' (' + a.login_id + ')',
          selected: String(curAdmin) === String(a.id)
        };
      })
    ));

    var formatSelect = A.select({ id: 'exp-format' }, [
      { value: 'csv', label: 'CSV形式 (.csv / UTF-8 BOM付き、Excel対応)' },
      { value: 'xlsx', label: 'Excelブック形式 (.xlsx)' }
    ]);

    var form = el('div.export-dialog-content', { style: 'display:flex;flex-direction:column;gap:18px;' }, [
      el('div', {
        style: 'background:#F8FAFC;border:1px solid var(--a-line-2,#E2E8F0);border-radius:6px;padding:12px 16px;font-size:13px;color:var(--a-ink-sub,#475569);line-height:1.6;'
      }, [
        el('div', { style: 'font-weight:700;color:var(--a-ink);margin-bottom:2px;', text: '操作ログの書き出し条件' }),
        el('div', { text: '期間（発生日）またはログIDの範囲を指定して、該当する操作ログをダウンロードします。未入力の項目は全範囲が対象となります。' })
      ]),

      el('div', {
        style: 'background:#FFFFFF;border:1px solid var(--a-line,#CBD5E1);border-radius:8px;padding:16px 20px;display:flex;flex-direction:column;gap:16px;'
      }, [
        el('div', {
          style: 'font-size:14px;font-weight:700;color:var(--a-ink);border-bottom:1px solid var(--a-line-2,#F1F5F9);padding-bottom:8px;',
          text: '1. 出力範囲の指定'
        }),

        A.field('期間指定（発生日時）', el('div', { style: 'display:flex;align-items:center;gap:10px;' }, [
          el('div', { style: 'flex:1;min-width:0;' }, [dateFrom]),
          el('span.dim', { style: 'font-size:16px;font-weight:600;color:var(--a-ink-weak);flex-shrink:0;', text: '〜' }),
          el('div', { style: 'flex:1;min-width:0;' }, [dateTo])
        ]), { hint: '※ 指定した期間内に行われた操作ログを対象にします（未入力時は全期間）。' }),

        A.field('ログID範囲（番号）', el('div', { style: 'display:flex;align-items:center;gap:10px;' }, [
          el('div', { style: 'flex:1;min-width:0;' }, [idFrom]),
          el('span.dim', { style: 'font-size:16px;font-weight:600;color:var(--a-ink-weak);flex-shrink:0;', text: '〜' }),
          el('div', { style: 'flex:1;min-width:0;' }, [idTo])
        ]), { hint: '※ 一覧の「ログID」列に表示されている番号（例: 100 〜 250）の範囲のみを対象にします。' })
      ]),

      el('div', {
        style: 'background:#FFFFFF;border:1px solid var(--a-line,#CBD5E1);border-radius:8px;padding:16px 20px;display:flex;flex-direction:column;gap:14px;'
      }, [
        el('div', {
          style: 'font-size:14px;font-weight:700;color:var(--a-ink);border-bottom:1px solid var(--a-line-2,#F1F5F9);padding-bottom:8px;',
          text: '2. 絞り込み条件（任意）'
        }),
        el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:14px;' }, [
          A.field('操作種別', actionSelect),
          A.field('担当者', adminSelect)
        ]),
        A.field('検索キーワード', keyword, { hint: '※ 予約番号、会場名、担当者名などで絞り込む場合に指定します。' })
      ]),

      el('div', {
        style: 'background:#FFFFFF;border:1px solid var(--a-line,#CBD5E1);border-radius:8px;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px;'
      }, [
        el('div', {}, [
          el('div', { style: 'font-size:14px;font-weight:700;color:var(--a-ink);', text: '3. ファイル形式' }),
          el('div.field__hint', { style: 'margin-top:2px;', text: '出力するファイルのフォーマットを選択してください' })
        ]),
        el('div', { style: 'width:300px;' }, [formatSelect])
      ])
    ]);

    A.modal({
      title: '操作ログの書き出し',
      size: 'wide',
      body: form,
      actions: [
        { label: 'キャンセル' },
        {
          label: '書き出し (ダウンロード)',
          tone: 'primary',
          onClick: function () {
            var f = dateFrom.value;
            var t = dateTo.value;
            var ifr = idFrom.value.trim();
            var ito = idTo.value.trim();

            if (f && t && f > t) {
              A.toast('期間の開始日は終了日以前を指定してください。', 'warn');
              return false;
            }
            if (ifr && ito && parseInt(ifr, 10) > parseInt(ito, 10)) {
              A.toast('開始ログIDは終了ログID以下で指定してください。', 'warn');
              return false;
            }

            var exportUrl = '/api/v1/admin/audit-logs/export-csv' + A.query({
              keyword: keyword.value.trim(),
              action: actionSelect.value,
              admin_user_id: adminSelect.value,
              from: f,
              to: t,
              log_id_from: ifr || '',
              log_id_to: ito || '',
              format: formatSelect.value
            });

            window.open(exportUrl, '_blank');
            A.toast('操作ログの書き出し（' + formatSelect.value.toUpperCase() + '）を開始しました。', 'ok');
          }
        }
      ]
    });
  }

  /* ======================================================================
     검색 조건
     ====================================================================== */

  function filterCard(criteria) {
    var keyword = A.input({
      id: 'f-keyword',
      value: criteria.keyword,
      placeholder: '予約番号・会場名・担当者'
    });

    var action = A.select({ id: 'f-action' }, [{ value: '', label: 'すべての操作' }].concat(
      filters.actions.map(function (a) {
        return { value: a.value, label: a.label, selected: criteria.action === a.value };
      })
    ));

    var admin = A.select({ id: 'f-admin' }, [{ value: '', label: 'すべての担当者' }].concat(
      filters.admins.map(function (a) {
        return {
          value: String(a.id),
          label: a.name + ' (' + a.login_id + ')',
          selected: String(criteria.admin_user_id) === String(a.id)
        };
      })
    ));

    var from = A.input({ id: 'f-from', type: 'date', value: criteria.from });
    var to = A.input({ id: 'f-to', type: 'date', value: criteria.to });

    var logIdFrom = A.input({
      id: 'f-log-id-from',
      type: 'number',
      value: criteria.log_id_from || '',
      placeholder: '開始ID',
      style: 'width:100%;min-width:0;'
    });
    var logIdTo = A.input({
      id: 'f-log-id-to',
      type: 'number',
      value: criteria.log_id_to || '',
      placeholder: '終了ID',
      style: 'width:100%;min-width:0;'
    });

    function submit() {
      A.go('audit-logs', {
        keyword: keyword.value.trim(),
        action: action.value,
        admin_user_id: admin.value,
        from: from.value,
        to: to.value,
        log_id_from: logIdFrom.value.trim(),
        log_id_to: logIdTo.value.trim(),
        page: 1
      });
    }

    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
    });
    logIdFrom.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
    });
    logIdTo.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
    });

    return A.card('検索条件', {
      body: el('div.filters', {}, [
        A.field('検索', keyword),
        A.field('操作種別', action),
        A.field('担当者', admin),
        A.field('日時（から）', from),
        A.field('日時（まで）', to),
        A.field('ログID範囲', el('div', { style: 'display:flex;align-items:center;gap:4px;min-width:0;' }, [
          logIdFrom,
          el('span.dim', { style: 'flex-shrink:0;', text: '〜' }),
          logIdTo
        ])),
        el('div.filters__actions', {}, [
          el('button.btn.btn--primary', { type: 'button', text: '検索', onClick: submit }),
          el('button.btn.btn--ghost', {
            type: 'button', text: 'リセット',
            onClick: function () { A.go('audit-logs', {}); }
          })
        ])
      ])
    });
  }

  /* ======================================================================
     결과
     ====================================================================== */

  function resultCard(page, criteria) {
    var card = A.card('操作履歴', {
      desc: A.fmt.number(page.total) + '件 ・ 行をクリックすると変更前後を確認できます。',
      flush: true,
      body: buildTable(page.items)
    });

    var foot = A.pager(page.page, page.size, page.total, function (next) {
      A.go('audit-logs', Object.assign({}, criteria, { page: next }));
    });
    if (foot) card.appendChild(foot);

    return card;
  }

  function buildTable(rows) {
    var wrap = el('div.table-wrap');
    var node = el('table.table');

    var head = el('thead', {}, el('tr', {}, [
      el('th', { text: 'ログID', style: 'width:75px;text-align:center;' }),
      el('th', { text: '日時', style: 'width:140px' }),
      el('th', { text: '担当者', style: 'width:150px' }),
      el('th', { text: '操作', style: 'width:170px' }),
      el('th', { text: '内容' }),
      el('th', { text: 'IP', style: 'width:120px' }),
      el('th', { text: '', style: 'width:80px' })
    ]));
    node.appendChild(head);

    var body = el('tbody');

    if (!rows.length) {
      body.appendChild(el('tr', {}, el('td', { colSpan: 7 },
        el('div.empty', {}, [
          el('p.empty__title', { text: '条件に一致する履歴はありません' }),
          el('p', { text: '期間を広げるか、操作種別を「すべて」に変更してお試しください。' })
        ]))));
    }

    rows.forEach(function (log) {
      var detailRow = null;

      var toggle = el('button.btn.btn--sm.btn--ghost', {
        type: 'button',
        text: '展開',
        onClick: function (ev) {
          ev.stopPropagation();
          toggleRow();
        }
      });

      function toggleRow() {
        if (detailRow) {
          detailRow.remove();
          detailRow = null;
          toggle.textContent = '展開';
          line.classList.remove('is-expanded');
          return;
        }
        detailRow = buildDetailRow(log);
        line.parentNode.insertBefore(detailRow, line.nextSibling);
        toggle.textContent = '閉じる';
        line.classList.add('is-expanded');
      }

      var summaryText = formatTargetLabel(log);

      var line = el('tr', {
        style: 'cursor:pointer;',
        onClick: function () { toggleRow(); }
      }, [
        el('td.dim.mono', { style: 'text-align:center;font-weight:600;font-size:12px;', text: '#' + log.id }),
        el('td.dim', { style: 'letter-spacing:-0.2px;line-height:1.5;', text: A.fmt.datetime(log.created_at) }),
        el('td', { style: 'line-height:1.4;' }, [
          el('div', { style: 'letter-spacing:-0.2px;', text: log.admin_name || 'システム' }),
          el('div.field__hint', { style: 'letter-spacing:-0.1px;', text: log.admin_login_id || 'system' })
        ]),
        el('td', {}, actionBadge(log)),
        el('td.wrap', {}, [
          el('div', { style: 'color:var(--a-ink);letter-spacing:-0.2px;line-height:1.45;' }, summaryText),
          buildQuickPreview(log)
        ]),
        el('td.dim.mono', { style: 'letter-spacing:0.2px;line-height:1.5;', text: A.fmt.or(log.ip_address, '—') }),
        el('td', {}, toggle)
      ]);

      body.appendChild(line);
    });

    node.appendChild(body);
    wrap.appendChild(node);
    return wrap;
  }

  /* ======================================================================
     키·값 변환 사전
     ====================================================================== */

  var KEY_LABELS = {
    // 예약
    id: '識別番号',
    reservation_no: '予約番号',
    slot_id: '時間帯識別番号',
    schedule_id: '日程識別番号',
    hospital_id: '会場識別番号',
    slot_date: '受診日',
    time_label: '受診日時',
    start_time: '開始時刻',
    end_time: '終了時刻',
    channel: '受付経路',
    status: 'ステータス',
    admin_notes: '管理者メモ',
    option_names: 'オプション検査',
    hospital: '会場',
    time: '健診時間',
    choice: '希望順位',
    defect: '不備理由',
    cancel_reason: 'キャンセル理由',
    memo: 'メモ',
    has_defect: '不備有無',
    defect_note: '不備理由',
    fiscal_year: '会計年度',
    created_by_admin_id: '作成管理者 ID',
    cancelled_at: 'キャンセル日時',

    // 수검자 정보
    target_person_id: '対象者識別番号',
    last_name: '姓',
    first_name: '名',
    middle_name: 'ミドルネーム',
    last_name_kana: '姓（カナ）',
    first_name_kana: '名（カナ）',
    middle_name_kana: 'ミドルネーム（カナ）',
    gender: '性別',
    birth_date: '生年月日',
    insurer_no: '保険者番号',
    insurance_symbol: '保険証記号',
    insurance_no: '保険証番号',
    postal_code: '郵便番号',
    address: '住所',
    address_detail: '番地',
    building: 'アパート・マンション名',
    tel_mobile: '携帯電話',
    tel_home: '固定電話',
    email: 'メールアドレス',

    // 회장
    code: '会場コード',
    name: '会場名',
    name_kana: 'フリガナ',
    area: '地域',
    city: '市区町村',
    transit_info: '交通情報',
    access_minutes: '所要時間（分）',
    event_date: '開催日',
    booking_close_date: '予約締切日',
    open_time: '開始時刻',
    reception_end_time: '受付終了時刻',
    has_parking: '駐車場の有無',
    latitude: '緯度',
    longitude: '経度',
    tel: '電話番号',
    is_visible: '予約画面表示',
    schedules: '開催日程',
    sort_order: '並び順',

    // 옵션
    option_type: 'オプション種別',
    price: '料金',
    description: '説明',
    note: '開催回メモ',
    target_gender: '対象性別',
    target_age_min: '最小対象年齢',
    target_age_max: '最大対象年齢',

    // 연락
    method: '連絡方法',
    result: '連絡結果',
    count: '連絡回数',

    // 파일/일괄
    rows: 'データ行数',
    format: 'ファイル形式',
    kind: 'データ種別',
    header_mode: 'ヘッダー行の有無',
    encoding: '文字コード（文字化け防止）',
    sheet: 'シート名',
    batch_id: '一括処理ID',

    // 계정
    login_id: 'ログインID',
    admin_login_id: '管理者ID',
    admin_name: '管理者名',
    role: '権限',
    is_active: '有効状態',

    // 메일
    template: 'メール種別',
    subject: '件名',
    body_diff: '本文の変更内容',

    // 정원
    cells: '時間帯別定員',
    dates: '対象日',
    delta: '定員の増減',
    updated: '変更件数',
    updated_slots: '変更された枠一覧',
    blocked: 'ブロック件数',
    set_closed: '受付停止の有無',
    closed: '受付状態',
    is_closed: '休診の有無',

    // 기타
    created: '新規登録件数',
    unchanged: '変更なし件数',
    created_at: '作成日時',
    updated_at: '更新日時',
    cutoff: '削除基準日時',
    deleted: '削除件数',
    deleted_reservations: '削除された予約一覧',
    grace_minutes: '削除前の猶予時間（分）'
  };

  /** 영문 코드 → 한국어 매핑 */
  var VALUE_LABELS = {
    CONFIRMED: '確定',
    PENDING_DEFECT: '不備（仮受付）',
    CANCELLED: 'キャンセル',
    PHONE: '電話',
    EMAIL: 'メール',
    MAIL: '郵送',
    CONNECTED: '応答',
    NO_ANSWER: '不在',
    LEFT_MESSAGE: '伝言残し',
    CALLBACK_REQUESTED: '折り返し希望',
    M: '男性',
    F: '女性',
    SYSTEM_ADMIN: 'システム管理者',
    BUSINESS_ADMIN: '業務管理者',
    STAFF: '一般スタッフ',
    SUCCESS: '成功',
    FAILED: '失敗',
    RESERVE_COMPLETE: '予約確定案内メール',
    REMINDER: 'リマインダーメール',
    confirmation: '予約確認メール',
    cancellation: 'キャンセル案内メール',
    reminder: 'リマインダーメール',

    // 操作
    HOSPITAL_SCHEDULE_SAVE: '会場日程保存',

    // 시트 이름
    capacity: '定員カレンダー',
    hospital: '会場マスター',
    exam_option: 'オプション検査マスター',
    postal_code: '郵便番号',

    // 가져오기 옵션
    HEADER: 'ヘッダーあり（スキップして読み込み）',
    NO_HEADER: 'ヘッダーなし（1行目からデータ）'
  };

  function translateKey(key) {
    return KEY_LABELS[key] || key;
  }

  function translateValue(v, key) {
    if (v === null || v === undefined || v === '') return '（なし）';
    if (key === 'closed' || key === 'is_closed' || key === 'set_closed') {
      return v ? '受付停止（締切）' : '通常受付（再開）';
    }
    if (key === 'has_parking') {
      return v ? 'あり' : 'なし';
    }
    if (key === 'is_visible') {
      return v ? '表示' : '非表示';
    }
    if (key === 'is_active') {
      return v ? '有効' : '無効';
    }
    if (v === true) return 'はい';
    if (v === false) return 'いいえ';
    if (Array.isArray(v)) {
      if (v.length === 0) return '（なし）';
      return v.map(function (item) { return translateValue(item, key); }).join(', ');
    }
    if (typeof v === 'object') return JSON.stringify(v, null, 0);
    var s = String(v);
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) {
      return A.fmt.datetime(s);
    }
    // 시각 초 단위 절삭: "15:00:00" -> "15:00"
    if (/^\d{2}:\d{2}:\d{2}$/.test(s)) {
      return s.substring(0, 5);
    }
    return VALUE_LABELS[s] || s;
  }

  /* ======================================================================
     일괄 저장 레이블 정돈 헬퍼
     "(新規 0 ・ 修正 0 ・ 変更なし 20)" 형태의 번잡한 표기를 깔끔하게 정돈
     ====================================================================== */

  function cleanBulkLabel(label) {
    if (!label) return label || '—';
    if (label.indexOf('新規') !== -1 || label.indexOf('修正') !== -1 || label.indexOf('変更なし') !== -1) {
      var bulkMatch = label.match(/^(.*?)\s*[\(（](?:新規\s*(\d+)\s*[・,]\s*)?(?:修正\s*(\d+)\s*[・,]\s*)?(?:変更なし\s*(\d+)\s*)?[\)）]$/);
      if (bulkMatch) {
        var baseTitle = bulkMatch[1].trim();
        var c = parseInt(bulkMatch[2] || '0', 10);
        var u = parseInt(bulkMatch[3] || '0', 10);
        var parts = [];
        if (c > 0) parts.push('新規 ' + c + '件');
        if (u > 0) parts.push('修正 ' + u + '件');

        if (parts.length === 0) {
          return [
            el('span', { text: baseTitle + ' ' }),
            el('span.dim', { style: 'font-size:0.88em;', text: '（変更なし）' })
          ];
        } else {
          return [
            el('span', { text: baseTitle + ' ' }),
            el('strong', { style: 'color:var(--a-primary); font-size:0.88em;', text: '（' + parts.join('・') + '）' })
          ];
        }
      }
    }
    return label;
  }

  function cleanBulkLabelText(label) {
    if (!label) return '';
    if (label.indexOf('新規') !== -1 || label.indexOf('修正') !== -1 || label.indexOf('変更なし') !== -1) {
      var bulkMatch = label.match(/^(.*?)\s*[\(（](?:新規\s*(\d+)\s*[・,]\s*)?(?:修正\s*(\d+)\s*[・,]\s*)?(?:変更なし\s*(\d+)\s*)?[\)）]$/);
      if (bulkMatch) {
        var baseTitle = bulkMatch[1].trim();
        var c = parseInt(bulkMatch[2] || '0', 10);
        var u = parseInt(bulkMatch[3] || '0', 10);
        var parts = [];
        if (c > 0) parts.push('新規 ' + c + '件');
        if (u > 0) parts.push('修正 ' + u + '件');

        if (parts.length === 0) {
          return baseTitle + '（変更なし）';
        } else {
          return baseTitle + '（' + parts.join('・') + '）';
        }
      }
    }
    return label;
  }

  /* ======================================================================
     대상 레이블 포맷 (조작 종류별 맥락에 맞게)
     ====================================================================== */

  function formatTargetLabel(log) {
    var label = log.target_label || '—';
    var action = log.action || '';

    // 예약 관련: "aGCeHrgfuHsx 田中 太郎" → 구조화된 표시
    // 단, 일괄 삭제(RESERVATION_PURGE)는 예약번호+이름 형식이 아니므로 제외한다.
    if (log.target_type === 'reservation' && label && label !== '—' && action !== 'RESERVATION_PURGE') {
      // 메일 재발송: "aGCeHrgfuHsx → user@email.com"
      if (action === 'MAIL_RESEND' && label.indexOf('→') !== -1) {
        var mailParts = label.split('→');
        return [
          el('span', { text: '予約番号: ' }),
          el('strong', { style: 'color:var(--a-primary);', text: mailParts[0].trim() }),
          el('span', { text: ' → ' + mailParts[1].trim() })
        ];
      }

      // 우편 일괄: "우편 일괄 입력 표 15행 (CSV)"
      if (label.indexOf('郵送一括') !== -1) {
        return label;
      }

      // 일반 예약: "aGCeHrgfuHsx 田中 太郎"
      var firstSpace = label.indexOf(' ');
      if (firstSpace !== -1) {
        var resNo = label.substring(0, firstSpace);
        var name = label.substring(firstSpace + 1);
        return [
          el('span', { text: '予約番号: ' }),
          el('strong', { style: 'color:var(--a-primary);', text: resNo }),
          el('span', { text: ',  受診者: ' }),
          el('strong', { text: name })
        ];
      }
    }

    // 회장 관련: "H001 サンプル会館 A"
    if (log.target_type === 'hospital' && label && label !== '—') {
      var hSpace = label.indexOf(' ');
      if (hSpace !== -1) {
        return [
          el('span', { text: '会場: ' }),
          el('strong', { text: label.substring(hSpace + 1) }),
          el('span.field__hint', { text: ' (' + label.substring(0, hSpace) + ')' })
        ];
      }
    }

    // 일괄 저장 되돌리기: 복잡한 해시와 0건 통계 대신 실제 되돌린 대상을 표시
    if (action === 'BATCH_REVERT') {
      var afterObj = log.after_json || {};
      var items = afterObj.items || [];
      var validTargets = [];
      items.forEach(function (item) {
        if (item.plan !== 'SKIP' && item.target_label) {
          validTargets.push(item.target_label);
        }
      });
      validTargets = validTargets.filter(function (v, i, a) { return a.indexOf(v) === i; });

      if (validTargets.length === 1) {
        return [
          el('span', { text: '対象: ' }),
          el('strong', { text: validTargets[0] })
        ];
      } else if (validTargets.length > 1) {
        return [
          el('span', { text: '対象: ' }),
          el('strong', { text: validTargets[0] }),
          el('span.field__hint', { text: ' 他 ' + (validTargets.length - 1) + '件' })
        ];
      }

      var clean = (label || '一括保存')
        .replace(/\s*\[[0-9a-fA-F]+\]\s*/g, ' ')
        .replace(/—\s*.*$/, '')
        .trim();
      return clean || '一括保存';
    }

    // 일괄 저장 (정원/회장/옵션 일괄변경): "(新規 0 ・ 修正 0 ・ 変更なし 20)" 형태의 번잡한 표기를 정돈
    return cleanBulkLabel(label);
  }

  /* ======================================================================
     조작 종류별 자연어 미리보기
     ====================================================================== */

  /** 내역 간략 미리보기 — 조작 종류에 따라 맥락 있는 한 줄 요약을 만든다 */
  function buildQuickPreview(log) {
    var action = log.action || '';
    var after = log.after_json;
    var before = log.before_json;

    if (!after && !before) return null;

    var text = null;

    // --- 우편 접수 등록 ---
    if (action === 'RESERVATION_CREATE_POSTAL' && after) {
      var parts = [];
      if (after.hospital) parts.push(after.hospital);
      if (after.time) parts.push(after.time);
      if (after.choice) parts.push('第' + after.choice + '希望割当');
      if (after.status === 'PENDING_DEFECT' && after.defect) {
        parts.push('不備 (' + after.defect + ')');
      }
      text = parts.join(' · ');
    }

    // --- 예약 수정 (diff 형식) ---
    else if (action === 'RESERVATION_UPDATE' && after) {
      text = buildDiffPreview(after);
    }

    // --- 예약 취소 ---
    else if (action === 'RESERVATION_CANCEL' && after) {
      var pieces = [];
      if (after.status && after.status.before) {
        pieces.push(translateValue(after.status.before) + ' → ' + translateValue(after.status.after));
      }
      if (after.cancel_reason && after.cancel_reason.after) {
        pieces.push('理由: ' + after.cancel_reason.after);
      }
      text = pieces.join(' · ') || null;
    }

    // --- 연락 이력 추가 ---
    else if (action === 'CONTACT_ADD' && after) {
      var contactParts = [];
      if (after.method) contactParts.push(translateValue(after.method) + ' 連絡');
      if (after.result) contactParts.push('→ ' + translateValue(after.result));
      if (after.count) contactParts.push('(' + after.count + '回目)');
      text = contactParts.join(' ');
    }

    // --- 우편 일괄 가져오기 ---
    else if (action === 'POSTAL_BULK_IMPORT' && after) {
      var impParts = [];
      if (after.kind) impParts.push('郵送受付ファイル取り込み (' + String(after.kind).toUpperCase() + ')');
      else impParts.push('郵送受付ファイル取り込み');
      if (after.rows !== undefined) impParts.push(after.rows + '件');
      text = impParts.join(' · ');
    }

    // --- 우편 일괄 내보내기 ---
    else if (action === 'POSTAL_BULK_EXPORT' && after) {
      var expParts = [];
      if (after.format) expParts.push('郵送受付ファイル書き出し (' + String(after.format).toUpperCase() + ')');
      else expParts.push('郵送受付ファイル書き出し');
      if (after.rows !== undefined) expParts.push(after.rows + '件');
      text = expParts.join(' · ');
    }

    // --- 표 일괄 가져오기 ---
    else if (action === 'BULK_SHEET_IMPORT' && after) {
      var iParts = [];
      var sName = translateValue(after.sheet);
      if (after.kind) iParts.push(sName + ' ファイル取り込み (' + String(after.kind).toUpperCase() + ')');
      else iParts.push(sName + ' ファイル取り込み');
      if (after.rows !== undefined) iParts.push(after.rows + '件');
      text = iParts.join(' · ');
    }

    // --- 표 일괄 내보내기 ---
    else if (action === 'BULK_SHEET_EXPORT' && after) {
      var eParts = [];
      var sName = translateValue(after.sheet);
      if (after.format) eParts.push(sName + ' ファイル書き出し (' + String(after.format).toUpperCase() + ')');
      else eParts.push(sName + ' ファイル書き出し');
      if (after.rows !== undefined) eParts.push(after.rows + '件');
      text = eParts.join(' · ');
    }

    // --- 메일 템플릿 수정 ---
    else if (action === 'MAIL_TEMPLATE_UPDATE' && after) {
      var mParts = [];
      if (after.subject) mParts.push('件名変更');
      if (after.body_diff) mParts.push('本文変更');
      text = mParts.join(' · ') || '変更なし';
    }

    // --- 메일 재발송 ---
    else if (action === 'MAIL_RESEND' && after) {
      var mailParts = [];
      if (after.template) mailParts.push(translateValue(after.template));
      if (after.status) mailParts.push('→ ' + translateValue(after.status));
      text = mailParts.join(' ');
    }

    // --- 회장/옵션/일정 수정 (diff 형식) ---
    else if ((action === 'HOSPITAL_UPDATE' || action === 'HOSPITAL_CREATE' ||
      action === 'EXAM_OPTION_UPDATE' || action === 'EXAM_OPTION_CREATE' ||
      action === 'HOSPITAL_SCHEDULE_SAVE') && after) {
      text = buildDiffPreview(after);
    }

    // --- 일괄 저장 ---
    else if (action === 'HOSPITAL_BULK_SAVE' || action === 'EXAM_OPTION_BULK_SAVE' || action === 'SLOT_BULK_UPDATE') {
      // The target_label already has "(新規 X ・ 修正 Y ・ 変更なし Z)" so we don't need a quick preview
      text = null;
    }

    // --- 정원 변경 ---
    else if (action === 'SLOT_UPDATE' && after) {
      text = buildSlotPreview(after);
    }

    // --- 기간 경과 예약 자동 삭제 ---
    else if (action === 'RESERVATION_PURGE' && after) {
      text = '受診時刻から ' + (after.grace_minutes || 60) + '分が経過した過去の予約 ' + (after.deleted || 0) + '件をシステムが自動的に整理（削除）しました。';
    }

    // --- 계정 관련 ---
    else if (action.indexOf('ACCOUNT') !== -1 && after) {
      text = buildDiffPreview(after);
    }

    // --- 삭제 복원 ---
    else if (action === 'RECORD_RESTORE' && after) {
      text = restoreSummary(log);
    }

    // --- 일괄 저장 되돌리기 ---
    else if (action === 'BATCH_REVERT' && after) {
      var totalChanged = (after.reverted || 0) + (after.deleted || 0);
      if (totalChanged === 0 && after.skipped) {
        text = '変更なし（' + after.skipped + '件スキップ）';
      } else {
        var chgFields = [];
        (after.items || []).forEach(function (item) {
          if (item.plan !== 'SKIP') {
            (item.changes || []).forEach(function (c) {
              var fName = c.label || c.field || '';
              fName = translateKey(c.field || fName);
              if (fName && chgFields.indexOf(fName) === -1) {
                chgFields.push(fName);
              }
            });
          }
        });

        var fieldSummary = chgFields.length > 0
          ? ' (' + chgFields.slice(0, 2).join(', ') + (chgFields.length > 2 ? ' 他' : '') + ')'
          : '';
        text = totalChanged + '件変更' + fieldSummary;

        if (after.skipped && after.skipped > 0) {
          text += ' · スキップ ' + after.skipped + '件';
        }
      }
    }

    // --- 기본 fallback: 키-값을 자연어로 ---
    else if (after && typeof after === 'object') {
      text = buildGenericPreview(after);
    }

    if (!text) return null;

    return el('div.log-preview', { text: text });
  }

  /** 시간대별 정원 변경 사항을 사람이 한눈에 알아보기 쉽게 포맷팅 (단위 및 증감 표시) */
  function formatSlotChange(time, vb, va) {
    var bNum = (typeof vb === 'number');
    var aNum = (typeof va === 'number');
    var bStr = bNum ? (vb + '名') : '受付枠なし';
    var aStr = aNum ? (va + '名') : '受付枠なし';

    var note = '';
    if (bNum && aNum) {
      var delta = va - vb;
      if (delta > 0) note = '（+' + delta + '名増加）';
      else if (delta < 0) note = '（' + Math.abs(delta) + '名減少）';
      else note = '（変更なし）';
    } else if (!bNum && aNum) {
      note = '（新規 ' + va + '名）';
    } else if (bNum && !aNum) {
      note = '（受付停止）';
    }

    return time + '枠: ' + bStr + ' → ' + aStr + (note ? ' ' + note : '');
  }

  function formatCellsLog(v) {
    if (!v) return '設定なし';
    var raw = v;
    if (typeof raw === 'string') {
      try { raw = JSON.parse(raw); } catch (e) { }
    }
    if (!raw || typeof raw !== 'object') return String(raw);

    // Case 1: 최상위에 before 와 after 가 있는 경우 { before: {...}, after: {...} }
    if (('before' in raw) && ('after' in raw)) {
      var cBefore = {};
      var cAfter = {};
      try { cBefore = typeof raw.before === 'string' ? JSON.parse(raw.before || '{}') : (raw.before || {}); } catch (e) { }
      try { cAfter = typeof raw.after === 'string' ? JSON.parse(raw.after || '{}') : (raw.after || {}); } catch (e) { }

      var changedKeys = [];
      var allKeys = Object.keys(cBefore).concat(Object.keys(cAfter));
      allKeys.forEach(function (time) {
        if (changedKeys.indexOf(time) === -1) {
          if (cBefore[time] !== cAfter[time]) {
            changedKeys.push(time);
          }
        }
      });
      changedKeys.sort();

      if (changedKeys.length === 0) return '変更なし';
      return changedKeys.map(function (time) {
        return formatSlotChange(time, cBefore[time], cAfter[time]);
      }).join(', ');
    }

    // Case 2: 시간대 키 아래에 {before, after} 가 있는 중첩 diff 형태
    var keys = Object.keys(raw);
    keys.sort();
    var hasNestedDiff = keys.some(function (k) {
      var val = raw[k];
      return val && typeof val === 'object' && ('before' in val || 'after' in val);
    });

    if (hasNestedDiff) {
      var diffList = [];
      keys.forEach(function (time) {
        var val = raw[time];
        if (val && typeof val === 'object' && ('before' in val || 'after' in val)) {
          diffList.push(formatSlotChange(time, val.before, val.after));
        } else if (val !== null && val !== undefined) {
          diffList.push(time + '枠: ' + val + '名');
        }
      });
      return diffList.length ? diffList.join(', ') : '変更なし';
    }

    // Case 3: 단순 스냅샷 객체 (시간대별 정원 목록)
    var validKeys = keys.filter(function (time) { return raw[time] !== null && raw[time] !== undefined; });
    if (validKeys.length === 0) return '設定なし';
    return validKeys.map(function (time) {
      return time + '枠: ' + raw[time] + '名';
    }).join(', ');
  }

  /** diff 형식({before, after} 쌍)의 미리보기를 자연어로 변환 */
  function buildDiffPreview(obj) {
    if (!obj || typeof obj !== 'object') return null;
    var items = [];
    var keys = Object.keys(obj).filter(function (k) {
      return !(k === 'slot_id' && 'time_label' in obj);
    });

    keys.slice(0, 3).forEach(function (k) {
      var v = obj[k];
      if (k === 'cells') {
        items.push(translateKey(k) + ': ' + formatCellsLog(v));
      } else if (v && typeof v === 'object' && ('before' in v) && ('after' in v)) {
        items.push(translateKey(k) + ': ' + translateValue(v.before, k) + ' → ' + translateValue(v.after, k));
      } else {
        items.push(translateKey(k) + ': ' + translateValue(v, k));
      }
    });

    if (keys.length > 3) items.push('他 ' + (keys.length - 3) + '件');

    return items.join(' · ') || null;
  }

  /** 일반적인(비 diff) 객체의 미리보기 */
  function buildGenericPreview(obj) {
    if (!obj || typeof obj !== 'object') return null;
    var items = [];
    var keys = Object.keys(obj);

    keys.slice(0, 4).forEach(function (k) {
      if (k === 'cells') {
        items.push(translateKey(k) + ': ' + formatCellsLog(obj[k]));
      } else {
        items.push(translateKey(k) + ': ' + translateValue(obj[k], k));
      }
    });

    if (keys.length > 4) items.push('他 ' + (keys.length - 4) + '件');

    return items.join(' · ') || null;
  }

  /** 정원 변경 전용 미리보기 */
  function buildSlotPreview(obj) {
    if (!obj || typeof obj !== 'object') return null;
    var parts = [];

    // 정원 증감
    if (obj.delta !== null && obj.delta !== undefined && obj.delta !== '') {
      var d = Number(obj.delta);
      if (d > 0) parts.push('定員 +' + d + '名増加');
      else if (d < 0) parts.push('定員 ' + d + '名減少');
    }

    // 접수 중지/재개
    if (obj.closed === true || obj.set_closed === true) parts.push('受付停止（締切）');
    else if (obj.closed === false || obj.set_closed === false) parts.push('受付再開');

    // 변경 건수 및 상세 날짜
    if (obj.updated !== undefined) {
      if (obj.updated_slots && Array.isArray(obj.updated_slots) && obj.updated_slots.length > 0) {
        var slots = obj.updated_slots;
        if (slots.length === 1) {
          parts.push('1件変更 (' + slots[0] + ')');
        } else {
          parts.push(obj.updated + '件変更 (' + slots[0] + ' 他 ' + (slots.length - 1) + '件)');
        }
      } else {
        parts.push(obj.updated + '件変更');
      }
    }

    // 대상 날짜 수 (일괄 변경일 때만 추가 표시)
    if (obj.dates && Array.isArray(obj.dates) && obj.dates.length > 0 && (!obj.updated_slots || obj.updated_slots.length === 0)) {
      parts.push(obj.dates.length + '日対象');
    }

    // 차단된 건
    if (obj.blocked && obj.blocked > 0) {
      parts.push(obj.blocked + '件ブロック （予約超過）');
    }

    return parts.join(' · ') || null;
  }

  function actionBadge(log) {
    var tone = 'muted';
    var action = log.action || '';
    if (action.indexOf('CANCEL') !== -1 || action.indexOf('DELETE') !== -1 || action.indexOf('PURGE') !== -1) tone = 'danger';
    else if (action.indexOf('CREATE') !== -1 || action.indexOf('POSTAL_INTAKE') !== -1) tone = 'ok';
    else if (action.indexOf('UPDATE') !== -1 || action.indexOf('SAVE') !== -1) tone = 'info';
    else if (action.indexOf('FAILED') !== -1 || action.indexOf('LOGIN_FAIL') !== -1) tone = 'warn';

    return el('span.badge.badge--' + tone, {
      text: log.action_label || action
    });
  }

  /* ======================================================================
     데이터 테이블 미리보기 (일괄 등록/내보내기)
     ====================================================================== */
  function buildDataTable(rows) {
    var table = el('table.log-compare', { style: 'margin-top:8px;font-size:12px;white-space:nowrap;overflow-x:auto;display:block;' });
    var thead = el('thead');
    var tbody = el('tbody');

    var columns = [];
    rows.forEach(function (r) {
      if (typeof r !== 'object' || r === null) return;
      Object.keys(r).forEach(function (k) {
        if (columns.indexOf(k) === -1) columns.push(k);
      });
    });

    var trHead = el('tr');
    columns.forEach(function (c) {
      trHead.appendChild(el('th', { text: translateKey(c), style: 'padding:6px 10px;' }));
    });
    thead.appendChild(trHead);

    rows.forEach(function (r) {
      var tr = el('tr');
      columns.forEach(function (c) {
        var val = (r && typeof r === 'object') ? r[c] : '';
        tr.appendChild(el('td', { text: translateValue(val), style: 'padding:6px 10px;' }));
      });
      tbody.appendChild(tr);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return table;
  }

  /* ======================================================================
     변경 전후 상세 — 구조화된 비교 테이블
     ====================================================================== */

  /* 삭제 복원 로그의 한 줄 요약. `log_id` 같은 내부 값은 보여 주지 않는다. */
  function restoreWhat(log) {
    return log.target_type === 'exam_option' ? 'オプション検査' : '会場';
  }

  function restoreSummary(log) {
    return '削除された' + restoreWhat(log) + 'を元の内容で復元しました';
  }

  function buildDetailRow(log) {
    var content = el('div.log-detail');

    if (log.action === 'RECORD_RESTORE') {
      var info = log.after_json || {};
      content.appendChild(el('div.log-detail__title', { text: '削除を元に戻した内容' }));

      var restoreTable = el('table.log-info');
      var restoreBody = el('tbody');
      var rows = [
        ['復元した' + restoreWhat(log), (log.target_label || '').replace(/\s*（削除を元に戻す）\s*$/, '')]
      ];
      if (info.deleted_at) rows.push(['削除された日時', A.fmt.datetime(info.deleted_at)]);
      if (info.deleted_by) rows.push(['削除した担当者', info.deleted_by]);
      if (Array.isArray(info.schedule_lines) && info.schedule_lines.length) {
        rows.push(['開催日程', info.schedule_lines.join('\n')]);
      }
      rows.forEach(function (r) {
        restoreBody.appendChild(el('tr', {}, [
          el('td.log-info__label', { text: r[0] }),
          el('td.log-info__value', { text: r[1], style: 'white-space:pre-line' })
        ]));
      });
      restoreTable.appendChild(restoreBody);
      content.appendChild(restoreTable);

      return el('tr.log-detail-row', {}, el('td', { colSpan: 7 }, content));
    }

    if (log.action === 'BATCH_REVERT') {
      var after = log.after_json || {};
      content.appendChild(el('div.log-detail__title', { text: '一括処理を元に戻した内容' }));

      var summaryTable = el('table.log-info', { style: 'margin-bottom: 16px;' });
      var summaryBody = el('tbody');

      var labels = { reverted: '元に戻した件数', deleted: '削除した件数', skipped: 'スキップした件数' };
      ['reverted', 'deleted', 'skipped'].forEach(function (k) {
        if (after[k] !== undefined && after[k] > 0 || k === 'reverted') {
          summaryBody.appendChild(el('tr', {}, [
            el('td.log-info__label', { text: labels[k] }),
            el('td.log-info__value', { text: after[k] + '件' })
          ]));
        }
      });
      summaryTable.appendChild(summaryBody);
      content.appendChild(summaryTable);

      if (after.items && after.items.length > 0) {
        var doing = after.items.filter(function (i) { return i.plan !== 'SKIP'; });
        if (doing.length > 0) {
          content.appendChild(revertDetail(doing));
        }

        var skips = after.items.filter(function (i) { return i.plan === 'SKIP'; });
        if (skips.length > 0) {
          var skipsDiv = el('div.preview-warn', { style: 'margin-top: 16px;' }, [
            el('p.preview-warn__title', { text: skips.length + '件は元に戻しませんでした' }),
            el('ul.preview-warn__list', {}, skips.slice(0, 10).map(function (i) {
              return el('li', { text: i.target_label + ' — ' + i.reason });
            }))
          ]);
          content.appendChild(skipsDiv);
        }
      } else {
        content.appendChild(el('p.field__hint', { text: '※ この履歴には詳細な項目データが含まれていません。' }));
      }
      return el('tr.log-detail-row', {}, el('td', { colSpan: 6 }, content));
    }

    var hasDiff = false;
    var hasPlainAfter = false;
    var hasPlainBefore = false;

    // after_json 에 {before, after} 쌍이 있는지 판정
    if (log.after_json && typeof log.after_json === 'object') {
      var afterKeys = Object.keys(log.after_json);
      afterKeys.forEach(function (k) {
        var v = log.after_json[k];
        if (v && typeof v === 'object' && ('before' in v) && ('after' in v)) {
          hasDiff = true;
        } else {
          hasPlainAfter = true;
        }
      });
    }

    if (log.before_json && typeof log.before_json === 'object' && !hasDiff) {
      hasPlainBefore = true;
    }

    // --- Case 1: diff 형식이 있는 경우 → 3열 비교 테이블 ---
    if (hasDiff) {
      content.appendChild(el('div.log-detail__title', { text: '変更内容' }));
      var diffTable = el('table.log-compare');
      diffTable.appendChild(el('thead', {}, el('tr', {}, [
        el('th', { text: '項目', style: 'width:140px' }),
        el('th', { text: '変更前' }),
        el('th', { text: '変更後' })
      ])));
      var diffBody = el('tbody');

      var diffKeys = Object.keys(log.after_json).filter(function (k) {
        return !(k === 'slot_id' && 'time_label' in log.after_json);
      });

      diffKeys.forEach(function (k) {
        var v = log.after_json[k];
        var isDiffPair = (v && typeof v === 'object' && ('before' in v) && ('after' in v));
        var isCellsNestedDiff = (k === 'cells' && v && typeof v === 'object' && Object.keys(v).some(function (sk) {
          return v[sk] && typeof v[sk] === 'object' && ('before' in v[sk] || 'after' in v[sk]);
        }));

        if (isDiffPair || isCellsNestedDiff) {
          if (k === 'cells') {
            var cBefore = {};
            var cAfter = {};
            if (isDiffPair) {
              try { cBefore = typeof v.before === 'string' ? JSON.parse(v.before || '{}') : (v.before || {}); } catch (e) { }
              try { cAfter = typeof v.after === 'string' ? JSON.parse(v.after || '{}') : (v.after || {}); } catch (e) { }
            } else {
              Object.keys(v).forEach(function (sk) {
                if (v[sk] && typeof v[sk] === 'object') {
                  cBefore[sk] = v[sk].before;
                  cAfter[sk] = v[sk].after;
                }
              });
            }

            var changedKeys = [];
            var allKeys = Object.keys(cBefore).concat(Object.keys(cAfter));
            allKeys.forEach(function (time) {
              if (changedKeys.indexOf(time) === -1) {
                if (cBefore[time] !== cAfter[time]) {
                  changedKeys.push(time);
                }
              }
            });
            changedKeys.sort();

            var beforeNodes = [];
            var afterNodes = [];

            if (changedKeys.length === 0) {
              beforeNodes.push(el('div', { text: '変更なし' }));
              afterNodes.push(el('div', { text: '変更なし' }));
            } else {
              changedKeys.forEach(function (time) {
                var vb = cBefore[time];
                var va = cAfter[time];
                var bNum = (typeof vb === 'number');
                var aNum = (typeof va === 'number');
                var bStr = bNum ? (vb + '名') : '受付枠なし';
                var aStr = aNum ? (va + '名') : '受付枠なし';

                var note = '';
                if (bNum && aNum) {
                  var delta = va - vb;
                  if (delta > 0) note = ' （+' + delta + '名増加）';
                  else if (delta < 0) note = ' （' + Math.abs(delta) + '名減少）';
                } else if (!bNum && aNum) {
                  note = ' （新規受付）';
                } else if (bNum && !aNum) {
                  note = ' （受付停止）';
                }

                beforeNodes.push(el('div', { text: time + '枠 : ' + bStr }));
                afterNodes.push(el('div', { text: time + '枠 : ' + aStr + note }));
              });
            }

            diffBody.appendChild(el('tr', {}, [
              el('td.log-compare__label', { text: translateKey(k) }),
              el('td.log-compare__before', {}, beforeNodes),
              el('td.log-compare__after', {}, afterNodes)
            ]));
          } else {
            diffBody.appendChild(el('tr', {}, [
              el('td.log-compare__label', { text: translateKey(k) }),
              el('td.log-compare__before', { text: translateValue(v.before) }),
              el('td.log-compare__after', { text: translateValue(v.after) })
            ]));
          }
        }
      });

      diffTable.appendChild(diffBody);
      content.appendChild(diffTable);
    }

    // --- Case 2: 단순 after 값 (생성, 접수 등) → 2열 정보 테이블 ---
    if (hasPlainAfter && !hasDiff) {
      content.appendChild(el('div.log-detail__title', { text: '内容' }));
      var infoTable = el('table.log-info');
      var infoBody = el('tbody');
      var dataArray = null;

      Object.keys(log.after_json).forEach(function (k) {
        var v = log.after_json[k];
        if (k === 'data' && Array.isArray(v)) {
          dataArray = v;
          return;
        }
        // diff 쌍이 아닌 것만
        if (!(v && typeof v === 'object' && ('before' in v) && ('after' in v))) {
          // 일괄 저장 결과에서 0건인 항목은 잡음이 되므로 생략
          if ((k === 'created' || k === 'updated' || k === 'unchanged' || k === 'deleted' || k === 'skipped') && v === 0) {
            return;
          }
          infoBody.appendChild(el('tr', {}, [
            el('td.log-info__label', { text: translateKey(k) }),
            el('td.log-info__value', { text: translateValue(v, k) })
          ]));
        }
      });

      // 일괄 저장에서 신규/수정이 모두 0건이라 표시할 항목이 없는 경우
      if (infoBody.childNodes.length === 0 && (log.after_json.created !== undefined || log.after_json.updated !== undefined || log.after_json.unchanged !== undefined)) {
        infoBody.appendChild(el('tr', {}, [
          el('td.log-info__label', { text: '変更内容' }),
          el('td.log-info__value', { text: '変更なし' })
        ]));
      }

      if (infoBody.childNodes.length > 0) {
        infoTable.appendChild(infoBody);
        content.appendChild(infoTable);
      }

      if (dataArray && dataArray.length > 0) {
        content.appendChild(el('div.log-detail__title', { text: 'データプレビュー（最大50件）', style: 'margin-top:16px;' }));
        content.appendChild(buildDataTable(dataArray));
      }
    }

    // diff 형식에 섞인 단순 after 값도 보여주기
    if (hasPlainAfter && hasDiff) {
      var extraItems = [];
      Object.keys(log.after_json).forEach(function (k) {
        var v = log.after_json[k];
        if (!(v && typeof v === 'object' && ('before' in v) && ('after' in v))) {
          if (k !== 'slot_id') {
            extraItems.push(translateKey(k) + ': ' + translateValue(v));
          }
        }
      });
      if (extraItems.length) {
        content.appendChild(el('div', {
          style: 'margin-top:8px;font-size:13px;color:var(--a-ink-sub);',
          text: extraItems.join(' · ')
        }));
      }
    }

    // --- Case 3: before_json만 있는 경우 (삭제 등) → 2열 테이블 ---
    if (hasPlainBefore && !log.after_json) {
      content.appendChild(el('div.log-detail__title', { text: '削除前のデータ' }));
      var delTable = el('table.log-info');
      var delBody = el('tbody');

      Object.keys(log.before_json).forEach(function (k) {
        var shown = log.before_json[k];
        // 회장 삭제 때 남긴 회차 목록(객체 배열)은 날짜만 요약해 보여 준다.
        if (k === 'schedules' && Array.isArray(shown)) {
          shown = shown.length
            ? shown.map(function (s) { return s.event_date; }).join(', ') + '（' + shown.length + '件）'
            : '';
        }
        delBody.appendChild(el('tr', {}, [
          el('td.log-info__label', { text: translateKey(k) }),
          el('td.log-info__value', { text: translateValue(shown) })
        ]));
      });

      delTable.appendChild(delBody);
      content.appendChild(delTable);
    }

    // before_json이 있고 after에 diff가 있으면 before 스냅샷도 접을 수 있게
    if (hasPlainBefore && hasDiff) {
      var toggle = el('button.btn.btn--xs.btn--ghost', {
        type: 'button',
        text: '変更前全体を表示',
        style: 'margin-top:8px;',
        onClick: function () {
          if (beforeBlock.style.display === 'none') {
            beforeBlock.style.display = '';
            toggle.textContent = '変更前全体を閉じる';
          } else {
            beforeBlock.style.display = 'none';
            toggle.textContent = '変更前全体を表示';
          }
        }
      });

      var beforeTable = el('table.log-info', { style: 'margin-top:6px;' });
      var bBody = el('tbody');
      Object.keys(log.before_json).forEach(function (k) {
        bBody.appendChild(el('tr', {}, [
          el('td.log-info__label', { text: translateKey(k) }),
          el('td.log-info__value', { text: translateValue(log.before_json[k]) })
        ]));
      });
      beforeTable.appendChild(bBody);

      var beforeBlock = el('div', { style: 'display:none;' }, beforeTable);
      content.appendChild(toggle);
      content.appendChild(beforeBlock);
    }

    // 내용이 아무것도 없는 경우
    if (!content.firstChild) {
      content.appendChild(el('p.field__hint', { text: '記録された詳細内容がない操作です。' }));
    }

    // 바로가기 링크
    var links = el('div', { style: 'margin-top:12px;display:flex;gap:8px' });
    if (log.target_type === 'reservation' && log.target_id) {
      links.appendChild(el('a.btn.btn--sm', {
        href: '#/reservation?id=' + log.target_id,
        text: 'この予約を表示'
      }));
    }
    if (log.target_type === 'hospital' && log.target_id && log.action !== 'HOSPITAL_DELETE') {
      links.appendChild(el('a.btn.btn--sm', {
        href: '#/capacity?hospital_id=' + log.target_id,
        text: 'この会場の定員を表示'
      }));
    }
    if (log.action === 'HOSPITAL_DELETE' || log.action === 'EXAM_OPTION_DELETE') {
      links.appendChild(el('button.btn.btn--sm.btn--primary', {
        type: 'button',
        text: '削除を元に戻す',
        onClick: function () { restoreDeleted(log); }
      }));
    }

    return el('tr.log-detail-row', {}, el('td', { colSpan: 7 }, [
      content,
      links
    ]));
  }

})();
