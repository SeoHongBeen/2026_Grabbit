// RpiClient.kt
package com.toi.grabbit.model

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

object RpiClient {

    /**
     * RPi(또는 mock server)의 /latest 엔드포인트에서 JSON 문자열을 가져온다.
     * 네트워크 작업이므로 IO 디스패처에서 실행, 실패 시 null 반환.
     */
    suspend fun fetchLatest(baseUrl: String): String? = withContext(Dispatchers.IO) {
        try {
            val url = URL("$baseUrl/latest")
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "GET"
            connection.connectTimeout = 3000
            connection.readTimeout = 3000

            val responseCode = connection.responseCode
            if (responseCode == HttpURLConnection.HTTP_OK) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                null
            }
        } catch (e: Exception) {
            null
        }
    }
}