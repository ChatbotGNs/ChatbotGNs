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
            message="Tengo problemas con mi internet, ¿me ayudas?"
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
            actions = [
                cl.Action(
                    name="menu_action",  
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
    # TODO borrar esto
    print(f"[chainlit_app] received: {text!r}", flush=True)
    
    # Recuperamos el bot de la sesión actual
    bot = cl.user_session.get("bot")

    # Ejecutar la lógica del bot en un hilo y esperar el resultado
    try:
        async with cl.Step("Analizando...") as step:
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


    # TODO borrar esto
    # Debug: imprimir la respuesta antes de enviarla
    print(f"[chainlit_app] reply: {reply!r}", flush=True)

    # Enviar la respuesta como UN solo mensaje. Si parece un menú, adjuntar botones al mismo mensaje.
    try:
        reply_text = str(reply)
        buttons = None
        # FASE 2.2: Desacoplar botones del texto usando bot.current_flow
        if bot.current_flow is None:
            # Si el flujo es None, el usuario está libre (en el menú principal o terminó un proceso)
            buttons = [
                {"label": "Estado de mi Ticket", "value": "1"},
                {"label": "Reportar Falla", "value": "2"},
                {"label": "Gestión de Cuenta", "value": "3"},
                {"label": "Hablar con Técnico", "value": "4"},
            ]
        else:
            # Si hay un flujo activo, el usuario está a la mitad de un proceso (ej. reportando falla)
            buttons = [
                {"label": "Menú Principal", "value": "menu"},
                {"label": "Cancelar", "value": "cancelar"}
            ]
        # Intentar enviar usando safe_send
        try:
            await safe_send(reply_text, buttons=buttons)
            return
        except Exception as e:
            print(f"[chainlit_app] safe_send failed: {e}", flush=True)

        # Fallbacks...
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
    
    if valor_elegido in ["menu", "cancelar"]:
        await cl.Message(content=f"👉 *Acción: {valor_elegido.capitalize()}*").send()
    else:
        await cl.Message(content=f"👉 *Seleccionaste la opción: {valor_elegido}*").send()

    # 4. ¡MAGIA! En lugar de procesarlo aquí y perder los próximos botones,
    # mandamos el valor del botón directamente a nuestra función `main` como si 
    # el usuario lo hubiera tecleado en el chat.
    await main(valor_elegido)
