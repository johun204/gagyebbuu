package com.johun.gagyebbuu

import java.text.Normalizer
import java.time.DateTimeException
import java.time.LocalDateTime
import java.util.regex.Matcher
import java.util.regex.Pattern

/**
 * 기기 알림(문자/카드앱/은행앱/알림톡 등) 문구에서 입출금 내역을 뽑아낸다.
 *
 * 해석은 기기에서 하고, 거래로 판단된 알림만 서버로 보낸다. 서버의 txparse.py(구버전 앱용)를 그대로 옮긴 것이라
 * 규칙을 고칠 때는 두 곳을 함께 고친다. 둘의 결과가 같은지는 txparse_cases.json 으로 검사한다 (tests/app_parser_cases.py).
 * 특정 앱 전용 규칙 없이 흔한 형태만으로 판단한다.
 *   - '항목 : 값' 형태(알림톡): 승인금액/가맹점명/거래일시/거래구분 등
 *   - 한 줄/여러 줄 카드·은행 문자: 금액+'원', '₩12,000', '입금 50,000', 'MM/DD HH:MM', 마스킹된 이름 등
 *   - 문장형 앱 알림: '스타벅스에서 12,000원 결제', '홍길동님이 5만원을 보냈어요' 등
 * 금액을 원화로 알 수 없는 해외 결제는 amount=0 으로 돌려주고(사용자가 금액 입력), 제목에 통화를 남긴다.
 */
object TxParser {
    const val MAX_RAW_LEN = 1000
    const val MAX_TITLE_LEN = 100
    const val MAX_AMOUNT = 999_999_999_999L
    const val EXPENSE = "지출"
    const val INCOME = "수입"

    class Parsed(val txType: String, val amount: Long, val title: String, val datetime: LocalDateTime)

    private fun rx(p: String, flags: Int = 0): Pattern = Pattern.compile(p, flags)

    private const val NUM = """\d{1,3}(?:,\d{3})+|\d+"""
    private const val CUR = "USD|JPY|EUR|CNY|GBP|HKD|SGD|AUD|CAD|THB|VND|PHP|TWD|CHF"
    private val KRW = rx("""(?:₩|KRW|원화)\s*($NUM)|($NUM)\s*원(?!화)""")
    private val FOREIGN = rx("""($CUR|US\$|\$|€|£|¥)\s*(\d[\d,]*(?:\.\d+)?)""" +
            """|(\d[\d,]*(?:\.\d+)?)\s*($CUR|달러|엔|유로|위안)""")
    // 원 표기가 없는 은행 문자: '입금 50,000', '출금\n50,000', '금액:50,000'
    private val BARE_AFTER_KEYWORD = rx(
        """(?:입금|출금|이체|결제|승인|지급|인출|송금|금액)\s*:?\s*(?<![\d\-])($NUM)(?![\d,]*\s*원)(?![\-/:.*\d])""")
    private val ONLY_NUM = rx("""\s*($NUM)\s*""")

    // 금액 바로 앞/뒤에 이런 말이 있으면 거래 금액이 아니다
    private val EXCLUDE_BEFORE = rx(
        """(누적|잔액|잔여|잔고|한도|가능|포인트|적립|합계|총액|수수료|예정|청구|최대|최소|할인|이용가능|사용가능)[^\n\d]{0,4}$""")
    private val EXCLUDE_AFTER = rx("""^\s*(적립|할인|포인트|이상|이하|한도)""")

    private val TX_WORDS = rx("승인|결제|출금|입금|사용|이체|송금|보냈|받았|들어왔|환불|취소|납부|지급|인출|캐시백|급여|이자|구매|충전")
    private val INCOME_WORDS = rx("입금(?!자|처|예정)|받았|받은|들어왔|들어옴|환불|캐시백|급여|이자|수령|입금됨|충전")
    private val EXPENSE_WORDS = rx("승인|결제|출금|사용|보냈|보낸|송금|납부|자동이체|이체|지급|인출|구매")
    private val CARD_HINT = rx("카드|체크")
    private val CLOCK = rx("""(?<!\d)\d{1,2}:\d{2}(?!\d)""")
    private val WON_SIGN = rx("""₩\s*\d""")
    private val REFUND = rx("취소|환불")
    private val REJECT = rx(
        """\(광고\)|\[광고\]|^광고|승인\s*거절|거절|예정|명세서|인증\s*번호|OTP|결제일\s*안내|미납|연체|이벤트|혜택\s*안내|실패""")
    private val SENT_TO_ME = rx("""님(?:이|께서)\s.*(?:보냈|보내셨|송금했|입금했)""")
    private val SENT_BY_ME = rx("""님(?:에게|께)\s.*(?:보냈|송금|이체)""")

    // '항목 : 값' 줄
    private val KV_LINE = rx("""^\s*[\[(<]?\s*([가-힣A-Za-z][가-힣A-Za-z ]{0,11}?)\s*[\])>]?\s*[:=]\s*(.+?)\s*$""")
    private val KV_AMOUNT = listOf("금액", "결제액", "출금액", "입금액", "이용액", "승인액", "거래액", "송금액", "이체액")
    private val KV_AMOUNT_NOT = listOf("누적", "잔액", "한도", "가능", "예정", "포인트", "합계", "총", "수수료", "청구")
    private val KV_MERCHANT = listOf("가맹점", "사용처", "이용처", "상호", "결제처", "거래처", "상점", "받는분", "받는사람", "보낸분",
        "보낸사람", "입금자", "출금처", "송금인", "수취인", "적요", "내용", "이용내역", "사용내역", "판매자", "업체")
    private val KV_DATETIME = listOf("일시", "일자", "시간", "날짜", "시각")
    private val KV_TYPE = setOf("거래구분", "구분", "거래종류", "거래유형", "유형", "종류")

    // 날짜/시간
    private val DT_PATTERNS = listOf(
        rx("""(?<y>20\d{2})\s*[./\-]\s*(?<mo>\d{1,2})\s*[./\-]\s*(?<d>\d{1,2})\.?(?:\s*\([^)]*\))?[\s,]*(?<h>\d{1,2}):(?<mi>\d{2})"""),
        rx("""(?<![\d.,])(?<mo>\d{1,2})[./\-](?<d>\d{1,2})(?:\s*\([^)]*\))?[\s,]*(?<h>\d{1,2}):(?<mi>\d{2})"""),
        rx("""(?:(?<y>20\d{2})년\s*)?(?<mo>\d{1,2})월\s*(?<d>\d{1,2})일(?:\s*\([^)]*\))?\s*(?:(?<ap>오전|오후)\s*)?(?<h>\d{1,2})(?:시|:)\s*(?:(?<mi>\d{1,2})분?)?"""),
        rx("""(?<y>20\d{2})\s*[./\-]\s*(?<mo>\d{1,2})\s*[./\-]\s*(?<d>\d{1,2})"""),
        rx("""(?:(?<y>20\d{2})년\s*)?(?<mo>\d{1,2})월\s*(?<d>\d{1,2})일"""),
        rx("""(?<![\d.,/])(?<mo>\d{1,2})/(?<d>\d{1,2})(?![\d/])"""),
        rx("""(?<![\d:])(?:(?<ap>오전|오후)\s*)?(?<h>\d{1,2}):(?<mi>\d{2})(?::\d{2})?(?![\d:])"""),
    )

    // 가맹점(상대방) 후보에서 지울 것들. 지운 자리에서 조각을 나눈다.
    private val NOISE_PATTERNS = listOf(
        rx("""\[[^\]]*\]"""),                              // [Web발신], [KB]
        rx("""(?:누적|잔액|잔여|잔고|한도|가능|포인트|적립|합계|총액|수수료)\s*:?\s*(?:₩|KRW)?\s*[\-+]?(?:$NUM)\s*원?"""),  // 잔액-5,202,047 (마이너스통장)
        FOREIGN,
        rx("""(?:₩|KRW|원화)\s*(?:$NUM)|(?:$NUM)\s*원"""),
        rx("""(?:20\d{2}\s*[./\-]\s*)?\d{1,2}\s*[./\-]\s*\d{1,2}(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?"""),
        rx("""(?:20\d{2}년\s*)?\d{1,2}월\s*\d{1,2}일|(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?|\d{1,2}:\d{2}(?::\d{2})?"""),
        rx("""\S*\*\S*"""),                                // 홍*동, 123-***-456, 1*2*
        rx("""[→←▶▷►]|->|<-|\|"""),
        rx("""(?<![\p{L}\p{N}_])[\d\-]{4,}(?![\p{L}\p{N}_])"""),  // 계좌/카드 번호
    )
    private val NOISE_WORDS = setOf(
        "승인", "결제", "일시불", "입금", "출금", "이체", "사용", "취소", "승인취소", "결제취소", "환불", "지급", "거절",
        "누적", "잔액", "원", "을", "를", "이", "가", "은", "는", "에서", "으로", "로", "님", "금액", "알림", "내역", "안내",
        "Web발신", "web발신", "해외", "국내", "건", "완료", "결제완료", "승인완료", "출금완료", "입금완료", "송금완료",
        "이용", "거래", "총", "내", "통장", "계좌", "입출금", "입출금통장", "고객님", "회원님", "본인", "가족", "개인", "법인",
        "신용", "체크", "할부", "무이자", "승인안내", "결제안내", "이용안내", "거래안내", "입출금알림", "결제알림", "승인알림",
        "자동이체", "송금", "받기", "보내기", "충전", "출금예정", "타행", "당행", "이체입금", "이체출금", "전자금융", "인터넷", "모바일",
        "적립", "보낸", "받은", "돈", "돈이", "돈을", "들어온", "결제한", "사용한", "이용한", "보낸돈", "받은돈",
        "ATM", "CD", "해외승인", "해외결제", "체크승인", "신용승인", "정상", "처리", "접수", "사용금액", "결제금액", "승인금액",
    )
    // 카드사/은행/간편결제 이름 (정확히 이 낱말일 때만 지운다)
    private val BRAND_WORDS = setOf(
        "신한", "KB", "국민", "KB국민", "우리", "하나", "농협", "NH", "NH농협", "IBK", "기업", "SC", "SC제일", "씨티", "새마을",
        "새마을금고", "MG", "우체국", "신협", "수협", "산업", "KDB", "광주", "전북", "경남", "부산", "대구", "제주", "BNK", "DGB",
        "삼성", "현대", "롯데", "BC", "비씨", "토스", "toss", "Toss", "카카오페이", "네이버페이", "Npay", "N페이", "페이코", "PAYCO",
        "삼성페이", "토스페이", "애플페이", "제로페이", "페이북", "SOL", "KB Pay", "KBPay", "스마일페이", "SSGPAY", "SSG페이",
        "카카오뱅크", "토스뱅크", "케이뱅크", "하나머니", "카카오페이머니", "네이버페이머니", "페이머니", "머니",
    )
    private val VERB_TAIL = rx("""(습니다|니다|어요|아요|해요|돼요|세요|었음|됨)[.!~?]*$""")
    private val KIND_WORD = rx("""^\S{1,6}(?:입금|출금)$""")  // 은행 문자의 거래 종류: FBS출금, 전자금융입금, ATM출금
    private val HALBU = rx("""^(?:할부)?\d*개월$|^할부\S*$""")
    private val COUNTERPARTY = rx("""^(.+?)님(?:이|께서|으로부터|에게서)$""")   // 보낸 사람: 홍길동님이
    private val RECIPIENT = rx("""^(.+?)님(?:에게|께)$""")                     // 받는 사람: 홍길동님에게
    private val SALUTATION = rx("""^.+님[,!.]*$|^.+고객님""")                   // 홍길동님, (인사말)
    private val CORP = rx("""\(주\)|㈜|주식회사|\(유\)|유한회사""")
    private val ONLY_DIGITS = rx("""[\d,.%]+""")
    private val PARTICLE_TAIL = rx("""(에서|으로|에게|에서의)$""")
    private val WON_TAIL = rx("""\d(원)$""")
    private val WON_OR_NIM_TAIL = rx("""(원|님)$""")
    private val WHOLE_PAREN = rx("""\([^()]*\)""")
    private val PAREN = rx("""\(([^()\n]*)\)""")
    private val WEEKDAY = rx("[월화수목금토일]")
    private val ARROW = Regex("""→|->|▶|▷|►""")

    // 카드사/은행 낱말(신한카드1234승인, 토스뱅크 등)은 지우되 '카드대금', '통신요금' 같은 거래 내용은 남긴다
    private val ISSUER_TOKEN = rx("""\S*(?:카드|은행|뱅크|뱅킹|BANK|Bank|bank|체크)\S*""")
    private val KEEP_ISSUER = rx("대금|요금|수수료|보험|연회비|이자")

    private val INVISIBLE = rx("""[​-‏‪-‮⁠⁦-⁩﻿]""")
    private val BULLET = rx("""^[ \t]*[■□▶▷●○◆◇※•·\-*>]+[ \t]*""", Pattern.MULTILINE)  // 글머리표
    private val SPACES = rx("""[ \t ]+""")
    private val BLANK_LINES = rx("""\n\s*\n+""")

    private fun String.strip(chars: String) = trim { it in chars }

    /** 공백으로 나눈 낱말들 (빈 낱말 없음) */
    private fun words(s: String): List<String> {
        val out = ArrayList<String>()
        var start = -1
        for (i in s.indices) {
            if (s[i].isWhitespace()) {
                if (start >= 0) { out.add(s.substring(start, i)); start = -1 }
            } else if (start < 0) start = i
        }
        if (start >= 0) out.add(s.substring(start))
        return out
    }

    /** 패턴에 없는 이름이거나 해당 부분이 없으면 null */
    private fun Matcher.named(name: String): String? = try { group(name) } catch (e: IllegalArgumentException) { null }

    private fun replace(p: Pattern, s: String, f: (Matcher) -> String): String {
        val m = p.matcher(s)
        val sb = StringBuilder()
        var last = 0
        while (m.find()) {
            sb.append(s, last, m.start()).append(f(m))
            last = m.end()
        }
        return sb.append(s, last, s.length).toString()
    }

    fun normalize(title: String?, text: String?): String {
        var full = listOf(title.orEmpty().trim(), text.orEmpty().trim()).filter { it.isNotEmpty() }.joinToString("\n")
        full = Normalizer.normalize(full, Normalizer.Form.NFKC).replace("\r", "")
        full = INVISIBLE.matcher(full).replaceAll("")
        full = BULLET.matcher(full).replaceAll("")
        full = SPACES.matcher(full).replaceAll(" ")
        full = BLANK_LINES.matcher(full).replaceAll("\n")
        return full.trim().take(MAX_RAW_LEN)
    }

    private fun toLong(s: String) = s.replace(",", "").toLongOrNull() ?: Long.MAX_VALUE

    private fun krwIn(s: String): Long? {
        val m = KRW.matcher(s)
        if (m.find()) return toLong(m.group(1) ?: m.group(2))
        val only = ONLY_NUM.matcher(s)
        return if (only.matches()) toLong(only.group(1)) else null
    }

    private class Kv(var amount: Long? = null, var merchant: String? = null, var datetime: String? = null, var type: String? = null)

    private fun parseKv(full: String): Kv {
        val kv = Kv()
        for (line in full.split('\n')) {
            val m = KV_LINE.matcher(line)
            if (!m.find()) continue
            val key = m.group(1).replace(" ", "")
            val value = m.group(2).trim()
            if (kv.amount == null && KV_AMOUNT.any { it in key } && KV_AMOUNT_NOT.none { it in key }) {
                kv.amount = krwIn(value)
            } else if (kv.merchant == null && KV_MERCHANT.any { it in key }) {
                kv.merchant = value
            } else if (kv.datetime == null && KV_DATETIME.any { it in key }) {
                kv.datetime = value
            } else if (kv.type == null && key in KV_TYPE) {
                kv.type = value
            }
        }
        return kv
    }

    private class Candidate(val pos: Int, val amount: Long, val score: Int)

    /** (위치, 금액, 점수) 목록. 거래 단어(승인/결제/입금 등)와 붙어 있을수록 점수가 높다. */
    private fun amountCandidates(full: String): List<Candidate> {
        val out = ArrayList<Triple<Int, Int, Long>>()
        val krw = KRW.matcher(full)
        while (krw.find()) out.add(Triple(krw.start(), krw.end(), toLong(krw.group(1) ?: krw.group(2))))
        val bare = BARE_AFTER_KEYWORD.matcher(full)
        while (bare.find()) out.add(Triple(bare.start(1), bare.end(1), toLong(bare.group(1))))
        val scored = ArrayList<Candidate>()
        for ((start, end, n) in out) {
            val lineStart = full.lastIndexOf('\n', start - 1) + 1
            val before = full.substring(maxOf(lineStart, start - 12), start)
            val after = full.substring(end, minOf(full.length, end + 8))
            if (n <= 0 || EXCLUDE_BEFORE.matcher(before).find() || EXCLUDE_AFTER.matcher(after).find()) continue
            val near = full.substring(maxOf(0, start - 8), minOf(full.length, end + 8))
            scored.add(Candidate(start, n, if (TX_WORDS.matcher(near).find()) 1 else 0))
        }
        return scored
    }

    private fun pickAmount(full: String): Candidate? =
        amountCandidates(full).maxWithOrNull(compareBy<Candidate> { it.score }.thenByDescending { it.pos })

    private fun pickForeign(full: String): String? {
        val m = FOREIGN.matcher(full)
        if (!m.find()) return null
        return if (m.group(1) != null) "${m.group(1)} ${m.group(2)}" else "${m.group(4)} ${m.group(3)}"
    }

    /** (지출/수입, 취소·환불 여부) */
    private fun txType(full: String, kvType: String?, amountPos: Int?): Pair<String, Boolean> {
        if (!kvType.isNullOrEmpty()) {
            if (REFUND.matcher(kvType).find()) return INCOME to true
            if (INCOME_WORDS.matcher(kvType).find()) return INCOME to false
            if (EXPENSE_WORDS.matcher(kvType).find()) return EXPENSE to false
        }
        if (REFUND.matcher(full).find()) return INCOME to true
        // 송금 문장: '홍길동님이 ... 보냈어요' = 받음, '홍길동님에게 ... 보냈어요' = 보냄
        if (SENT_TO_ME.matcher(full).find()) return INCOME to false
        if (SENT_BY_ME.matcher(full).find()) return EXPENSE to false
        // 금액과 가장 가까운 입금/출금 단어로 판단 (동점이면 지출)
        val pos = amountPos ?: 0
        fun dist(p: Pattern): Int {
            val m = p.matcher(full)
            var best = 1_000_000
            while (m.find()) best = minOf(best, kotlin.math.abs(m.start() - pos))
            return best
        }
        return (if (dist(INCOME_WORDS) < dist(EXPENSE_WORDS)) INCOME else EXPENSE) to false
    }

    private fun pickDatetime(s: String, postedAt: LocalDateTime): LocalDateTime {
        for (p in DT_PATTERNS) {
            val m = p.matcher(s)
            while (m.find()) {
                val gy = m.named("y")
                val gmo = m.named("mo")
                val gh = m.named("h")
                val gmi = m.named("mi")
                val ap = m.named("ap")
                val hasDate = gmo != null
                val hasTime = gh != null
                val y = gy?.toInt() ?: postedAt.year
                val mo = if (hasDate) gmo!!.toInt() else postedAt.monthValue
                val d = if (hasDate) m.named("d")!!.toInt() else postedAt.dayOfMonth
                var h = if (hasTime) gh!!.toInt() else postedAt.hour
                val mi = if (hasTime && !gmi.isNullOrEmpty()) gmi.toInt() else if (hasTime) 0 else postedAt.minute
                if (ap == "오후" && h < 12) h += 12
                else if (ap == "오전" && h == 12) h = 0
                var dt = try { LocalDateTime.of(y, mo, d, h, mi) } catch (e: DateTimeException) { continue }
                if (gy == null && hasDate && dt > postedAt.plusDays(1)) dt = dt.minusYears(1)  // 1월 초에 받은 12월 31일 문자
                if (!hasDate && dt > postedAt.plusMinutes(5)) dt = dt.minusDays(1)  // 자정 직후에 받은 전날 밤 결제
                return dt
            }
        }
        return postedAt
    }

    private fun cleanMerchant(raw: String?): String {
        var s = CORP.matcher(raw.orEmpty()).replaceAll(" ")
        s = words(s).joinToString(" ").strip(" ,.:;|/-")
        if (WHOLE_PAREN.matcher(s).matches()) s = s.substring(1, s.length - 1).trim()  // '(스타비해외)' 처럼 통째로 괄호에 싸인 경우
        return s.take(MAX_TITLE_LEN)
    }

    private fun cleanToken(token: String): String {
        var tok = token.strip(" ,.:;|/·-~!?\"'")
        if (tok.count { it == '(' } != tok.count { it == ')' }) tok = tok.strip("()")  // '카드입금(' 처럼 짝이 안 맞는 괄호
        if (tok.isEmpty() || ONLY_DIGITS.matcher(tok).matches() || KIND_WORD.matcher(tok).find()) return ""
        if (tok in NOISE_WORDS || tok in BRAND_WORDS || VERB_TAIL.matcher(tok).find() || HALBU.matcher(tok).find()) return ""
        for (p in listOf(COUNTERPARTY, RECIPIENT)) {
            val m = p.matcher(tok)
            if (m.find()) return m.group(1)
        }
        if (SALUTATION.matcher(tok).find()) return ""
        if (tok.length > 3) tok = PARTICLE_TAIL.matcher(tok).replaceAll("")
        if (WON_TAIL.matcher(tok).find()) tok = WON_OR_NIM_TAIL.matcher(tok).replaceAll("")
        return if (tok in NOISE_WORDS || tok in BRAND_WORDS) "" else tok
    }

    private fun paren(m: Matcher): String {
        // (1*2*), (일시불), (목) 같은 부가 정보는 지우고, '씨유(CU)' 처럼 상호의 일부인 괄호는 남긴다
        val inner = m.group(1).trim()
        if (inner.isEmpty() || inner.any { it.isDigit() || it == '*' } || WEEKDAY.matcher(inner).matches()
            || CORP.matcher(m.group()).matches()) return "\n"
        return if (words(inner).any { cleanToken(it).isNotEmpty() }) m.group() else "\n"
    }

    /** 줄마다 (원래 낱말들, 잡음을 지운 낱말들) */
    private fun fragments(src: String): List<Pair<List<String>, List<String>>> {
        var s = replace(PAREN, src, ::paren)
        for (p in NOISE_PATTERNS) s = p.matcher(s).replaceAll("\n")
        s = replace(ISSUER_TOKEN, s) { if (KEEP_ISSUER.matcher(it.group()).find()) it.group() else "\n" }
        val frags = ArrayList<Pair<List<String>, List<String>>>()
        for (line in s.split('\n')) {
            val raw = words(line)
            val cleaned = raw.map(::cleanToken).filter { it.isNotEmpty() }
            if (cleaned.isNotEmpty()) frags.add(raw to cleaned)
        }
        return frags
    }

    private fun pickTitle(full: String, txType: String): String {
        // 1) 'A → B' 송금/이체: 들어온 돈이면 A(보낸 사람), 나간 돈이면 B(받는 쪽)
        for (line in full.split('\n')) {
            val parts = ARROW.split(line)
            if (parts.size == 2) {
                val frags = fragments(if (txType == INCOME) parts[0] else parts[1])
                if (frags.isNotEmpty()) return cleanMerchant(frags.last().second.joinToString(" "))
            }
        }
        // 2) 송금 문장의 상대방: '홍길동님이 보냈어요', '홍길동님에게 보냈어요'
        for (tok in words(full)) {
            val t = tok.strip(" ,.")
            for (p in listOf(COUNTERPARTY, RECIPIENT)) {
                val m = p.matcher(t)
                if (m.find()) {
                    if ('*' !in m.group(1)) return cleanMerchant(m.group(1))
                    break
                }
            }
        }
        val frags = fragments(full)
        if (frags.isEmpty()) return ""
        // 3) '스타벅스 강남점에서 12,000원 결제' 처럼 '~에서' 가 붙은 말
        for ((raw, _) in frags) {
            for ((i, token) in raw.withIndex()) {
                val t = token.strip(" ,.")
                if (t.length > 2 && t.endsWith("에서")) {
                    val words = raw.take(i).map(::cleanToken).filter { it.isNotEmpty() } + t.dropLast(2)
                    return cleanMerchant(words.joinToString(" "))
                }
            }
        }
        // 4) 카드/은행 문자는 대개 가맹점(상대방)이 맨 뒤에 온다
        return cleanMerchant(frags.last().second.joinToString(" "))
    }

    /**
     * 알림 제목/본문에서 거래 내역을 뽑는다. 거래 알림이 아니면 null.
     * 원화 금액을 알 수 없는 해외 결제는 amount=0 (사용자가 금액을 입력).
     */
    fun parse(title: String?, text: String?, postedAt: LocalDateTime): Parsed? {
        val full = normalize(title, text)
        // 거래 단어가 없어도 '₩4,800 | 이디야커피' 처럼 원화 기호가 붙은 금액이거나,
        // 'KB국민체크 9090 / 11/13 13:22 / 38,000원' 처럼 카드 이름과 시각이 함께 있으면 결제 알림으로 본다
        if (full.isEmpty() || REJECT.matcher(full).find() || !(TX_WORDS.matcher(full).find() || WON_SIGN.matcher(full).find()
                    || (CARD_HINT.matcher(full).find() && CLOCK.matcher(full).find()))) return null

        val kv = parseKv(full)
        val kvAmount = kv.amount?.takeIf { it != 0L }
        val picked = if (kvAmount == null) pickAmount(full) else null
        var amount = kvAmount ?: picked?.amount
        var foreign: String? = null
        if (amount == null) {
            foreign = pickForeign(full) ?: return null
            amount = 0L
        }

        val (type, refund) = txType(full, kv.type, picked?.pos)
        var merchant = if (!kv.merchant.isNullOrEmpty()) cleanMerchant(kv.merchant) else pickTitle(full, type)
        if (foreign != null) merchant = if (merchant.isNotEmpty()) "$merchant ($foreign)".trim() else "해외결제 ($foreign)"
        if (refund && merchant.isNotEmpty()) merchant = "$merchant (취소)"
        var dt = if (!kv.datetime.isNullOrEmpty()) pickDatetime(kv.datetime!!, postedAt) else null
        if (dt == null || dt == postedAt) dt = pickDatetime(full, postedAt)
        return Parsed(type, amount, merchant.take(MAX_TITLE_LEN), dt)
    }
}
