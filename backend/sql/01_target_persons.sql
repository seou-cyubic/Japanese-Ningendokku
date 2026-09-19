-- ==========================================================================
-- 검진 대상자 명부 (target_persons)
--
-- ※ 이 파일은 참조용 문서다. 실제 생성은 아래 명령으로 수행한다.
--      python -m scripts.init_db
--    정식 개발 단계에서는 Alembic 마이그레이션으로 전환한다. (plan.md §11.2)
--
-- 이 테이블에는 **신원 정보만** 둔다.
-- 「예약했는가」는 예약 테이블(reservations)만이 답한다.
-- 같은 사실을 두 곳에 적으면 취소·자동 삭제 때 한쪽만 갱신되어 어긋나고,
-- 어긋난 순간 「예약이 있다는데 내역이 없다」는 문의가 된다.
-- (plan.md §16.6)
-- ==========================================================================

CREATE DATABASE IF NOT EXISTS `kenshin_reservation`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE `kenshin_reservation`;

CREATE TABLE IF NOT EXISTS `target_persons` (
  `id`                BIGINT       NOT NULL AUTO_INCREMENT,

  -- 성명 (한자) ------------------------------------------------------------
  -- 표기 흔들림(전각 공백 등)은 대조 시점에 normalize_name() 으로 흡수한다.
  -- 정규화 값을 따로 저장하지 않는 이유는, 같은 정보를 두 벌 두면
  -- 한쪽만 갱신되어 어긋날 수 있기 때문이다.
  `last_name`         VARCHAR(60)  NOT NULL COMMENT '성 (한자) 예: 田中',
  `first_name`        VARCHAR(60)  NOT NULL COMMENT '이름 (한자) 예: 太郎',

  -- 후리가나 (전각 가타카나) -------------------------------------------------
  -- 같은 한자라도 읽는 법이 다르면 다른 사람이므로 본인 확인 대조 키에 포함한다.
  -- 탁점·작은 글자는 정규화하지 않는다. (plan.md §16.1)
  `last_name_kana`    VARCHAR(60)  NOT NULL DEFAULT '' COMMENT '성 후리가나 (전각 가타카나) 예: タナカ',
  `first_name_kana`   VARCHAR(60)  NOT NULL DEFAULT '' COMMENT '이름 후리가나 (전각 가타카나) 예: タロウ',

  -- 미들네임 (외국인 전용, 통상 공란) ----------------------------------------
  -- 대조 키에는 넣지 않는다. 명부에 대부분 공란이라 넣으면 입력한 사람이 튕긴다.
  `middle_name`       VARCHAR(120) NOT NULL DEFAULT '' COMMENT '미들네임 (표기)',
  `middle_name_kana`  VARCHAR(120) NOT NULL DEFAULT '' COMMENT '미들네임 후리가나',

  -- 기타 신원 ---------------------------------------------------------------
  `gender`            ENUM('M','F') NOT NULL COMMENT '성별 M=남성 F=여성',
  `birth_date`        DATE         NOT NULL COMMENT '생년월일 (서기)',

  -- 건강보험증 -------------------------------------------------------------
  -- 실물 카드 표기 순서에 맞춰 3개 항목으로 분리 보관한다.
  -- 테스트 데이터는 전건 0000-ABCD-0000 이다.
  `insurer_no`        VARCHAR(20)  NOT NULL COMMENT '보험자 번호',
  `insurance_symbol`  VARCHAR(20)  NOT NULL COMMENT '기호',
  `insurance_no`      VARCHAR(20)  NOT NULL COMMENT '번호',

  PRIMARY KEY (`id`),

  -- 본인 확인 조회 : 생년월일 + 보험증 3항목으로 후보를 좁힌 뒤
  --                 성·이름을 정규화 비교한다. (services/verify_service.py)
  KEY `ix_target_lookup` (`birth_date`, `insurer_no`, `insurance_symbol`, `insurance_no`),
  KEY `ix_target_name` (`last_name`, `first_name`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_general_ci
  COMMENT='건강검진 대상자 명부 (신원 정보 전용)';
