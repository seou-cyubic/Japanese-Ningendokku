/* ==========================================================================
   reservations.js — A-10 예약 검색 및 EMR/CRM 작업 현황판
   --------------------------------------------------------------------------
   · 회장 EMR/CRM 상단 고속 검색 & 민트/그린 액션 바
   · 상태별 특수 색상 행 하이라이트 (미방문/임시 = 분홍, 확정 = 흰색, 취소 = 취소선)
   · 칸반 보드 뷰 (Kanban View) & 컴팩트 표 뷰 (Table View) 1-Click 전환
   · 우측 슬라이딩 EMR 상세 드로어 연결
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var filters = null;
  var currentViewMode = localStorage.getItem('kenshin_res_view_mode') || 'table'; // Default 'table' for EMR feel

  A.route('reservations', function (view, params) {
    A.setTitle('予約検索', '受診者の予約検索・確認', [
      el('button.btn.btn--sm.btn--csv', {
        type: 'button',
        text: 'CSV 書き出し',
        onClick: function () { exportCurrentReservations(params, 'csv'); }
      }),
      el('a.btn.btn--sm.btn--primary', {
        href: '#/postal', text: '＋ 郵送受付入力'
      })
    ]);

    var ready = filters
      ? Promise.resolve(filters)
      : A.api.get('/reservations/filters').then(function (body) {
        filters = body.data;
        return filters;
      });

    ready
      .then(function () { return load(view, params); })
      .catch(function (error) { A.fail(view, error); });
  });

  /** 옵션 검사 id → 사람이 읽는 이름. 선택지는 `/reservations/filters` 가 준다. */
  function optionLabel(optionId) {
    var found = ((filters && filters.exam_options) || []).filter(function (o) {
      return String(o.id) === String(optionId);
    })[0];
    return found ? found.name : ('#' + optionId);
  }

  function load(view, params) {
    var criteria = {
      keyword: params.keyword || '',
      status: params.status || '',
      channel: params.channel || '',
      hospital_id: params.hospital_id || '',
      // 「이 옵션 검사를 신청한 예약만」. 옵션 검사 관리에서 신청 건수를
      // 더블 클릭하면 이 조건을 달고 들어온다.
      option_id: params.option_id || '',
      from: params.from || '',
      to: params.to || '',
      defect: params.defect || '',
      created_date: params.created_date || '',
      page: Number(params.page || 1),
      size: 50
    };

    A.clear(view);

    // 필터 카드
    view.appendChild(buildFilterCard(criteria));

    // 옵션으로 좁혀 들어온 경우에는 그 사실을 말해 준다. 목록이 갑자기
    // 짧아진 이유를 콤보 하나에서 읽어 내게 두면 안 된다.
    if (criteria.option_id) {
      view.appendChild(A.notice('info',
        'オプション検査「' + optionLabel(criteria.option_id) + '」をお申し込みの予約のみ' +
        '表示しています。キャンセルされた予約も表示されます。'));
    }

    if (criteria.created_date) {
      view.appendChild(A.notice('info',
        '受付日が「' + criteria.created_date + '」の予約のみ表示しています。'));
    }

    if (criteria.defect) {
      view.appendChild(A.notice('warn',
        '対応が必要な予約（仮受付・登録情報不備・日程変更要）のみ表示しています。'));
    }

    var resultSlot = el('div');
    resultSlot.appendChild(A.loading('予約を読み込んでいます…'));
    view.appendChild(resultSlot);

    return A.api.get('/reservations' + A.query(criteria))
      .then(function (body) {
        A.clear(resultSlot).appendChild(buildResult(body.data, criteria, function () {
          load(view, params);
        }));
      })
      .catch(function (error) {
        A.clear(resultSlot);
        A.fail(resultSlot, error);
      });
  }


  /* ======================================================================
     CSV / 엑셀 내보내기
     ====================================================================== */
  function exportCurrentReservations(params, format) {
    format = format || 'csv';
    var kw = document.getElementById('f-keyword') ? document.getElementById('f-keyword').value.trim() : (params.keyword || '');
    var st = document.getElementById('f-status') ? document.getElementById('f-status').value : (params.status || '');
    var ch = document.getElementById('f-channel') ? document.getElementById('f-channel').value : (params.channel || '');
    var hosp = document.getElementById('f-hospital') ? document.getElementById('f-hospital').value : (params.hospital_id || '');
    var opt = document.getElementById('f-option') ? document.getElementById('f-option').value : (params.option_id || '');
    var fr = document.getElementById('f-from') ? document.getElementById('f-from').value : (params.from || '');
    var to = document.getElementById('f-to') ? document.getElementById('f-to').value : (params.to || '');

    var exportUrl = '/api/v1/admin/reservations/export-csv' + A.query({
      keyword: kw,
      status: st,
      channel: ch,
      hospital_id: hosp,
      // 화면에서 거른 조건과 내려받는 파일이 달라지면 안 된다.
      option_id: opt,
      from: fr,
      to: to,
      defect: params ? (params.defect || '') : '',
      created_date: params ? (params.created_date || '') : '',
      format: format
    });

    window.open(exportUrl, '_blank');
  }

  /* ======================================================================
     필터 카드 및 뷰 모드 토글
     ====================================================================== */
  function buildFilterCard(criteria) {
    var keyword = A.input({
      id: 'f-keyword',
      value: criteria.keyword,
      placeholder: '予約番号・お名前・フリガナ・電話番号・メールアドレス　（「/」キーで移動）',
      autocomplete: 'off',
      // 목록 화면에서 「/」를 누르면 이 칸으로 온다. (assets/js/admin/app.js)
      dataset: { shortcut: 'search' }
    });

    var status = A.select({ id: 'f-status' }, [{ value: '', label: 'すべてのステータス' }].concat(
      filters.statuses.map(function (s) {
        return { value: s.value, label: s.label, selected: criteria.status === s.value };
      })
    ));

    var channel = A.select({ id: 'f-channel' }, [{ value: '', label: 'すべての経路' }].concat(
      filters.channels.map(function (c) {
        return { value: c.value, label: c.label, selected: criteria.channel === c.value };
      })
    ));

    var hospital = A.select({ id: 'f-hospital' }, [{ value: '', label: 'すべての会場' }].concat(
      filters.hospitals.map(function (h) {
        return {
          value: String(h.id),
          label: h.name + (h.is_visible ? '' : ' （非表示）'),
          selected: String(criteria.hospital_id) === String(h.id)
        };
      })
    ));

    // 옵션 검사. 선택지는 이미 `/reservations/filters` 가 주고 있었는데
    // 화면이 쓰지 않아, 「어느 예약이 어떤 검사를 신청했나」를 이 화면에서는
    // 볼 수도 거를 수도 없었다.
    //
    // **사용 안 함 검사도 목록에 남긴다.** 지난 예약이 그 검사를 달고 있으므로
    // 거를 수 있어야 한다.
    var option = A.select({ id: 'f-option' }, [{ value: '', label: 'すべてのオプション検査' }].concat(
      ((filters && filters.exam_options) || []).map(function (o) {
        return {
          value: String(o.id),
          label: o.name + (o.is_active ? '' : ' （無効）'),
          selected: String(criteria.option_id) === String(o.id)
        };
      })
    ));

    var from = A.input({ id: 'f-from', type: 'date', value: criteria.from });
    var to = A.input({ id: 'f-to', type: 'date', value: criteria.to });

    function submit() {
      A.go('reservations', {
        keyword: keyword.value.trim(),
        status: status.value,
        channel: channel.value,
        hospital_id: hospital.value,
        option_id: option.value,
        from: from.value,
        to: to.value,
        defect: criteria.defect,
        page: 1
      });
    }

    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
    });
    status.addEventListener('change', submit);
    channel.addEventListener('change', submit);
    hospital.addEventListener('change', submit);
    option.addEventListener('change', submit);
    from.addEventListener('change', submit);
    to.addEventListener('change', submit);

    var form = el('div.filters', {}, [
      A.field('検索', keyword),
      A.field('ステータス', status),
      A.field('受付経路', channel),
      A.field('会場', hospital),
      A.field('オプション検査', option),
      A.field('受診日（開始）', from),
      A.field('受診日（終了）', to),
      el('div.filters__actions', {}, [
        el('button.btn.btn--primary', { type: 'button', text: '検索', onClick: submit }),
        el('button.btn.btn--ghost', {
          type: 'button', text: 'リセット',
          onClick: function () { A.go('reservations', {}); }
        })
      ])
    ]);

    // 뷰 전환 토글 (Kanban vs Table)
    var btnKanban = el('button.view-toggle-btn' + (currentViewMode === 'kanban' ? '.active' : ''), {
      type: 'button', text: 'カンバンボード',
      onClick: function () { setViewMode('kanban'); }
    });
    var btnTable = el('button.view-toggle-btn' + (currentViewMode === 'table' ? '.active' : ''), {
      type: 'button', text: 'テーブル一覧',
      onClick: function () { setViewMode('table'); }
    });

    function setViewMode(mode) {
      currentViewMode = mode;
      localStorage.setItem('kenshin_res_view_mode', mode);
      A.render();
    }

    var viewToggleBar = el('div.view-toggle-bar', {}, [btnTable, btnKanban]);

    return A.card('詳細検索条件', {
      tools: [viewToggleBar],
      body: form
    });
  }

  /* ======================================================================
     결과 뷰 (칸반 보드 vs EMR 테이블 표)
     ====================================================================== */

  function buildResult(page, criteria, onRefresh) {
    if (currentViewMode === 'kanban') {
      return buildKanbanBoard(page.items, page, criteria, onRefresh);
    }
    return buildTableView(page, criteria);
  }

  /* ======================================================================
     칸반 보드 (Kanban Board) 뷰
     ====================================================================== */
  function buildKanbanBoard(items, page, criteria, onRefresh) {
    var pendingItems = items.filter(function (i) { return i.status === 'PENDING'; });
    var confirmedItems = items.filter(function (i) { return i.status === 'CONFIRMED'; });
    var cancelledItems = items.filter(function (i) { return i.status === 'CANCELLED'; });

    var colPending = buildKanbanColumn('仮・受付待ち', 'pending', pendingItems, onRefresh);
    var colConfirmed = buildKanbanColumn('予約確定', 'confirmed', confirmedItems, onRefresh);
    var colCancelled = buildKanbanColumn('キャンセル・整理', 'cancelled', cancelledItems, onRefresh);

    var board = el('div.kanban-board', {}, [colPending, colConfirmed, colCancelled]);

    var foot = A.pager(page.page, page.size, page.total, function (next) {
      A.go('reservations', Object.assign({}, criteria, { page: next }));
    });

    var container = el('div.kanban-container', {}, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;' }, [
        el('div.card__title', { text: '予約作業状況ボード（全 ' + A.fmt.number(page.total) + '件）' })
      ]),
      board
    ]);

    if (foot) container.appendChild(foot);

    return container;
  }

  function buildKanbanColumn(title, type, items, onRefresh) {
    var cardsSlot = el('div.kanban-cards');

    if (!items.length) {
      cardsSlot.appendChild(el('div.kanban-empty', { text: '該当するステータスの予約はありません。' }));
    } else {
      items.forEach(function (item) {
        cardsSlot.appendChild(buildKanbanCard(item, onRefresh));
      });
    }

    var col = el('div.kanban-col.kanban-col--' + type, {}, [
      el('div.kanban-col__header', {}, [
        el('span.kanban-col__title', { text: title }),
        el('span.kanban-col__count', { text: items.length })
      ]),
      cardsSlot
    ]);

    return col;
  }

  function buildKanbanCard(r, onRefresh) {
    var header = el('div.kanban-card__header', {}, [
      el('button.kanban-card__no', {
        type: 'button',
        title: 'クリックで予約番号をコピー',
        style: 'background:none;border:none;padding:0;font-weight:700;cursor:pointer;color:var(--a-ink);font-family:var(--font-mono);font-size:13px;display:inline-flex;align-items:center;gap:4px;',
        onClick: function (ev) {
          ev.stopPropagation();
          try {
            navigator.clipboard.writeText(r.reservation_no);
            A.toast('予約番号をコピーしました (' + r.reservation_no + ')', 'ok');
          } catch (e) {
            A.toast('予約番号: ' + r.reservation_no, 'info');
          }
        }
      }, [
        el('span', { text: r.reservation_no }),
        A.icon('copy', { size: 13, style: 'opacity:0.55;margin-left:2px;flex-shrink:0;' })
      ]),
      A.statusBadge(r.status, r.status_label, r.is_holiday)
    ]);

    var nameBlock = el('div.kanban-card__name', {}, [
      el('a', {
        href: '#/reservation?id=' + r.id,
        title: 'クリックで詳細を表示',
        style: 'color:var(--a-primary);font-weight:600;cursor:pointer;',
        onClick: function (ev) { ev.stopPropagation(); A.go('reservation', { id: r.id }); }
      }, [
        el('span', { text: r.full_name }),
        el('span.kanban-card__kana', { text: r.full_name_kana ? ' (' + r.full_name_kana + ')' : '' })
      ])
    ]);

    var infoBlock = el('div.kanban-card__info', {}, [
      el('div', {
        text: r.hospital_name,
        style: 'cursor:default;',
        onClick: function (ev) { ev.stopPropagation(); }
      }),
      el('div', { text: A.fmt.dateShort(r.slot_date) + ' ' + r.time_label }),
      el('div', { text: r.tel_primary || '連絡先なし' })
    ]);

    var optionNames = r.option_names || [];
    var badges = el('div.kanban-card__badges', {}, [
      el('span.badge.badge--' + (r.channel === 'POSTAL' ? 'info' : 'muted'), { text: r.channel_label }),
      r.has_defect ? el('span.badge.badge--danger', { text: '登録情報不備' }) : null,
      r.contact_count ? el('span.badge.badge--warn', { text: (r.contact_connected ? '連絡済 ' : '応答なし ') + r.contact_count + '回' }) : null,
      // 표 뷰와 같은 사실을 말한다. 카드는 좁으므로 건수만 적고 이름은 툴팁에.
      optionNames.length
        ? el('span.badge.badge--info', {
          text: 'オプション ' + optionNames.length + '件',
          title: optionNames.join(', ')
        })
        : null
    ].filter(Boolean));

    var actions = el('div.kanban-card__actions');

    var btnDetail = el('a.btn.btn--xs', {
      href: '#/reservation?id=' + r.id,
      text: '詳細',
      onClick: function (ev) {
        ev.stopPropagation();
        A.go('reservation', { id: r.id });
      }
    });
    actions.appendChild(btnDetail);

    return el('div.kanban-card.kanban-card--' + r.status.toLowerCase(), {}, [header, nameBlock, infoBlock, badges, actions]);
  }

  /* ======================================================================
     EMR 상태별 색상 강조 테이블 표 (EMR Table View)
     ====================================================================== */
  function buildTableView(page, criteria) {
    var items = page.items || [];

    var node = A.card('予約一覧', {
      desc: A.fmt.number(page.total) + '件（予約番号クリックでコピー / お名前クリックで詳細表示）',
      flush: true,
      body: A.table({
        columns: [
          {
            label: '予約番号', align: 'center', mono: true, width: '150px',
            render: function (r) {
              return el('button', {
                type: 'button',
                dataset: { tooltip: '予約番号をコピー' },
                style: 'background:none;border:none;padding:0;font-family:var(--font-mono);font-size:13.5px;font-weight:600;color:var(--a-ink);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:4px;',
                onClick: function (ev) {
                  ev.stopPropagation();
                  try {
                    navigator.clipboard.writeText(r.reservation_no);
                    A.toast('予約番号をコピーしました (' + r.reservation_no + ')', 'ok');
                  } catch (e) {
                    A.toast('予約番号: ' + r.reservation_no, 'info');
                  }
                }
              }, [
                el('span', { text: r.reservation_no }),
                A.icon('copy', { size: 13, style: 'opacity:0.55;margin-left:2px;flex-shrink:0;' })
              ]);
            }
          },
          {
            label: 'ステータス', align: 'center', width: '130px',
            render: function (r) {
              return A.statusBadge(r.status, r.status_label, r.is_holiday);
            }
          },
          {
            label: 'お名前', width: '120px',
            render: function (r) {
              return el('a', {
                href: '#/reservation?id=' + r.id,
                dataset: { tooltip: '詳細を表示' },
                style: 'color:var(--a-primary);font-weight:600;cursor:pointer;',
                onClick: function (ev) { ev.stopPropagation(); A.go('reservation', { id: r.id }); }
              }, r.full_name);
            }
          },
          {
            label: 'フリガナ', width: '130px',
            render: function (r) {
              return el('span.cell-sub', { text: r.full_name_kana || '—' });
            }
          },
          {
            label: '性別/生年月日', width: '135px',
            render: function (r) {
              return el('span', { style: 'font-size:13px;' }, (r.gender_label || '') + ' ' + (r.birth_date || ''));
            }
          },
          {
            label: '受診会場',
            render: function (r) {
              return el('div', {
                style: 'cursor:default;user-select:text;',
                onClick: function (ev) { ev.stopPropagation(); }
              }, r.hospital_name);
            }
          },
          {
            label: '受診日時', width: '150px',
            render: function (r) {
              return el('span', {
                style: 'font-size:13px;',
                text: A.fmt.dateShort(r.slot_date) + ' ' + (r.time_label || '')
              });
            }
          },
          {
            // 무엇을 신청했는지가 목록에 보여야, 전화 응대 중에 상세를
            // 열지 않고 답할 수 있다. 세 개 이상은 「+N」으로 접고 전부는
            // 툴팁에 담는다 — 행 높이가 예약마다 달라지면 표가 읽기 어려워진다.
            label: 'オプション検査', align: 'center', width: '190px',
            render: function (r) {
              var names = r.option_names || [];
              if (!names.length) return el('span.cell-sub', { text: '—' });

              var box = el('div.cell-marks', {
                style: 'display:inline-flex;gap:4px;flex-wrap:wrap;justify-content:center;'
              });
              names.slice(0, 2).forEach(function (n) {
                box.appendChild(el('span.badge.badge--info', { text: n, title: n }));
              });
              if (names.length > 2) {
                box.appendChild(el('span.badge.badge--muted', {
                  text: '+' + (names.length - 2),
                  title: names.join(', ')
                }));
              }
              return box;
            }
          },
          {
            label: '連絡先', width: '135px',
            render: function (r) {
              if (!r.tel_primary) return el('span.cell-sub', { text: '—' });
              return el('span', { style: 'font-size:13px;color:var(--a-ink);', text: r.tel_primary });
            }
          },
          {
            label: '経路', align: 'center', width: '80px',
            render: function (r) {
              var isPostal = (r.channel === 'POSTAL' || r.channel_label === '郵送' || String(r.channel_label).indexOf('郵送') !== -1);
              // 모서리를 지정하지 않는다. .badge 가 이미 타원(999px)이며,
              // 여기서 4px 로 덮으면 같은 배지가 화면마다 다른 모양이 된다.
              var badgeStyle = (isPostal
                ? 'background:#E8F5E9;color:#2E7D32;'
                : 'background:#E3F2FD;color:#1565C0;')
                + 'font-weight:700;padding:3px 10px;font-size:12px;';
              return el('span.badge', {
                style: badgeStyle,
                text: isPostal ? '郵送' : 'WEB'
              });
            }
          },
          {
            label: '表示', align: 'center', width: '110px',
            render: function (r) {
              var marks = el('div.cell-marks', { style: 'display:inline-flex;justify-content:center;gap:4px;' });
              if (r.has_defect) {
                marks.appendChild(el('span.badge.badge--danger', { text: '登録情報不備' }));
              }
              if (r.contact_count) {
                // 취소 대상은 3회 **미연결**이다. 횟수만 적으면 통화가 된 건과
                // 부재중 세 번이 같은 배지로 보여, 뒷사람이 건너뛴다.
                marks.appendChild(r.contact_connected
                  ? el('span.badge.badge--ok', {
                    text: '連絡済',
                    title: '連絡履歴があります（合計 ' + r.contact_count + '回試行）'
                  })
                  : el('span.badge.badge--warn', {
                    text: '応答なし ' + r.contact_count + '回',
                    title: '3回連絡しても応答がない場合はキャンセル対象となります。'
                  }));
              }
              if (!r.email) {
                marks.appendChild(el('span.badge.badge--muted', {
                  text: 'メールアドレス未登録', title: '確認・リマインドメールを送信できません。'
                }));
              }
              return marks.childNodes.length ? marks : '—';
            }
          }
        ],
        rows: page.items,
        rowClass: function (r) {
          if (r.status === 'CANCELLED') return 'emr-row-cancelled';
          if (r.status === 'PENDING' || r.has_defect) return 'emr-row-pending';
          return 'emr-row-confirmed';
        },
        empty: {
          title: '条件に一致する予約がありません',
          desc: '検索キーワードを減らすか、期間を広げてみてください。'
        }
      })
    });

    var foot = A.pager(page.page, page.size, page.total, function (next) {
      A.go('reservations', Object.assign({}, criteria, { page: next }));
    });
    if (foot) node.appendChild(foot);

    return node;
  }

})();
