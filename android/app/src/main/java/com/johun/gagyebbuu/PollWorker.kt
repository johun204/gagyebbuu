package com.johun.gagyebbuu

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

/**
 * 앱(WebView)은 웹 푸시를 받을 수 없어서, 상대방 활동 알림은 서버의 알림 목록을 주기적으로(약 15분,
 * 안드로이드가 허용하는 최소 간격) 확인해 새 항목을 기기 알림으로 띄운다.
 */
class PollWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (!prefs.partnerPush) return Result.success()
        val token = prefs.token ?: return Result.success()
        val after = prefs.lastLogId
        val conn = URL("${BuildConfig.BASE_URL}/api/notifications/poll" + if (after >= 0) "?after=$after" else "")
            .openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 15_000
            conn.readTimeout = 20_000
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            conn.setRequestProperty("Authorization", "Bearer $token")
            if (conn.responseCode != 200) return Result.success()
            val body = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val items = body.optJSONArray("items")
            if (after >= 0 && items != null) {
                for (i in 0 until items.length()) {
                    val it = items.getJSONObject(i)
                    Notifier.showPartner(applicationContext, it.optLong("id"), it.optString("title"),
                        it.optString("body"), it.optString("url", "/home"))
                }
            }
            prefs.lastLogId = maxOf(after, body.optLong("last_id", after))
        } catch (e: IOException) {
            return Result.retry()
        } finally {
            conn.disconnect()
        }
        return Result.success()
    }

    companion object {
        private const val NAME = "partner-poll"

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<PollWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        fun cancel(context: Context) = WorkManager.getInstance(context).cancelUniqueWork(NAME)
    }
}
