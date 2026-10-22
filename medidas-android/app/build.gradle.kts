plugins {
    id("com.android.application")
}

// Cada versión que fabrica GitHub lleva un número mayor, para poder instalarla encima de la anterior.
val numeroVersion = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "es.taller.medidas"
    compileSdk = 35

    defaultConfig {
        applicationId = "es.taller.medidas"
        minSdk = 29
        // 34 y no 35: con 35 Android 15 obliga a dibujar bajo la barra de estado.
        targetSdk = 34
        versionCode = numeroVersion
        versionName = "1.0.$numeroVersion"
    }

    // Siempre la misma firma: si cambiara, Android no dejaría actualizar y habría que desinstalar
    // (y desinstalar borra las medidas guardadas).
    signingConfigs {
        create("taller") {
            storeFile = file("../firma/medidas.jks")
            storePassword = "medidas-taller"
            keyAlias = "medidas"
            keyPassword = "medidas-taller"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("taller")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        // No se publica en la Play Store: sus requisitos no aplican.
        checkReleaseBuilds = false
        abortOnError = false
    }

    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/pagina"))
}

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.core:core:1.13.1")
}

// La página es la misma que la versión web (pagina/medidas.html); aquí se le pone el
// principio y el final de documento que en la web añade claude.ai al publicarla.
val origenPagina = rootProject.file("pagina")
val destinoPagina = layout.buildDirectory.dir("generated/pagina")
val prepararPagina by tasks.registering {
    inputs.dir(origenPagina)
    outputs.dir(destinoPagina)
    doLast {
        val destino = destinoPagina.get().asFile
        destino.mkdirs()
        val cuerpo = File(origenPagina, "medidas.html").readText()
        File(destino, "index.html").writeText(
            "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">" +
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">" +
                "<style>body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>" +
                "</head><body>" + cuerpo + "</body></html>"
        )
        File(origenPagina, "jszip.min.js").copyTo(File(destino, "jszip.min.js"), overwrite = true)
    }
}
tasks.named("preBuild") { dependsOn(prepararPagina) }
