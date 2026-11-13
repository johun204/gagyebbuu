import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.johun.gagyebbuu"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.johun.gagyebbuu"
        minSdk = 26
        targetSdk = 36
        versionCode = 5
        versionName = "1.2.2"
        // 앱은 이 주소의 웹앱을 크롬(Trusted Web Activity)으로 그대로 띄운다. 화면/기능/웹 푸시는 웹 배포만으로
        // 바뀌므로 앱 업데이트가 필요 없다.
        buildConfigField("String", "BASE_URL", "\"https://gagyebbuu.vercel.app\"")
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin { jvmToolchain(17) }
    buildFeatures { buildConfig = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-ktx:1.11.0")
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.7.4")
}
