/* ==========================================================================
   accounts.js — A-50 관리자 계정 관리
   --------------------------------------------------------------------------
   L3(시스템 관리자) 전용.

   계정을 **삭제하지 않는다.** 정지(사용 안 함)만 한다.
   계정을 지우면 그 사람이 남긴 조작 로그의 주인이 사라져,
   「누가 이 예약을 취소했는가」에 답할 수 없게 된다 (자체 피드백 M-8).
   화면에도 삭제 버튼을 두지 않는다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  var roles = null;
  var allRows = [];
  var criteria = { keyword: '', role: '', status: '' };

  function applyFilters(rows) {
    var keyword = criteria.keyword.trim().toLowerCase();

    return rows.filter(function (a) {
      if (keyword) {
        var haystack = [a.login_id, a.name, a.email].join(' ').toLowerCase();
        if (haystack.indexOf(keyword) === -1) return false;
      }
      if (criteria.role && a.role !== criteria.role) return false;
      if (criteria.status === 'active' && !a.is_active) return false;
      if (criteria.status === 'inactive' && a.is_active) return false;
      return true;
    });
  }

  A.route('accounts', function (view) {
    A.setTitle('アカウント管理', '管理画面を使う担当者と権限の管理', [
      el('button.btn.btn--sm.btn--primary', {
        type: 'button', text: '＋ アカウント登録',
        onClick: function () { openEditor(view, null); }
      })
    ]);

    criteria = { keyword: '', role: '', status: '' };

    var ready = roles
      ? Promise.resolve()
      : A.api.get('/accounts/roles').then(function (body) { roles = body.data; });

    ready
      .then(function () { return A.api.get('/accounts'); })
      .then(function (body) {
        allRows = body.data;
        draw(view, allRows);
      })
      .catch(function (error) { A.fail(view, error); });
  });

  function load(view) {
    A.api.get('/accounts')
      .then(function (body) {
        allRows = body.data;
        draw(view, allRows);
      })
      .catch(function (error) { A.fail(view, error); });
  }

  function draw(view, rows) {
    A.clear(view);

    // 권한 설명 -------------------------------------------------------------
    view.appendChild(A.card('権限3段階', {
      desc: '上位権限は下位権限の機能をすべて含みます。',
      flush: true,
      body: A.table({
        columns: [
          { label: 'レベル', width: '70px', render: function (r) { return 'L' + r.level; } },
          { label: '権限', width: '140px', render: function (r) { return r.label; } },
          { label: 'できること', wrap: true, render: function (r) { return r.can; } },
          {
            label: '人数', align: 'right', width: '70px',
            render: function (r) {
              return rows.filter(function (a) {
                return a.role === r.value && a.is_active;
              }).length + '名';
            }
          }
        ],
        rows: roles,
        empty: { title: '', desc: '' }
      })
    }));

    var tableBox = el('div');
    view.appendChild(buildFilterCard(view, tableBox));
    view.appendChild(tableBox);

    renderTable(view, tableBox, rows);

    // 使い方は「使い方」ボタンへ移した (guide.js)。常時表示すると表がその分狭くなる。
  }

  function renderTable(view, tableBox, rows) {
    A.clear(tableBox);

    var shown = applyFilters(rows);
    var isFiltered = shown.length !== rows.length;

    // 계정 목록 -------------------------------------------------------------
    tableBox.appendChild(A.card(
      isFiltered ? 'アカウント ' + shown.length + '件（全体 ' + rows.length + '）' : 'アカウント ' + rows.length + '件',
      {
        flush: true,
        body: A.table({
          columns: [
            { label: 'ログイン ID', mono: true, render: function (a) { return a.login_id; } },
            { label: '担当者', render: function (a) { return a.name; } },
            { label: 'メールアドレス', dim: true, render: function (a) { return a.email; } },
            {
              label: '権限', width: '150px',
              render: function (a) {
                var tone = { 3: 'danger', 2: 'info', 1: 'muted' }[a.level] || 'muted';
                return el('span.badge.badge--' + tone, {
                  text: 'L' + a.level + ' ' + a.role_label
                });
              }
            },
            {
              label: 'ステータス', width: '90px',
              render: function (a) {
                return el('span.badge.badge--' + (a.is_active ? 'ok' : 'muted'), {
                  text: a.is_active ? '有効' : '停止'
                });
              }
            },
            { label: '最終ログイン', dim: true,
              render: function (a) { return A.fmt.datetime(a.last_login_at); } },
            { label: '登録日', dim: true,
              render: function (a) { return A.fmt.datetime(a.created_at); } },
            {
              label: '', width: '150px',
              render: function (a) {
                return el('div', { style: 'display:flex;gap:6px' }, [
                  el('button.btn.btn--sm', {
                    type: 'button', text: '修正',
                    onClick: function () { openEditor(view, a); }
                  }),
                  el('a.btn.btn--sm', {
                    href: '#/audit-logs?admin_user_id=' + a.id, text: '操作ログ'
                  })
                ]);
              }
            }
          ],
          rows: shown,
          empty: isFiltered
            ? { title: '条件に一致するアカウントがありません', desc: '検索キーワードやフィルターをクリアして再度お試しください。' }
            : { title: 'アカウントがありません', desc: '' }
        })
      }
    ));
  }

  /* ======================================================================
     검색 · 필터 바
     ====================================================================== */

  function buildFilterCard(view, tableBox) {
    var keyword = A.input({
      value: criteria.keyword,
      placeholder: 'ログインID・担当者名・メールアドレス',
      autocomplete: 'off'
    });

    var role = A.select({}, [{ value: '', label: 'すべての権限' }].concat(
      roles.map(function (r) {
        return { value: r.value, label: 'L' + r.level + ' ' + r.label, selected: criteria.role === r.value };
      })
    ));

    var status = A.select({}, [
      { value: '', label: 'すべてのステータス' },
      { value: 'active', label: '利用中', selected: criteria.status === 'active' },
      { value: 'inactive', label: '停止', selected: criteria.status === 'inactive' }
    ]);

    function rerender() {
      criteria.keyword = keyword.value;
      criteria.role = role.value;
      criteria.status = status.value;

      renderTable(view, tableBox, allRows);
    }

    keyword.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); rerender(); }
    });
    role.addEventListener('change', rerender);
    status.addEventListener('change', rerender);

    var form = el('div.filters.filters--compact', {}, [
      A.field('検索', keyword),
      A.field('権限', role),
      A.field('ステータス', status),
      el('div.filters__actions', {}, [
        el('button.btn.btn--primary', {
          type: 'button', text: '検索',
          onClick: function () { rerender(); }
        }),
        el('button.btn.btn--ghost', {
          type: 'button', text: 'リセット',
          onClick: function () {
            criteria = { keyword: '', role: '', status: '' };
            keyword.value = '';
            role.value = '';
            status.value = '';
            renderTable(view, tableBox, allRows);
          }
        })
      ])
    ]);

    return A.card('検索条件', { body: form });
  }

  /* ======================================================================
     등록 · 수정
     ====================================================================== */

  function openEditor(view, a) {
    var isNew = !a;
    a = a || { login_id: '', name: '', email: '', role: 'STAFF', is_active: true };

    var f = {
      login_id: A.input({
        value: a.login_id, disabled: !isNew, autocomplete: 'off',
        autocapitalize: 'off', spellcheck: false
      }),
      name: A.input({ value: a.name }),
      email: A.input({ value: a.email, type: 'email' }),
      role: A.select({}, roles.filter(function (r) {
        // 서버가 `selectable: false` 로 표시한 권한(L3)은 고를 수 없다.
        // 이미 그 권한인 계정을 수정할 때만 자기 값이 보이도록 남긴다 —
        // 빼 버리면 L3 본인의 이름·메일조차 저장할 수 없게 된다.
        // 서버도 같은 판정을 한 번 더 한다 (`admin_auth_service`).
        if (r.selectable === false && a.role !== r.value) {
          return false;
        }
        return true;
      }).map(function (r) {
        return {
          value: r.value,
          label: 'L' + r.level + ' ' + r.label,
          selected: a.role === r.value
        };
      })),
      password: A.input({ type: 'password', autocomplete: 'new-password' })
    };

    var activeBox = A.checkbox('このアカウントを有効にする', { checked: a.is_active });
    var roleHint = el('p.field__hint');

    function updateRoleHint() {
      var role = roles.filter(function (r) { return r.value === f.role.value; })[0];
      roleHint.textContent = role ? role.can : '';
    }
    f.role.addEventListener('change', updateRoleHint);
    updateRoleHint();

    A.modal({
      title: isNew ? 'アカウント登録' : 'アカウント修正 — ' + a.login_id,
      body: [
        el('div.grid.grid--2', {}, [
          A.field('ログイン ID', f.login_id, {
            required: isNew,
            hint: isNew ? '登録後は変更できません。' : '変更できません。'
          }),
          A.field('担当者名', f.name, { required: true }),
          A.field('メールアドレス', f.email),
          A.field('権限', f.role, { required: true }),
          A.field(isNew ? 'パスワード' : '新しいパスワード', f.password, {
            span: 'span-2',
            required: isNew,
            hint: isNew
              ? '8文字以上。登録後は再確認できませんので、担当者に直接お伝えください。'
              : '未入力の場合はパスワードを変更しません。'
          }),
          el('div.field', { style: 'justify-content:flex-end' }, activeBox)
        ]),
        el('div', { style: 'margin-top:10px' }, roleHint)
      ],
      actions: [
        { label: 'キャンセル' },
        {
          label: isNew ? '登録' : '保存',
          tone: 'primary',
          onClick: function () {
            var payload = {
              name: f.name.value.trim(),
              email: f.email.value.trim(),
              role: f.role.value,
              is_active: activeBox.querySelector('input').checked,
              password: f.password.value
            };

            var call;
            if (isNew) {
              payload.login_id = f.login_id.value.trim();
              if (payload.password.length < 8) {
                A.toast('パスワードは8文字以上である必要があります。', 'warn');
                return Promise.reject(new Error('weak password'));
              }
              call = A.api.post('/accounts', payload);
            } else {
              call = A.api.put('/accounts/' + a.id, payload);
            }

            return call.then(function (body) {
              A.toast(body.message, 'ok');
              load(view);
            }).catch(function (error) {
              A.toast(error.message, 'danger');
              throw error;
            });
          }
        }
      ]
    });
  }

})();
