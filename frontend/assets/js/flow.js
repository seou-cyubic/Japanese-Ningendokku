/* ==========================================================================
   flow.js — 예약 흐름의 단계를 한 곳에서 관리한다
   --------------------------------------------------------------------------
   예약은 다섯 단계이며, 입구는 하나다.

       ① 회장 · 일시 선택 → ② 본인 확인 → ③ 정보 입력 → ④ 정보 확인 → ⑤ 예약 완료
          schedule.html      verify.html    form.html     confirm.html  complete.html

   **남은 자리를 먼저 보여 준 뒤 본인 확인을 받는다.** 개인정보를 다 넣고 나서
   「그 날은 자리가 없습니다」를 듣는 것이 가장 나쁜 순서이기 때문이다.
   빈자리를 보는 것과 예약하는 것이 같은 길이므로 입구를 나누지 않는다.
   (plan.md P-10 / U-30)

   순서·번호·이전 링크를 여기 한 곳에만 둔다. 화면마다 「5단계 중 3단계」를
   박아 두면, 순서를 한 번 바꿀 때 어느 한 화면이 빠져서 이용자가 자기가
   어디쯤 왔는지 알 수 없게 된다.

   각 화면은 진행 표시 요소에 자기 단계를 적어 두기만 하면 된다.

       <div class="progress" data-step="verify"> … </div>
   ========================================================================== */

(function () {
  'use strict';

  var flowStart = 'slot';
  try {
    flowStart = sessionStorage.getItem('kenshin.flowStart') || 'slot';
  } catch (e) {}

  var STEPS = flowStart === 'verify' ? [
    { id: 'verify', label: '本人確認',        href: 'verify.html' },
    { id: 'slot',   label: '会場・日時の選択', href: 'schedule.html' },
    { id: 'info',   label: '情報の入力',        href: 'form.html' },
    { id: 'check',  label: '内容の確認',        href: 'confirm.html' },
    { id: 'done',   label: '予約完了',        href: 'complete.html' }
  ] : [
    { id: 'slot',   label: '会場・日時の選択', href: 'schedule.html' },
    { id: 'verify', label: '本人確認',        href: 'verify.html' },
    { id: 'info',   label: '情報の入力',        href: 'form.html' },
    { id: 'check',  label: '内容の確認',        href: 'confirm.html' },
    { id: 'done',   label: '予約完了',        href: 'complete.html' }
  ];

  // 첫 단계에서 「이전」은 메인 화면이다.
  var HOME = '../index.html';

  function indexOf(stepId) {
    for (var i = 0; i < STEPS.length; i += 1) {
      if (STEPS[i].id === stepId) return i;
    }
    return -1;
  }

  /** 그 화면에서 「이전 단계로」가 가리켜야 할 곳. 첫 단계면 메인. */
  function prevHref(stepId) {
    var i = indexOf(stepId);
    return i <= 0 ? HOME : STEPS[i - 1].href;
  }

  function isFirst(stepId) {
    return indexOf(stepId) === 0;
  }

  /* ----------------------------------------------------------------------
     진행 표시 다시 그리기
     ---------------------------------------------------------------------- */

  function applyProgress(root, at) {
    var human = at + 1;                                  // 1-based
    var percent = Math.round(human / STEPS.length * 100);

    var count = root.querySelector('.progress__count span');
    if (count) count.textContent = String(human);

    var bar = root.querySelector('.progress__bar');
    if (bar) {
      bar.setAttribute('aria-valuenow', String(human));
      bar.setAttribute('aria-valuemax', String(STEPS.length));
    }

    var fill = root.querySelector('.progress__fill');
    if (fill) fill.style.width = percent + '%';

    var ol = root.querySelector('.progress__steps');
    if (!ol) return;

    ol.textContent = '';
    STEPS.forEach(function (step, i) {
      var li = document.createElement('li');
      li.className = 'progress__step';
      li.textContent = step.label;
      if (i === at) li.setAttribute('aria-current', 'step');
      // 지나온 단계에 표시를 남긴다. 「어디까지 왔는지」가 보여야
      // 남은 단계가 몇 개인지 가늠할 수 있다.
      if (i < at) li.classList.add('is-done');
      ol.appendChild(li);
    });
  }

  /* ----------------------------------------------------------------------
     예약을 그만두고 나가기 전 확인
     --------------------------------------------------------------------
     「메인 화면으로」는 예약 흐름을 통째로 버리는 문이다. 「이전 단계로」와
     같은 자리에 같은 모양으로 놓여 있어, 한 칸 앞으로 돌아가려다 그대로
     밖으로 나가는 일이 생긴다. 되돌릴 수 없으므로 한 번 묻는다.

     브라우저 기본 confirm() 을 쓰지 않는 이유는 예약 확인 모달과 같다 —
     글자가 작고 버튼 문구를 우리가 정할 수 없다. 여기서는 「확인」이
     머무르는 것인지 나가는 것인지가 정확히 반대로 읽힐 수 있다.

     마크업을 스크립트로 만든다. 이 확인창이 필요한 화면이 셋(회장·일시,
     정보 입력, 정보 확인)인데, HTML 을 세 번 붙여 두면 문구를 한 번 고칠 때
     반드시 한 곳을 잊는다.
     ---------------------------------------------------------------------- */

  var leaveDialog = null;      // { root, title, desc, stay, leave }
  var leaveLastFocused = null;
  var leaveOnConfirm = null;

  function buildLeaveDialog() {
    if (leaveDialog) return leaveDialog;

    var root = document.createElement('div');
    root.className = 'modal is-hidden';

    var backdrop = document.createElement('div');
    backdrop.className = 'modal__backdrop';

    var panel = document.createElement('div');
    panel.className = 'modal__panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'flow-leave-title');
    panel.setAttribute('aria-describedby', 'flow-leave-desc');

    var title = document.createElement('h2');
    title.className = 'modal__title';
    title.id = 'flow-leave-title';

    var desc = document.createElement('p');
    desc.className = 'modal__desc';
    desc.id = 'flow-leave-desc';

    var actions = document.createElement('div');
    actions.className = 'modal__actions';

    // 머무르는 쪽을 먼저·기본으로 둔다. 되돌릴 수 없는 쪽에 포커스를
    // 두면 Enter 한 번으로 예약이 날아간다.
    var stay = document.createElement('button');
    stay.type = 'button';
    stay.className = 'btn btn--primary';

    var leave = document.createElement('button');
    leave.type = 'button';
    leave.className = 'btn btn--ghost';

    actions.appendChild(stay);
    actions.appendChild(leave);

    panel.appendChild(title);
    panel.appendChild(desc);
    panel.appendChild(actions);

    root.appendChild(backdrop);
    root.appendChild(panel);
    document.body.appendChild(root);

    stay.addEventListener('click', closeLeaveDialog);
    backdrop.addEventListener('click', closeLeaveDialog);
    leave.addEventListener('click', function () {
      var go = leaveOnConfirm;
      closeLeaveDialog();
      if (go) go();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (root.classList.contains('is-hidden')) return;
      closeLeaveDialog();
    });

    leaveDialog = {
      root: root, panel: panel, title: title, desc: desc,
      stay: stay, leave: leave
    };
    return leaveDialog;
  }

  function closeLeaveDialog() {
    if (!leaveDialog) return;
    leaveDialog.root.classList.add('is-hidden');
    document.body.classList.remove('is-modal-open');
    leaveOnConfirm = null;
    if (leaveLastFocused && leaveLastFocused.focus) leaveLastFocused.focus();
  }

  /**
   * 예약을 버리고 나가기 전에 묻는다.
   *
   *   confirmLeave({
   *     title: '…', desc: '…', stayLabel: '…', leaveLabel: '…',
   *     onLeave: function () { location.href = '…'; }
   *   })
   */
  function confirmLeave(options) {
    var dialog = buildLeaveDialog();
    var opts = options || {};

    dialog.title.textContent =
      opts.title || 'ご予約をやめて最初の画面へ戻りますか';
    dialog.desc.textContent =
      opts.desc || 'ここまでにお選びいただいた会場・日時と、ご入力の内容は保存されません。';
    dialog.stay.textContent = opts.stayLabel || '予約を続ける';
    dialog.leave.textContent = opts.leaveLabel || '最初の画面へ戻る';

    leaveOnConfirm = opts.onLeave || null;
    leaveLastFocused = document.activeElement;

    dialog.root.classList.remove('is-hidden');
    document.body.classList.add('is-modal-open');
    dialog.stay.focus();
  }

  /**
   * 링크 하나를 「누르면 먼저 묻는」 링크로 바꾼다.
   * href 는 그대로 둔다 — 스크립트가 죽어도 링크는 동작해야 한다.
   */
  function guardLink(link, options) {
    if (!link || link.dataset.flowGuarded === '1') return;
    link.dataset.flowGuarded = '1';

    link.addEventListener('click', function (event) {
      // 새 탭으로 여는 것(Ctrl/⌘·가운데 버튼)까지 막지 않는다.
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
        return;
      }
      event.preventDefault();

      var href = link.getAttribute('href');
      var opts = options || {};

      confirmLeave({
        title: opts.title,
        desc: opts.desc,
        stayLabel: opts.stayLabel,
        leaveLabel: opts.leaveLabel,
        onLeave: function () { window.location.href = href; }
      });
    });
  }

  /** 「이전 단계로」 링크(`data-flow-prev`)를 현재 단계에 맞춘다. */
  function applyPrevLink(current) {
    var link = document.querySelector('[data-flow-prev]');
    if (!link) return;

    link.setAttribute('href', prevHref(current));

    // 첫 단계에서만 이 링크가 흐름 밖으로 나간다. 한 칸 뒤로 가는
    // 나머지 단계에서는 묻지 않는다 — 되돌릴 수 있는 이동이다.
    if (!isFirst(current)) return;

    link.textContent = '最初の画面へ';
    guardLink(link);
  }

  /**
   * 머리말의 로고(`.brand`)도 같은 문이다. 예약 단계 화면에서는 같은 확인을
   * 태운다. 로고를 눌러 「처음으로 돌아가는」 것은 흔한 습관이라, 여기가
   * 「메인 화면으로」 버튼보다 오히려 자주 눌린다.
   */
  function applyHomeLinks() {
    var brands = document.querySelectorAll('.brand[href]');
    Array.prototype.forEach.call(brands, function (brand) {
      guardLink(brand, {
        title: 'ご予約をやめて最初の画面へ戻りますか',
        leaveLabel: '最初の画面へ戻る'
      });
    });
  }

  function apply() {
    var root = document.querySelector('.progress[data-step]');
    if (!root) return;

    var current = root.getAttribute('data-step');
    var at = indexOf(current);
    if (at < 0) return;

    applyProgress(root, at);
    applyPrevLink(current);

    // 예약이 끝난 화면(`done`)에서는 버릴 것이 없다.
    if (current !== 'done') applyHomeLinks();
  }

  /* 진행 표시의 높이를 CSS 로 넘긴다 (--progress-h)

     화면 위쪽에 붙어 있는 것은 헤더 하나가 아니라 「헤더 + 진행 표시」다.
     스크롤로 이동한 자리가 그 아래로 내려가려면 두 높이의 합이 필요하다.
     (main.css 의 scroll-padding-top)

     헤더 높이(--header-h)는 font-scale.js 가 잰다. 헤더는 모든 화면에 있고
     이 파일은 예약 단계 화면에만 실리기 때문이다. 여기서는 진행 표시만 맡는다. */
  function trackProgressHeight() {
    var progress = document.querySelector('.progress[data-step]');
    if (!progress) return;

    var root = document.documentElement;
    var lastHeight = -1;

    function measure() {
      var height = progress.offsetHeight;
      if (height === lastHeight) return;   // 같은 값이면 쓰지 않는다
      lastHeight = height;
      root.style.setProperty('--progress-h', height + 'px');
    }

    measure();

    if (window.ResizeObserver) {
      new ResizeObserver(measure).observe(progress);
    } else {
      window.addEventListener('resize', measure);
    }
  }

  window.KenshinFlow = {
    STEPS: STEPS,
    prevHref: prevHref,
    isFirst: isFirst,
    apply: apply,
    confirmLeave: confirmLeave,
    guardLink: guardLink
  };

  // 각 화면의 스크립트보다 먼저 실행된다. DOM 이 이미 파싱된 뒤에
  // 읽히도록 </body> 직전에 넣는다.
  apply();
  trackProgressHeight();

})();
