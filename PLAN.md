##  Mejoras por Hacer

* **Lógica de Escalado y Notificaciones:** Falta implementar la lógica final del envío de mensajes a los técnicos (vía WhatsApp o Correo Electrónico). 
  * Se puede automatizar la creación de un ticket con la función ya establecida, o enviar una notificación directa al técnico con los detalles del problema.
  * Se debe desarrollar la configuración para que las alertas se envíen desde un correo tipo "bot" o un número de teléfono corporativo, centralizando las notificaciones en un chat de soporte interno.
  * **Flexibilidad:** Este método de contacto (`ticket`, `email` o `whatsapp`) es totalmente dinámico y se puede cambiar a conveniencia de la empresa directamente desde el archivo `.env`.

##  Cosas a Tener en Cuenta

* **Respuestas de la IA (Ollama):** En ocasiones, el chatbot podría generar respuestas en inglés o incluir símbolos inusuales. Esto no es un error del código, sino una limitante natural del modelo de lenguaje que se escogió.
* **Escalabilidad del Modelo:** Este comportamiento se puede solucionar cambiando el modelo actual por uno más avanzado o mejor entrenado en español (como *Llama 3* u otros modelos soportados por Ollama).

## Integración Directa a WhatsApp

Migrar el chatbot a WhatsApp sería un proceso ágil gracias a su arquitectura actual, ya que el motor principal y la inteligencia artificial (`chatbot.py`) se mantendrían intactos. 

El cambio consistiría fundamentalmente en reemplazar la interfaz visual de Chainlit por un servidor web (como FastAPI o Flask) que funcione como Webhook conectado a una API de WhatsApp (como Meta Cloud o Twilio). Finalmente, solo habría que ajustar el código para que guarde el estado de la conversación por número de teléfono de cada usuario y adaptar los botones actuales al formato de "Mensajes Interactivos" nativos de WhatsApp, permitiendo que todo el flujo siga operando con la misma eficiencia.

## Tareas Pendientes (UI y Detalles Web)

* **Restricciones del Chat:** Deshabilitar la opción (el clip de adjuntar) para evitar que los usuarios puedan subir fotos o archivos al chat, ya que el bot actualmente es solo de texto.