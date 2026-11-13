package com.johun.gagyebbuu

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime

/**
 * 서버의 txparse.py 와 같은 결과를 내는지 검사한다.
 * 기대값(txparse_cases.json)은 tests/app_parser_cases.py 가 txparse.py 로 만든다.
 */
class TxParserTest {

    @Test
    fun sameResultAsServerParser() {
        val json = javaClass.getResourceAsStream("/txparse_cases.json")!!.bufferedReader(Charsets.UTF_8).use { it.readText() }
        val cases = JSONArray(json)
        assertTrue(cases.length() > 50)
        val wrong = ArrayList<String>()
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val r = TxParser.parse(c.getString("title"), c.getString("text"), LocalDateTime.parse(c.getString("posted_at")))
            val got = r?.let { listOf(it.txType, it.amount, it.title, it.datetime) }
            val want = c.optJSONObject("expected")?.let {
                listOf(it.getString("tx_type"), it.getLong("amount"), it.getString("title"), LocalDateTime.parse(it.getString("datetime")))
            }
            if (got != want) wrong += "#$i ${c.getString("title")} / ${c.getString("text")}\n  기대: $want\n  결과: $got"
        }
        assertEquals("", wrong.joinToString("\n"))
    }
}
