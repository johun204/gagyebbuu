package com.johun.gagyebbuu

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** 로그인 토큰, 읽을 앱 목록, 서버로 보낼 알림 대기열을 저장한다. */
class Prefs(context: Context) {
    private val sp = context.applicationContext.getSharedPreferences("gagyebbuu", Context.MODE_PRIVATE)

    /** 웹앱의 로그인 토큰(jwt_token). 웹의 '알림 자동 감지' 설정 링크로 전달받는다. */
    var token: String?
        get() = sp.getString("token", null)
        set(v) = sp.edit().putString("token", v).apply()

    /** token 이 가리키는 사용자 id (계정이 바뀌는지 확인용, -1 = 모름) */
    var userId: Long
        get() = sp.getLong("user_id", -1)
        set(v) = sp.edit().putLong("user_id", v).apply()

    var watchedPackages: Set<String>
        get() = sp.getStringSet("watched", emptySet())!!.toSet()
        set(v) = sp.edit().putStringSet("watched", v).apply()

    var introShown: Boolean
        get() = sp.getBoolean("intro_shown", false)
        set(v) = sp.edit().putBoolean("intro_shown", v).apply()

    @Synchronized
    fun enqueue(item: JSONObject) {
        val q = queue()
        q.put(item)
        // 너무 오래 오프라인이어도 무한히 쌓이지 않게 최근 200건만 유지
        val trimmed = JSONArray()
        for (i in maxOf(0, q.length() - 200) until q.length()) trimmed.put(q.get(i))
        sp.edit().putString("queue", trimmed.toString()).apply()
    }

    @Synchronized
    fun queue(): JSONArray = JSONArray(sp.getString("queue", "[]"))

    /** 처리한 항목(posted_at+key 로 식별)을 대기열에서 뺀다. */
    @Synchronized
    fun removeFromQueue(done: Set<String>) {
        val q = queue()
        val rest = JSONArray()
        for (i in 0 until q.length()) {
            val o = q.getJSONObject(i)
            if (o.optString("qid") !in done) rest.put(o)
        }
        sp.edit().putString("queue", rest.toString()).apply()
    }

    /** 같은 알림이 갱신되며 여러 번 올라오는 것을 걸러내기 위한 최근 본 알림 지문. */
    @Synchronized
    fun seenRecently(fingerprint: String, now: Long): Boolean {
        val seen = JSONObject(sp.getString("seen", "{}"))
        val cutoff = now - 24 * 60 * 60 * 1000L
        val keep = JSONObject()
        seen.keys().forEach { k -> if (seen.getLong(k) >= cutoff) keep.put(k, seen.getLong(k)) }
        val hit = keep.has(fingerprint)
        keep.put(fingerprint, now)
        sp.edit().putString("seen", keep.toString()).apply()
        return hit
    }
}
