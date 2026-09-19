/* ==========================================================================
   system-data.js — 시스템 데이터 상태
   --------------------------------------------------------------------------
   지금은 우편번호(주소) 데이터 하나를 본다.

   왜 화면이 필요한가
   ------------------
   「주소 찾기」가 그 데이터 위에서 돈다. 없으면 이용자 화면의 검색이 아무것도
   못 찾는데, 그 사실이 **서버 로그에만** 남는다. 담당자는 서버 콘솔을 볼 수
   없으므로, 「주소가 검색이 안 돼요」라는 문의가 들어와야 비로소 알게 된다.

   서버가 뜰 때 자동으로 채우게 해 두었지만(main.py 의 lifespan), 인터넷이
   막힌 환경이나 일본우편이 배포 형식을 바꾼 경우에는 실패한다. 그때
   **무엇이 어떻게 안 되고 있는지**와 **다시 시도하는 버튼**이 여기 있다.

   적재는 1~2분 걸리고 백그라운드로 돈다. 그래서 이 화면은 누른 뒤 상태를
   **스스로 다시 물어본다** — 사람이 새로고침을 누르게 두면 「눌렀는데
   아무 일도 안 일어난다」로 읽힌다.
   ========================================================================== */

(function () {
  'use strict';

  var A = Admin;
  var el = A.el;

  // 적재 중일 때 상태를 다시 묻는 주기. 12만 건에 1~2분이라 5초면 충분하다.
  var POLL_MS = 5000;

  var timer = null;

  var TONE = {
    READY:    { tone: 'ok',     label: '正常' },
    RUNNING:  { tone: 'info',   label: '取り込み中' },
    MISSING:  { tone: 'warn',   label: 'データなし' },
    DISABLED: { tone: 'warn',   label: '自動取り込み無効' },
    FAILED:   { tone: 'danger', label: '取り込み失敗' }
  };

  A.route('system-data', function (view) {
    A.setTitle('システムデータ', '利用者画面が参照する基準データの状態');
    stopPolling();
    load(view);
  });

  function stopPolling() {
    if (timer) { window.clearTimeout(timer); timer = null; }
  }

  function load(view) {
    A.api.get('/system/postal-status')
      .then(function (body) {
        // 화면을 옮긴 뒤에 응답이 오면 남의 화면에 그린다.
        if (A.parseHash().name !== 'system-data') { stopPolling(); return; }
        draw(view, body.data);
      })
      .catch(function (error) { stopPolling(); A.fail(view, error); });
  }

  function draw(view, data) {
    A.clear(view);

    var meta = TONE[data.state] || TONE.MISSING;
    var enough = data.count >= data.minimum;

    if (data.state === 'READY') {
      view.appendChild(A.notice('warn',
        '利用者画面の「住所検索」がこのデータを使用します。日本郵便が毎月' +
        '更新するため、半年に1回程度再取り込みすることをおすすめします。'));
    } else if (data.state === 'RUNNING') {
      view.appendChild(A.notice('info',
        '現在取り込み中です。1～2分かかり、完了するまで利用者画面の' +
        '「住所検索」は「直接ご入力ください」と案内されます。' +
        'この画面は自動で状態を再確認します。'));
    } else {
      view.appendChild(A.notice('danger',
        '郵便番号データがないため、利用者画面の「住所検索」が動作しません。' +
        '利用者は郵便番号と住所を直接入力する必要があります。' +
        '下の「今すぐ取り込み」を押してください。'));
    }

    view.appendChild(A.card('郵便番号（住所）データ', {
      desc: '日本郵便 KEN_ALL — 利用者画面「住所検索」の元データ',
      tools: buildTools(view, data),
      body: el('div.datastat', {}, [
        statRow('ステータス', el('span.badge.badge--' + meta.tone, { text: meta.label })),
        statRow('取り込み件数', el('span', {
          text: A.fmt.number(data.count) + '件' +
                (enough ? '' : ' (基準 ' + A.fmt.number(data.minimum) + '件未満)')
        })),
        statRow('最終取り込み', el('span', { text: A.fmt.datetime(data.finished_at) })),
        statRow('自動取り込み', el('span', {
          text: data.auto_import
            ? '有効 — サーバー起動時に未登録の場合は自動で取り込みます。'
            : '無効 — POSTAL_AUTO_IMPORT=true に設定すると自動で取り込みます。'
        })),
        statRow('取得元', el('span.mono', { text: data.source })),
        data.message
          ? statRow('メッセージ', el('span', { text: data.message }))
          : null
      ])
    }));

    if (data.state === 'RUNNING') {
      timer = window.setTimeout(function () { load(view); }, POLL_MS);
    }
  }

  function statRow(label, value) {
    return el('div.datastat__row', {}, [
      el('span.datastat__label', { text: label }),
      el('span.datastat__value', {}, [value])
    ]);
  }

  function buildTools(view, data) {
    // 적재는 L3 만. 12만 건을 지우고 다시 넣는 일이라 아무나 누를 것이 아니다.
    if (!A.me || A.me.level < 3) {
      return [el('span.field__hint', {
        text: '取り込みはシステム管理者のみ実行できます。'
      })];
    }

    var running = data.state === 'RUNNING';

    return [el('button.btn.btn--sm' + (running ? '' : '.btn--primary'), {
      type: 'button',
      text: running ? '取り込み中…' : (data.count ? '再取り込み' : '今すぐ取り込み'),
      disabled: running,
      title: '日本郵便からダウンロードして全件入れ替えます。1～2分かかります。',
      onClick: function () { confirmImport(view, data); }
    })];
  }

  function confirmImport(view, data) {
    A.confirm({
      title: data.count ? '郵便番号データを再取り込みしますか？' : '郵便番号データを取り込みますか？',
      message: data.count
        ? '現在登録されている ' + A.fmt.number(data.count) + '件を削除し、最新データを取り込みます。'
        : '日本郵便から約12万件をダウンロードして取り込みます。',
      detail: '1～2分かかり、バックグラウンドで処理されます。その間、利用者画面の' +
              '「住所検索」は「直接ご入力ください」と案内されます。' +
              '予約受付自体は停止しません。',
      okLabel: '取り込む',
      tone: 'primary'
    }).then(function (yes) {
      if (!yes) return;

      A.api.post('/system/postal-import')
        .then(function (body) {
          A.toast(body.message, 'ok');
          load(view);
        })
        .catch(function (error) { A.toast(error.message, 'danger'); });
    });
  }

})();
