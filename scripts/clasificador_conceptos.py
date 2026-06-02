"""
clasificador_conceptos.py
--------------------------
Clasificador NLP para la columna CONCEPTO del archivo reporteMensual_FACTURAS.xlsx.

PROBLEMA QUE RESUELVE
---------------------
Las facturas tienen descripciones en texto libre (ej. "SERVICIO DE MANTENIMIENTO
A EQUIPOS DE AIRE ACONDICIONADO"). Sin una categoría estandarizada es imposible
hacer reportes confiables. Este script asigna automáticamente una de 5 categorías:

    mantenimiento_preventivo  — revisiones, limpiezas, servicios periódicos
    mantenimiento_correctivo  — reparaciones, atención a fallas
    instalacion_nueva         — instalaciones, adecuaciones, puestas en marcha
    venta_refaccion           — venta de piezas, refacciones, componentes
    otro                      — todo lo que no encaja en las anteriores

PIPELINE DE APRENDIZAJE AUTOMÁTICO
-----------------------------------
Como NO tenemos etiquetas reales, seguimos tres pasos:

    Paso 1 — Etiquetado automático por reglas (keywords)
              Creamos etiquetas "aproximadas" usando palabras clave del dominio HVAC.
              Esto se llama "distant supervision" (supervisión a distancia).

    Paso 2 — Entrenamiento: TF-IDF + Regresión Logística
              TF-IDF convierte texto → números (vector de frecuencias).
              Logistic Regression aprende patrones estadísticos sobre esos números.

    Paso 3 — Evaluación y exportación
              Medimos qué tan bien generalizó el modelo con métricas estándar.
              Exportamos el CSV con la columna CATEGORIA añadida.

CÓMO EJECUTAR
-------------
    cd "Cesym Chatbot"
    .\venv_Cesym_Chatbot\Scripts\Activate.ps1
    python scripts/clasificador_conceptos.py

    Con archivo real:
    python scripts/clasificador_conceptos.py --excel ruta/a/reporteMensual_FACTURAS.xlsx

DEPENDENCIAS NUEVAS (pip install scikit-learn)
----------------------------------------------
    scikit-learn >= 1.3.0
"""

import re
import unicodedata
import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import Pipeline


# =============================================================================
# PASO 0: DATOS DE EJEMPLO
# =============================================================================
# Cuando no hay Excel disponible, estos conceptos simulan la columna real.
# Son representativos del lenguaje real de facturas HVAC en México.

CONCEPTOS_EJEMPLO = [
    # mantenimiento_preventivo (etiqueta esperada)
    "SERVICIO DE MANTENIMIENTO A EQUIPOS DE AIRE ACONDICIONADO",
    "MANTENIMIENTO PREVENTIVO A UNIDADES MINISPLIT",
    "SERVICIO DE MANTENIMIENTO Y LIMPIEZA A EQUIPO DE REFRIGERACION",
    "REVISION Y LIMPIEZA A SISTEMA DE CLIMATIZACION",
    "MANTENIMIENTO PREVENTIVO TRIMESTRAL A CHILLER YORK",
    "SERVICIO DE MANTENIMIENTO A EQUIPOS HVAC SUCURSAL MONTERREY",
    "LIMPIEZA DE FILTROS Y VERIFICACION DE OPERACION DE EQUIPOS",
    "MANTENIMIENTO A UNIDADES CONDENSADORAS EN AZOTEA",
    "INSPECCION Y AJUSTE DE EQUIPOS DE AIRE ACONDICIONADO",
    "MANTENIMIENTO SEMESTRAL A MANEJADORAS DE AIRE",
    "SERVICIO DE MANTENIMIENTO PREVENTIVO A EQUIPOS DE REFRIGERACION COMERCIAL",
    "REVISION GENERAL DE EQUIPOS SPLIT Y MINI SPLIT",
    "VERIFICACION DE PRESIONES Y CARGA DE GAS REFRIGERANTE",
    "SERVICIO DE MANTENIMIENTO A FANCOILS DE OFICINAS",
    "LIMPIEZA PROFUNDA DE CONDENSADORES Y EVAPORADORES",
    # mantenimiento_correctivo
    "REPARACION DE COMPRESOR EN EQUIPO SPLIT 5 TONELADAS",
    "ATENCION A FALLA EN SISTEMA DE ENFRIAMIENTO PLANTA 2",
    "MANTENIMIENTO CORRECTIVO A CHILLER CARRIER SUCURSAL NORTE",
    "REPARACION DE FUGA DE GAS REFRIGERANTE R22",
    "DIAGNOSTICO Y REPARACION DE MANEJADORA YORK",
    "ATENCION DE EMERGENCIA POR FALLA EN CONDENSADOR",
    "REPARACION TARJETA ELECTRONICA EQUIPO DAIKIN",
    "CORRECTIVO A UNIDAD MINISPLIT POR FALLA DE VENTILADOR",
    "SERVICIO CORRECTIVO EN EQUIPO LENNOX TIENDA REFORMA",
    "REPARACION DE AVERIA EN BOMBA DE CALOR EDIFICIO CENTRAL",
    "ATENCION A FALLA ELECTRICA EN MANEJADORA DE AIRE",
    "DIAGNOSTICO EQUIPO CON FALLA INTERMITENTE DE ENFRIAMIENTO",
    "REPARACION SISTEMA DE REFRIGERACION CAMARA FRIA",
    "CORRECTIVO POR SOBRECALENTAMIENTO EN UNIDAD CONDENSADORA",
    "ATENCION A FUGA DE REFRIGERANTE R410A EN SUCURSAL GDLAJARA",
    # instalacion_nueva
    "ADECUACION EN SISTEMAS DE CONTROL ELECTRICO PLANTA NORTE",
    "INSTALACION DE EQUIPO DE AIRE ACONDICIONADO TIPO CASSETTE",
    "INSTALACION NUEVA DE SISTEMA VRF EN EDIFICIO CORPORATIVO",
    "PUESTA EN MARCHA DE CHILLER TRANE 60 TONELADAS",
    "MONTAJE E INSTALACION DE MANEJADORAS DE AIRE PISO 3",
    "INSTALACION DE RED DE DUCTOS EN AREA DE PRODUCCION",
    "ADECUACION Y AMPLIACION DE SISTEMA HVAC TIENDA PERISUR",
    "OBRA DE INSTALACION HVAC EN SUCURSAL NUEVA GUADALAJARA",
    "INSTALACION DE EQUIPOS SPLIT ZONA ADMINISTRATIVA",
    "PUESTA EN MARCHA Y COMISIONAMIENTO SISTEMA DE CLIMA DATACENTER",
    "INSTALACION DE SISTEMA DE EXTRACCION DE AIRE BODEGA",
    "ADECUACION DE DUCTOS PARA NUEVA DISTRIBUCION EN PLANTA",
    "MONTAJE DE UNIDADES CONDENSADORAS EN AZOTEA EDIFICIO B",
    "INSTALACION DE SISTEMA DE CLIMATIZACION SALA DE SERVIDORES",
    "AMPLIACION DE RED DE REFRIGERACION AREA DE CARNES",
    # venta_refaccion
    "COMPRESOR DANFOSS SCROLLA PARA CHILLER CARRIER",
    "VALVULA DE EXPANSION ELECTRONICA EMERSON R410A",
    "FILTRO DESHIDRATADOR PARA EQUIPO DE REFRIGERACION",
    "MOTOR VENTILADOR EVAPORADOR 1/4 HP 208-230V",
    "CAPACITOR DE ARRANQUE 45/5 MFD PARA COMPRESOR",
    "CONTACTOR TRIPOLAR 30A PARA CONDENSADORA",
    "TERMOSTATO DIGITAL HONEYWELL T6360",
    "TARJETA ELECTRONICA PRINCIPAL DAIKIN RZQ",
    "SENSOR DE TEMPERATURA NTC 10K PARA MANEJADORA",
    "BANDA PARA MOTOR DE MANEJADORA TRANE 3X440",
    "REFRIGERANTE R22 CILINDRO 30 LB",
    "REFRIGERANTE R410A CILINDRO 25 LB",
    "RODAMIENTO 6205 2Z PARA MOTOR VENTILADOR",
    "BOMBA DE AGUA PARA CHILLER CENTRIFUGO",
    "REPUESTO VALVULA SOLENOIDE 24V PARA UNIDAD CONDENSADORA",
    "REFACCION TARJETA INVERSORA MITSUBISHI HEAVY",
    "COMPRESOR SCROLL COPELAND ZP54K5E TFD PARA EQUIPO 5T",
    "EVAPORADOR RIEL PARA CAMARA DE REFRIGERACION",
    "CONDENSADOR TUBOS Y ALETAS CARRIER 5 TONELADAS",
    "PIEZA PRESOSTATO DE ALTA Y BAJA PRESION UNIVERSAL",
    # otro
    "CAPACITACION AL PERSONAL TECNICO EN USO DE EQUIPOS HVAC",
    "ASESORIA TECNICA PARA PROYECTO DE CLIMATIZACION",
    "ELABORACION DE PLANOS Y MEMORIAS DE CALCULO",
    "VISITA TECNICA Y LEVANTAMIENTO DE INFORMACION",
    "TRANSPORTE Y FLETE DE EQUIPOS A SUCURSAL",
    "RENTA DE ANDAMIO PARA TRABAJOS EN ALTURA",
    "ELABORACION DE PROYECTO EJECUTIVO HVAC",
    "MANO DE OBRA GENERAL EN INSTALACION",
]


# =============================================================================
# PASO 1: NORMALIZACIÓN DE TEXTO
# =============================================================================

def normalizar(texto: str) -> str:
    """
    Limpia y normaliza un concepto de factura para que sea comparable.

    Transformaciones:
        "COMPRESOR DANFOSS" → "compresor danfoss"
        "VÁLVULA"          → "valvula"      (elimina acentos)
        "R-22"             → "r 22"         (normaliza guiones)

    Por qué normalizar:
        TF-IDF trata "Compresor" y "COMPRESOR" como tokens distintos
        si no estandarizamos el case. Los acentos también causan splits
        innecesarios en vocabulario.
    """
    if not isinstance(texto, str):
        return ""
    # 1. Minúsculas
    texto = texto.lower()
    # 2. Quitar acentos: descompone "á" en "a" + marca diacrítica, luego filtra
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    # 3. Reemplazar guiones y barras por espacio
    texto = re.sub(r"[-/]", " ", texto)
    # 4. Conservar solo letras, números y espacios
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    # 5. Colapsar espacios múltiples
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


# =============================================================================
# PASO 1B: ETIQUETADO AUTOMÁTICO POR REGLAS (DISTANT SUPERVISION)
# =============================================================================
# Estrategia: lista de palabras clave por categoría, con orden de prioridad.
# Si un concepto contiene keywords de varias categorías, gana la primera
# en la lista REGLAS (top = mayor prioridad).
#
# ¿Por qué este orden?
#   - correctivo > preventivo: "reparacion" es más específico que "mantenimiento"
#   - instalacion > refaccion: "instalacion de compresor" es instalación, no venta
#   - refaccion > preventivo: "compresor para" indica venta aunque se mencione servicio

REGLAS = [
    (
        "mantenimiento_correctivo",
        [
            "correctivo", "reparaci", "falla", "averia", "emergencia",
            "diagnostico", "fuga de gas", "fuga de refrigerante",
        ],
    ),
    (
        "instalacion_nueva",
        [
            "instalaci", "adecuaci", "puesta en marcha", "montaje",
            "obra nueva", "obra de", "ampliaci", "comisionamiento",
        ],
    ),
    (
        "venta_refaccion",
        [
            "compresor ", "valvul", "filtro deshi", "motor ventilad",
            "capacitor", "contactor", "termostato", "tarjeta electron",
            "sensor de temperatura", "sensor ntc", "banda para motor",
            "refrigerante r", "rodamiento", "bomba de agua",
            "repuesto", "refaccion", "evaporador riel",
            "condensador tubos", "presostato", "tarjeta inversor",
            "compresor scroll", "copeland", "emerson r", "danfoss",
        ],
    ),
    (
        "mantenimiento_preventivo",
        [
            "mantenimiento", "preventivo", "servicio de mantenimiento",
            "limpieza", "inspeccion", "revision", "verificacion",
            "servicio de", "chequeo",
        ],
    ),
]


def etiquetar_por_reglas(texto_normalizado: str) -> str:
    """
    Aplica las REGLAS de keywords sobre el texto ya normalizado.
    Devuelve la categoría de la primera regla que coincida, o 'otro'.
    """
    for categoria, keywords in REGLAS:
        for kw in keywords:
            if kw in texto_normalizado:
                return categoria
    return "otro"


# =============================================================================
# PASO 2: CONSTRUCCIÓN DEL PIPELINE TF-IDF + REGRESIÓN LOGÍSTICA
# =============================================================================

def construir_pipeline() -> Pipeline:
    """
    Crea el pipeline de sklearn con dos etapas:

    TfidfVectorizer
    ---------------
    Convierte texto a una matriz numérica. Cada columna es un n-grama
    (secuencia de 1 o 2 palabras). El valor es TF-IDF:
        TF  = frecuencia del término en este documento
        IDF = log(N / docs que contienen el término)
    Términos muy comunes ("de", "en") obtienen IDF bajo → peso bajo.
    Términos raros pero informativos ("copeland", "adecuaci") → IDF alto.

    Parámetros elegidos:
        ngram_range=(1,2)  — captura bigramas como "puesta en" o "fuga de"
        max_features=3000  — límite de vocabulario para evitar sobreajuste
        min_df=1           — incluye incluso términos que aparecen una vez
                             (dataset pequeño, no podemos desperdiciar info)
        sublinear_tf=True  — aplica log(1+tf) en lugar de tf raw,
                             reduce el efecto de repetición excesiva

    LogisticRegression
    ------------------
    Modelo lineal que aprende un hiperplano separador por clase.
    Para multi-clase, lbfgs usa automáticamente softmax multinomial.
        C=1.0  — regularización L2 estándar (penaliza pesos grandes)
        max_iter=1000  — suficiente para convergencia con corpus pequeño
    """
    return Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                ngram_range=(1, 2),
                max_features=3000,
                min_df=1,
                sublinear_tf=True,
            ),
        ),
        (
            "clf",
            LogisticRegression(
                C=1.0,
                max_iter=1000,
                solver="lbfgs",
                random_state=42,
            ),
        ),
    ])


# =============================================================================
# PASO 3: ENTRENAMIENTO Y EVALUACIÓN
# =============================================================================

def entrenar_y_evaluar(df: pd.DataFrame) -> Pipeline:
    """
    Entrena el pipeline y muestra métricas de evaluación.

    División train/test (80/20):
        Usamos stratify=y para garantizar que cada categoría aparezca
        en ambos splits con la misma proporción. Importante con clases
        pequeñas como 'otro'.

    Métricas reportadas:
        precision — de los que predije como X, ¿cuántos eran realmente X?
        recall    — de todos los X reales, ¿cuántos capturé?
        f1-score  — media armónica de precision y recall
        support   — cuántos ejemplos reales hay de cada clase
    """
    X = df["concepto_norm"]
    y = df["etiqueta_auto"]

    print(f"\n{'='*60}")
    print("DISTRIBUCIÓN DE ETIQUETAS (generadas por reglas)")
    print("="*60)
    print(y.value_counts().to_string())
    print(f"\nTotal de conceptos: {len(df)}")

    # Separar train (80%) y test (20%), estratificado por clase
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    print(f"\nEntrenamiento: {len(X_train)} ejemplos | Prueba: {len(X_test)} ejemplos")

    # Entrenar
    pipeline = construir_pipeline()
    pipeline.fit(X_train, y_train)

    # Evaluar en test
    y_pred = pipeline.predict(X_test)

    print(f"\n{'='*60}")
    print("REPORTE DE CLASIFICACIÓN (conjunto de prueba)")
    print("="*60)
    print(classification_report(y_test, y_pred, zero_division=0))

    print(f"\n{'='*60}")
    print("MATRIZ DE CONFUSIÓN")
    print("="*60)
    clases = sorted(y.unique())
    cm = confusion_matrix(y_test, y_pred, labels=clases)
    cm_df = pd.DataFrame(cm, index=clases, columns=clases)
    print("Filas = real | Columnas = predicho")
    print(cm_df.to_string())

    # Reentrenar con TODOS los datos para usar el modelo en producción
    # (common practice: una vez validadas las métricas, entrenamos con todo)
    pipeline.fit(X, y)
    print(f"\n[OK] Modelo reentrenado con todos los datos ({len(X)} ejemplos)")

    return pipeline


# =============================================================================
# PASO 4: INSPECCIÓN DE PESOS (EXPLICABILIDAD)
# =============================================================================

def mostrar_pesos_por_clase(pipeline: Pipeline, top_n: int = 8) -> None:
    """
    Muestra los n-gramas más importantes para cada categoría.

    ¿Por qué es útil?
        Logistic Regression asigna un coeficiente a cada feature (n-grama).
        Un coeficiente alto para la clase X significa que ese n-grama empuja
        fuerte hacia X. Esto permite verificar que el modelo aprendió cosas
        razonables y detectar keywords "falsas" que contaminan la predicción.
    """
    vectorizer = pipeline.named_steps["tfidf"]
    clf = pipeline.named_steps["clf"]
    feature_names = vectorizer.get_feature_names_out()

    print(f"\n{'='*60}")
    print(f"TOP {top_n} N-GRAMAS MÁS INFLUYENTES POR CATEGORÍA")
    print("="*60)
    for i, clase in enumerate(clf.classes_):
        coefs = clf.coef_[i]
        top_idx = coefs.argsort()[-top_n:][::-1]
        top_features = [(feature_names[j], round(coefs[j], 3)) for j in top_idx]
        print(f"\n  {clase}:")
        for feat, peso in top_features:
            print(f"    '{feat}' -> {peso:+.3f}")


# =============================================================================
# FLUJO PRINCIPAL
# =============================================================================

def cargar_datos(ruta_excel: str | None) -> pd.DataFrame:
    """
    Carga conceptos desde el Excel real o usa los ejemplos embebidos.
    Espera una columna llamada CONCEPTO (insensible a mayúsculas/espacios).
    """
    if ruta_excel:
        path = Path(ruta_excel)
        if not path.exists():
            print(f"[ERROR] No se encontró el archivo: {ruta_excel}", file=sys.stderr)
            sys.exit(1)
        df = pd.read_excel(path, engine="openpyxl")
        # Buscar columna CONCEPTO con nombre aproximado
        col_concepto = next(
            (c for c in df.columns if "concepto" in c.lower()), None
        )
        if col_concepto is None:
            print(
                f"[ERROR] No se encontró columna CONCEPTO. "
                f"Columnas disponibles: {list(df.columns)}",
                file=sys.stderr,
            )
            sys.exit(1)
        df = df[[col_concepto]].rename(columns={col_concepto: "concepto"})
        df = df.dropna(subset=["concepto"])
        print(f"[OK] Excel cargado: {len(df)} filas desde '{ruta_excel}'")
        return df
    else:
        print("[INFO] No se especificó Excel. Usando datos de ejemplo embebidos.")
        return pd.DataFrame({"concepto": CONCEPTOS_EJEMPLO})


def main():
    parser = argparse.ArgumentParser(
        description="Clasificador NLP de conceptos de facturas HVAC"
    )
    parser.add_argument(
        "--excel",
        type=str,
        default=None,
        help="Ruta al archivo reporteMensual_FACTURAS.xlsx",
    )
    parser.add_argument(
        "--salida",
        type=str,
        default="conceptos_clasificados.csv",
        help="Nombre del CSV de salida (default: conceptos_clasificados.csv)",
    )
    args = parser.parse_args()

    # ---- Paso 0: Cargar datos -----------------------------------------------
    df = cargar_datos(args.excel)

    # ---- Paso 1: Normalizar + etiquetar por reglas --------------------------
    df["concepto_norm"] = df["concepto"].apply(normalizar)
    df["etiqueta_auto"] = df["concepto_norm"].apply(etiquetar_por_reglas)

    print("\nEJEMPLOS DE ETIQUETADO AUTOMÁTICO (primeras 10 filas):")
    print("-" * 60)
    for _, row in df.head(10).iterrows():
        print(f"  [{row['etiqueta_auto']:<28}] {row['concepto'][:55]}")

    # ---- Paso 2+3: Entrenar y evaluar ---------------------------------------
    pipeline = entrenar_y_evaluar(df)

    # ---- Paso 4: Explicabilidad ---------------------------------------------
    mostrar_pesos_por_clase(pipeline)

    # ---- Paso 5: Predecir con el modelo entrenado ---------------------------
    # Usamos el modelo (no las reglas) para la predicción final.
    # Esto es útil porque el modelo puede generalizar a conceptos que no
    # contienen exactamente las keywords pero son estadísticamente similares.
    df["categoria_modelo"] = pipeline.predict(df["concepto_norm"])

    # ---- Paso 6: Exportar ---------------------------------------------------
    salida_path = Path(args.salida)
    columnas_exportar = ["concepto", "etiqueta_auto", "categoria_modelo"]
    df[columnas_exportar].to_csv(salida_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] Resultados exportados a: {salida_path.resolve()}")

    # Comparar reglas vs modelo
    coincidencia = (df["etiqueta_auto"] == df["categoria_modelo"]).mean()
    print(f"[INFO] Coincidencia reglas vs modelo: {coincidencia:.1%}")
    print("\nCLASIFICACIÓN COMPLETADA.")


if __name__ == "__main__":
    main()
