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


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Reportar Falla",
            message="Tengo un problema con mi internet"
        ),
        cl.Starter(
            label="Consultar Plan",
            message="Quiero consultar mi plan actual"
        ),
        cl.Starter(
            label="Diagnóstico rápido",
            message="Mi internet está lento o fallando, ¿qué puedo hacer para diagnosticar el problema?"
        ),
        cl.Starter(
            label="Hablar con Técnico",
            message="Quiero hablar con un técnico"
        ),
    ]



@cl.on_chat_start
async def start():
    # Instanciar por cada sesión de usuario y guardarlo en el estado
    cl.user_session.set("bot", Chatbot())

# Helper seguro para enviar mensajes y botones compatible con distintas versiones de Chainlit
async def safe_send(content: str | None = None, buttons: list | None = None):
    try:
        if buttons:
            # En Chainlit, los botones interactivos se crean con cl.Action
            actions = [
                cl.Action(
                    name="menu_action",  # Nombre clave para vincular la acción
                    payload={"value": b["value"]}, 
                    label=b["label"]
                ) for b in buttons
            ]
            await cl.Message(content=content, actions=actions).send()
            return
            
        await cl.Message(content=content).send()
        
    except Exception as e:
        print(f"[chainlit_app] no pudo enviar la respuesta: {e}", flush=True)


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
    
    # Recuperamos el bot de la sesión actual
    bot = cl.user_session.get("bot")
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

@cl.action_callback("menu_action")
async def on_action(action: cl.Action):
    # 1. Extraemos el número de la opción que el usuario clickeó (1, 2, 3 o 4)
    valor_elegido = action.payload["value"]
    
    # 2. Opcional: Borramos los botones del chat para que se vea limpio
    await action.remove()
    
    # 3. Imprimimos la selección para que el usuario sepa qué eligió
    await cl.Message(content=f"👉 *Seleccionaste la opción: {valor_elegido}*").send()
    
    # 4. Recuperamos el bot de la sesión y le mandamos el valor como si el usuario lo hubiera escrito
    bot = cl.user_session.get("bot")
    
    # Corremos la lógica de respuesta sin bloquear el servidor
    respuesta = await cl.make_async(bot.ask)(valor_elegido)
    
    # Enviamos la respuesta final al chat
    await safe_send(respuesta)