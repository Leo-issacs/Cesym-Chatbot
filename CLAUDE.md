# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Cesym Chatbot** — proyecto en Python para construir un agente interno que pueda consultar y, en versiones futuras, modificar archivos Excel relacionados con cartera, facturas, órdenes de compra, cotizaciones pendientes y trabajos realizados.

El objetivo final es que el agente pueda responder consultas desde WhatsApp, pero la primera versión debe funcionar de forma local desde consola, sin conectarse todavía a WhatsApp ni modificar archivos originales.

## Contexto del proyecto

Este proyecto busca crear un chatbot/agente para automatizar consultas sobre archivos Excel usados manualmente en la empresa.

El primer Excel conocido es `CARTERA AL 11032026.xlsx`. Este archivo contiene información relacionada con:
- Facturas.
- Órdenes de compra.
- Montos facturados.
- Fechas.
- Estados como aceptada, prioridad o pendiente.
- Cotizaciones pendientes de orden de compra.

El archivo tiene hojas como:
- `OC FACTURADO`: contiene facturas, órdenes de compra, montos, fechas y observaciones.
- `PTE OC 25-26`: contiene cotizaciones pendientes de OC, sucursal, importe y concepto.
- `Hoja1`: aparentemente vacía.

El segundo Excel todavía no está disponible, pero probablemente contendrá información de trabajos realizados por tienda o sucursal. Más adelante se deberá cruzar la información de ambos archivos.

## Objetivo inicial

Construir primero una versión local que pueda:

1. Leer el Excel.
2. Limpiar y normalizar los datos.
3. Ignorar filas vacías, encabezados manuales y filas de totales.
4. Convertir fechas de Excel a fechas legibles.
5. Permitir consultas desde consola.
6. Generar resúmenes.
7. Detectar errores o inconsistencias.
8. No modificar el archivo original.

## Reglas importantes

- No modificar ningún archivo Excel original sin confirmación explícita.
- Antes de cualquier modificación futura, crear un backup automático.
- No borrar registros desde el chatbot.
- Separar claramente la lectura de Excel, limpieza de datos, consultas, validaciones, chatbot y logs.
- Trabajar por versiones pequeñas.
- Priorizar código claro, modular y fácil de entender.
- Documentar en español.
- Explicar qué archivo se va a crear o modificar antes de hacer cambios grandes.
- No crear una arquitectura demasiado compleja al inicio.
- Mantener actualizado el archivo `README.md`.

## Environment

- Python 3.11.9
- Virtual environment: `venv_Cesym_Chatbot/`
- Activate venv: `.\venv_Cesym_Chatbot\Scripts\Activate.ps1` PowerShell
- Operating system: Windows
- Editor: VS Code

## Setup

```powershell
# Activate the virtual environment
.\venv_Cesym_Chatbot\Scripts\Activate.ps1

# Install dependencies once a requirements.txt exists
pip install -r requirements.txt