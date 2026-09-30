/* ==========================================================================
   keep-text.js — 끊기면 읽기 어려운 덩어리를 한 줄로 묶는다
   --------------------------------------------------------------------------
   base.css 의 `word-break: auto-phrase` 가 문절 단위로 줄을 바꿔 주지만,
   전화번호 · 번지 · 괄호 속 설명처럼 **문절이 아닌 덩어리**나, 문절 사전이
   둘로 나누는 「お問い / 合わせ」는 여전히 중간에서 꺾인다.

   이 스크립트는 화면의 글자(나중에 스크립트가 넣는 안내 · 오류 문구 포함)에서
   그런 덩어리를 찾아 `<span class="keep">` 으로 감싼다. 글자 내용은 바뀌지
   않으므로 textContent 를 읽는 코드와 화면 낭독기에는 차이가 없다.

   직접 넣을 때는 textContent 대신 이렇게 쓴다.
     KeepText.set(el, '平日 9:00～17:00 (土・日・祝日を除く)');
   ========================================================================== */

(function () {
  'use strict';

  /* 주소. 문절 사전은 「東京都新宿区西新宿2丁目」를 한 덩어리로 보아, 한 줄에
     안 들어가면 「西新 / 宿」처럼 아무 데서나 끊는다. 도도부현 · 시구정촌 ·
     ○○n丁目 단위로 나눠 그 사이에서만 꺾이게 한다(piece 참조). */
  var KANJI = '[\\u4E00-\\u9FFF\\u30A0-\\u30FF々]';
  var PREF = '(?:東京都|北海道|京都府|大阪府|[\\u4E00-\\u9FFF]{2,3}県)';
  var CITY = KANJI + '{1,6}?[市区町村郡]';
  var TOWN = KANJI + '{1,6}?\\d+丁目';
  var ADDRESS = new RegExp('^(' + PREF + ')(' + CITY + ')?(' + CITY + ')?(' + TOWN + ')?$');

  // 앞쪽 규칙이 먼저 맞는다. 일시(2026-10-22 11:30)가 번지 규칙에 먼저
  // 잡히면 날짜와 시각 사이에서 꺾이므로 가장 앞에 둔다. 괄호로 싸여 있으면
  // 괄호까지 함께 묶는다 — 「受診後( / 2026-10-22 11:30)」가 되지 않게.
  var PATTERN = new RegExp([
    '[（(]?\\d{4}-\\d{1,2}-\\d{1,2} \\d{1,2}:\\d{2}[）)]?',  // 일시
    '\\d{1,2}:\\d{2} ?[～〜~\\-] ?\\d{1,2}:\\d{2}',          // 시간대 (10:00～10:30)
    PREF + '(?:' + CITY + '){0,2}(?:' + TOWN + ')?',   // 주소
    '[\\w.+-]+@[\\w-]+(?:\\.[\\w-]+)+',          // 메일 주소
    '\\d{2,5}-\\d{1,4}-\\d{3,4}',                // 전화번호
    '\\d+(?:-\\d+)+',                            // 번지 · 우편번호
    '「[^「」]{1,14}」(?: ?直結)?',              // 역 · 버튼 이름 (「直結」만 떨어지지 않게)
    '[（(][^（）()]{1,14}[）)]',                 // 짧은 괄호 설명
    'お問い合わせ',
    'お受け取り',
    'この(?:サイト|画面|番号)[をはでにのが]?'   // 조사까지 — 「この画面 / を」가 되지 않게
  ].join('|'), 'g');

  // 이 안의 글자는 건드리지 않는다
  var SKIP = 'script, style, textarea, select, option, input, [contenteditable], .keep, .nobr';

  function keepSpan(text) {
    var span = document.createElement('span');
    span.className = 'keep';
    span.textContent = text;
    return span;
  }

  /* 찾은 덩어리 하나를 노드로. 여러 칸으로 나눈 덩어리는 칸 사이에서만 꺾인다.
       kenshin@example.jp         → [kenshin][@example][.jp]
         한 덩어리로 두면 좁은 칸에서 「kenshin@exa / mple.jp」가 된다.
       東京都新宿区西新宿2丁目    → [東京都][新宿区][西新宿2丁目] */
  function piece(text) {
    var parts;
    var at = text.indexOf('@');
    var address = ADDRESS.exec(text);

    if (at > 0) {
      parts = [text.slice(0, at)].concat(text.slice(at).split(/(?=\.)/));
    } else if (address) {
      parts = address.slice(1).filter(Boolean);
    } else {
      return keepSpan(text);
    }

    var frag = document.createDocumentFragment();
    parts.forEach(function (part) { frag.appendChild(keepSpan(part)); });
    return frag;
  }

  /* 글자 노드 하나를 묶음이 들어간 조각으로 바꾼다. 바꿀 것이 없으면 null. */
  function build(text) {
    var frag = document.createDocumentFragment();
    var last = 0;
    var match;
    PATTERN.lastIndex = 0;

    while ((match = PATTERN.exec(text)) !== null) {
      if (match.index > last) {
        frag.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      frag.appendChild(piece(match[0]));
      last = match.index + match[0].length;
    }
    if (!last) return null;

    if (last < text.length) {
      frag.appendChild(document.createTextNode(text.slice(last)));
    }
    return frag;
  }

  function set(el, text) {
    if (!el) return;
    text = text == null ? '' : String(text);
    el.textContent = text;
    apply(el);
  }

  /* 버튼처럼 flex · grid 인 요소 안에서는 span 하나하나가 따로 배치되어
     글자가 흩어진다. 그런 곳은 묶지 않는다(버튼은 CSS 의 text-wrap 으로 처리). */
  function isLayoutBox(el) {
    var display = window.getComputedStyle(el).display;
    return /flex|grid/.test(display);
  }

  function processText(node) {
    var parent = node.parentElement;
    if (!parent || !node.nodeValue || !node.nodeValue.trim()) return;
    if (parent.closest(SKIP) || isLayoutBox(parent)) return;

    var frag = build(node.nodeValue);
    if (frag) parent.replaceChild(frag, node);
  }

  function apply(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      processText(root);
      return;
    }
    if (root.nodeType !== 1 || root.closest(SKIP)) return;

    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    var node;
    while ((node = walker.nextNode())) nodes.push(node);
    nodes.forEach(processText);
  }

  function start() {
    apply(document.body);

    // 화면 스크립트가 나중에 넣는 안내 · 오류 · 조회 결과도 같은 규칙으로
    if (!window.MutationObserver) return;
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'characterData') {
          processText(record.target);
          return;
        }
        Array.prototype.forEach.call(record.addedNodes, apply);
      });
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.KeepText = { set: set };
})();
