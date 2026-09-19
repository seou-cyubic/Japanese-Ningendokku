/* ==========================================================================
   font-scale.js — 글자 크기 조절 (접근성)
   --------------------------------------------------------------------------
   대상 이용자는 만 40~74세이며 60대 이상이 상당수다.
   :root 의 --font-scale 값 하나만 바꿔 전체를 비례 확대한다.
   선택 값은 localStorage 에 저장하여 다음 방문 시에도 유지한다.

   plan.md §12.4 / 자체 피드백 P-2
   다른 화면 스크립트에 기대지 않는 독립 모듈이라, 필요 없는 화면에서는 빼면 된다.
   ========================================================================== */

(function () {
  'use strict';

  var STORAGE_KEY = 'kenshin.fontScale';
  var ALLOWED = ['1', '1.15', '1.3'];
  var DEFAULT = '1';

  var root = document.documentElement;
  var buttons = document.querySelectorAll('[data-scale]');
  var liveRegion = document.getElementById('font-scale-status');

  // 혹시 기저장되어 있던 data-theme 제거
  try {
    root.removeAttribute('data-theme');
    window.localStorage.removeItem('kenshin.theme');
  } catch (e) {}

  /**
   * 배율을 적용하고 버튼 상태를 갱신한다.
   * @param {string} scale  ALLOWED 중 하나
   * @param {boolean} announce  스크린 리더에 변경 사실을 알릴지 여부
   */
  function apply(scale, announce) {
    if (ALLOWED.indexOf(scale) === -1) {
      scale = DEFAULT;
    }

    root.style.setProperty('--font-scale', scale);
    measureHeader();   // 글자가 커지면 헤더도 커진다

    var label = '';

    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      var isActive = btn.getAttribute('data-scale') === scale;

      btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');

      if (isActive) {
        label = btn.getAttribute('data-scale-label') || btn.textContent;
      }
    }

    if (announce && liveRegion) {
      liveRegion.textContent = '文字サイズを' + label + 'に変更しました。';
    }
  }

  /** 저장된 설정을 읽는다. (프라이빗 모드 등에서 접근이 막힐 수 있어 방어) */
  function load() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || DEFAULT;
    } catch (e) {
      return DEFAULT;
    }
  }

  /** 설정을 저장한다. */
  function save(scale) {
    try {
      window.localStorage.setItem(STORAGE_KEY, scale);
    } catch (e) {
      /* 저장 실패해도 현재 세션에서는 정상 동작해야 한다 */
    }
  }

  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function () {
      var scale = this.getAttribute('data-scale');
      apply(scale, true);
      save(scale);
    });
  }

  /* ------------------------------------------------------------------
     헤더 높이를 CSS 로 넘긴다 (--header-h)

     헤더는 화면 위에 붙어 있어서, 「이용 안내」 같은 링크로 특정 자리에
     이동하면 그 자리가 헤더에 가려진 채 멈춘다. 그만큼 도착점을 내리려면
     헤더가 몇 px 인지 알아야 한다. (main.css 의 scroll-padding-top)

     높이를 상수로 박을 수 없다. 바로 이 파일이 바꾸는 글자 크기에 따라
     헤더가 커지고, 좁은 화면에서는 두 줄로 접히기 때문이다.

     이 측정을 flow.js 가 아니라 여기에 두는 이유는, 헤더가 모든 화면에
     있는데 flow.js 는 예약 단계 화면에만 실리기 때문이다. 이 파일은
     전 화면에 실린다.
     ------------------------------------------------------------------ */
  var header = document.querySelector('.site-header');
  var lastHeaderHeight = -1;

  function measureHeader() {
    if (!header) return;
    var height = header.offsetHeight;
    if (height === lastHeaderHeight) return;   // 같은 값이면 쓰지 않는다
    lastHeaderHeight = height;
    root.style.setProperty('--header-h', height + 'px');
  }

  if (header && window.ResizeObserver) {
    new ResizeObserver(measureHeader).observe(header);
  } else if (header) {
    window.addEventListener('resize', measureHeader);
  }

  // 초기 적용 (저장 값 복원)
  apply(load(), false);
  measureHeader();
})();
