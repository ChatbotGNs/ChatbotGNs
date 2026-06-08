import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import json
import logging
from datetime import datetime
import subprocess
import re

# LangChain intentionally disabled to avoid import errors in environments
# where langchain/OpenAI are not available. The chatbot will run in a
# deterministic fallback mode for testing. If later you add OPENAI_API_KEY
# and want to enable LangChain, restore appropriate imports and initialization.


class Chatbot:
    """Simple conversational chatbot with optional LLM disabled by default.

    Usage:
        from chatbot import Chatbot
        bot = Chatbot()
        bot.ask("Hola")
    """

    def __init__(self, temperature: float = 0.2, model: str = "lama2:7b-chat"):
        load_dotenv()
        
        #Si se quiere usar un Chat GPT o una IA ya existente con una llave
        #api_key = os.getenv("OPENAI_API_KEY")
        
        self.model = model 
        # Sirve para cambiar....
        self.temperature = temperature
        
        # Partner API configuration (set in .env)
        self.partner_base = os.getenv("PARTNER_API_BASE")
        self.partner_user = os.getenv("PARTNER_API_USER")
        self.partner_key = os.getenv("PARTNER_API_KEY")
        self.partner_password = os.getenv("PARTNER_API_PASSWORD")
        
        if self.partner_user and self.partner_password:
            self.auth = HTTPBasicAuth(self.partner_user, self.partner_password)
        else:
            self.auth = None

        # Logger configuration (persistent local log file)
        log_path = os.getenv("CHATBOT_LOG_PATH", "chatbot.log")
        self.logger = logging.getLogger("chatbot")
        if not self.logger.handlers:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.addHandler(handler)
            self.logger.addHandler(console_handler)
            self.logger.setLevel(logging.INFO)

        self.logger.info("Chatbot iniciado correctamente (Ollama LLM Activado)")

        self.current_flow = None


    # Actual function
    def _handle_menu_flows(self, text: str) -> str:
        """
        Maneja la lógica cuando el usuario está a la mitad de una opción del menú.
        Actúa como un enrutador hacia las funciones específicas.
        """
        # Permitir al usuario cancelar el flujo en cualquier momento
        if text.lower() in ["cancelar", "salir", "menu", "menú", "regresar"]:
            self.current_flow = None
            return "Operación cancelada. ¿En qué más puedo ayudarte? (Escribe 'menú' para ver opciones)"

        action = self.current_flow.get("action")
        step = self.current_flow.get("step")

        # Agrega este LOG temporal para ver qué está pasando:
        self.logger.info(f"[ENRUTADOR] Action: {action} | Step: {step} | Text: {text}")
        
        # Enrutar a la función correspondiente
        if action == "check_plan":
            return self._handle_check_plan_flow(text)    
        elif action == "report_issue":
            return self._handle_report_issue_flow(text, step)
        elif action == "auto_diagnostic":
            return self._handle_auto_diagnostic_flow(text, step)
        elif action == "contact_technician":
            return self._handle_speak_technician_flow(text, step)
        
    
        # Si no coincide con nada
        self.current_flow = None
        return "Flujo terminado con errores o no reconocido."

    def _handle_check_plan_flow(self, text: str) -> str:
        """
        Sub-flujo para manejar la consulta del plan y saldo del cliente.
        """
        if not text.strip().isdigit():
            return "Por favor, ingresa únicamente los números de tu ID de Cliente. (O escribe 'cancelar' para regresar al menú principal):"
        
        customer_id = text.strip()
        self.current_flow = None # Limpiamos estado inmediatamente
        
        # 1. Buscamos sus servicios
        servicios_res = self._get_services_by_customer(customer_id)
        self.logger.info(f"[API CALL] Consultando servicios para el cliente ID: {customer_id}")
        if not servicios_res.get("success"):
            self.logger.error(f"[API ERROR] Falló la consulta para {customer_id}.")
            return "No pude encontrar servicios activos para ese número de cliente."
        
        # 2. Buscamos su saldo
        saldo_res = self._get_balance_by_customer(customer_id)
        
        json_servicios = servicios_res.get("data", {})
        mensaje = f"**Información de tu Plan (Cliente {customer_id}):**\n"
        
        lista_servicios = []
        if isinstance(json_servicios, list):
            lista_servicios = json_servicios
        elif isinstance(json_servicios, dict):
            # Busca llaves comunes donde las APIs guardan listas de datos
            lista_servicios = json_servicios.get("services", json_servicios.get("servicios", json_servicios.get("data", [])))
            # Si no encontró ninguna lista interna, metemos el dict en una lista
            if not lista_servicios and json_servicios:
                lista_servicios = [json_servicios]

        if lista_servicios:
            for s in lista_servicios:
                if isinstance(s, dict): # Doble verificación de seguridad
                    nombre_servicio = s.get("service", s.get("name", "Desconocido"))
                    estatus = s.get("status", "N/A")
                    expiracion = s.get("date_expiration", s.get("expiration_date", "N/A"))
                    mensaje += f"Paquete: {nombre_servicio}\n  Estatus: {estatus}\n  Expiración: {expiracion}\n\n"
        else:
            mensaje += "No se encontraron servicios activos registrados.\n\n"   
        
        if saldo_res.get("success"):
            json_saldo = saldo_res.get("data", {})
            
            # Si por alguna razón el saldo viene en lista, extraemos el primero
            if isinstance(json_saldo, list) and len(json_saldo) > 0:
                json_saldo = json_saldo[0]
            
            if isinstance(json_saldo, dict):
                saldo = json_saldo.get("total_to_pay", "0.00")
                package_price = json_saldo.get("package_price", "0.00")
                due_date = json_saldo.get("due_date", "N/A")
                mensaje += f"**Costo del plan:** ${package_price}\n**Saldo pendiente:** ${saldo}\n**Fecha límite de pago:** {due_date}\n"
            else:
                mensaje += "No se pudo interpretar el formato del saldo.\n"
        else:
            mensaje += "No se pudo consultar el saldo pendiente en este momento.\n"
        
        mensaje += "\n---\n✅ *Consulta exitosa. ¿En qué más te puedo ayudar hoy? Escoge una de las opciones o platicanos tu problema*\n\n"

        mensaje += self._show_menu_action()
        return mensaje
    
    def _handle_report_issue_flow(self, text: str, step: str) -> str:
        """
        Sub-flujo interactivo paso a paso para reportar una falla técnica.
        """
        # PASO 1: Pedir ID de Cliente para buscar el idCustomerPackage en la API
        if step == "get_customer_id":
            if not text.strip().isdigit():
                return "Por favor, ingresa únicamente números para tu ID de Cliente (o escribe **cancelar**):"
            
            customer_id = text.strip()
            try:
                self.logger.info(f"Consultando servicios en la API para el cliente: {customer_id}...")
                
                # Vamos a la API a buscar los servicios de este cliente
                servicios_res = self._get_services_by_customer(customer_id)
                
                # PREVENCIÓN DE ERROR: Verificamos que la API realmente devolvió un diccionario
                if not servicios_res or not isinstance(servicios_res, dict):
                    self.logger.error(f"[API ERROR] La respuesta de la API no es válida: {servicios_res}")
                    return "Hubo un error de conexión con la base de datos. Por favor, intenta de nuevo más tarde o escribe **cancelar**."

                if not servicios_res.get("success") or not servicios_res.get("data"):
                    self.logger.warning(f"No se encontraron servicios para el ID {customer_id}")
                    return f"No encontré un servicio activo asociado al ID **{customer_id}**.\n\nPor favor, verifica el número e **ingrésalo de nuevo** (o escribe 'cancelar' para regresar al menú):"
                
                # Acceso seguro al JSON según tu estructura
                datos_api = servicios_res["data"]
                
                if isinstance(datos_api, dict) and "idPackage" in datos_api:
                    primer_servicio = datos_api["idPackage"]
                elif isinstance(datos_api, list) and len(datos_api) > 0:
                    primer_servicio = datos_api[0].get("idPackage", datos_api[0])
                else:
                    primer_servicio = datos_api
                
                id_paquete = primer_servicio.get("id") if isinstance(primer_servicio, dict) else primer_servicio
                
                if not id_paquete:
                    self.current_flow = None
                    return "No se pudo extraer el ID del paquete de servicio. Operación cancelada."

                if "payload" not in self.current_flow:
                    self.current_flow["payload"] = {}
                # Guardamos el idCustomerPackage requerido por la API de tickets
                self.current_flow["payload"]["idCustomerPackage"] = int(id_paquete)
                self.current_flow["step"] = "problem"
        
                return "Servicio localizado. Ahora, por favor **describe brevemente la falla** que presentas:"

            except ValueError:
                # Si id_paquete tiene letras y no se puede convertir a int()
                self.logger.error(f"Error de conversión. id_paquete recibido: {id_paquete}")
                self.current_flow = None
                return "El formato del ID del paquete es incorrecto. Operación cancelada."
                
            except Exception as e:
                # ¡AQUÍ ATRAPAMOS EL ERROR INVISIBLE! 
                import traceback
                error_trace = traceback.format_exc()
                self.logger.error(f"[CRASH EN GET_CUSTOMER_ID] Error: {str(e)}\n{error_trace}")
                
                self.current_flow = None
                return "Ocurrió un error interno al validar tus datos. Por favor, escribe **menú** para intentarlo de nuevo."
            
        # PASO 2: Capturar el problema
        elif step == "problem":
            if len(text.strip()) < 5:
                return "Por favor, sé un poco más descriptivo con el problema:"
            
            self.current_flow["payload"]["problem"] = text.strip()
            self.current_flow["step"] = "contact_name"
            return "Gracias. ¿Cuál es el **nombre de la persona de contacto**? (o escribe **'saltar'** o **'siguiente'** para dejarlo vacío)"

        # PASO 3: Capturar el nombre de contacto (OPCIONAL)
        elif step == "contact_name":
            entrada = text.strip()
            if entrada.lower() in ["saltar", "siguiente", "omitir", "no", "vacio", "vacío"]:
                self.current_flow["payload"]["contact_name"] = "No especificado"
            else:
                self.current_flow["payload"]["contact_name"] = entrada
            
            self.current_flow["step"] = "phone_number"
            return "Anotado. ¿A qué **número de teléfono** podemos comunicarnos contigo? (o escribe **'saltar'** o **'siguiente'** para dejarlo vacío)"

        # PASO 4: Capturar el teléfono (OPCIONAL)
        elif step == "phone_number":
            entrada = text.strip()
            if entrada.lower() in ["saltar", "siguiente", "omitir", "no", "vacio", "vacío"]:
                self.current_flow["payload"]["phone_number"] = "No especificado"
            else:
                if len(entrada) < 7 or not entrada.isdigit():
                    return "Ese no parece un número de teléfono válido. Por favor ingresa solo números o escribe **'saltar'**:"
                self.current_flow["payload"]["phone_number"] = entrada
            
            self.current_flow["step"] = "visit_date"
            return "Casi terminamos. Si necesitaras una visita técnica, ingresa una **fecha sugerida para esta** (ej. 2026-06-15). Si no, escribe **'saltar'**."

        # PASO 5: Capturar la fecha y ENVIAR EL TICKET
        elif step == "visit_date":
            entrada = text.strip()
            if entrada.lower() in ["saltar", "siguiente", "no", "ninguna", "omitir", "vacio"]:
                self.current_flow["payload"]["visit_date"] = None
            else:
                import re
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", entrada):
                    return "El formato de la fecha no es válido. Debe ser **YYYY-MM-DD** (ejemplo: 2026-06-15) o escribe 'saltar':"
                self.current_flow["payload"]["visit_date"] = entrada

            # ---- ¡PROCESO DE ENVÍO! ----
            # 1. Asignamos la categoría por defecto
            self.current_flow["payload"]["idCategory"] = int(os.getenv("DEFAULT_ID_CATEGORY", 9))
            
            final_payload = self.current_flow["payload"]
            self.current_flow = None # Liberamos el bot de inmediato
            
            # TODO: Cambiarlo a la correcta después de test
            return self._submit_new_ticket_local(final_payload)

        return "Error interno en los pasos del reporte."

    #Local function
    def _submit_new_ticket_local(self, payload: dict) -> str:
        """
        Guarda el ticket de manera local en un archivo JSON para pruebas.
        """
        try:
            # Tu lógica actual para guardar el archivo JSON (si aplica)
            archivo_tickets = "tickets_locales.json"
            
            # Cargar existentes
            tickets = []
            if os.path.exists(archivo_tickets):
                with open(archivo_tickets, "r", encoding="utf-8") as f:
                    try:
                        tickets = json.load(f)
                    except Exception:
                        tickets = []

            with open(archivo_tickets, "w", encoding="utf-8") as f:
                json.dump(tickets, f, indent=4, ensure_ascii=False)
            
            # 🚨 ¡ESTA ES LA LÍNEA CRUCIAL QUE FALTA O ESTÁ FALLANDO! 🚨
            return "✅ **¡Falla reportada con éxito de manera local!**\nTu reporte ha sido registrado en nuestro sistema de pruebas.\nUn técnico revisará tu caso pronto."
            
        except Exception as e:
            self.logger.error(f"Error en _submit_new_ticket_local: {e}")
            return f"❌ Ocurrió un error local al guardar el ticket: {e}"

    #Actual funtcion
    def _submit_new_ticket(self, payload: dict) -> str:
        """
        Envía el JSON validado al endpoint de creación de tickets basándose en los Body Params oficiales.
        """
        # Limpiar valores nulos para no enviar campos vacíos si la API es estricta
        clean_payload = {k: v for k, v in payload.items() if v is not None}
        
        try:
            # Aquí asumo que el endpoint es /tickets, ajústalo si es diferente
            url = f"{self.partner_base.rstrip('/')}/tickets"
            headers = {"Content-Type": "application/json"}
            if self.partner_key:
                headers["Authorization"] = f"Bearer {self.partner_key}"

            # Hacemos la petición POST
            response = requests.post(url, headers=headers, json=clean_payload, auth=self.auth, timeout=10)
            
            if response.status_code in [200, 201]:
                # Éxito: Puedes extraer el ID del ticket de la respuesta si tu API lo devuelve
                data = response.json()
                ticket_id = data.get("idTicket", "desconocido")
                mensaje = f" **¡Falla reportada con éxito!**\nTu reporte ha sido registrado con el número de ticket: **{ticket_id}**.\nUn técnico revisará tu caso pronto.\n\nTambién podemos intentar diagnosticar lo que está fallando para solucionarlo."
            else:
                self.logger.error(f"Error creando ticket. HTTP {response.status_code}: {response.text}")
                mensaje = "⚠️ Recibimos tus datos, pero hubo un problema al guardarlos en el sistema. Intenta de nuevo más tarde o comunícate directamente con un Técnico."                
        
        except Exception as e:
            self.logger.error(f"Excepción al crear ticket: {e}")
            mensaje = "⚠️ El sistema no está disponible en este momento. Intenta más tarde."

        mensaje += self._show_menu_action() 
        
        return mensaje
    

    def _get_services_by_customer(self, customer_id: str) -> dict:
        """Llama al endpoint GET Obtener servicios por ID del cliente."""
        # Ajusta la ruta exacta de tu API
        url = f"{self.partner_base.rstrip('/')}/services/{customer_id}"
        headers = {"Authorization": f"Bearer {self.partner_key}"} if self.partner_key else {}
        
        try:
            response = requests.get(url, headers=headers, auth=self.auth, timeout=10)
            if response.status_code == 200:
                print("succes")
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"Error {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_balance_by_customer(self, customer_id: str) -> dict:
        """Llama al endpoint GET Obtener saldo a pagar por ID del Cliente."""
        url = f"{self.partner_base.rstrip('/')}/total-to-pay/{customer_id}"
        headers = {"Authorization": f"Bearer {self.partner_key}"} if self.partner_key else {}
        
        try:
            response = requests.get(url, headers=headers, auth=self.auth, timeout=10)
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"Error {response.status_code}"}
        except Exception:
            return {"success": False, "error": "Error de conexión"}

    def _build_diagnostic_prompt(self, problem: str, history: str = "", new_input: str = "") -> str:
        """
        Inyecta las reglas estrictas de tu empresa al LLM para que no alucine pasos.
        """
        ruta_archivo = "instruccionesAutodiagnositoc.txt"
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                instrucciones_estrictas = f.read()
        except FileNotFoundError:
            # Fallback de seguridad por si se borra el archivo
            self.logger.error(f"No se encontró el archivo {ruta_archivo}")
            instrucciones_estrictas = (
                "Eres un asistente técnico. Ayuda al usuario paso a paso con su problema. "
                "Si no puedes resolverlo, responde: ACCION_ESCALAR"
            )
        # 2. Construir el Prompt si es el inicio de la charla
        if not history:
            return (
                f"{instrucciones_estrictas}\n\n"
                f"El usuario reporta el siguiente problema inicial: {problem}\n"
                "Selecciona el manual adecuado según el problema y ¿Cuál es tu primer paso técnico?"
            )
        # 3. Construir el Prompt si ya están platicando (seguimiento)
        return (
            f"{instrucciones_estrictas}\n\n"
            f"Problema original reportado: {problem}\n\n"
            f"Historial de la conversación:\n{history}\n"
            f"El cliente acaba de responder: {new_input}\n\n"
            "Analiza el historial y el manual. ¿Cuál es tu respuesta o siguiente paso?"
        )

    def _handle_auto_diagnostic_flow(self, text: str, step: str) -> str:
        """
        Maneja la conversación de ida y vuelta con el LLM, manteniendo un contexto local.
        """
        # El usuario siempre puede forzar la salida
        if text.lower() in ["cancelar", "salir", "menu", "menú", "humano", "asesor"]:
            self.current_flow = None
            return "Entendido. Si el problema continúa, te sugiero presionar la Opción 2 para levantar un ticket de falla formal."

        if step == "ask_problem":
            # 1. Guardamos el problema inicial
            self.current_flow["problem"] = text
            self.current_flow["step"] = "troubleshooting"
            
            # 2. Le pedimos a la IA que inicie el diagnóstico
            prompt = self._build_diagnostic_prompt(problem=text)
            respuesta_ai = self._run_llm(prompt) # Llama a tu función de Ollama
            
            # 3. Guardamos esto en la memoria temporal del flujo
            self.current_flow["history"] = f"Usuario: {text}\nAsistente: {respuesta_ai}\n"
            
            return respuesta_ai

        elif step == "troubleshooting":
            problema_original = self.current_flow["problem"]
            historial_previo = self.current_flow["history"]
            
            # FASE 2.3: Tolerancia a respuestas cortas
            texto_procesado = text
            respuestas_cortas = ["si", "sí", "no", "ok", "ya", "listo", "claro", "no funciona"]
            
            # Si el mensaje es muy corto y es una confirmación, le damos más contexto al LLM
            if len(text.strip()) <= 12 and text.lower().strip() in respuestas_cortas:
                texto_procesado = (
                    f"[{text}] -> (Nota interna para la IA: El usuario acaba de confirmar "
                    "o negar la instrucción anterior. Evalúa el historial y procede "
                    "con el siguiente paso técnico lógico de la guía)."
                )
            
            # 1. Le pasamos todo el contexto a la IA junto con la nueva respuesta enriquecida
            nuevo_prompt = self._build_diagnostic_prompt(
                problem=problema_original, 
                history=historial_previo, 
                new_input=texto_procesado
            )
            
            respuesta_ai = self._run_llm(nuevo_prompt)
            
            # ==========================================
            # EL INTERCEPTOR: ¿La IA decidió que ya no puede más?
            # ==========================================
            if "ACCION_ESCALAR" in respuesta_ai or "accion_escalar" in respuesta_ai.lower():
                self.current_flow = None # Limpiamos el flujo de diagnóstico
                
                # Aquí lo mandamos mágicamente al flujo de "Reportar Falla" para pedirle sus datos
                # UPDATE: Aqui se puede crear un ticket automatico en el futuro
                return (
                    "Parece que los pasos básicos no resolvieron el problema. "
                    "Vamos a transferir este caso a nuestros ingenieros.\n\n"
                    "Para levantar tu reporte oficial, por favor escribe el número **2** (o selecciona 'Reportar Falla' en el menú)."
                )
            # ==========================================
            # EL NUEVO INTERCEPTOR DE ÉXITO: ¿El problema se solucionó?
            # ==========================================
            if "ACCION_RESUELTO" in respuesta_ai or "accion_resuelto" in respuesta_ai.lower():
                self.current_flow = None # ¡Liberamos al usuario del flujo!
                
                # Le damos un mensaje bonito de despedida y le mostramos el menú
                mensaje = "¡Qué excelente noticia! Me da mucho gusto haber podido solucionar tu problema con el servicio.\n\n"
                mensaje += "*¿En qué más te puedo ayudar hoy?*\n\n"
                mensaje += self._show_menu_action()

                return mensaje
            
            # Si la IA sigue diagnosticando, guardamos la plática (guardamos el text original del usuario, no el enriquecido)
            self.current_flow["history"] += f"Usuario: {text}\nAsistente: {respuesta_ai}\n"
            
            return respuesta_ai
   
    def _run_llm(self, prompt: str) -> str:
        """Se conecta a Ollama usando su API interna.
        Esto elimina por completo los caracteres raros y los errores de Unicode en Windows."""
        # Prefer local Ollama if configured
        modelo_ia = os.getenv("OLLAMA_MODEL")
        url = "http://localhost:11434/api/generate"
        
        payload = {
            "model": modelo_ia,
            "prompt": prompt,
            "stream": False # Le decimos que nos dé el texto limpio, sin animaciones
        }

        try:
            # Hacemos la petición a Ollama local
            respuesta = requests.post(url, json=payload, timeout=60)
            
            # Validamos que todo haya salido bien
            if respuesta.status_code == 200:
                datos = respuesta.json()
                texto_limpio = datos.get("response", "")
                self.logger.info(f"[OLLAMA RESPONSE] La IA respondió: {texto_limpio.strip()}")
                return texto_limpio.strip()
            else:
                self.logger.error(f"Error de Ollama API: {respuesta.text}")
                return "Hubo un problema procesando tu consulta con la IA."
                
        except requests.exceptions.ConnectionError:
            return "No me pude conectar con la IA. Asegúrate de que 'ollama serve' esté corriendo en tu terminal."
        except Exception as e:
            self.logger.error(f"Error ejecutando IA: {e}")
            return "Ocurrió un error inesperado al consultar la IA."
        

    def _classify_intent_with_llm(self, text: str) -> str:
        """
        Usa el LLM para entender qué quiere hacer el usuario y devuelve una etiqueta estricta.
        """
        ruta_archivo = "classificationIntentLLM.txt"
        
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            # Fallback de seguridad si se borra el archivo
            self.logger.error(f"No se encontró el archivo {ruta_archivo}. Usando prompt por defecto.")
            prompt_template = """Eres un clasificador de intenciones. Responde ÚNICAMENTE con una etiqueta:
            - ROUTE_DIAGNOSTIC
            - ROUTE_CHECK_PLAN
            - ROUTE_REPORT_ISSUE
            - ROUTE_CHECK_TICKET
            - UNKNOWN

            Mensaje del usuario: "{user_message}"
            ETIQUETA:"""

        # ¡AQUÍ ESTÁ LA MAGIA! Reemplazamos {user_message} con lo que escribió el cliente
        prompt = prompt_template.format(user_message=text)

        # Usamos tu función de Ollama
        respuesta = self._run_llm(prompt)
        
        # Limpiamos la respuesta por si la IA agregó un punto final o espacios
        return respuesta.strip().upper()
    
    def _handle_speak_technician_flow(self, text: str, step: str) -> str:
        """
        Flujo rápido para capturar datos y notificar a un técnico humano.
        """

        # Asegurarnos de que existe el diccionario payload para no tener errores
        if "payload" not in self.current_flow:
            self.current_flow["payload"] = {}

        # PASO 1: Guardamos el problema y preguntamos quién es
        if step == "ask_problem":
            self.current_flow["payload"]["problem"] = text.strip()
            self.current_flow["step"] = "ask_name"
            return "Entendido. Para agilizar el soporte, ¿me podrías proporcionar tu **Nombre completo** o **ID de Cliente**?"
        # PASO 2: Guardamos la identidad y preguntamos el medio de contacto
        elif step == "ask_name":
            self.current_flow["payload"]["user_identity"] = text.strip()
            self.current_flow["step"] = "ask_contact"
            return "Gracias. Finalmente, para que el técnico te contacte de inmediato, por favor **ingresa tu número de teléfono o correo electrónico**:"
        
        # PASO 3: Guardamos el contacto y enviamos el reporte
        elif step == "ask_contact":
            contacto = text.strip()
            problema = self.current_flow["payload"].get("problem", "No especificado")
            identidad = self.current_flow["payload"].get("user_identity", "No especificado")

            es_correo = re.match(r"[^@]+@[^@]+\.[^@]+", contacto)
            tipo_contacto = "Correo" if es_correo else "Teléfono"
            
            # Combinamos todo en un texto estructurado
            descripcion_completa = (
                f"SOLICITUD DE CONTACTO \n"
                f"Cliente/ID: {identidad}\n"
                f"{tipo_contacto} de contacto: {contacto}\n"
                f"Problema reportado: {problema}"
            )

            # 2. LEEMOS LA PREFERENCIA DEL ADMINISTRADOR DESDE EL .ENV
            metodo_preferido = os.getenv("ESCALATION_METHOD", "ticket").lower()
            
            exito = False
            # 3. ENRUTAMOS SEGÚN LA CONVENIENCIA DEL TÉCNICO
            if metodo_preferido == "ticket":
                # Armamos el payload para tu función de tickets
                payload_ticket = {
                    "problem": descripcion_completa,
                    "contact_name": identidad,
                    "phone_number": contacto if not es_correo else "N/A",
                    "idCategory": 1, # O el ID que represente "URGENTE / CONTACTO HUMANO" en tu base
                    # ... otros campos requeridos por tu API ...
                }
                # Usamos tu función existente de tickets (la local o la de API)
                #TODO: Cambiar a la funcion real
                mensaje_resultado = self._submit_new_ticket_local(payload_ticket)
                # Como tu función ya devuelve un texto de éxito, lo podemos usar o sobreescribir
                exito = True if "éxito" in mensaje_resultado.lower() else False

            elif metodo_preferido in ["whatsapp", "email"]:
                # Usamos tu función actual, pasándole el método elegido en el .env
                exito = self._contact_technician(
                    user_contact=contacto, 
                    problem_description=descripcion_completa, 
                    method=metodo_preferido
                )
            
            # Limpiamos el flujo
            self.current_flow = None
            
            # 4. MENSAJE FINAL (Le agregamos tu menú para que no se quede atascado)
            if exito:
                mensaje = "**¡Listo!** He notificado a nuestro equipo técnico. Un asesor revisará tu caso y te contactará."
            else:
                mensaje = "Hubo un problema al intentar contactar al técnico. Por favor, intenta usar la opción de 'Reportar Falla' en el menú principal."
            
            mensaje += "\n\n---\n*¿Qué te gustaría hacer ahora?*\n\n"
            mensaje += self._show_main_menu()
            
            return mensaje
    
    def _contact_technician(self, user_contact: str, problem_description: str, method: str = "whatsapp") -> bool:
        """
        Envía un mensaje predeterminado a un técnico vía WhatsApp o Correo.
        Method puede ser "whatsapp" o "correo".
        """
        # 1. Armamos el mensaje predeterminado
        mensaje_predeterminado = (
            f"*NUEVO REPORTE - ASISTENCIA HUMANA REQUERIDA* 🚨\n\n"
            f"Un cliente ha solicitado hablar con un técnico desde el Chatbot.\n"
            f"*Contacto del cliente:* {user_contact}\n"
            f"*Problema/Motivo:* {problem_description}\n\n"
            f"Por favor, comunícate con el cliente lo antes posible."
        )
        
        try:
            if method == "whatsapp":
                # TODO: Aquí va tu código real para enviar WhatsApp (ej. Twilio, Meta API, API de tu proveedor)
                # Ejemplo imaginario: requests.post("api.whatsapp.com/send", json={"to": "numerotecnico", "text": mensaje_predeterminado})
                
                self.logger.info(f"[WHATSAPP SIMULADO] Enviando mensaje al técnico:\n{mensaje_predeterminado}")
                
            elif method == "correo":
                # TODO: Aquí va tu código real para enviar correo (ej. smtplib, Sendgrid, Resend)
                
                self.logger.info(f"[CORREO SIMULADO] Enviando email al técnico:\n{mensaje_predeterminado}")
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error al intentar notificar al técnico: {e}")
            return False

    def _show_menu_action(self) -> str:
        """
        Devuelve el texto del menú principal.
        """
        return (
            "¿Qué te gustaría hacer o revisar?\n\n"
            "Selecciona una opción o escríbela:\n"
            "1) Reportar Falla\n"
            "2) Consultar Plan\n"
            "3) Diagnóstico Rápido\n"
            "4) Hablar con Técnico\n"
        )

    def ask(self, message: str) -> str:
        """
        Punto de entrada principal. Recibe el mensaje, verifica si estamos en medio
        de un flujo y, si no, evalúa qué opción del menú eligió el usuario.
        """
        text = message.strip()
        self.logger.info(f"[MENSAJE USUARIO] Texto recibido: {text}")
        low_text = text.lower()

        class MenuOption:
            def __init__(self, buttonCall, keywords):
                self.buttonCall = buttonCall
                self.keywords = keywords

        buttonCallLeadingCharacters = "-:-:-/-!"

        # Diccionarios de palabras exactas (Ruta Rápida)
        report_issue_keywords = MenuOption(buttonCallLeadingCharacters + "1", ["1", "opción 1", "reportar falla", "reportar", "tengo un problema con mi internet"])
        check_plan_keywords = MenuOption(buttonCallLeadingCharacters + "2", ["2", "opción 2", "gestión de cuenta", "consultar plan", "quiero consultar mi plan actual"])
        auto_diagnostic_keywords = MenuOption(buttonCallLeadingCharacters + "3", ["3", "opción 3", "soporte", "diagnóstico rápido", "diagnóstico", "tengo problemas con mi internet, ¿me ayudas?"])
        contact_technician_keywords = MenuOption(buttonCallLeadingCharacters + "4", ["4", "opción 3", "humano", "tecnico", "mensaje", "quiero hablar con un técnico"])
        all_menu_option_keywords = [report_issue_keywords, check_plan_keywords, auto_diagnostic_keywords, contact_technician_keywords]
        menu_keywords = ["cancelar", "salir", "menu", "menú", "regresar", "inicio", "que puedo hacer"]

        # ==========================================
        # 1. RUTA RÁPIDA (Botones y Comandos Exactos)
        # Tienen prioridad absoluta y rompen cualquier flujo activo.
        # ==========================================
        if low_text in menu_keywords:
            
            if(self.current_flow != None):
                self.logger.warning(f"[FLUJO CANCELADO] El usuario canceló el flujo: {self.current_flow.get('action')}")
                self.current_flow = None # Destruimos el flujo
                # Devolvemos el texto directamente:
                return (
                    "Operación cancelada. ¿Qué te gustaría hacer ahora?\n\n"
                    "Selecciona una opción o escribela:\n"
                    "1) Reportar Falla\n"
                    "2) Consultar Plan\n"
                    "3) Diagnostico Rapido\n"
                    "4) Hablar con Técnico\n"
                )
            else:
                return self._show_menu_action()
        
        # If: 
        # a) The user is currently in the menu section, and an option keyword / option button call string is sent.
        # b) The user is NOT in the menu section, but the provided text matches the specific string type sent by a button.
        if ((self.current_flow is None) or (self.current_flow is not None and any(low_text == option.buttonCall for option in all_menu_option_keywords))):
            low_text = low_text.replace(buttonCallLeadingCharacters, '')
            if low_text in report_issue_keywords.keywords:
                self.current_flow = {"action": "report_issue", "step": "get_customer_id"}
                return "Has elegido Reportar Falla.\n\nPara empezar, por favor ingresa tu **ID de Cliente**:"

            elif low_text in check_plan_keywords.keywords:
                self.current_flow = {"action": "check_plan", "step": "get_customer_info", "payload": {}}
                return "Has elegido Consultar Plan y Saldo.\n\nPor favor, ingresa tu **ID de Cliente**:"

            elif low_text in auto_diagnostic_keywords.keywords:
                self.current_flow = {"action": "auto_diagnostic", "step": "ask_problem"}
                return "Has elegido Auto-Diagnóstico / Soporte Técnico.\n\nPor favor, **descríbeme con detalle cuál es el problema** que tienes con tu servicio:"

            elif low_text in contact_technician_keywords.keywords:
                self.current_flow = {"action": "contact_technician", "step": "ask_problem", "history": ""}
                return "Has elegido Diagnóstico Rápido / Soporte Técnico.\n\nPor favor, **descríbeme con detalle cuál es el problema** que tienes con tu servicio:"

        # ==========================================
        # 2. CONTINUAR FLUJO ACTIVO
        # Si no presionó un botón de menú, y ya estaba haciendo algo, que siga.
        # ==========================================
        if self.current_flow is not None:
            return self._handle_menu_flows(text)
        
        # ==========================================
        # 3. RUTA INTELIGENTE (El Interceptor LLM)
        # Si NO está en un flujo, y escribió una frase larga natural.
        # ==========================================
        if len(text) > 10 and not text.isdigit():
            
            intencion = self._classify_intent_with_llm(text)
            self.logger.info(f"[ENRUTAMIENTO LLM] Intención detectada: {intencion} para el texto: '{text}'")
            # A. Si quiere probar solucionarlo
            if "ROUTE_DIAGNOSTIC" in intencion:
                self.current_flow = {
                    "action": "auto_diagnostic",
                    "step": "troubleshooting", 
                    "problem": text, 
                    "history": ""
                }
                prompt = self._build_diagnostic_prompt(problem=text)
                respuesta_ai = self._run_llm(prompt)
                self.current_flow["history"] = f"Usuario: {text}\nAsistente: {respuesta_ai}\n"
                return f"Entiendo que tienes problemas con el servicio. Vamos a revisarlo:\n\n{respuesta_ai}"

            # B. Si detecta que quiere consultar su PLAN
            elif "ROUTE_CHECK_PLAN" in intencion:
                self.current_flow = {"action": "check_plan"}
                return "Entiendo que quieres consultar la información de tu cuenta.\n\nPor favor, ingresa tu **ID de Cliente**:"
            
            # D. Si detecta que quiere REPORTAR FALLA FORMAL
            elif "ROUTE_REPORT_ISSUE" in intencion:
                self.current_flow = {"action": "report_issue", "step": "get_customer_id", "payload": {}}
                return "Entiendo que deseas levantar un reporte de falla.\n\nPara empezar, por favor ingresa tu **ID de Cliente**:"
            
            elif "ROUTE_TECHNICIAN" in intencion:
                self.current_flow = {"action": "contact_technician"}
                return "Entiendo que quieres hablar con un Tecnico, :"
            
            elif "UNKNOWN" in intencion:
                self.current_flow = None
                return self._show_menu_action()
            
        # ==========================================
        # 4. SALUDOS Y FALLBACK (Por Defecto)
        # ==========================================
        # Si el mensaje fue corto (ej. "hola"), o si el LLM devolvió "UNKNOWN".
        return (
            "¡Hola! ¿Qué te gustaría hacer o revisar?\n\n"
            "Selecciona una opción:\n"
            "1) Reportar Falla\n"
            "2) Gestión de Cuenta\n"
            "3) Auto Diagnostico\n"
            "4) Hablar con Técnico\n"
        )