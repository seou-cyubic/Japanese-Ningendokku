/* ==========================================================================
   guide.js — 화면마다의 사용법을 「使い方」 뒤에 둔다
   --------------------------------------------------------------------------
   예전에는 화면 위에 파란 띠로 늘 깔려 있었다. 늘 보이니 늘 62px 을 먹었고,
   한 번 익힌 담당자에게는 그만큼 표가 줄어드는 대가만 남았다.

   그래서 아이콘 뒤로 옮긴다.
     · 늘 차지하는 자리 0 — 닫혀 있을 때는 흔적이 없다.
     · 옆으로 미는 패널이 아니라 **떠 있는 팝업**이다. 패널은 본문 1017px 중
       400px 을 덮는데, 이 표들은 이미 가로로 넘쳐 스크롤한다. 가이드를 보려고
       연 사람이 정작 표의 오른쪽을 못 보게 된다.
     · **화면 아무 데나 누르면 닫힌다.** 창구는 바쁘다. 닫는 법을 따로 익혀야
       하는 창은 열린 채 남아 표를 가린다. 표를 누르는 그 동작이 곧 닫는
       동작이 되게 둔다.

   화면 위에 늘 깔려 있던 파란·노란 띠(「후리가나가 빈 회장이 있다」 등)는
   건수를 띄우는 대신, **그 띠가 설명하던 것**을 여기 사용법으로 풀어 쓴다.
   몇 곳인지는 표의 상태 열과 검색 조건이 이미 보여 준다.

   글을 쓰는 법 : 하려는 **일 단위**로 끊는다. 한 단계를 머리에 담고 표로
   돌아갈 수 있어야 하므로, 한 토막은 두세 줄을 넘기지 않는다.
   ========================================================================== */

(function () {
  'use strict';

  /* ----------------------------------------------------------------------
     화면별 사용법.  키는 라우트 이름(A.setTitle 을 부르는 화면).
     [소제목, 본문, 'warn' 이면 눈에 띄게]
     ---------------------------------------------------------------------- */
  var GUIDE = {
    'search': {
      title: '検索結果',
      items: [
        ['探せるもの',
         '氏名（漢字・ひらがな・カタカナ）・予約番号・電話番号（4桁以上）・メールアドレス・' +
         '生年月日・会場名/フリガナ/コード・検査名で、予約・会場・オプション検査・' +
         '操作ログをまとめて探します。'],
        ['予約番号を電話で聞いたとき',
         '大文字・小文字はそのままでかまいません。0とO、1とlとIも同じものとして' +
         '探しますので、聞き取れたとおりに入力してください。2件出たときは生年月日で' +
         '見分けてください。'],
        ['生年月日で探す',
         '「1958-11-03」「S33.11.3」「昭和33年11月3日」のどの形でも探せます。' +
         '「1958」だけならその年生まれ全員です。「佐藤 1958-11-03」のように' +
         '空白で区切ると、両方に当てはまる予約だけに絞れます。'],
        ['件数の見かた',
         '上の件数で、どこに該当があるかが分かります。件数を押すと、その種類だけを' +
         '表示します。予約が数百件のときは一覧を読まず「予約検索で絞り込む」へ進み、' +
         '会場や受診日で絞ってください。'],
        ['同姓同名のとき',
         'お電話では生年月日を伺うのが最も早い確認方法です。聞いた生年月日を' +
         '氏名のあとに続けて入力してください。行の生年月日には和暦（S33 など）も' +
         '添えています。'],
        ['会場が見つかったとき',
         '「会場管理」は所在地などの編集、「定員管理」は開催回ごとの定員へ進みます。' +
         'その会場の予約は、すぐ下の「その会場の予約」に続けて表示します。'],
        ['結果が1件のとき',
         '予約番号などで該当が1件だけのときは、この画面を通らず、その予約の詳細を' +
         '直接開きます。']
      ]
    },

    'postal-bulk': {
      title: '郵送受付一括入力',
      items: [
        ['入力する',
         'セルをクリックしてそのまま入力できます。Excel で複数セルをコピーし、' +
         '開始セルをクリックして Ctrl+V で貼り付けられます。'],
        ['ファイルから読み込む',
         'CSV・Excel ファイルは「読み込み」を押すか、表の上にドラッグしてください。'],
        ['希望の日時',
         '第1希望が満席の場合は、第2・第3希望へ自動で繰り下がります。' +
         '郵送でも定員を超えて受け付けることはありません。']
        // 「保存のきまり」は画面いちばん上に常時表示しているため、ここには置かない。
      ]
    },

    'bulk-capacity': {
      title: '定員管理',
      items: [
        ['締め切る（右クリック）',
         'セルを右クリックすると、その時間帯だけ締め切り・解除ができます。' +
         '締切は「定員保存」を押した時点で予約画面に反映されます。', 'warn'],
        ['表の見かた',
         '1行が1つの開催回です。セルの数字はその時間帯の定員で、' +
         '隣の小さい数字はすでに予約済みの人数です。'],
        ['空欄と 0 の違い',
         '空欄は「その時間帯を開けない」という意味です。0 は枠はあるが満席で、' +
         '空欄とは別です。', 'warn'],
        ['定員を下げるとき',
         '予約済みの人数を下回る定員は保存できません。そのセルに理由が表示されます。']
      ]
    },

    'bulk-venues': {
      title: '会場管理',
      items: [
        ['表の見かた',
         '1行が1つの会場です。開催日と定員はこの表にありません —「定員管理」で扱います。'],
        ['状態欄の見かた',
         '「日程未登録」は開催日程が一度も登録されておらず、利用者画面に表示されません。' +
         '「今期終了」は過去の日程がすべて終了した会場です（今後の開催回なし）。' +
         '「位置情報未設定」は緯度・経度が空で、地図の位置がずれることがあります。' +
         '「フリガナ未登録」は管理画面のクイック検索でひらがなから探せません。' +
         '利用者画面への影響はありません。'],
        ['利用者画面に出ない会場',
         '「予約画面に表示」が「いいえ」の会場、受付締切日を過ぎた会場、' +
         '今後の開催回がない会場は、利用者画面の会場一覧から外れます。' +
         '既存の予約はそのまま残り、郵送受付も引き続き登録できます。' +
         '検索条件の「受付状態」で絞り込めます。'],
        ['入力する',
         'セルを押してそのまま編集できます。Excel からコピーした複数セルは、' +
         '開始セルをクリックして Ctrl+V で貼り付けられます。'],
        ['古い表を取り込む',
         '列の並び順が以前と異なります。古い表は貼り付けず「読み込み」をお使いください。' +
         '見出し行を見て、列を自動で対応づけます。'],
        ['削除する',
         '行を右クリックしてください。今後の予約がある会場は削除できません。'],
        ['保存のきまり',
         '1セルでもエラーがあれば、1件も保存しません。' +
         'この表にない会場は削除されません。', 'warn']
      ]
    },

    'bulk-exam-options': {
      title: 'オプション検査管理',
      items: [
        ['対象条件',
         '条件に合わない検査は、利用者画面の選択肢にそもそも表示されません。' +
         'グレー表示にしないのは、「なぜ申し込めないのか」という問い合わせを' +
         '生まないためです。'],
        ['料金',
         'この表に金額の欄はありません。受診当日に会場でお支払いいただきます。'],
        ['削除する',
         '行を右クリックしてください。申込済みの予約があると削除できません。' +
         '新規の申込だけを止めるなら「予約画面に表示」を「いいえ」にします。'],
        ['申込状況を見る',
         '行を右クリックして「予約一覧を見る」を押すと、その検査を申し込んだ予約一覧へ' +
         '移動します。']
      ]
    },

    'accounts': {
      title: 'アカウント管理',
      items: [
        ['この画面でできること',
         '管理画面を使う担当者の登録・修正・停止と、その担当者が何をしたか' +
         '（操作ログ）の確認ができます。上の表は権限3段階と、いま何名いるかです。'],
        ['担当者を登録する',
         '右上の「＋ アカウント登録」を押します。ログインID・担当者名・権限・' +
         'パスワードが必須です。'],
        ['ログインIDは後から変えられない',
         '登録すると変更できません。操作ログがこのIDで残るためです。' +
         '担当者名やメールアドレスは後からでも直せます。', 'warn'],
        ['権限は3段階',
         'L1 一般スタッフは予約検索・修正・キャンセルと郵送受付の入力。' +
         'L2 業務管理者はそれに会場・定員・オプション検査の管理が加わります。' +
         'L3 システム管理者は全機能です。上位は下位をすべて含みます。'],
        ['パスワード',
         '8文字以上。登録後は再表示できないため、担当者へ直接お伝えください。' +
         '忘れた場合は「修正」から新しいパスワードに変えます。'],
        ['削除せず「停止」にする',
         'アカウントを削除すると、その担当者が残した操作ログが' +
         '誰の操作だったのか分からなくなります。使わなくなったら' +
         '「このアカウントを有効にする」のチェックを外して停止してください。', 'warn'],
        ['誰が何をしたか見る',
         '一覧の「操作ログ」を押すと、その担当者の操作だけを絞り込んで表示します。']
      ]
    }
  };

  var current = null;      // 지금 화면의 가이드
  var pop = null;          // 열려 있는 팝업
  var btn = null;          // 「使い方」 단추

  function close() {
    if (pop) { pop.remove(); pop = null; }
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
      btn.classList.remove('is-open');
    }
  }

  function open() {
    if (!current || pop) return;
    pop = document.createElement('div');
    pop.className = 'guide-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', current.title + ' の使い方');

    var head = document.createElement('div');
    head.className = 'guide-pop__head';
    var name = document.createElement('span');
    name.className = 'guide-pop__title';
    name.textContent = current.title;
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'guide-pop__x';
    x.setAttribute('aria-label', '閉じる');
    x.textContent = '×';
    x.addEventListener('click', function (e) { e.stopPropagation(); close(); });
    head.appendChild(name);
    head.appendChild(x);
    pop.appendChild(head);

    var body = document.createElement('div');
    body.className = 'guide-pop__body';

    current.items.forEach(function (item) {
      var h = document.createElement('h4');
      h.textContent = item[0];
      var p = document.createElement('p');
      p.textContent = item[1];
      if (item[2] === 'warn') p.className = 'guide-pop__warn';
      body.appendChild(h);
      body.appendChild(p);
    });
    pop.appendChild(body);

    document.body.appendChild(pop);

    // 단추 아래에 붙이되, 오른쪽 끝을 넘지 않게 한다
    var r = btn.getBoundingClientRect();
    pop.style.top = (r.bottom + 10) + 'px';
    var left = r.right - pop.offsetWidth;
    pop.style.left = Math.max(12, Math.min(left, innerWidth - pop.offsetWidth - 12)) + 'px';

    // 팝업 안을 누른 것은 「바깥」이 아니다
    pop.addEventListener('click', function (e) { e.stopPropagation(); });

    btn.setAttribute('aria-expanded', 'true');
    btn.classList.add('is-open');
  }

  function toggle(e) {
    e.stopPropagation();
    if (pop) close(); else open();
  }

  /** 화면이 바뀔 때마다 불린다 (core.js 의 setTitle). */
  function mount(r) {
    close();
    if (btn) { btn.remove(); btn = null; }
    current = GUIDE[r] || null;
    if (!current) return;

    var actions = document.getElementById('view-tools');
    if (!actions) return;

    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--sm guide-btn';   // 옆 단추와 같은 크기·모양을 쓴다
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">' +
      '<circle cx="12" cy="12" r="9"></circle>' +
      '<path d="M9.6 9.2a2.5 2.5 0 1 1 3.2 2.6c-.6.2-.8.7-.8 1.3v.4"></path>' +
      '<path d="M12 17h.01"></path></svg><span>使い方</span>';
    btn.addEventListener('click', toggle);
    actions.insertBefore(btn, actions.firstChild);
  }

  // 화면 아무 데나 누르면 닫힌다 — 표를 누르는 동작이 곧 닫는 동작이다
  document.addEventListener('click', function () { if (pop) close(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && pop) close();
  });
  addEventListener('resize', close);

  window.AdminGuide = { mount: mount, close: close, has: function (r) { return !!GUIDE[r]; } };
})();
