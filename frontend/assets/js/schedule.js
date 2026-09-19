/* ==========================================================================
   schedule.js — 예약 1단계 : 회장 → 날짜(달력) → 시간(목록)  (U-12 / U-30)
   --------------------------------------------------------------------------
   한 화면을 3단으로 나눈다.

     ① 회장  : 한 줄 = 한 회장인 목록. 고르면 즉시 ②가 열리고 ①은 한 줄로 접힌다.
     ② 날짜  : 달력. 칸에는 「남은 좌석 수」만 적는다.
     ③ 시간  : 고른 날짜의 30분 단위 목록. 「남은 좌석 / 총 좌석」을 적는다.

   확인 버튼을 따로 두지 않는다. 고르는 행위 자체가 다음 단을 여는 신호다.

   왜 이 화면이 첫 단계인가
   ------------------------
   개인정보를 다 넣고 나서 「그 날은 자리가 없습니다」를 듣는 것이 가장 나쁜
   순서다. 그래서 본인 확인보다 먼저 남은 자리를 보여 준다.
   「빈자리만 보고 싶다」(U-30)와 「예약하고 싶다」(U-12)가 같은 길이 되므로
   입구를 나누지 않는다. (plan.md P-10)

   시간을 고른 뒤의 행선지
   -----------------------
     · 본인 확인 전 → 「이 시간으로 예약하시겠습니까?」를 묻고 본인 확인으로.
                      개인정보를 넣기 직전이므로 여기서 한 번 확인받는다.
     · 본인 확인 후 → 묻지 않고 정보 입력으로.
                      확인 화면의 「회장·일시 수정」으로 되돌아온 경우가 이쪽이다.

     GET /api/v1/hospitals
     GET /api/v1/hospitals/{id}/availability?date=YYYY-MM-DD
   ========================================================================== */

(function () {
  'use strict';

  var API_HOSPITALS = '/api/v1/hospitals';
  var VERIFIED_KEY  = 'kenshin.verifiedPerson';
  var PICK_KEY      = 'kenshin.selectedSlot';

  var WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];

  // 地域(都道府県). 목록의 왼쪽 배지가 이 순서로 읽힌다.
  // 전국지방공공단체 코드 순(북 → 남)이라, 지도에서 자기 동네를 찾는 사람의
  // 눈 움직임과 맞는다.
  //
  // 여기에 없는 이름은 뒤로 보낸다. 마스터에 새 지역이 생겨도 목록이
  // 무너지지 않고 맨 아래에 붙는다.
  var AREA_ORDER = [
    '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
    '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
    '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県',
    '静岡県', '愛知県', '三重県', '滋賀県', '京都府', '大阪府', '兵庫県',
    '奈良県', '和歌山県', '鳥取県', '島根県', '岡山県', '広島県', '山口県',
    '徳島県', '香川県', '愛媛県', '高知県', '福岡県', '佐賀県', '長崎県',
    '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県'
  ];

  function regionRank(area) {
    var i = AREA_ORDER.indexOf(area);
    return i === -1 ? AREA_ORDER.length : i;
  }

  /* 회장은 하루만 연다. 「2026년 7월 17일 (금)」처럼 요일까지 붙여야
     사람이 자기 일정과 맞춰 볼 수 있다. */
  function formatEventDate(iso) {
    if (!iso) return '';
    var parts = String(iso).split('-');
    if (parts.length !== 3) return String(iso);
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return parts[0] + '年' + Number(parts[1]) + '月' + Number(parts[2]) + '日(' +
           WEEKDAY[d.getDay()] + ')';
  }

  /* 회장 1곳이 여러 날 열 수 있다. 서버가 주는 `schedules` 는 **아직 접수
     중인 회차만** 개최일 순으로 담고 있다. `event_date` 는 그 중 첫 회차의
     값일 뿐이라, 그것만 찍으면 나머지 날짜가 화면에서 사라진다. */
  function openDates(h) {
    var list = (h && h.schedules) || [];
    if (list.length) {
      return list.map(function (s) { return s.event_date; });
    }
    return h && h.event_date ? [h.event_date] : [];
  }

  /** 회장 목록 한 줄에 들어갈 검진일 문구. */
  function eventDateLabel(h) {
    var dates = openDates(h);
    if (!dates.length) return '';
    if (dates.length === 1) return formatEventDate(dates[0]);
    // 날짜를 전부 늘어놓으면 한 줄이 넘친다. 가장 이른 날을 적고 나머지는
    // 개수로 알린다 — 「고를 날이 더 있다」는 사실만 전하면 충분하고,
    // 어느 날인지는 눌러서 달력에서 고른다.
    return formatEventDate(dates[0]) + '　ほか' + (dates.length - 1) + '日';
  }

  // --- DOM ---------------------------------------------------------------
  var elRegionSelect  = document.getElementById('region-select');
  /* --------------------------------------------------------------------
     회장 위치 지도

     키 없이 도는 테스트용 URL 을 기본값으로 둔다. 정식 키가 나오면
     MAP_EMBED_KEY 에 넣기만 하면 공식 Maps Embed API 로 갈아탄다.
     화면·CSS·나머지 코드는 손대지 않는다.

       테스트(키 없음) : maps.google.com/maps?q=..&output=embed
                         문서화되지 않은 형식이므로 운영에 쓰지 않는다.
       운영(키 있음)   : google.com/maps/embed/v1/place  ← 공식 · 무제한 무료

     좌표는 회장 마스터(緯度/経度)에서 그대로 온다. 주소 문자열로 검색시키면
     일본 주소 표기 흔들림으로 엉뚱한 곳이 찍히므로 좌표를 쓴다.
     -------------------------------------------------------------------- */
  var MAP_EMBED_KEY = '';   // 정식 키를 받으면 여기에 넣는다

  /* 지도에 넣을 검색어를 고른다.

     1순위 좌표    — 숫자로 찍으므로 위치가 절대 틀리지 않는다.
     2순위 이름+주소 — 좌표가 비어 있을 때. 구글이 찾아 준다.

     좌표가 없다고 지도를 통째로 없애면, 그 회장을 고른 사람만
     아무 안내도 못 받는다. 위치가 조금 흔들릴 위험보다
     「아무것도 안 보이는」 쪽이 나쁘다. 둘 다 없을 때만 숨긴다. */
  function mapQuery(hospital, lat, lng) {
    if (typeof lat === 'number' && typeof lng === 'number') {
      return lat + ',' + lng;
    }
    return [hospital.name, hospital.address]
      .filter(function (v) { return v; })
      .join(' ');
  }

  function mapEmbedUrl(query) {
    if (MAP_EMBED_KEY) {
      return 'https://www.google.com/maps/embed/v1/place'
        + '?key=' + encodeURIComponent(MAP_EMBED_KEY)
        + '&q=' + encodeURIComponent(query)
        + '&zoom=16&language=ja';
    }
    return 'https://maps.google.com/maps'
      + '?q=' + encodeURIComponent(query)
      + '&z=16&hl=ja&output=embed';
  }

  /* 「구글 지도에서 보기」 링크.

     지도(iframe)와 링크는 일부러 다른 값을 쓴다.

       지도 = 좌표      위치가 절대 틀리지 않는다. 대신 핀에 이름이 안 나온다.
       링크 = 이름+주소  구글이 시설을 찾아내 이름을 보여 준다.

     좌표로 링크를 걸면 「35.6584491, 139.7455360」이 떠서 이용자가
     맞게 찾아가는지 확인할 수 없다. 이름으로 걸면 시설명이 그대로 뜬다.
     이름+주소 검색이 좌표와 어긋날 위험은 샘플 회장으로 확인했다.
     サンプル会館 A(東京都港区芝公園4丁目2-8) → 구글이 35.6584,139.7455 로 해석.
     마스터 값과 일치.

     길찾기(dir)가 아니라 장소 보기(search)를 쓰는 이유
     ---------------------------------------------------
     dir 로 열면 구글이 곧바로 출발지를 잡으려 하고, 위치 권한이 없으면
     IP 로 추정한다. 그 추정이 틀려도 화면에는 「現在地」라고 적히기 때문에,
     이용자는 엉뚱한 출발지로 그려진 경로를 맞다고 믿게 된다.
     (실측: 위치 권한을 막은 상태에서 도쿄 회장의 출발지가 해외로 잡혔다)

     게다가 링크를 누르자마자 위치 권한 팝업이 뜨는 것은 고령 이용자에게
     그 자체로 이탈 요인이다. search 로 열면 권한을 묻지 않고 시설 정보가
     바로 뜨며, 길을 찾고 싶은 사람은 거기서 「経路」를 누르면 된다.

     이름이나 주소가 비어 있는 회장은 좌표로 되돌린다. */
  function mapLinkUrl(hospital, lat, lng) {
    var label = [hospital.name, hospital.address]
      .filter(function (v) { return v; })
      .join(' ');

    var query = label || (lat + ',' + lng);

    return 'https://www.google.com/maps/search/?api=1'
      + '&query=' + encodeURIComponent(query)
      + '&hl=ja';
  }

  var elVenueMap       = document.getElementById('venue-map');
  var elVenueMapFrame  = elVenueMap ? elVenueMap.querySelector('.vmap__frame') : null;
  var elVenueMapIframe = document.getElementById('venue-map-iframe');
  var elVenueMapLock   = document.getElementById('venue-map-lock');
  var elVenueMapLink   = document.getElementById('venue-map-link');

  if (elVenueMapLock && elVenueMapFrame) {
    elVenueMapLock.addEventListener('click', function () {
      elVenueMapFrame.classList.add('is-unlocked');
    });
  }

  /* 회장을 고를 때마다 지도를 갈아 끼운다.
     좌표가 없는 회장(담당자가 엑셀에서 빠뜨린 경우)은 지도를 감춘다.
     빈 지도나 엉뚱한 위치를 보여 주느니 없는 편이 낫다. */
  function renderVenueMap(hospital) {
    if (!elVenueMap || !elVenueMapIframe) return;

    var lat = hospital ? hospital.latitude : null;
    var lng = hospital ? hospital.longitude : null;
    var query = hospital ? mapQuery(hospital, lat, lng) : '';

    /* 좌표도 주소도 없으면 지도가 성립하지 않는다. 이때만 숨긴다. */
    if (!query) {
      elVenueMap.classList.add('is-hidden');
      elVenueMapIframe.removeAttribute('src');
      return;
    }

    elVenueMapIframe.src = mapEmbedUrl(query);
    elVenueMapIframe.title = (hospital.name || '受診会場') + 'の地図';
    if (elVenueMapLink) elVenueMapLink.href = mapLinkUrl(hospital, lat, lng);
    if (elVenueMapFrame) elVenueMapFrame.classList.remove('is-unlocked');
    elVenueMap.classList.remove('is-hidden');
  }

  var elHospitalList  = document.getElementById('hospital-list');
  var elHospitalCount = document.getElementById('hospital-count');
  var elPicker        = document.getElementById('hospital-picker');
  var elPicked        = document.getElementById('picked-hospital');
  var elPickedName    = document.getElementById('picked-name');
  var elPickedMeta    = document.getElementById('picked-meta');
  var elChangeBtn     = document.getElementById('change-hospital');

  var elStepHospital  = document.getElementById('step-hospital');
  var elStepDate      = document.getElementById('step-date');
  var elStepTime      = document.getElementById('step-time');

  var elCalPrev       = document.getElementById('cal-prev');
  var elCalNext       = document.getElementById('cal-next');
  var elCalTitle      = document.getElementById('cal-title');
  var elDatePicks     = document.getElementById('date-picks');
  var elDatePicksLead = document.getElementById('date-picks-lead');
  var elDatePicksList = document.getElementById('date-picks-list');
  var elCalGrid       = document.getElementById('cal-grid');

  var elTimeDate      = document.getElementById('time-date');
  var elTimeList      = document.getElementById('time-list');
  var elTimeNote      = document.getElementById('time-note');

  var elStickyBar     = document.getElementById('sticky-bar');
  var elPickSummary   = document.getElementById('pick-summary');
  var elNextBtn       = document.getElementById('next-btn');

  var elAlert         = document.getElementById('global-alert');
  var elAlertText     = document.getElementById('global-alert-text');
  var elLive          = document.getElementById('live-status');
  var elPageLead      = document.getElementById('page-lead');
  var elPeekNote      = document.getElementById('peek-note');

  var elModal         = document.getElementById('confirm-modal');
  var elModalBackdrop = document.getElementById('confirm-backdrop');
  var elModalHospital = document.getElementById('confirm-hospital');
  var elModalWhen     = document.getElementById('confirm-when');
  var elModalYes      = document.getElementById('confirm-yes');
  var elModalNo       = document.getElementById('confirm-no');

  // --- 상태 --------------------------------------------------------------
  var hospitals = [];
  var selectedHospital = null;

  var dateMap = {};        // 'YYYY-MM-DD' → DateSummary
  var months = [];         // ['2026-08', '2026-09'] — 접수 가능한 달
  var monthIndex = 0;

  var selectedDate = null; // 'YYYY-MM-DD'
  var selectedSlot = null;

  /** 본인 확인을 마쳤는가. 시간을 고른 뒤의 행선지가 여기서 갈린다. */
  function isVerified() {
    try {
      return !!sessionStorage.getItem(VERIFIED_KEY);
    } catch (e) {
      return false;   // sessionStorage 를 막아 둔 브라우저
    }
  }

  // 아직 본인 확인 전인가. 확인 화면에서 「수정」으로 되돌아온 경우는 false.
  var beforeVerify = !isVerified();

  /* ======================================================================
     공통 유틸
     ====================================================================== */

  function showAlert(message) {
    elAlertText.textContent = message;
    elAlert.classList.add('is-visible');
    scrollToEl(elAlert);
  }

  function clearAlert() {
    elAlert.classList.remove('is-visible');
  }

  function announce(text) {
    if (elLive) elLive.textContent = text;
  }

  function show(el)  { el.classList.remove('is-hidden'); }
  function hide(el)  { el.classList.add('is-hidden'); }

  function getJson(url) {
    return fetch(url).then(function (res) {
      return res.json().then(function (body) {
        if (!res.ok || !body.success) {
          throw new Error((body.error && body.error.message) ||
                          '情報を読み込めませんでした。');
        }
        return body.data;
      });
    });
  }

  /** '2026-08-10' → [2026, 8, 10] */
  function parseIso(iso) {
    var p = String(iso).split('-');
    return [parseInt(p[0], 10), parseInt(p[1], 10), parseInt(p[2], 10)];
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /** '2026-08-10' → '2026年8月10日(月)' */
  function formatDateLong(iso) {
    var p = parseIso(iso);
    var wd = WEEKDAY[new Date(p[0], p[1] - 1, p[2]).getDay()];
    return p[0] + '年' + p[1] + '月' + p[2] + '日（' + wd + '）';
  }

  /** '2026-08-10' → '8月10日(月)' */
  function formatDateShort(iso) {
    var p = parseIso(iso);
    var wd = WEEKDAY[new Date(p[0], p[1] - 1, p[2]).getDay()];
    return p[1] + '月' + p[2] + '日（' + wd + '）';
  }

  function scrollToEl(el) {
    window.setTimeout(function () {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
  }

  /* ======================================================================
     ① 회장 목록
     ====================================================================== */

  /* 거르는 축은 **地域** 이다.
     표시용 지역(`region`)은 「東京都港区」처럼 회장마다 값이 달라, 그것으로
     선택지를 만들면 회장 수만큼 항목이 생겨 거르는 뜻이 없어진다. */
  function renderRegionOptions() {
    var regions = [];
    hospitals.forEach(function (h) {
      var key = h.area || h.region;
      if (key && regions.indexOf(key) === -1) regions.push(key);
    });
    regions.sort(function (a, b) {
      var d = regionRank(a) - regionRank(b);
      return d !== 0 ? d : a.localeCompare(b, 'ja');
    });

    elRegionSelect.textContent = '';

    var all = document.createElement('option');
    all.value = '';
    all.textContent = 'すべて(' + hospitals.length + '会場)';
    elRegionSelect.appendChild(all);

    regions.forEach(function (r) {
      var n = hospitals.filter(function (h) {
        return (h.area || h.region) === r;
      }).length;
      var opt = document.createElement('option');
      opt.value = r;
      opt.textContent = r + ' (' + n + '会場)';
      elRegionSelect.appendChild(opt);
    });
  }

  function renderHospitals() {
    var region = elRegionSelect.value;
    var list = region
      ? hospitals.filter(function (h) { return (h.area || h.region) === region; })
      : hospitals.slice();

    // 개최일 순으로 늘어놓는다. 회장이 며칠만 열기 때문에, 이용자가
    // 먼저 맞춰야 하는 것은 「어디」가 아니라 「언제」다. 여러 날 여는
    // 회장은 **가장 이른 날**로 줄을 세운다 — 이용자가 다음에 갈 수 있는
    // 날이 그 날이기 때문이다.
    // 같은 날이면 지역 순으로 묶어 왼쪽 배지가 순서대로 읽히게 한다.
    list.sort(function (a, b) {
      var da = openDates(a)[0] || '9999-12-31';
      var db = openDates(b)[0] || '9999-12-31';
      if (da !== db) return da < db ? -1 : 1;
      var d = regionRank(a.area) - regionRank(b.area);
      if (d !== 0) return d;
      return a.name.localeCompare(b.name, 'ja');
    });

    elHospitalCount.textContent = '会場 ' + list.length + '会場';
    elHospitalList.textContent = '';

    if (!list.length) {
      var empty = document.createElement('li');
      empty.className = 'state-box';
      empty.textContent = 'この地域で受け付け中の会場はありません。';
      elHospitalList.appendChild(empty);
      return;
    }

    list.forEach(function (h) {
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hitem';

      var when = eventDateLabel(h);
      btn.setAttribute('aria-label',
        h.name + ', ' + h.region + ', ' + h.access_info +
        (when ? '、受診日 ' + when : '') +
        '。選ぶとお時間を指定できます。');

      btn.innerHTML =
        '<span class="hitem__region"></span>' +
        '<span class="hitem__body">' +
          '<strong class="hitem__name"></strong>' +
          '<span class="hitem__when"></span>' +
          '<span class="hitem__access"></span>' +
        '</span>' +
        '<svg class="hitem__arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M9 5l7 7-7 7"></path></svg>';

      btn.querySelector('.hitem__region').textContent = h.area || h.region;
      btn.querySelector('.hitem__name').textContent = h.name;
      btn.querySelector('.hitem__when').textContent = when ? '受診日 ' + when : '';
      btn.querySelector('.hitem__access').textContent = h.access_info;

      btn.addEventListener('click', function () { selectHospital(h); });

      li.appendChild(btn);
      elHospitalList.appendChild(li);
    });
  }

  function selectHospital(hospital) {
    selectedHospital = hospital;
    selectedDate = null;
    selectedSlot = null;

    hide(elPicker);
    show(elPicked);
    elPickedName.textContent = hospital.name;

    var meta = [hospital.region, hospital.address];
    if (hospital.has_parking) meta.push('駐車場あり');
    if (hospital.tel) meta.push('TEL ' + hospital.tel);
    elPickedMeta.textContent = meta.join(' · ');

    renderVenueMap(hospital);

    hide(elStepTime);
    hide(elStickyBar);

    elPageLead.textContent = 'カレンダーから受診される日をお選びください。';
    announce(hospital.name + 'を選びました。日付をお選びください。');

    loadCalendar(hospital.id);
  }

  function reopenPicker() {
    selectedHospital = null;
    selectedDate = null;
    selectedSlot = null;

    show(elPicker);
    hide(elPicked);
    if (elVenueMap) elVenueMap.classList.add('is-hidden');
    hide(elStepDate);
    hide(elStepTime);
    hide(elStickyBar);

    elPageLead.textContent = '下の一覧から、受診される会場をお選びください。';
    scrollToEl(elStepHospital);
  }

  elChangeBtn.addEventListener('click', reopenPicker);
  elRegionSelect.addEventListener('change', renderHospitals);

  /* ======================================================================
     ② 달력
     ====================================================================== */

  function loadCalendar(hospitalId) {
    clearAlert();

    getJson(API_HOSPITALS + '/' + hospitalId + '/availability')
      .then(function (data) {
        dateMap = {};
        months = [];

        (data.dates || []).forEach(function (d) {
          dateMap[d.date] = d;
          var ym = String(d.date).slice(0, 7);
          if (months.indexOf(ym) === -1) months.push(ym);
        });
        months.sort();

        show(elStepDate);

        if (!months.length) {
          hide(elDatePicks);
          elCalTitle.textContent = '';
          elCalGrid.textContent = '';
          var empty = document.createElement('p');
          empty.className = 'state-box';
          empty.textContent = 'ただいまご予約いただける日がありません。';
          elCalGrid.appendChild(empty);
          return;
        }

        // 예약 가능한 날이 가장 먼저 있는 달을 펼친다.
        // 만석뿐인 달을 먼저 보여 주면 「예약이 안 되는 곳」처럼 보인다.
        monthIndex = 0;
        for (var i = 0; i < months.length; i++) {
          var has = Object.keys(dateMap).some(function (iso) {
            return iso.slice(0, 7) === months[i] && dateMap[iso].remaining > 0;
          });
          if (has) { monthIndex = i; break; }
        }

        renderDatePicks();
        renderCalendar();

        /* 날짜 칸으로 내려가지 않는다. 회장을 고르면 그 자리에 지도가 켜지는데,
           스크롤이 그 아래 달력으로 가 버리면 방금 켜진 지도가 화면 밖으로 밀린다.

           아무것도 하지 않는 것으로는 부족하다. 회장 목록이 접히면서 문서
           높이가 줄어, 목록 아래쪽에서 고른 사람은 브라우저가 스크롤을
           클램프해 결국 날짜 칸 근처에 떨어진다. 「고른 회장 + 지도」의
           머리에 맞춰 두면 달력은 그 아래로 자연스럽게 이어진다. */
        scrollToEl(elStepHospital);
      })
      .catch(function (err) {
        showAlert(err.message ||
          'ご予約いただける日を読み込めませんでした。しばらくしてからもう一度お試しください。');
      });
  }

  /* --------------------------------------------------------------------
     회장이 여는 날 바로가기
     --------------------------------------------------------------------
     달력은 한 달만 보여 준다. 회장이 9월·10월·11월에 열면 이용자는 9월
     달력만 보고 「이 회장은 9월 15일 하루뿐」이라 생각하고 넘어간다.
     실제로 고를 수 있는 날은 몇 개뿐이므로 전부 늘어놓는다.

     날이 하나뿐이면 감춘다 — 달력이 이미 그 달을 펴 놓았고, 버튼 하나를
     더 두면 「눌러야 하는 것이 있나」 하고 멈추게 된다.
     -------------------------------------------------------------------- */

  function renderDatePicks() {
    var isoList = Object.keys(dateMap).sort();
    elDatePicksList.textContent = '';

    if (isoList.length < 2) {
      hide(elDatePicks);
      return;
    }

    elDatePicksLead.textContent =
      'この会場の開催は' + isoList.length + '日です。日付をお選びいただくと、その日の時間帯が表示されます。';

    isoList.forEach(function (iso) {
      var info = dateMap[iso] || {};
      var full = info.remaining <= 0;

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'datepick__btn' + (full ? ' datepick__btn--full' : '');
      btn.dataset.date = iso;
      btn.disabled = full;

      var when = document.createElement('span');
      when.className = 'datepick__when';
      when.textContent = formatEventDate(iso);

      var seats = document.createElement('span');
      seats.className = 'datepick__seats';
      seats.textContent = full ? '満席' : '空き' + info.remaining + '名';

      btn.appendChild(when);
      btn.appendChild(seats);
      btn.setAttribute('aria-label',
        formatEventDate(iso) + ', ' + seats.textContent +
        (full ? '。お選びいただけません。' : '。選ぶとお時間を指定できます。'));

      btn.addEventListener('click', function () {
        // 달력도 그 날이 있는 달로 함께 옮긴다. 시간표만 바뀌고 달력이
        // 다른 달에 남아 있으면, 어느 날을 고른 것인지 화면이 두 가지로
        // 답하게 된다.
        var ym = iso.slice(0, 7);
        var index = months.indexOf(ym);
        if (index !== -1 && index !== monthIndex) {
          monthIndex = index;
          renderCalendar();
        }
        selectDate(iso);
      });

      elDatePicksList.appendChild(btn);
    });

    show(elDatePicks);
  }

  /** 바로가기 버튼의 선택 표시를 갱신한다. */
  function markDatePick(iso) {
    Array.prototype.forEach.call(
      elDatePicksList.querySelectorAll('.datepick__btn'),
      function (btn) {
        btn.setAttribute('aria-pressed', btn.dataset.date === iso ? 'true' : 'false');
        btn.classList.toggle('is-current', btn.dataset.date === iso);
      }
    );
  }

  function renderCalendar() {
    var ym = months[monthIndex];
    var year = parseInt(ym.slice(0, 4), 10);
    var month = parseInt(ym.slice(5, 7), 10);   // 1~12

    elCalTitle.textContent = year + '年' + month + '月';
    elCalPrev.disabled = monthIndex <= 0;
    elCalNext.disabled = monthIndex >= months.length - 1;

    elCalGrid.textContent = '';

    var first = new Date(year, month - 1, 1);
    var lastDate = new Date(year, month, 0).getDate();

    // 1일 앞의 빈 칸
    for (var p = 0; p < first.getDay(); p++) {
      var pad = document.createElement('span');
      pad.className = 'day day--pad';
      elCalGrid.appendChild(pad);
    }

    for (var d = 1; d <= lastDate; d++) {
      var iso = year + '-' + pad2(month) + '-' + pad2(d);
      elCalGrid.appendChild(buildDay(iso, d));
    }
  }

  function buildDay(iso, dayNum) {
    var info = dateMap[iso];

    // 접수하지 않는 날 — 일요일 휴진이거나 접수 기간 밖
    if (!info) {
      var none = document.createElement('span');
      none.className = 'day day--none';
      none.innerHTML = '<span class="day__n"></span>';
      none.querySelector('.day__n').textContent = dayNum;
      return none;
    }

    /* 못 고르는 날은 두 가지다.

         마감      자리가 다 찼다. 같은 회장의 다른 날을 보면 된다.
         검진 없음 그 날 아예 열지 않는다(휴진). 다른 날이나 다른 회장을
                   봐야 한다.

       예전에는 둘 다 「마감」이었다. 「마감」을 본 분은 다른 날을 찾는데,
       회장이 1년에 하루만 여는 곳이 많아 찾을 다른 날이 없었다. */
    var isHoliday = info.is_holiday === true;
    var isFull = isHoliday || info.remaining <= 0;
    var cls = isHoliday ? 'day--off'
            : (isFull ? 'day--full'
            : (info.availability === 'LIMITED' ? 'day--limited' : 'day--available'));

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'day ' + cls;
    btn.disabled = isFull;
    btn.setAttribute('aria-pressed', iso === selectedDate ? 'true' : 'false');
    btn.setAttribute('aria-label',
      formatDateLong(iso)
      + (isHoliday ? '　この日は健診を実施しません'
      : (isFull ? '　満席' : '　空き' + info.remaining + '名')));

    btn.innerHTML =
      '<span class="day__n"></span>' +
      '<span class="day__left"></span>';

    btn.querySelector('.day__n').textContent = dayNum;
    btn.querySelector('.day__left').textContent =
      isHoliday ? '実施なし' : (isFull ? '満席' : info.remaining + '名');

    if (!isFull) {
      btn.addEventListener('click', function () { selectDate(iso); });
    }
    return btn;
  }

  elCalPrev.addEventListener('click', function () {
    if (monthIndex > 0) { monthIndex--; renderCalendar(); }
  });

  elCalNext.addEventListener('click', function () {
    if (monthIndex < months.length - 1) { monthIndex++; renderCalendar(); }
  });

  /* ======================================================================
     ③ 시간 목록
     ====================================================================== */

  var STATE = {
    AVAILABLE: { mark: '○', text: '予約できます', cls: 'tslot--available' },
    LIMITED:   { mark: '△', text: '残りわずか', cls: 'tslot--limited' },
    FULL:      { mark: '×', text: '満席',      cls: 'tslot--full' },
    CLOSED:    { mark: '×', text: '受付なし', cls: 'tslot--closed' }
  };

  function selectDate(iso) {
    selectedDate = iso;
    selectedSlot = null;
    hide(elStickyBar);
    clearAlert();

    // 달력의 선택 표시를 갱신한다 (전체를 다시 그리지 않는다)
    Array.prototype.forEach.call(elCalGrid.querySelectorAll('.day'), function (el) {
      if (el.tagName === 'BUTTON') el.setAttribute('aria-pressed', 'false');
    });
    var cells = elCalGrid.querySelectorAll('button.day');
    for (var i = 0; i < cells.length; i++) {
      if (cells[i].getAttribute('aria-label').indexOf(formatDateLong(iso)) === 0) {
        cells[i].setAttribute('aria-pressed', 'true');
        break;
      }
    }

    markDatePick(iso);

    announce(formatDateLong(iso) + 'を選びました。お時間をお選びください。');
    elPageLead.textContent = '受診されるお時間をお選びください。';

    getJson(API_HOSPITALS + '/' + selectedHospital.id +
            '/availability?date=' + encodeURIComponent(iso))
      .then(function (data) {
        renderSlots(iso, data.slots || []);
        show(elStepTime);
        scrollToEl(elStepTime);
      })
      .catch(function (err) {
        showAlert(err.message ||
          '時間帯を読み込めませんでした。しばらくしてからもう一度お試しください。');
      });
  }

  function renderSlots(iso, slots) {
    var info = dateMap[iso];
    elTimeDate.textContent = formatDateLong(iso) +
      (info ? '　・　空き' + info.remaining + '名' : '');

    elTimeList.textContent = '';

    if (!slots.length) {
      var empty = document.createElement('li');
      empty.className = 'state-box';
      empty.textContent = 'この日は受け付けておりません。別の日をお選びください。';
      elTimeList.appendChild(empty);
      return;
    }

    // 오전·오후에 실제로 열려 있는 시간 폭. 회장마다 다르므로 **고정 문구를
    // 쓰지 않고 그 날의 슬롯에서 계산한다.** 예전에는 「09:00 ~ 12:00」이
    // 박혀 있었는데, 지금 데이터는 회장에 따라 09:30 이나 10:00 에 시작한다.
    var periodRange = {};
    slots.forEach(function (slot) {
      var range = periodRange[slot.period];
      if (!range) {
        periodRange[slot.period] = { start: slot.start_time, end: slot.end_time };
        return;
      }
      if (slot.start_time < range.start) range.start = slot.start_time;
      if (slot.end_time > range.end) range.end = slot.end_time;
    });

    // 오전 끝과 오후 시작 사이가 비어 있으면 그 이유를 적어 준다.
    // 「왜 12시대가 없나」는 문의가 되기 전에 화면에서 답해야 하는 질문이다.
    if (elTimeNote) {
      var am = periodRange.AM;
      var pm = periodRange.PM;
      elTimeNote.textContent = (am && pm && am.end < pm.start)
        ? '※ ' + am.end + ' ~ ' + pm.start + 'は受け付けておりません。'
        : '';
    }

    var lastPeriod = null;

    slots.forEach(function (slot) {
      var s = STATE[slot.availability] || STATE.FULL;

      // 오전 / 오후 구분 머리 — 점심시간이 비어 있는 이유를 여기서 드러낸다
      if (slot.period !== lastPeriod) {
        lastPeriod = slot.period;
        var range = periodRange[slot.period];
        var head = document.createElement('li');
        head.className = 'tlist__group';
        head.innerHTML =
          '<span class="tlist__group-name"></span>' +
          '<span class="tlist__group-range"></span>';
        head.querySelector('.tlist__group-name').textContent =
          slot.period === 'AM' ? '午前' : '午後';
        head.querySelector('.tlist__group-range').textContent =
          range ? range.start + ' ~ ' + range.end : '';
        elTimeList.appendChild(head);
      }

      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tslot ' + s.cls;
      btn.disabled = !slot.is_available;
      btn.setAttribute('aria-pressed', 'false');
      btn.setAttribute('data-slot-id', slot.slot_id);

      // 스크린 리더에는 한 문장으로 읽어 준다
      btn.setAttribute('aria-label',
        slot.time_label + ' ' + s.text +
        '、空き' + slot.remaining + '名、定員' + slot.capacity + '名');

      btn.innerHTML =
        '<span class="tslot__head">' +
          '<span class="tslot__time"></span>' +
          '<span class="tslot__state">' +
            '<span class="tslot__mark" aria-hidden="true"></span>' +
            '<span class="tslot__state-text"></span>' +
          '</span>' +
        '</span>' +
        '<span class="tslot__seats" aria-hidden="true">' +
          '<span class="tslot__seats-k">空き</span>' +
          '<span class="tslot__seats-v">' +
            '<strong class="tslot__rem"></strong>' +
            '<span class="tslot__cap"></span>' +
          '</span>' +
        '</span>';

      btn.querySelector('.tslot__time').textContent = slot.time_label;
      btn.querySelector('.tslot__mark').textContent = s.mark;
      btn.querySelector('.tslot__state-text').textContent = s.text;
      btn.querySelector('.tslot__rem').textContent = slot.remaining;
      btn.querySelector('.tslot__cap').textContent = ' / ' + slot.capacity + '名';

      if (slot.is_available) {
        btn.addEventListener('click', function () { selectSlot(slot, btn); });
      }

      li.appendChild(btn);
      elTimeList.appendChild(li);
    });
  }

  function selectSlot(slot, btn) {
    selectedSlot = slot;

    Array.prototype.forEach.call(elTimeList.querySelectorAll('.tslot'), function (el) {
      el.setAttribute('aria-pressed', 'false');
    });
    btn.setAttribute('aria-pressed', 'true');

    elPickSummary.textContent = '';

    var line1 = document.createElement('strong');
    line1.textContent = selectedHospital.name;

    var line2 = document.createElement('span');
    line2.className = 'muted';
    line2.textContent = formatDateShort(selectedDate) + '  ' + slot.time_label;

    elPickSummary.appendChild(line1);
    elPickSummary.appendChild(line2);

    show(elStickyBar);
    announce(slot.time_label + 'を選びました。');
  }

  /* ======================================================================
     선택을 다음 화면으로 넘긴다
     ====================================================================== */

  function savePick() {
    try {
      sessionStorage.setItem(PICK_KEY, JSON.stringify({
        hospital: selectedHospital,
        date: selectedDate,
        slot: selectedSlot
      }));
      return true;
    } catch (e) {
      return false;
    }
  }

  /* --- 예약 진행 확인 모달 ------------------------------------------------ */

  var lastFocused = null;

  function openModal() {
    elModalHospital.textContent = selectedHospital.name;
    elModalWhen.textContent =
      formatDateLong(selectedDate) + '  ' + selectedSlot.time_label;

    lastFocused = document.activeElement;
    elModal.classList.remove('is-hidden');
    // 뒤 화면이 같이 스크롤되면 어디를 보고 있었는지 잃는다.
    document.body.classList.add('is-modal-open');
    elModalYes.focus();
  }

  function closeModal() {
    elModal.classList.add('is-hidden');
    document.body.classList.remove('is-modal-open');
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function proceed() {
    if (!savePick()) {
      showAlert('ブラウザの設定により、お選びいただいた内容を保存できませんでした。' +
                'プライベートモードを解除するか、別のブラウザでお試しください。');
      return;
    }

    // 본인 확인을 마쳤으면 정보 입력으로, 아니면 본인 확인부터.
    window.location.href = beforeVerify ? 'verify.html' : 'form.html';
  }

  elNextBtn.addEventListener('click', function () {
    if (!selectedSlot) return;

    var oldHtml = elNextBtn.innerHTML;
    elNextBtn.textContent = '確認中...';
    elNextBtn.disabled = true;

    getJson(API_HOSPITALS + '/' + selectedHospital.id + '/availability?date=' + encodeURIComponent(selectedDate))
      .then(function (data) {
        elNextBtn.innerHTML = oldHtml;
        elNextBtn.disabled = false;

        var slots = data.slots || [];
        var currentSlot = null;
        for (var i = 0; i < slots.length; i++) {
          if (slots[i].slot_id === selectedSlot.slot_id) {
            currentSlot = slots[i];
            break;
          }
        }

        if (!currentSlot || !currentSlot.is_available) {
          showAlert('この時間帯はすでに満席になりました。恐れ入りますが、別の時間帯をお選びください。');
          renderSlots(selectedDate, slots);
          hide(elStickyBar);
          selectedSlot = null;
          return;
        }

        if (!beforeVerify) {
          proceed();
          return;
        }

        openModal();
      })
      .catch(function (err) {
        elNextBtn.innerHTML = oldHtml;
        elNextBtn.disabled = false;
        showAlert(err.message || '空き状況の確認に失敗しました。');
      });
  });

  elModalYes.addEventListener('click', function() {
    var oldHtml = elModalYes.innerHTML;
    elModalYes.textContent = '処理中...';
    elModalYes.disabled = true;
    proceed();
  });

  elModalNo.addEventListener('click', closeModal);
  elModalBackdrop.addEventListener('click', closeModal);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !elModal.classList.contains('is-hidden')) {
      closeModal();
    }
  });

  /* ======================================================================
     시작
     ====================================================================== */

  // 확인 화면에서 「회장·일시 수정」으로 되돌아온 경우에는
  // 「아직 예약이 아닙니다」 안내를 감춘다. 이미 다 아는 이야기다.
  if (!beforeVerify) hide(elPeekNote);

  getJson(API_HOSPITALS)
    .then(function (data) {
      hospitals = data || [];
      renderRegionOptions();
      renderHospitals();
    })
    .catch(function (err) {
      elHospitalList.textContent = '';
      showAlert(err.message ||
        '会場の一覧を読み込めませんでした。しばらくしてからもう一度お試しください。');
    });

})();
