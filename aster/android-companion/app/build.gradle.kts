plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "dev.aster.companion"
    compileSdk = 35
    defaultConfig {
        applicationId = "dev.aster.companion"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-offline-prototype"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
