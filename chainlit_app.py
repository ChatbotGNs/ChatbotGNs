"""Chainlit wrapper para exponer el chatbot en web.

Inicio rápido:
- Instala dependencias: pip install -r requirements.txt
- Ejecuta: chainlit run chainlit_app.py

Este archivo crea una instancia de Chatbot y delega cada mensaje entrante a la
método ask en un hilo para no bloquear el loop async de Chainlit.
"""
import asyncio
import chainlit as cl
from chatbot import Chatbot

# Instanciar una sola vez para reutilizar estado y cachés locales
bot = Chatbot()

# Helper seguro para enviar mensajes y botones compatible con distintas versiones de Chainlit
async def safe_send(content: str | None = None, buttons: list | None = None):
    """Try several APIs to send a message with optional buttons. Always fall back to plain text.

    This prevents the handler from failing if the Chainlit API in the runtime does not
    support Message(...).send() or Button objects in the same way.
    """
    # Prefer modern API: cl.Message(...).send()
    try:
        if buttons:
            # try to build actions using cl.Button if available
            actions = None
            try:
                actions = [cl.Button(label=b["label"], value=b["value"]) for b in buttons]
            except Exception:
                # try alternative import
                try:
                    from chainlit import Button as _Button
                    actions = [_Button(label=b["label"], value=b["value"]) for b in buttons]
                except Exception:
                    actions = None

            if actions is not None:
                try:
                    msg = cl.Message(content=content or "", actions=actions)
                    send_m = getattr(msg, "send", None)
                    if callable(send_m):
                        await send_m()
                        return
                    # If msg object can't be sent, continue to fallback
                except Exception:
                    pass

        # No buttons or buttons failed: try sending simple Message
        try:
            msg = cl.Message(content=content or "")
            send_m = getattr(msg, "send", None)
            if callable(send_m):
                await send_m()
                return
        except Exception:
            pass

        # Fallback to top-level cl.send if available
        try:
            send_fn = getattr(cl, "send", None)
            if callable(send_fn):
                await send_fn(content or "")
                return
        except Exception:
            pass

    except Exception:
        pass

    # Ultimate fallback: print to server log (user will not see it) but avoid crashing
    try:
        print("[chainlit_app] safe_send fallback, content:", content, flush=True)
    except Exception:
        pass

@cl.on_message
async def main(message):
    """Manejador principal de mensajes entrantes desde la UI web de Chainlit.

    Usa asyncio.to_thread para ejecutar la llamada bloqueante `bot.ask` sin
    bloquear el event loop.
    """
    # Normalizar el mensaje a string: Chainlit puede pasar un objeto Message
    if isinstance(message, str):
        text = message
    else:
        # Chainlit Message suele exponer `.content`; si no, probar `.text` o usar str()
        text = getattr(message, "content", None) or getattr(message, "text", None) or str(message)

    # Debug: imprimir en consola para verificar llegada del mensaje
    print(f"[chainlit_app] received: {text!r}", flush=True)

    # Ejecutar la lógica del bot en un hilo y esperar el resultado
    try:
        reply = await asyncio.to_thread(bot.ask, text)
    except Exception as e:
        print(f"[chainlit_app] bot.ask raised: {e}", flush=True)
        # Usar safe_send en lugar de cl.send para ser compatible con distintas versiones de Chainlit
        try:
            await safe_send(f"Error interno al procesar el mensaje: {e}")
        except Exception:
            # Intentar el top-level cl.send solo si existe, evitar KeyError en runtimes sin esa función
            try:
                send_fn = getattr(cl, "send", None)
                if callable(send_fn):
                    await send_fn(f"Error interno al procesar el mensaje: {e}")
                else:
                    print(f"[chainlit_app] no se pudo notificar al cliente del error: {e}", flush=True)
            except Exception:
                print(f"[chainlit_app] fallo al intentar notificar al cliente sobre el error: {e}", flush=True)
        return

    # Debug: imprimir la respuesta antes de enviarla
    print(f"[chainlit_app] reply: {reply!r}", flush=True)

    # Enviar la respuesta como UN solo mensaje. Si parece un menú, adjuntar botones al mismo mensaje.
    try:
        reply_text = str(reply)
        lower = reply_text.lower()
        menu_keywords = ["elige una opción", "responde con el número", "selecciona una opción", "sugerencias rápidas", "paso 1/", "opción 1", "estado de mi ticket", "selecciona una opción:"]
        buttons = None
        if any(k in lower for k in menu_keywords):
            buttons = [
                {"label": "Estado de mi Ticket", "value": "1"},
                {"label": "Reportar Falla", "value": "2"},
                {"label": "Gestión de Cuenta", "value": "3"},
                {"label": "Hablar con Técnico", "value": "4"},
            ]

        # Intentar enviar usando safe_send (que maneja Message/actions o cl.send según la versión)
        try:
            await safe_send(reply_text, buttons=buttons)
            return
        except Exception as e:
            print(f"[chainlit_app] safe_send failed: {e}", flush=True)

        # Fallbacks: intentar Message().send() luego cl.send
        try:
            await cl.Message(content=reply_text).send()
            return
        except Exception:
            pass

        try:
            await cl.send(reply_text)
            return
        except Exception:
            pass

        # Último recurso: imprimir en logs
        print("[chainlit_app] no pudo enviar la respuesta al cliente", reply_text, flush=True)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[chainlit_app] unexpected error preparing send:\n{tb}", flush=True)
