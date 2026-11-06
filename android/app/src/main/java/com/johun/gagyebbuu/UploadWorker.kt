package com.johun.gagyebbuu

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** 대기열의 알림을 서버(/api/detected)로 보낸다. 네트워크가 없으면 연결될 때까지 기다렸다가 보낸다. */
class UploadWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        val token = prefs.token ?: return Result.success() // 계정이 연결되면 SettingsActivity 가 다시 예약한다
        val queue = prefs.queue()
        val done = mutableSetOf<String>()
        val expire = System.currentTimeMillis() - 7L * 24 * 60 * 60 * 1000

        try {
            for (i in 0 until queue.length()) {
                val item = queue.getJSONObject(i)
                val qid = item.optString("qid")
                if (item.optLong("posted_at") < expire) { done += qid; continue }

                val (code, body) = post(token, item)
                when {
                    code in 200..299 -> {
                        done += qid
                        body.optJSONObject("notify")?.let {
                            Notifier.showDetected(applicationContext, body.optInt("id"),
                                it.optString("title"), it.optString("body"), it.optString("url"))
                        }
                    }
                    code == 401 -> { prefs.token = null; break } // 다시 로그인하면 이어서 보낸다
                    code in 400..499 -> done += qid // 잘못된 항목은 버린다
                    else -> { prefs.removeFromQueue(done); return Result.retry() }
                }
            }
        } catch (e: IOException) {
            prefs.removeFromQueue(done)
            return Result.retry()
        }
        prefs.removeFromQueue(done)
        return Result.success()
    }

    private fun post(token: String, item: JSONObject): Pair<Int, JSONObject> {
        val conn = URL("${BuildConfig.BASE_URL}/api/detected").openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 15_000
            conn.readTimeout = 20_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            conn.setRequestProperty("Authorization", "Bearer $token")
            val payload = JSONObject(item.toString()).apply { remove("qid") }
            conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code < 400) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            return code to json
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        fun schedule(context: Context) {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }
    }
}
