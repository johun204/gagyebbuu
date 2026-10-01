-- 0001: 금액 컬럼 BIGINT 확장 + 거래자 사용자 id 컬럼 추가
--
-- 모두 "추가/확장"만 하는 변경이라 이 마이그레이션을 적용한 뒤에도 이전 버전 앱 코드가
-- 그대로 동작한다 (새 컬럼은 NULL 허용, 기존 컬럼은 타입만 넓어짐). 여러 번 실행해도 안전하다.

-- 1) 21억원(INTEGER 한계)을 넘는 금액/예산을 입력하면 DB 오류가 나던 문제 방지
ALTER TABLE "transaction" ALTER COLUMN amount TYPE BIGINT;
ALTER TABLE ledger ALTER COLUMN monthly_budget TYPE BIGINT;
ALTER TABLE category ALTER COLUMN budget TYPE BIGINT;

-- 2) 거래자를 닉네임 문자열 대신 사용자 id로도 식별 (닉네임 변경 시 색상/집계 끊김 방지)
ALTER TABLE "transaction" ADD COLUMN IF NOT EXISTS transactor_user_id INTEGER REFERENCES "user"(id);
CREATE INDEX IF NOT EXISTS ix_transaction_transactor_user_id ON "transaction" (transactor_user_id);
CREATE INDEX IF NOT EXISTS ix_category_ledger_id ON category (ledger_id);

-- 3) 기존 내역 채우기: 같은 가계부의 현재 참여자 중 닉네임이 정확히 한 명과 일치하면 그 사람
UPDATE "transaction" t
SET transactor_user_id = u.id
FROM "user" u
WHERE t.transactor_user_id IS NULL
  AND t.transactor <> '함께'
  AND u.ledger_id = t.ledger_id
  AND u.nickname = t.transactor
  AND (SELECT count(*) FROM "user" u2 WHERE u2.ledger_id = t.ledger_id AND u2.nickname = t.transactor) = 1;

-- 4) 그래도 비어 있으면(가계부를 나간 사용자 등) 등록자 본인의 닉네임과 일치할 때 등록자로 채움
UPDATE "transaction" t
SET transactor_user_id = t.user_id
FROM "user" u
WHERE t.transactor_user_id IS NULL
  AND t.transactor <> '함께'
  AND u.id = t.user_id
  AND u.nickname = t.transactor;
