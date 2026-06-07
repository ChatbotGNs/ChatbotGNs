# 📋 Plan de Acción y Mejoras - ChatGNs

Este documento define la hoja de ruta para optimizar la experiencia de usuario, estabilizar el backend y preparar el chatbot para un entorno de producción seguro y escalable.

---

## Fase 1: Entorno y Arranque Rápido (Setup)
*Objetivo: Lograr un despliegue "Zero-Config" donde la aplicación arranque sin requerir ajustes manuales del desarrollador.*

- [✅] **1.1. Automatización del Setup:** Actualizar `setup.sh` para fijar la versión de Python (3.11), instalar dependencias automáticamente y permitir que el comando `chainlit run chainlit_app.py -w` arranque sin errores.
- [✅ ] **1.2. Bienvenida Proactiva:** Modificar `chainlit_app.py` (`@cl.on_chat_start`) para que te de una mini explicacion de que hacer
      Traducciones nomas corregidas en ingles y español
- [ ✅] **1.3.  hacer starters con el menu para que este padre y de ahi puedan hacer el menu de opciones, verfificr cuales poner
  poner el final el mensaaje de escoge otra accion o escribe menu para ver lo que se puede hacer

## Fase 2: Experiencia de Usuario (UI/UX) y Tiempos de Carga
*Objetivo: Mejorar la percepción de velocidad y evitar errores visuales en la interfaz web.*

- [ ] **2.1. Indicador de "Pensando...":** Implementar un estado de carga (loader visual en Chainlit) y ajustar *timeouts* durante la ejecución de Ollama para que la UI no parezca congelada.
- [ ] **2.2. Solución al Bug del "Menú Infinito":** Desacoplar la UI de Chainlit del texto plano. Refactorizar el código para enviar *payloads* o diccionarios que rendericen botones de acción en lugar de buscar coincidencias de texto como `"paso 1/"`.
- [ ] **2.3. Tolerancia a Bypass de IA (Respuestas cortas):** Ajustar las validaciones para que el bot no se rompa al recibir respuestas cortas afirmativas o negativas ("sí", "no", "ok"), permitiendo fluidez en el diagnóstico.
- [ ] **2.4. Agregar en el readme instrucciones basicas para el usuario
- [ ] **2.5. Cambiar el logo de favicon para que se vea bien


## Fase 3: Flujos Guiados y Análisis de Problemas (Stateful Chatbot)
*Objetivo: Lograr que el bot mantenga el control de la conversación y derive correctamente los problemas.*

- [ ] **3.1. Máquina de Estados (Paso a Paso):** Implementar un flujo estricto. Si el usuario se desvía del tema, Ollama debe analizar la interrupción, responder educadamente y redirigir al usuario al paso en el que se quedó.
- [ ] **3.2. Filtro Inteligente de Problemas ("Falso Escalamiento"):** Reemplazar el *trigger* rígido de palabras ("se me cortó") por un análisis de intención semántica en Ollama, diferenciando caídas masivas de problemas locales de router.

## Fase 4: Validación de Datos y Seguridad
*Objetivo: Evitar suplantación de identidad y uso indebido del LLM.*

- [ ] **4.1. Prevención del Falso ID de Cliente:** Eliminar la extracción automática de números globales. Configurar un *Slot* donde el bot pida explícitamente el "ID de cliente" y solo valide esa respuesta aislada.
que si mete un dato equiocado mandar mensaje de que repita o que escriba menu o otra cosa para ver el siguiente paso o que show
- [ ] **4.2. Prevención de Prompt Injection:** Blindar el `system prompt` de Ollama mediante plantillas rígidas. Separar las reglas inalterables del sistema del *input* del usuario para evitar que fuercen escalamientos fraudulentos.

## Fase 5: Backend, Base de Datos y API
*Objetivo: Hacer que el sistema sea estable, no consuma memoria en exceso y se recupere de fallas de red.*

- [ ] **5.1. Aislamiento de Errores (Payload Inválido):** Capturar errores de la API (ej. falta de ID) de forma segura. Si el escalamiento falla, mostrar un mensaje amigable al usuario y guardar el *Traceback* solo en los logs internos (`logger.error`).
- [ ] **5.2. Migración a Consultas Dinámicas (Adiós a JSON en RAM):** Eliminar la carga de `customers.json` y `tickets.json` al inicializar el bot. Modificar los métodos para consultar la Base de Datos o API externa únicamente en el momento en que se requiere la información.

---
*Documento generado para el repositorio de ChatGNs.*