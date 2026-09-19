# Japanese-Ningendokku

**[日本語](#日本語) ・ [English](#english) ・ [한국어](#한국어)**

人間ドック・健康診断の Web 予約システム（サンプル実装）
A web reservation system for Japanese health checkups (*Ningen Dock*) — sample implementation
일본 건강검진(인간독) 웹 예약 시스템 — 샘플 구현

---

<a id="日本語"></a>

# 日本語

架空の医療法人「Sample Group」を想定して作成した、人間ドック・健康診断の予約受付システムです。
受診者が Web から自分で予約し、予約センターの担当者が管理画面で予約・会場・定員・郵送申込を処理します。
画面に表示される会場・人物・連絡先はすべて架空のサンプルデータです。

## 技術スタック

| 分類 | 技術 |
|---|---|
| 言語 | Python 3.10+ / JavaScript (ES5〜ES2017) / HTML5 / CSS3 / SQL |
| Web フレームワーク | FastAPI, Starlette（StaticFiles・ミドルウェア） |
| ASGI サーバー | Uvicorn (`uvicorn[standard]`) |
| データ検証・設定 | Pydantic v2, pydantic-settings, python-dotenv, email-validator |
| ORM・DB | SQLAlchemy 2.0（型付き `Mapped` 宣言）, PyMySQL, cryptography, MySQL 8.0（utf8mb4 / InnoDB） |
| マイグレーション | Alembic（起動時自動適用・MySQL `GET_LOCK` による排他） |
| 認証・セキュリティ | itsdangerous（HMAC 署名トークン・署名 Cookie）, bcrypt, Python `secrets` |
| ファイル入出力 | openpyxl（Excel）, csv（UTF-8 / CP932 自動判定）, zipfile, python-multipart |
| メール | Resend API（未設定時は送信ログのみ記録） |
| 非同期処理 | asyncio バックグラウンドタスク, `asyncio.to_thread` |
| フロントエンド | Vanilla JavaScript（フレームワーク・ビルドツールなし）, CSS カスタムプロパティ（デザイントークン） |
| ブラウザ API | sessionStorage / localStorage, Clipboard API, `window.print` + 印刷用 CSS, bfcache (`pageshow`) |
| 外部サービス | Google Maps Embed / 経路検索リンク, Google Fonts（管理画面）, 日本郵便 郵便番号データ（KEN_ALL） |
| 運用 | cron / Windows タスクスケジューラ（前日リマインドメール） |
| テスト | シナリオ型テストスクリプト（API・表計算入出力・正規化・定員計算） |

## 構成

```
frontend/   受診者画面（index・予約 5 ステップ・予約照会・FAQ）と管理画面（SPA）
backend/    FastAPI アプリ（API 約 80 本）・SQLAlchemy モデル（14 テーブル）・Alembic・運用スクリプト
data/       サンプル会場マスター（CSV / Excel）
```

FastAPI が `/api/v1/*` の JSON API と静的ファイルを同じプロセスで配信する単一サーバー構成です。
フロントエンドはビルド工程を持たず、HTML・CSS・JS をそのまま配信します。

## 各部分の技術

### 1. 受診者向け予約フロー

**会場・日時選択 → 本人確認 → 情報入力 → 内容確認 → 完了** の 5 ステップで構成されています。

- **本人確認（名簿照合）** — 生年月日・保険者番号・記号・番号で名簿の候補を絞り込み、漢字氏名、ふりがなの順に照合します。結果は「対象外」「ふりがな不一致」「性別不一致」「予約済み」「予約可能」などに分けて返し、それぞれに合った案内を表示します。照合の前に、全角・半角、ひらがな・カタカナ、長音記号の揺れをサーバー側で正規化します。
- **照合結果の受け渡し** — 本人確認を通過した事実は itsdangerous の署名付き・有効期限付きトークンで次の画面に渡します。サーバーにセッションを持たないため、Redis などの外部ストアは不要です。
- **入力内容の保持** — 入力途中の値は sessionStorage に保存し、「戻る」を押しても消えません。予約完了後にブラウザの「戻る」で確認画面に戻ると、bfcache 復元を検知して「予約はすでに完了しています」と表示します。
- **地図** — 会場の地図は Google Maps Embed で表示し、「経路を調べる」は Google マップの経路検索につなぎます。API キーがなくても代替の埋め込み URL で表示できます。
- **住所検索** — 日本郵便の郵便番号データ（約 12 万件）を起動時に自動で取り込みます。全角数字、各種ハイフン、「〒」、ひらがな入力をそのまま受け付けます。
- **アクセシビリティ** — 文字サイズを 3 段階で切り替えられ（localStorage に保存）、全画面のフォントを Meiryo に統一しています。対象者は主に 40〜74 歳です。

### 2. 予約確定と予約番号

- **二重予約・定員超過の防止** — 予約確定は 1 トランザクションで処理します。定員行を `SELECT … FOR UPDATE` でロックし、空き枠と重複予約を再確認してから、予約番号の発行、予約数の加算、予約の登録を行います。画面で「空きあり」と表示されていても、確定の判定は必ずロック後の DB の値で行います。
- **予約番号** — 英大文字・英小文字・数字 62 種からなる 12 桁の完全ランダム文字列（約 3.2×10²¹ 通り）です。暗号論的乱数（`secrets`）で生成し、連番や日付のような推測できる規則を持たせません。予約番号だけで予約照会ができるため、DB 列を `utf8mb4_bin` にして大文字・小文字を厳密に区別します。
- **予約照会の保護** — 照会の試行回数を IP 単位で制限し、総当たりを防ぎます。

### 3. 定員モデル（30 分 × 16 枠のグリッド）

時間枠は 9:00〜17:00 の 30 分刻み 16 枠です。「会場 × 開催日」1 行に 16 列の定員を持ち、予約数も同じ形の行で管理します。管理画面の表、Excel のマスター、担当者の認識がいずれも「1 行 16 枠」なので、保存形式もそれに合わせました。グリッドを扱うコードは 1 モジュールに閉じ込め、既存の API には「枠」単位のアダプターで同じ形の応答を返します。

### 4. 管理画面

ハッシュルーティングの SPA で、画面は 14 あります。

- **権限 3 段階** — L1 スタッフ / L2 業務管理者 / L3 システム管理者。画面の表示とサーバーの認可を二重に判定します。パスワードは bcrypt でハッシュ化し、セッションは HttpOnly の署名 Cookie です。同じ IP からのログイン失敗が続くと一時的にブロックします。
- **ダッシュボード** — 当日の会場別受診状況のほか、日別・週別・月別の統計を表示します。統計には性別、年代、申込経路（Web・郵送）、予約状態（確定・仮・事前取消・当日取消）、オプション検査ごとの申込率が含まれます。項目を選んで CSV で出力でき、複数の表を選ぶと ZIP にまとめます。
- **横断検索** — 検索窓 1 つで予約・会場・オプション検査・操作ログをまとめて検索します。生年月日は `1958-11-03`、`19581103`、`S33.11.3`、`昭和33年11月3日`、年のみ、のいずれでも読めます。電話で聞き取った予約番号は `0/O`、`1/l/I` が区別しにくいため、管理者の検索に限ってこれらの違いを無視します。
- **郵送受付** — 紙の申込書を 1 件ずつ入力する画面と、Excel から貼り付けて一括登録する画面があります。一括登録はセルが 1 つでも誤っていれば 1 件も保存せず、誤りのあるセルを色で示します。第 1 希望が満員なら第 2・第 3 希望に回します。
- **Excel 風グリッド** — 自作の表コンポーネント（約 1,200 行）です。contentEditable によるセル編集、範囲選択、Excel からの矩形貼り付け、キーボード移動、固定ヘッダー・固定列、行フィルター、選択肢セル、セル単位のエラー表示に対応します。
- **CSV / Excel 入出力エンジン** — 見出し行の自動検出、CP932（日本語版 Excel の CSV）の判定、先頭ゼロが消えた郵便番号の検出、Excel の日付セル変換、CSV インジェクション（数式注入）対策を 1 か所にまとめ、会場・定員・オプション検査・郵送の各表で共通に使います。
- **保存前プレビューと取り消し** — 一括保存の前に変更点を差分で表示します。保存ごとに操作ログへ同じ `batch_id` を残し、1 回の保存をまとめて取り消せます。取り消しの間に他の人が同じ値を変更していた場合や、取り消すと定員が予約数を下回る場合は、その行を上書きせずに理由を示して飛ばします。
- **メール文面の編集** — 6 種類のメール（予約完了、前日リマインド、日程変更など）の件名と本文を画面で編集できます。`{{予約番号}}` のような差し込み変数を使え、保存時に未定義の変数を検出します。

### 5. メール

Resend API で送信します。API キーを設定していない場合は実際には送らず、`mail_logs` への記録だけを行います。そのため、配信基盤が決まる前でも「何をいつ送るべきだったか」が残り、キーを設定すればコードを変えずに実際の送信に切り替わります。前日リマインドは、毎日 12:00 にスクリプトをスケジューラーで実行して送ります。

### 6. データのライフサイクル

- **自動削除** — 受診時刻から一定時間（既定 60 分）が過ぎた予約は、asyncio のバックグラウンドタスクが定期的に削除します。個人情報を必要以上に持ち続けないためです。削除した件数は操作ログに残します。
- **操作ログ** — 管理画面での変更は、変更前後の値を JSON で記録します。

### 7. データベースとマイグレーション

スキーマは Alembic で管理しています。サーバーの起動時に、DB の作成、最新版までの移行、必須データの投入まで自動で行います。サーバーを複数台同時に起動しても二重に移行しないよう、MySQL の `GET_LOCK` で排他制御します。Alembic 導入前の既存 DB については、不足しているテーブル・列・インデックスを補ってから版番号を付けて引き継ぎます。

### 8. テスト

API の予約シナリオ（本人確認〜確定〜照会）、CSV / Excel の往復変換、郵送一括登録、文字の正規化、定員グリッドの計算を検証するシナリオ型テストスクリプトを同梱しています。

## 実際の効用

- **電話・紙の受付業務を減らす** — 受診者が 24 時間いつでも自分で予約でき、予約センターは「空きの確認」と「予約の記入」から解放されます。
- **Web と郵送を 1 つの台帳で管理** — 紙で申し込む受診者も切り捨てず、郵送分も同じ定員と同じ名簿照合を通して登録します。受付経路によって定員が食い違うことがありません。
- **定員超過・二重予約が起きない** — 同じ枠に同時に申し込みがあっても、ロックによって定員を超えません。同じ人が二重に予約することもありません。
- **対象者だけが予約できる** — 保険証の情報で名簿と照合するため、対象外の人の予約や、他人を名乗った予約を受付の段階で防げます。
- **問い合わせを減らす** — 予約番号の控え（コピー・印刷）、予約照会、前日リマインドメールで、最も多い「予約内容を忘れた」という問い合わせを減らします。
- **担当者は Excel の感覚で作業できる** — 会場・定員・郵送申込を Excel からそのまま貼り付けたりファイルで取り込んだりでき、保存前に差分を確認して、誤りがあれば取り消せます。
- **追跡でき、個人情報を溜め込まない** — 誰がいつ何を変えたかが残る一方で、受診が終わった予約は自動で消えます。

---

<a id="english"></a>

# English

A reservation system for *Ningen Dock* (comprehensive health checkups in Japan), built around a fictional medical corporation, "Sample Group".
Examinees book appointments on the web themselves, and reservation-center staff handle bookings, venues, capacity and mail-in applications from an admin console.
All venues, people and contact details shown are fictional sample data.

## Tech Stack

| Category | Technology |
|---|---|
| Languages | Python 3.10+ / JavaScript (ES5–ES2017) / HTML5 / CSS3 / SQL |
| Web framework | FastAPI, Starlette (StaticFiles, middleware) |
| ASGI server | Uvicorn (`uvicorn[standard]`) |
| Validation & settings | Pydantic v2, pydantic-settings, python-dotenv, email-validator |
| ORM & database | SQLAlchemy 2.0 (typed `Mapped` declarations), PyMySQL, cryptography, MySQL 8.0 (utf8mb4 / InnoDB) |
| Migrations | Alembic (applied automatically on startup, serialized with MySQL `GET_LOCK`) |
| Auth & security | itsdangerous (HMAC-signed tokens and cookies), bcrypt, Python `secrets` |
| File I/O | openpyxl (Excel), csv (automatic UTF-8 / CP932 detection), zipfile, python-multipart |
| Email | Resend API (logs only when not configured) |
| Async | asyncio background tasks, `asyncio.to_thread` |
| Frontend | Vanilla JavaScript (no framework, no build step), CSS custom properties (design tokens) |
| Browser APIs | sessionStorage / localStorage, Clipboard API, `window.print` with print CSS, bfcache (`pageshow`) |
| External services | Google Maps Embed and directions links, Google Fonts (admin console), Japan Post postal code data (KEN_ALL) |
| Operations | cron / Windows Task Scheduler (day-before reminder emails) |
| Testing | Scenario-based test scripts (API, spreadsheet I/O, normalization, capacity math) |

## Layout

```
frontend/   Examinee pages (home, 5-step booking, reservation lookup, FAQ) and the admin console (SPA)
backend/    FastAPI app (about 80 API endpoints), SQLAlchemy models (14 tables), Alembic, operational scripts
data/       Sample venue master (CSV / Excel)
```

A single FastAPI process serves both the JSON API under `/api/v1/*` and the static frontend.
The frontend has no build step; HTML, CSS and JS are served as-is.

## How Each Part Works

### 1. Examinee booking flow

Five steps: **choose venue and time → verify identity → enter details → review → done**.

- **Identity verification against a roster** — Candidates are narrowed down by date of birth plus the insurer number, symbol and number from the health insurance card, then matched by kanji name and then by kana reading. The result comes back as a specific outcome (not eligible, kana mismatch, gender mismatch, already booked, eligible, and so on), and each outcome shows its own guidance. Before matching, the server normalizes full-width/half-width characters, hiragana/katakana and long-vowel marks.
- **Carrying verification forward** — Passing verification is carried to the next step as an itsdangerous token that is signed and expires. No session is stored on the server, so no Redis or other external store is needed.
- **Keeping input** — Values being typed are kept in sessionStorage, so pressing Back does not lose them. If the user goes Back to the review page after completing a booking, the page detects the bfcache restore and shows "your reservation is already complete".
- **Maps** — Each venue is shown with Google Maps Embed, and a "directions" link opens Google Maps route search. Maps still appear without an API key, through a fallback embed URL.
- **Address lookup** — Japan Post's postal code data (about 120,000 rows) is imported automatically on startup. Full-width digits, hyphen variants, the 〒 mark and hiragana input are all accepted.
- **Accessibility** — Font size can be switched between three steps (remembered in localStorage), and every page uses the Meiryo font. The target users are mainly aged 40–74.

### 2. Booking confirmation and reservation numbers

- **No overbooking or double booking** — A booking is confirmed in one transaction. The capacity row is locked with `SELECT … FOR UPDATE`, free capacity and duplicate bookings are checked again, and then the reservation number is issued, the count is incremented and the booking is inserted. A slot showing "available" on screen guarantees nothing; the decision is always made on database values read after the lock.
- **Reservation numbers** — 12 fully random characters drawn from 62 (upper case, lower case and digits), about 3.2×10²¹ combinations. They are generated with a cryptographic random source (`secrets`) and carry no guessable pattern such as a sequence or a date. Because the number alone opens the reservation lookup, the column uses `utf8mb4_bin` so upper and lower case are strictly distinct.
- **Protecting lookups** — Lookup attempts are rate-limited per IP address to block brute force.

### 3. Capacity model (a 30-minute × 16-slot grid)

Time slots run from 9:00 to 17:00 in 30-minute steps, 16 in total. One row per "venue × date" holds 16 capacity columns, and bookings are counted in rows of the same shape. The admin tables, the Excel master and the staff's own mental model are all "one row, sixteen slots", so the storage follows the same shape. Code that knows about the grid is confined to one module, and an adapter lets the existing API keep answering in per-slot terms.

### 4. Admin console

A single-page app with hash routing and 14 screens.

- **Three permission levels** — L1 staff, L2 business admin, L3 system admin, checked both in the UI and on the server. Passwords are hashed with bcrypt, and sessions are HttpOnly signed cookies. Repeated failed logins from the same IP are temporarily blocked.
- **Dashboard** — Today's examinees by venue, plus daily, weekly and monthly statistics. The statistics cover gender, age band, channel (web or mail), booking status (confirmed, provisional, cancelled in advance, cancelled on the day) and uptake of each optional exam. You choose the items to export as CSV, and several tables are bundled into one ZIP.
- **Unified search** — One search box covers bookings, venues, optional exams and the audit log. Dates of birth are understood as `1958-11-03`, `19581103`, `S33.11.3`, `昭和33年11月3日` (Japanese era dates) or a year alone. Reservation numbers heard over the phone blur `0/O` and `1/l/I`, so staff search, and only staff search, ignores those differences.
- **Mail-in applications** — One screen enters paper forms one at a time; another takes a block pasted from Excel and registers many at once. In bulk mode, a single bad cell means nothing is saved, and the bad cells are highlighted. If the first choice is full, the second and third choices are tried.
- **Excel-like grid** — A custom table component of about 1,200 lines. It supports contentEditable cell editing, range selection, pasting rectangular blocks from Excel, keyboard navigation, frozen headers and columns, row filtering, choice cells and per-cell error display.
- **CSV / Excel engine** — Header-row detection, CP932 detection (CSV saved by Japanese Excel), detection of postal codes whose leading zero was lost, Excel date cell conversion and CSV (formula) injection protection live in one place. The venue, capacity, optional exam and mail-in tables all share it.
- **Preview and undo** — A diff of the changes is shown before a bulk save. Each save leaves one shared `batch_id` in the audit log, so a whole save can be undone at once. If someone else changed the same value in the meantime, or if undoing would push capacity below the number of bookings, that row is skipped with a reason instead of being overwritten.
- **Email template editor** — The subject and body of six emails (booking complete, day-before reminder, schedule change and others) can be edited on screen. They use merge variables such as `{{予約番号}}` (reservation number), and unknown variables are caught when saving.

### 5. Email

Mail is sent through the Resend API. Without an API key nothing is actually sent; each message is only recorded in `mail_logs`. That way, what should have gone out and when is on record even before a delivery provider is chosen, and adding a key switches to real delivery with no code change. The day-before reminder goes out when a scheduled script runs daily at 12:00.

### 6. Data lifecycle

- **Automatic deletion** — An asyncio background task periodically deletes bookings once a set time (60 minutes by default) has passed after the appointment, so personal data is not kept longer than needed. The number deleted is recorded in the audit log.
- **Audit log** — Every change made in the admin console records the before and after values as JSON.

### 7. Database and migrations

The schema is managed with Alembic. On startup the server creates the database if needed, migrates it to the latest version and loads the required data. MySQL `GET_LOCK` keeps several servers starting at once from migrating twice. A database from before Alembic is taken over by adding its missing tables, columns and indexes and then stamping the version.

### 8. Testing

The repository includes scenario-based test scripts covering the booking API (verify → confirm → lookup), CSV / Excel round trips, bulk mail-in registration, text normalization and capacity grid calculations.

## Real-World Value

- **Less phone and paper work** — Examinees can book on their own at any hour, and the reservation center no longer spends its time checking availability and writing bookings down.
- **Web and mail in one ledger** — Examinees who apply on paper are not left out. Mail-in applications go through the same capacity and the same roster check, so the channels never disagree on how many places are left.
- **No overbooking or double booking** — Even when several people apply for the same slot at the same moment, locking keeps capacity from being exceeded, and the same person cannot book twice.
- **Only eligible people can book** — Matching the health insurance card against the roster stops bookings from ineligible people or from someone using another person's identity, at the point of entry.
- **Fewer inquiries** — Copying or printing the reservation number, the lookup page and the day-before reminder cut down the most common inquiry: "I forgot my booking details".
- **Staff work the way they do in Excel** — Venues, capacity and mail-in applications can be pasted from Excel or imported as files, with a diff before saving and undo if something was wrong.
- **Traceable, without hoarding personal data** — Who changed what and when is recorded, while bookings are deleted automatically once the checkup is over.

---

<a id="한국어"></a>

# 한국어

가상의 의료법인 「Sample Group」을 가정해 만든 일본 건강검진(인간독) 예약 시스템입니다.
검진 대상자가 웹에서 직접 예약하고, 예약센터 담당자가 관리 화면에서 예약·회장·정원·우편 신청을 처리합니다.
화면에 나오는 회장·인물·연락처는 모두 가상의 샘플 데이터입니다.

## 기술 스택

| 분류 | 기술 |
|---|---|
| 언어 | Python 3.10+ / JavaScript (ES5~ES2017) / HTML5 / CSS3 / SQL |
| 웹 프레임워크 | FastAPI, Starlette (StaticFiles·미들웨어) |
| ASGI 서버 | Uvicorn (`uvicorn[standard]`) |
| 데이터 검증·설정 | Pydantic v2, pydantic-settings, python-dotenv, email-validator |
| ORM·DB | SQLAlchemy 2.0 (타입 기반 `Mapped` 선언), PyMySQL, cryptography, MySQL 8.0 (utf8mb4 / InnoDB) |
| 마이그레이션 | Alembic (서버 기동 시 자동 적용, MySQL `GET_LOCK`으로 동시 실행 방지) |
| 인증·보안 | itsdangerous (HMAC 서명 토큰·서명 쿠키), bcrypt, Python `secrets` |
| 파일 입출력 | openpyxl (Excel), csv (UTF-8 / CP932 자동 판별), zipfile, python-multipart |
| 메일 | Resend API (설정 전에는 발송 기록만 남김) |
| 비동기 처리 | asyncio 백그라운드 작업, `asyncio.to_thread` |
| 프런트엔드 | Vanilla JavaScript (프레임워크·빌드 도구 없음), CSS 사용자 정의 속성 (디자인 토큰) |
| 브라우저 API | sessionStorage / localStorage, Clipboard API, `window.print` + 인쇄용 CSS, bfcache (`pageshow`) |
| 외부 서비스 | Google Maps Embed·길찾기 링크, Google Fonts (관리 화면), 일본우편 우편번호 데이터 (KEN_ALL) |
| 운영 | cron / Windows 작업 스케줄러 (전날 알림 메일) |
| 테스트 | 시나리오형 테스트 스크립트 (API·표 입출력·정규화·정원 계산) |

## 구성

```
frontend/   이용자 화면(홈·예약 5단계·예약 조회·FAQ)과 관리 화면(SPA)
backend/    FastAPI 앱(API 약 80개)·SQLAlchemy 모델(테이블 14개)·Alembic·운영 스크립트
data/       샘플 회장 마스터 (CSV / Excel)
```

FastAPI 하나가 `/api/v1/*` JSON API와 정적 파일을 같은 프로세스에서 제공하는 단일 서버 구조입니다.
프런트엔드에는 빌드 과정이 없어서 HTML·CSS·JS 파일을 그대로 제공합니다.

## 부분별 기술

### 1. 이용자 예약 흐름

**회장·일시 선택 → 본인 확인 → 정보 입력 → 내용 확인 → 완료**의 5단계입니다.

- **본인 확인(명부 대조)** — 생년월일과 보험증의 보험자 번호·기호·번호로 명부 후보를 좁힌 뒤, 한자 성명, 후리가나 순으로 대조합니다. 결과는 「대상 아님」「후리가나 불일치」「성별 불일치」「이미 예약함」「예약 가능」 등으로 나누어 돌려주고, 결과마다 알맞은 안내를 보여 줍니다. 대조 전에 서버가 전각·반각, 히라가나·가타카나, 장음 기호의 차이를 정규화합니다.
- **확인 결과 넘기기** — 본인 확인을 통과했다는 사실은 itsdangerous로 서명하고 유효기간을 둔 토큰에 담아 다음 화면으로 넘깁니다. 서버에 세션을 두지 않으므로 Redis 같은 외부 저장소가 필요 없습니다.
- **입력값 유지** — 입력 중인 값은 sessionStorage에 저장되어 「뒤로」를 눌러도 사라지지 않습니다. 예약을 마친 뒤 브라우저의 「뒤로」로 확인 화면에 돌아가면, bfcache 복원을 감지해 「예약이 이미 완료되었습니다」를 보여 줍니다.
- **지도** — 회장 위치는 Google Maps Embed로 보여 주고, 「길 찾기」는 Google 지도 경로 검색으로 연결합니다. API 키가 없어도 대체 임베드 주소로 지도가 표시됩니다.
- **주소 찾기** — 일본우편 우편번호 데이터(약 12만 건)를 서버 기동 시 자동으로 적재합니다. 전각 숫자, 여러 종류의 하이픈, 「〒」, 히라가나 입력을 그대로 받습니다.
- **접근성** — 글자 크기를 3단계로 바꿀 수 있고(localStorage에 저장), 모든 화면의 글꼴을 Meiryo로 통일했습니다. 주 이용자는 40~74세입니다.

### 2. 예약 확정과 예약번호

- **초과 예약·중복 예약 방지** — 예약 확정은 한 트랜잭션에서 처리합니다. 정원 행을 `SELECT … FOR UPDATE`로 잠그고, 빈자리와 중복 예약을 다시 확인한 뒤, 예약번호 발행, 예약 수 증가, 예약 등록을 합니다. 화면에 「예약 가능」으로 보였더라도 확정 판정은 언제나 잠근 뒤의 DB 값으로 합니다.
- **예약번호** — 영문 대문자·소문자·숫자 62종으로 만든 12자리 완전 무작위 문자열입니다(약 3.2×10²¹가지). 암호학적 난수(`secrets`)로 만들고, 순번이나 날짜처럼 짐작할 수 있는 규칙을 넣지 않습니다. 예약번호만으로 예약 조회가 되기 때문에 DB 컬럼을 `utf8mb4_bin`으로 두어 대문자와 소문자를 엄격히 구별합니다.
- **조회 보호** — 예약 조회 시도 횟수를 IP 단위로 제한해 무작위 대입을 막습니다.

### 3. 정원 모델 (30분 × 16칸 격자)

시간대는 9:00~17:00을 30분 단위로 나눈 16칸입니다. 「회장 × 날짜」 한 행이 정원 16칸을 갖고, 예약 수도 같은 모양의 행으로 관리합니다. 관리 화면의 표, Excel 마스터, 담당자가 생각하는 방식이 모두 「한 줄에 16칸」이어서 저장 형식도 그에 맞췄습니다. 격자를 다루는 코드는 모듈 하나에 모아 두었고, 기존 API는 어댑터를 거쳐 「칸」 단위의 같은 응답을 계속 돌려줍니다.

### 4. 관리 화면

해시 라우팅을 쓰는 SPA이고, 화면은 14개입니다.

- **권한 3단계** — L1 스태프 / L2 업무 관리자 / L3 시스템 관리자. 화면 표시와 서버 권한 검사를 이중으로 합니다. 비밀번호는 bcrypt로 해시하고, 세션은 HttpOnly 서명 쿠키입니다. 같은 IP에서 로그인 실패가 이어지면 잠시 차단합니다.
- **대시보드** — 오늘의 회장별 검진 현황과 일별·주별·월별 통계를 보여 줍니다. 통계는 성별, 연령대, 접수 경로(웹·우편), 예약 상태(확정·임시·사전 취소·당일 취소), 옵션 검사별 신청 비율을 다룹니다. 항목을 골라 CSV로 내보낼 수 있고, 표를 여러 개 고르면 ZIP 하나로 묶습니다.
- **통합 검색** — 검색창 하나로 예약·회장·옵션 검사·조작 로그를 한꺼번에 찾습니다. 생년월일은 `1958-11-03`, `19581103`, `S33.11.3`, `昭和33年11月3日`(일본 연호), 연도만 입력한 경우 모두 읽습니다. 전화로 들은 예약번호는 `0/O`, `1/l/I`가 헷갈리기 쉬워서, 관리자 검색에서만 이 차이를 무시합니다.
- **우편 접수** — 종이 신청서를 한 건씩 입력하는 화면과, Excel에서 붙여 넣어 한꺼번에 등록하는 화면이 있습니다. 일괄 등록은 한 칸이라도 틀리면 한 건도 저장하지 않고, 틀린 칸을 색으로 표시합니다. 제1희망이 차 있으면 제2·제3희망으로 넘깁니다.
- **Excel 같은 표** — 직접 만든 표 컴포넌트(약 1,200줄)입니다. contentEditable 셀 편집, 범위 선택, Excel에서 복사한 사각형 영역 붙여넣기, 키보드 이동, 고정 머리글·고정 열, 행 거르기, 선택형 칸, 칸 단위 오류 표시를 지원합니다.
- **CSV / Excel 입출력 엔진** — 제목 줄 자동 찾기, CP932(일본어판 Excel이 저장한 CSV) 판별, 앞자리 0이 사라진 우편번호 감지, Excel 날짜 셀 변환, CSV 수식 주입 방어를 한곳에 모았습니다. 회장·정원·옵션 검사·우편 접수 표가 모두 이 엔진을 함께 씁니다.
- **저장 전 미리보기와 되돌리기** — 일괄 저장 전에 바뀌는 내용을 비교해 보여 줍니다. 저장할 때마다 조작 로그에 같은 `batch_id`를 남겨, 한 번의 저장을 통째로 되돌릴 수 있습니다. 그사이 다른 사람이 같은 값을 고쳤거나, 되돌리면 정원이 예약 수보다 적어지는 행은 덮어쓰지 않고 이유를 알리며 건너뜁니다.
- **메일 문면 편집** — 메일 6종(예약 완료, 전날 알림, 일정 변경 등)의 제목과 본문을 화면에서 고칠 수 있습니다. `{{予約番号}}`(예약번호) 같은 치환 변수를 쓰며, 저장할 때 정의되지 않은 변수를 잡아냅니다.

### 5. 메일

Resend API로 보냅니다. API 키가 없으면 실제로 보내지 않고 `mail_logs`에 기록만 남깁니다. 그래서 발송 수단이 정해지기 전에도 「무엇을 언제 보냈어야 하는지」가 남고, 키를 넣으면 코드 수정 없이 실제 발송으로 바뀝니다. 전날 알림 메일은 매일 12:00에 스케줄러로 스크립트를 실행해 보냅니다.

### 6. 데이터 수명 관리

- **자동 삭제** — 검진 시각에서 정해진 시간(기본 60분)이 지난 예약은 asyncio 백그라운드 작업이 주기적으로 삭제합니다. 개인정보를 필요 이상 보관하지 않기 위해서입니다. 삭제한 건수는 조작 로그에 남깁니다.
- **조작 로그** — 관리 화면에서 바꾼 내용은 바뀌기 전과 후의 값을 JSON으로 기록합니다.

### 7. 데이터베이스와 마이그레이션

스키마는 Alembic으로 관리합니다. 서버가 기동할 때 DB 생성, 최신 버전까지 이전, 필수 데이터 입력까지 자동으로 합니다. 서버 여러 대가 동시에 기동해도 이전이 두 번 일어나지 않도록 MySQL `GET_LOCK`으로 막습니다. Alembic을 도입하기 전의 DB는 빠진 테이블·컬럼·인덱스를 채운 뒤 버전을 붙여 이어받습니다.

### 8. 테스트

예약 API 시나리오(본인 확인 → 확정 → 조회), CSV / Excel 왕복 변환, 우편 일괄 등록, 문자 정규화, 정원 격자 계산을 검증하는 시나리오형 테스트 스크립트가 들어 있습니다.

## 실제 효용

- **전화·종이 접수 업무 감소** — 검진 대상자가 언제든 직접 예약할 수 있어, 예약센터는 「빈자리 확인」과 「예약 기록」에 쓰던 시간을 덜게 됩니다.
- **웹과 우편을 하나의 장부로** — 종이로 신청하는 대상자도 놓치지 않습니다. 우편 신청도 같은 정원과 같은 명부 대조를 거쳐 등록하므로 접수 경로마다 남은 자리가 어긋나지 않습니다.
- **초과 예약·중복 예약이 생기지 않음** — 같은 칸에 동시에 신청이 몰려도 잠금 때문에 정원을 넘지 않고, 같은 사람이 두 번 예약할 수도 없습니다.
- **대상자만 예약 가능** — 보험증 정보로 명부와 대조하므로, 대상이 아닌 사람의 예약이나 남의 이름을 쓴 예약을 접수 단계에서 막습니다.
- **문의 감소** — 예약번호 복사·인쇄, 예약 조회, 전날 알림 메일로 가장 많은 문의인 「예약 내용을 잊어버렸다」를 줄입니다.
- **담당자는 Excel 쓰듯 일함** — 회장·정원·우편 신청을 Excel에서 그대로 붙여 넣거나 파일로 가져올 수 있고, 저장 전에 바뀌는 내용을 확인하며, 잘못되면 되돌릴 수 있습니다.
- **추적은 되고 개인정보는 쌓이지 않음** — 누가 언제 무엇을 바꿨는지는 남고, 검진이 끝난 예약은 자동으로 지워집니다.
