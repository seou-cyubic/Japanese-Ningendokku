/* ==========================================================================
   address-search.js — 주소 검색 (U-14 정보 입력)
   --------------------------------------------------------------------------
   이용자가 우편번호와 한자 주소를 손으로 적게 하면 반드시 틀린다.
   특히 고령 이용자에게 「東京都千代田区外神田」을 정확히 입력하라는 요구는 무리다.
   틀린 주소는 안내문이 되돌아오는 것으로 끝나고, 그 뒤는 전부 전화 문의다.

   그래서 이렇게 한다.

     ① 시·구·정 이름이나 우편번호를 넣고 「주소 찾기」
     ② 나온 목록에서 자기 주소를 고른다
     ③ 우편번호와 주소가 자동으로 채워진다 — 손으로 고칠 수 없다
     ④ 이용자가 적는 것은 **번지와 건물명뿐**

   ③에서 손으로 고칠 수 있게 두면 우편번호와 주소가 어긋난 채 접수된다.
   바꾸고 싶으면 「다시 찾기」로 처음부터 고르게 한다.

       GET /api/v1/postal/search?keyword=...
   ========================================================================== */

(function () {
  'use strict';

  var API = '/api/v1/postal/search';

  // 이 화면에 검색 칸이 없으면(다른 화면에서 읽힌 경우) 아무것도 하지 않는다.
  var elQuery = document.getElementById('addr-query');
  if (!elQuery) return;

  var elBtn      = document.getElementById('addr-search-btn');
  var elStatus   = document.getElementById('addr-status');
  var elResults  = document.getElementById('addr-results');
  var elNotFound = document.getElementById('addr-notfound');

  var elPicked   = document.getElementById('addr-picked');
  var elEmpty    = document.getElementById('addr-empty');
  var elBody     = document.getElementById('addr-body');
  var elZipView  = document.getElementById('addr-zip-view');
  var elPrefView = document.getElementById('addr-pref');
  var elCityView = document.getElementById('addr-city');
  var elTownView = document.getElementById('addr-town');
  var elReset    = document.getElementById('addr-reset');

  var elPostal1  = document.getElementById('postal1');
  var elPostal2  = document.getElementById('postal2');
  var elAddress  = document.getElementById('address');
  var elDetail   = document.getElementById('address-detail');

  var busy = false;

  /* ======================================================================
     표시
     ====================================================================== */

  function setStatus(text, kind) {
    elStatus.textContent = text || '';
    elStatus.className = 'addr-status' + (kind ? ' addr-status--' + kind : '');
  }

  function hideResults() {
    elResults.textContent = '';
    elResults.classList.add('is-hidden');
  }

  /** '1010021' → '101-0021' */
  function formatZip(zip) {
    return zip.slice(0, 3) + '-' + zip.slice(3);
  }

  /* ----------------------------------------------------------------------
     찾지 못했을 때

     **직접 입력 칸을 열어 주지 않는다.** 검색에 나오지 않는 주소를 손으로
     적게 하면 우편번호와 주소가 어긋난 채 접수되고, 그것을 걸러 낼 방법이
     없다. 넣을 수 없는 것이 맞다 — 데이터를 지키는 장치다.

     다만 막다른 길로 두지도 않는다. 여기서 더 할 수 있는 일이 없는 사람에게는
     전화번호를 그 자리에서 보여 준다. 안내가 없으면 화면을 떠나거나
     아무 주소나 넣으려 든다. (plan.md P-9)
     ---------------------------------------------------------------------- */

  function showNotFound(keyword, contact) {
    setStatus(
      '「' + keyword + '」では住所が見つかりませんでした。',
      'warn'
    );

    elNotFound.textContent = '';

    var tips = document.createElement('p');
    tips.className = 'addr-notfound__tips';
    tips.textContent =
      '市区町村名だけで検索するか、郵便番号でお試しください。' +
      '（例：千代田区　・　1010021）';
    elNotFound.appendChild(tips);

    var help = document.createElement('p');
    help.className = 'addr-notfound__help';
    help.appendChild(document.createTextNode(
      'それでも見つからない場合は、下記までお電話ください。担当者が代わりに承ります。'
    ));
    elNotFound.appendChild(help);

    if (contact && contact.tel) {
      var tel = document.createElement('a');
      tel.className = 'addr-notfound__tel';
      tel.href = 'tel:' + contact.tel.replace(/[^0-9+]/g, '');
      tel.textContent = contact.tel;
      elNotFound.appendChild(tel);

      if (contact.hours) {
        var hours = document.createElement('span');
        hours.className = 'addr-notfound__hours';
        hours.textContent = contact.hours;
        elNotFound.appendChild(hours);
      }
    }

    elNotFound.classList.remove('is-hidden');
  }

  function hideNotFound() {
    elNotFound.classList.add('is-hidden');
    elNotFound.textContent = '';
  }

  /**
   * 주소 검색 자체를 쓸 수 없을 때 (서버에 우편번호 데이터가 없다).
   *
   * 「찾지 못했다」와 구별해서 말한다. 이용자가 자기 입력을 의심하며 몇 번씩
   * 고쳐 치는 것을 막아야 한다. 여기서는 아무리 고쳐 쳐도 결과가 같다.
   */
  function showUnavailable(message, contact) {
    setStatus(message || 'ただいま住所検索をご利用いただけません。', 'warn');

    elNotFound.textContent = '';

    var tips = document.createElement('p');
    tips.className = 'addr-notfound__tips';
    tips.textContent =
      'システム側の問題で、ご入力の内容に誤りはありません。' +
      'しばらくしてからもう一度お試しいただくか、下記までお電話ください。';
    elNotFound.appendChild(tips);

    var help = document.createElement('p');
    help.className = 'addr-notfound__help';
    help.textContent = 'お電話いただければ、担当者が代わりに承ります。';
    elNotFound.appendChild(help);

    if (contact && contact.tel) {
      var tel = document.createElement('a');
      tel.className = 'addr-notfound__tel';
      tel.href = 'tel:' + contact.tel.replace(/[^0-9+]/g, '');
      tel.textContent = contact.tel;
      elNotFound.appendChild(tel);

      if (contact.hours) {
        var hours = document.createElement('span');
        hours.className = 'addr-notfound__hours';
        hours.textContent = contact.hours;
        elNotFound.appendChild(hours);
      }
    }

    elNotFound.classList.remove('is-hidden');
  }

  /* ======================================================================
     고른 주소
     ====================================================================== */

  /* 고른 주소를 화면에 그린다.

     `parts` 는 검색 결과에서 온 도도부현·시구정촌·정역이다. 뒤로가기로 돌아와
     저장된 값만 있는 경우에는 없을 수 있으므로, 그때는 합쳐진 주소만 보여 준다. */
  function showPicked(zip, address, parts) {
    elPostal1.value = zip.slice(0, 3);
    elPostal2.value = zip.slice(3);
    elAddress.value = address;

    elZipView.textContent = formatZip(zip);

    if (parts) {
      elPrefView.textContent = parts.prefecture || '';
      elCityView.textContent = parts.city || '';
      elTownView.textContent = parts.town || '—';
    } else {
      // 조각을 모르면 도도부현 칸에 전체를 넣고 나머지는 감춘다.
      elPrefView.textContent = address;
      elCityView.textContent = '';
      elTownView.textContent = '';
    }

    // 값이 없는 조각은 줄째 감춘다. 빈 칸이 보이면 「입력이 덜 됐나」로 읽힌다.
    [[elPrefView], [elCityView], [elTownView]].forEach(function (pair) {
      var row = pair[0].parentNode;
      row.classList.toggle('is-hidden', !pair[0].textContent);
    });

    elPicked.classList.remove('is-empty');
    elEmpty.classList.add('is-hidden');
    elBody.classList.remove('is-hidden');
    elReset.classList.remove('is-hidden');
  }

  function clearPicked() {
    elPostal1.value = '';
    elPostal2.value = '';
    elAddress.value = '';

    elPicked.classList.add('is-empty');
    elEmpty.classList.remove('is-hidden');
    elBody.classList.add('is-hidden');
    elReset.classList.add('is-hidden');
  }

  /* ======================================================================
     검색
     ====================================================================== */

  function renderResults(items, truncated) {
    elResults.textContent = '';

    items.forEach(function (item) {
      var li = document.createElement('li');

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'addr-result';

      var zip = document.createElement('span');
      zip.className = 'addr-result__zip';
      zip.textContent = '〒 ' + formatZip(item.zipcode);

      var text = document.createElement('span');
      text.className = 'addr-result__text';
      text.textContent = item.address;

      btn.appendChild(zip);
      btn.appendChild(text);

      btn.addEventListener('click', function () {
        showPicked(item.zipcode, item.address, item);
        hideResults();
        setStatus('住所を選びました。続けて番地をご入力ください。', 'ok');
        // 고른 다음에 할 일이 번지 입력이므로 그리로 옮겨 준다.
        if (elDetail) elDetail.focus();
      });

      li.appendChild(btn);
      elResults.appendChild(li);
    });

    elResults.classList.remove('is-hidden');

    if (truncated) {
      setStatus(
        items.length + '件までを表示しています。お探しの住所がない場合は' +
        '市区町村名を加えてさらにしぼり込んでください。（例：千代田区 外神田）',
        'warn'
      );
    } else {
      setStatus(items.length + '件が見つかりました。下からお選びください。', 'ok');
    }
  }

  function search() {
    var keyword = elQuery.value.trim();

    if (!keyword) {
      setStatus('お住まいの市区町村名、または郵便番号をご入力ください。', 'warn');
      elQuery.focus();
      return;
    }
    if (busy) return;

    busy = true;
    elBtn.disabled = true;
    hideResults();
    hideNotFound();
    setStatus('検索しています…');

    fetch(API + '?keyword=' + encodeURIComponent(keyword))
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) {
            // 서버가 「무엇이 문제인지」를 문장으로 준다. 그대로 보여 준다.
            // (오류 형식은 app/main.py 의 예외 처리기가 통일한다)
            var error = new Error((body.error && body.error.message) ||
                                  '住所が見つかりませんでした。');
            error.code = body.error && body.error.code;
            error.contact = body.error && body.error.contact;
            throw error;
          }
          return body.data;
        });
      })
      .then(function (data) {
        if (!data.items.length) {
          showNotFound(keyword, data.contact);
          return;
        }
        hideNotFound();
        renderResults(data.items, data.truncated);
      })
      .catch(function (err) {
        // 「검색해도 안 나온다」와 「검색 기능이 죽었다」는 이용자에게 전혀
        // 다른 상황이다. 예전에는 둘 다 빈 목록이라, 주소 데이터를 넣지 않은
        // 환경에서는 무엇을 쳐도 0건이 나왔다. 이용자에게는 「내가 주소를
        // 잘못 쳤다」로 보이므로 고쳐 치고 또 고쳐 치다가 거기서 그만둔다.
        //
        // 이때 직접 입력 칸을 열어 주지는 않는다. 우편번호와 주소가 어긋난
        // 채 접수되는 것을 막는 것이 이 화면의 규칙이다(form.html 주석).
        // 대신 「이용자분 잘못이 아니다」를 말하고 전화 접수로 넘긴다.
        if (err.code === 'UNAVAILABLE') {
          showUnavailable(err.message, err.contact);
          return;
        }

        setStatus(
          (err.message || '住所が見つかりませんでした。') +
          '問題が続く場合は、下記のお問い合わせ先までご連絡ください。',
          'warn'
        );
      })
      .then(function () {
        busy = false;
        elBtn.disabled = false;
      });
  }

  /* ======================================================================
     연결
     ====================================================================== */

  elBtn.addEventListener('click', search);

  // 검색 칸에서 Enter 를 누르면 찾는다.
  // 이 칸은 폼 안에 있으므로 막지 않으면 폼이 통째로 제출된다.
  elQuery.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      search();
    }
  });

  elReset.addEventListener('click', function () {
    clearPicked();
    hideResults();
    hideNotFound();
    setStatus('');
    elQuery.value = '';
    elQuery.focus();
  });

  /* ======================================================================
     시작 — 앞서 입력한 값이 있으면 되살린다
     ====================================================================== */

  // apply.js 가 sessionStorage 에서 값을 되살린 뒤 이 화면이 그려진다.
  // 이미 채워져 있으면 「고른 상태」로 보여 준다. 그렇지 않으면
  // 뒤로가기로 돌아온 이용자가 주소를 처음부터 다시 찾아야 한다.
  var zip = (elPostal1.value || '') + (elPostal2.value || '');
  if (zip.length === 7 && elAddress.value) {
    showPicked(zip, elAddress.value);
  } else {
    clearPicked();
  }

})();