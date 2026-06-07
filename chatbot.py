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
    #TODO: revisar pq esta el str en el gpt turbo, si usamos el ollama
    def __init__(self, temperature: float = 0.2, model: str = "gpt-3.5-turbo"):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")

        self.use_llm = False
        self.llm = None
        self.memory = None
        self.chain = None

        # Partner API configuration (set in .env)
        self.partner_base = os.getenv("PARTNER_API_BASE")
        self.partner_key = os.getenv("PARTNER_API_KEY")
        self.partner_user = os.getenv("PARTNER_API_USER")
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
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        self.logger.info("Chatbot iniciado (modo fallback, sin LLM)")

        # Cargar datos locales (tickets, customers, comments) si existen en el repo raíz
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        self.tickets_path = os.path.join(base_dir, "tickets.json")
        self.customers_path = os.path.join(base_dir, "customers.json")
        self.comments_path = os.path.join(base_dir, "comments.json")
        self.categories_path = os.path.join(base_dir, "categories.json")

        self.tickets = []
        self.customers = []
        self.comments = []
        self.categories = []
        self._load_local_data()
        # Estado simple para flujos interactivos (por ejemplo, diagnóstico paso a paso)
        self.pending_action = None


        self.current_flow = None

    def _load_local_data(self):
        def _load(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                # Registrar detalle del error para facilitar depuración si el JSON es inválido o no se puede leer
                try:
                    self.logger.error(json.dumps({"type": "local_data_load_error", "path": path, "error": str(e)} , ensure_ascii=False))
                except Exception:
                    pass
                return []

        self.tickets = _load(self.tickets_path)
        self.customers = _load(self.customers_path)
        # Si no se cargaron customers y existe el archivo en otra ubicación posible, intentar la ruta relativa al módulo
        if not self.customers:
            alt_path = os.path.join(os.path.dirname(__file__), "..", "customers.json")
            alt_path = os.path.abspath(alt_path)
            if os.path.exists(alt_path) and alt_path != self.customers_path:
                try:
                    with open(alt_path, "r", encoding="utf-8") as f:
                        self.customers = json.load(f)
                    self.logger.info(json.dumps({"type": "local_data_alt_load", "path": alt_path, "customers_loaded": len(self.customers)}, ensure_ascii=False))
                except Exception as e:
                    try:
                        self.logger.error(json.dumps({"type": "local_data_alt_load_error", "path": alt_path, "error": str(e)}, ensure_ascii=False))
                    except Exception:
                        pass

        self.comments = _load(self.comments_path)
        self.categories = _load(self.categories_path)
        self.logger.info(json.dumps({"type": "local_data_load", "tickets": len(self.tickets), "customers": len(self.customers), "comments": len(self.comments), "categories": len(self.categories)}, ensure_ascii=False))


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
        
        # Enrutar a la función correspondiente
        if action == "check_plan":
            return self._handle_check_plan_flow(text)    
        elif action == "report_issue":
            return self._handle_report_issue_flow(text, step)
        elif action == "auto_diagnostic":
            return self._handle_auto_diagnostic_flow(text, step)
        
        # Si no coincide con nada
        self.current_flow = None
        return "Flujo terminado con errores o no reconocido."

    def _handle_check_plan_flow(self, text: str) -> str:
        """
        Sub-flujo para manejar la consulta del plan y saldo del cliente.
        """
        if not text.strip().isdigit():
            return "Por favor, ingresa únicamente números para tu ID de Cliente:"
        
        customer_id = text.strip()
        self.current_flow = None # Limpiamos estado inmediatamente
        
        # 1. Buscamos sus servicios
        servicios_res = self._get_services_by_customer(customer_id)
        if not servicios_res.get("success"):
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
        
        return mensaje
    
    def _handle_report_issue_flow(self, text: str, step: str) -> str:
        """
        Sub-flujo interactivo paso a paso para reportar una falla técnica.
        """
        # PASO 1: Pedir ID de Cliente para buscar el idCustomerPackage en la API
        if step == "get_customer_id":
            if not text.strip().isdigit():
                return "Ingresa tu ID de Cliente (solo números):"
            
            customer_id = text.strip()
            
            # Vamos a la API a buscar los servicios de este cliente
            servicios_res = self._get_services_by_customer(customer_id)
            if not servicios_res.get("success") or not servicios_res.get("data"):
                self.current_flow = None
                return "No encontré un servicio asociado a ese ID de Cliente. Operación cancelada."
            
            # Acceso seguro al JSON según tu estructura
            try:
                datos_api = servicios_res["data"]
                if isinstance(datos_api, dict) and "idPackage" in datos_api:
                    primer_servicio = datos_api["idPackage"]
                elif isinstance(datos_api, list) and len(datos_api) > 0:
                    primer_servicio = datos_api[0].get("idPackage", datos_api[0])
                else:
                    primer_servicio = datos_api
                
                id_paquete = primer_servicio.get("id") if isinstance(primer_servicio, dict) else primer_servicio
            except Exception:
                self.current_flow = None
                return "Hubo un problema al interpretar los datos del servicio. Operación cancelada."
            
            if not id_paquete:
                self.current_flow = None
                return "No se pudo extraer el ID del paquete de servicio. Operación cancelada."

            # Guardamos el idCustomerPackage requerido por la API de tickets
            self.current_flow["payload"]["idCustomerPackage"] = int(id_paquete)
            self.current_flow["step"] = "problem"
    
            return "Servicio localizado. Ahora, por favor **describe brevemente la falla** que presentas:"

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
                return f"**¡Falla reportada con éxito!**\nTu reporte ha sido registrado con el número de ticket: **{ticket_id}**.\nUn técnico revisará tu caso pronto. \n Tambien podemos intentar diagnosticar lo que esta fallando para solucionarlo"
            else:
                self.logger.error(f"Error creando ticket. HTTP {response.status_code}: {response.text}")
                return f"Recibimos tus datos, pero hubo un problema al guardarlos en el sistem. Intenta de nuevo más tarde o comunicate directamente con un Tecnico."
                
        except Exception as e:
            self.logger.error(f"Excepción al crear ticket: {e}")
            return "El sistema no está disponible en este momento. Intenta más tarde."

    def _get_services_by_customer(self, customer_id: str) -> dict:
        """Llama al endpoint GET Obtener servicios por ID del cliente."""
        # Ajusta la ruta exacta de tu API
        url = f"{self.partner_base.rstrip('/')}/services/{customer_id}"
        headers = {"Authorization": f"Bearer {self.partner_key}"} if self.partner_key else {}
        
        try:
            response = requests.get(url, headers=headers, auth=self.auth, timeout=10)
            if response.status_code == 200:
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

    def _diagnostic_flow(self, message: str) -> dict:
        """Flujo de diagnóstico simplificado que devuelve un dict con steps y severity.

        Devuelve solo pasos en lenguaje natural (sin adjuntar comandos técnicos).
        """
        low = (message or "").lower()
        steps = []
        severity = "low"

        if any(k in low for k in ["intermit", "intermitencia", "intermitente", "intermitir"]):
            steps = [
                "Reproducir y anotar exactamente cuándo ocurre (hora y acción).",
                "¿Puedo intentar revisar si hay errores registrados en el sistema (si tengo acceso)? Responde 'sí' para que lo intente o 'asistencia' para que lo haga un técnico.",
                "Comprobar si el problema ocurre en varios dispositivos (¿ocurre solo en un equipo o en varios?).",
                "Verificar si el servicio está sobrecargado o con problemas de recursos; si quieres que prepare un informe para un técnico, responde 'asistencia'.",
            ]
            severity = "medium"
        elif any(k in low for k in ["no conecta", "no funciona", "corte", "sin servicio"]):
            steps = [
                "Reinicia el módem y el router (espera 30s).",
                "Verifica que los cables estén conectados correctamente.",
                "Consulta el estado del servicio en tu área o con tu ISP.",
            ]
            severity = "high" if "corte" in low or "no funciona" in low else "medium"
        elif any(k in low for k in ["lentitud", "baja velocidad", "lag", "latencia"]):
            steps = [
                "Ejecuta un test de velocidad desde un equipo conectado por cable.",
                "Reinicia los equipos de red y vuelve a medir.",
                "Reduce dispositivos activos y comprueba si mejora la velocidad.",
            ]
            severity = "medium"
        else:
            steps = ["Proporciona más detalles: ¿corte, lentitud, intermitencia, hardware?"]
            severity = "low"

        return {"steps": steps, "severity": severity}

    
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
            
            # 1. Le pasamos todo el contexto a la IA junto con la nueva respuesta del usuario
            nuevo_prompt = self._build_diagnostic_prompt(
                problem=problema_original, 
                history=historial_previo, 
                new_input=text
            )
            
            respuesta_ai = self._run_llm(nuevo_prompt)
            
            # ==========================================
            # EL INTERCEPTOR: ¿La IA decidió que ya no puede más?
            # ==========================================
            if "ACCION_ESCALAR" in respuesta_ai or "accion_escalar" in respuesta_ai.lower():
                self.current_flow = None # Limpiamos el flujo de diagnóstico
                
                # Aquí lo mandamos mágicamente al flujo de "Reportar Falla" para pedirle sus datos
                return (
                    "Parece que los pasos básicos no resolvieron el problema. "
                    "Vamos a transferir este caso a nuestros ingenieros.\n\n"
                    "Para levantar tu reporte oficial, por favor escribe el número **2** (o selecciona 'Reportar Falla' en el menú)."
                )
            
            # Si la IA sigue diagnosticando, guardamos la plática y respondemos
            self.current_flow["history"] += f"Usuario: {text}\nAsistente: {respuesta_ai}\n"
            
            return respuesta_ai





































































    def _get_customer_segment(self, customer_id: str):
        # Buscar varios nombres de campo comunes para el id del cliente
        for c in self.customers:
            # posibles claves que representan el id del cliente
            candidates = [c.get("id"), c.get("customer_id"), c.get("idCustomer"), c.get("customerId"), c.get("id_customer")]
            for v in candidates:
                if v is None:
                    continue
                try:
                    if str(v) == str(customer_id):
                        # posibles campos que indican segmento/ tipo
                        return (
                            c.get("segment")
                            or c.get("segmento")
                            or c.get("category")
                            or c.get("type")
                            or c.get("group")
                            or "unknown"
                        )
                except Exception:
                    continue
        return "unknown"

    def _should_auto_escalate_by_segment(self, customer_id: str) -> bool:
        seg = str(self._get_customer_segment(customer_id)).lower()
        # Segmentos que requieren escalamiento automático
        auto_segments = ["carrier class", "empresarial", "business", "enterprise"]
        return any(s in seg for s in auto_segments)

    def _create_escalation_payload(self, user_message: str, customer_id: str | None, summary: str, severity: str) -> dict:
        """Crear payload acorde al esquema observado en la sandbox.
        Campos por defecto: idCategory=9, idPriority=2, idAttentionType=2
        """
        # intentar convertir customer_id a entero
        cid = None
        if customer_id:
            try:
                cid = int(customer_id)
            except Exception:
                # intentar buscar por customer id en customers.json
                for c in self.customers:
                    if str(c.get("id", c.get("customer_id", ""))) == str(customer_id):
                        cid = int(c.get("id", c.get("customer_id")))
                        break

        # valores por defecto configurables (puedes ajustarlos en .env si deseas)
        default_category = int(os.getenv("DEFAULT_ID_CATEGORY", 9))
        default_priority = int(os.getenv("DEFAULT_ID_PRIORITY", 2))
        default_attention = int(os.getenv("DEFAULT_ID_ATTENTION", 2))

        payload = {
            "idCustomer": cid if cid is not None else 0,
            "description": summary or user_message[:500],
            "idCategory": default_category,
            "idPriority": default_priority,
            "idAttentionType": default_attention,
        }

        # Añadir campos opcionales si se pueden inferir
        if severity and severity.lower() == "high":
            payload["idPriority"] = max(1, default_priority)  # priorizar si se requiere

        # metadata adicional
        payload["source"] = "chatbot"
        payload["external_reference"] = f"chatbot-{int(datetime.utcnow().timestamp())}"

        return payload

    def _log_interaction(self, user_message: str, bot_response: str, extra: dict | None = None):
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "user": user_message,
            "bot": bot_response,
        }
        if extra:
            entry.update(extra)
        self.logger.info(json.dumps(entry, ensure_ascii=False))

    def _query_partner_kb(self, query: str) -> dict:
        """Realiza un GET a la API de conocimiento del socio.
        La URL base y la clave se leen desde las variables de entorno PARTNER_API_BASE y PARTNER_API_KEY.
        Se espera un endpoint /kb?query=...
        """
        if not self.partner_base:
            raise EnvironmentError("PARTNER_API_BASE no configurada en .env")

        url = f"{self.partner_base.rstrip('/')}/kb"
        params = {"query": query}
        headers = {}
        if self.partner_key:
            headers["Authorization"] = f"Bearer {self.partner_key}"

        resp = requests.get(url, params=params, headers=headers, auth=self.auth, timeout=10)
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}

        # Log the KB query and response
        self.logger.info(json.dumps({"type": "kb_query", "query": query, "status_code": resp.status_code, "response": data}, ensure_ascii=False))
        return {"status_code": resp.status_code, "data": data}

    def _post_escalation(self, payload: dict) -> dict:
        """Envía un POST al endpoint de tickets del socio para escalar el caso.
        Se espera un endpoint /tickets que acepte JSON.
        """
        if not self.partner_base:
            raise EnvironmentError("PARTNER_API_BASE no configurada en .env")

        # Validate payload to avoid predictable 400 responses from partner
        if not payload.get("idCustomer") or int(payload.get("idCustomer") or 0) == 0:
            # Log and raise a clear error for the caller to handle and inform the user
            try:
                self.logger.info(json.dumps({"type": "escalation_validation_failed", "reason": "idCustomer_missing_or_zero", "payload": payload}, ensure_ascii=False))
            except Exception:
                pass
            raise ValueError("Payload inválido: 'idCustomer' es requerido y debe ser distinto de 0")

        url = f"{self.partner_base.rstrip('/')}/tickets"
        headers = {"Content-Type": "application/json"}
        if self.partner_key:
            headers["Authorization"] = f"Bearer {self.partner_key}"

        resp = requests.post(url, headers=headers, json=payload, auth=self.auth, timeout=10)
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}

        # Log the escalation POST and response. If the API returns an error status
        # (4xx/5xx) log as error and raise a RuntimeError with the response body for
        # easier debugging from the caller.
        entry = {"type": "escalation_post", "url": url, "payload": payload, "status_code": resp.status_code, "response": data}
        if resp.status_code >= 400:
            self.logger.error(json.dumps(entry, ensure_ascii=False))
            raise RuntimeError(f"POST {url} returned {resp.status_code}: {data}")

        # Normal successful path
        self.logger.info(json.dumps(entry, ensure_ascii=False))
        return {"status_code": resp.status_code, "data": data}

    def _run_ollama(self, prompt: str, timeout: int = 60) -> str:
        """Run a local Ollama model via CLI and return the output or an error string.

        Use stdin to pass the prompt to be compatible with different ollama versions.
        """
        model = os.getenv("OLLAMA_MODEL")
        if not model:
            return "No OLLAMA_MODEL configurado"

        cmd = ["ollama", "run", model]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, shell=True)
            # TODO: Add loading indicator for long-running processes (optional, can be removed if not desired)
            if proc.returncode == 0:
                return proc.stdout.strip()
            err = proc.stderr.strip() or proc.stdout.strip()
            return f"Error de Ollama: {err}"
        except FileNotFoundError:
            return "CLI de Ollama no encontrada. Instala ollama o ajusta OLLAMA_MODEL."
        except Exception as e:
            return f"Error ejecutando Ollama: {e}"

    def _run_llm(self, prompt: str) -> str:
        """Run configured LLM. If OLLAMA_MODEL is set use Ollama, otherwise use fallback responder."""
        # Prefer local Ollama if configured
        if os.getenv("OLLAMA_MODEL"):
            return self._run_ollama(prompt)

        # If a chain exists (LangChain), use it
        if getattr(self, "chain", None):
            try:
                return self.chain.run(prompt)
            except Exception as e:
                self.logger.error(f"Error ejecutando chain LLM: {e}")
                # fallthrough to fallback responder

        # Fallback simple responder (useful para pruebas sin clave de OpenAI)
        low = prompt.lower()
        if any(g in low for g in ("hola", "buenas", "buenos")):
            return "Hola, soy un asistente de prueba. Describe tu problema de conectividad y te ayudaré con pasos básicos."
        keywords = ["no funciona", "no conecta", "corte", "sincronizar", "hardware"]
        if any(k in low for k in keywords):
            return (
                "Parece un problema de conectividad. Prueba: 1) Reinicia el módem y router; 2) Verifica cables; "
                "3) Comprueba estado de servicio con tu ISP. Si persiste, puedo escalar el caso."
            )
        # Default fallback: echo and ask for more details
        return "No tengo acceso a un modelo LLM aquí. Describe con más detalle el problema (p. ej. 'no conecta', 'corte de servicio')."

    def _should_escalate(self, user: str, bot_reply: str) -> tuple[bool, dict | None]:
        """Pregunta al LLM (vía ConversationChain) si debe escalarse a soporte de segundo nivel.\n
        Devuelve (bool, escalation_json). Se solicita explícitamente un JSON limpio en caso afirmativo.
        """
        prompt = (
            "Eres un analista que decide si un caso debe escalarse a soporte de segundo nivel.\n"
            f"Mensaje del cliente: {user}\n"
            f"Respuesta provisional del asistente: {bot_reply}\n"
            "Contesta primero SI o NO. Si respondes SI, después incluye un JSON con los campos: reason, severity (low|medium|high), customer_summary, recommended_action. SOLO incluye el JSON y nada más aparte de la palabra SI.\n"
            "Ejemplo de salida si debe escalar:\n"
            "SI\n"
            '{"reason": "No respuesta de sincronización", "severity": "high", "customer_summary": "El equipo no logra sincronizar desde hace 24h", "recommended_action": "Escalar a ingeniero de campo"}\n'
        )

        decision_text = self._run_llm(prompt)
        self.logger.info(json.dumps({"type": "escalation_decision", "decision_text": decision_text}, ensure_ascii=False))

        # Buscar JSON en la salida
        start = decision_text.find("{")
        end = decision_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                json_text = decision_text[start:end+1]
                parsed = json.loads(json_text)
                # Considerar que si la primera parte contiene 'SI' o 'SÍ' se escalará
                should = decision_text[:start].strip().upper().startswith(("SI", "SÍ"))
                return should, (parsed if should else None)
            except json.JSONDecodeError:
                return False, None

        # Heurística alternativa: si la respuesta contiene palabras clave de escalación
        lower = (user + " " + bot_reply).lower()
        keywords = ["no funciona", "corte", "no conecta", "hardware", "fallo persistente", "reinicio"]
        if any(k in lower for k in keywords):
            # construir un JSON mínimo
            esc = {
                "reason": "Problema técnico detectado por heurística",
                "severity": "medium",
                "customer_summary": user[:500],
                "recommended_action": "Revisión por ingeniero de soporte"
            }
            return True, esc

        return False, None

    def _get_partner_resource(self, path: str) -> dict:
        """GET a resource under the partner base (path without leading slash)."""
        if not self.partner_base:
            raise EnvironmentError("PARTNER_API_BASE no configurada en .env")
        url = f"{self.partner_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {}
        if self.partner_key:
            headers["Authorization"] = f"Bearer {self.partner_key}"
        try:
            resp = requests.get(url, headers=headers, auth=self.auth, timeout=10)
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text}
            self.logger.info(json.dumps({"type": "partner_get", "url": url, "status_code": resp.status_code, "response": data}, ensure_ascii=False))
            return {"status_code": resp.status_code, "data": data}
        except Exception as e:
            self.logger.error(json.dumps({"type": "partner_get_error", "url": url, "error": str(e)}, ensure_ascii=False))
            raise

    def _find_customer_by_id(self, customer_id: str):
        """Busca un registro de customer por varias claves comunes y devuelve el dict completo o None."""
        if not self.customers:
            return None
        for c in self.customers:
            for key in ("idCustomer", "id", "customer_id", "customerId", "id_customer"):
                v = c.get(key)
                if v is None:
                    continue
                try:
                    if str(v) == str(customer_id):
                        return c
                except Exception:
                    continue
        return None
    
    # Helper corto: detectar que el usuario indica que no puede o quiere ayuda
    def _user_needs_assistance(txt: str) -> bool:
        low = (txt or "").lower()
        triggers = [
            "no puedo", "no sé", "no se", "no tengo", "no puedo hacerlo", "no entiendo",
            "necesito ayuda", "me ayudas", "ayuda", "no tengo acceso", "no tengo permisos",
            "no quiero", "no puedo seguir"
        ]
        return any(t in low for t in triggers)

    def ask(self, message: str) -> str:
        """Send a message to the chatbot and return the response. También decide si escalar y hace POST si es necesario."""
        text = message.strip()
        low_text = message.lower()

        # 1. Primero revisamos si el usuario YA estaba a la mitad de un flujo
        # (Es decir, si el bot ya le había pedido el ticket antes)
        if self.current_flow is not None:
            return self._handle_menu_flows(message)

        # 2. AQUÍ ESTÁ EL DISPARADOR DEL BOTÓN
        # Si el usuario picó el botón en la web o escribió "1" en la terminal
        if low_text in ["1", "opción 1", "reportar falla", "reportar", "tengo un problema con mi internet"]:
            # Inicializamos el estado para reportar falla, indicando el primer paso
            # y creando un diccionario vacío "payload" para guardar los datos.
            self.current_flow = {
                "action": "report_issue",
                "step": "get_customer_id",
                "payload": {}
            }
            return "Has elegido Reportar Falla.\n\nPara empezar, por favor ingresa tu **ID de Cliente**:"

        # 2. INTERCEPTAR BOTONES O PALABRAS CLAVE DEL MENÚ
        if low_text in ["2", "gestión de cuenta", "opción 2", "consultar plan", "quiero consultar mi plan actual"]:
            self.current_flow = {"action": "check_plan"}
            return "Has elegido Consultar Plan y Saldo.\n\nPor favor, ingresa tu **ID de Cliente**:"

        if low_text in ["3", "opción 3", "soporte", "auto diagnostico", "diagnóstico"]:
            self.current_flow = {
                "action": "auto_diagnostic",
                "step": "ask_problem",
                "history": "" # Aquí guardaremos la memoria de la plática
            }
            return "Has elegido Auto-Diagnóstico / Soporte Técnico.\n\nPor favor, **descríbeme con detalle cuál es el problema** que tienes con tu servicio:"

       # Responder 'menu' localmente (no consultar KB)
        if text.lower() in ("menu", "help", "inicio"):
            return (
                "¿Qué necesitas?\n"
                "1) Estado de ticket — 'ticket <id>'\n"
                "2) Diagnóstico rápido — 'diagnosticar <descripción>'\n"
                "3) consultar plan — 'cuenta <id_cliente>'\n"
                "4) Pedir asistencia remota — 'asistencia <id_cliente>'\n\n"
                "Responde con el número o el comando. Escribe 'más' para detalles."
            )

        # --- Progresión y descomposición: manejo de flujos paso-a-paso ---
        # Si estamos en un flujo y el usuario escribe algo que indica imposibilidad, ofrecer asistencia
        if getattr(self, 'pending_action', None) and self.pending_action.get('action') == 'step_flow':
            # si el usuario indica que no puede seguir, ofrecer asistencia técnica
            if _user_needs_assistance(text):
                return "Entiendo. Si prefieres que un técnico lo revise, responde 'asistencia' y yo prepararé la solicitud de ayuda remota. Si quieres intentar continuar escribe 'siguiente'."

        # Avanzar en un flujo activo (ej. 'siguiente', 'mas', 'más')
        if text.lower() in ("siguiente", "next", "mas", "más"):
            if self.pending_action and self.pending_action.get("action") == "step_flow":
                steps = self.pending_action["steps"]
                current_stage = int(self.pending_action.get("stage", 0))
                # Si hay un siguiente paso
                if current_stage + 1 < len(steps):
                    self.pending_action["stage"] = current_stage + 1
                    next_idx = self.pending_action["stage"]
                    return f"Paso {next_idx+1}/{len(steps)}: {steps[next_idx]}\n\nResponde 'siguiente' para continuar o 'todos' para ver la lista completa."
                else:
                    # No hay más pasos
                    # Si el flujo indicaba severidad alta, sugerir asistencia proactiva
                    sev = self.pending_action.get('severity')
                    self.pending_action = None
                    if sev == 'high':
                        return f"Has completado los {len(steps)} pasos. Dado que este caso parece técnico, ¿quieres solicitar asistencia remota ahora? Responde 'asistencia' para solicitar ayuda o 'no' para finalizar."
                    return f"Has completado los {len(steps)} paso(s). ¿Necesitas que prepare un informe para pedir asistencia remota? Responde 'sí' o 'no'."
            else:
                return "No hay un flujo activo. Escribe 'diagnosticar <descripción>' para iniciar un diagnóstico rápido."

        # Eliminar la opción de 'mostrar comandos' para mantener el lenguaje centrado en el cliente
        # (antes se ofrecían comandos técnicos; ahora no se muestran al cliente final)

        # Iniciar diagnóstico: 'diagnosticar <descripción>' o detectar palabras clave como 'intermitencia'
        low = text.lower()
        if low.startswith("diagnosticar") or any(k in low for k in ("intermiten", "intermitencia", "no conecta", "corte", "no funciona")):
            # extraer descripción (si la hubo)
            desc = text[len("diagnosticar"):].strip() if low.startswith("diagnosticar") else text
            df = self._diagnostic_flow(desc)
            steps = df.get("steps", ["Proporciona más detalles: ¿corte, lentitud, intermitencia, hardware?"])
            severity = df.get("severity")
            # Guardar estado para la progresión (sin comandos técnicos)
            self.pending_action = {"action": "step_flow", "steps": steps, "stage": 0, "severity": severity}

            # Si la severidad indica caso técnico, sugerir asistencia desde el inicio
            if severity == 'high':
                return (
                    "Detecto un problema que parece técnico y de alta prioridad. ¿Quieres que solicite asistencia remota de inmediato?\n"
                    "Responde 'asistencia' para que prepare la solicitud o 'siguiente' si prefieres intentar los pasos tú mismo."
                )

            # Preparar la respuesta inicial dependiendo del primer paso
            first = steps[0].strip()
            # Si el primer paso es una pregunta, pedir solo la información y esperar la respuesta
            if first.endswith("?") or first.lower().startswith("proporciona") or "¿" in first:
                return (
                    "Detecto un posible problema. Antes de continuar necesito más información:\n"
                    f"{first}\n\n"
                    "Por favor responde con los detalles solicitados. Si prefieres que lo revise un técnico, responde 'asistencia'."
                )

            # Si hay múltiples pasos, mostrar el primero y ofrecer avanzar
            if len(steps) > 1:
                return (
                    f"Detecto un posible problema. Te propongo {len(steps)} pasos rápidos.\n\n"
                    f"Paso 1/{len(steps)}: {first}\n\n"
                    "Responde 'siguiente' para continuar, 'todos' para verlos todos o 'asistencia' para solicitar ayuda técnica."
                )

            # Si solo hay un paso que no es pregunta, mostrar y ofrecer acciones
            return (
                f"Detecto un posible problema.\n\n{first}\n\n"
                "Si prefieres, puedo preparar un resumen para que tu técnico lo revise. Responde 'asistencia'."
            )

        # Short menu choices: show automated options for 1..4
        if text in ("1", "2", "3", "4"):
            if text == "1":
                return (
                    "Opción 1 — Estado de mi Ticket:\n"
                    "- ver <id>: Ver estado del ticket (ej.: 'ver 1234' o usa 'ticket 1234').\n"
                    "- ejemplo: 'ticket 1234'\n"
                    "(Todas las acciones son automáticas: consulta de estado y sugerencias, sin intervención humana.)"
                )
            if text == "2":
                # iniciar flujo interactivo de diagnóstico
                self.pending_action = {"action": "diagnostic_quick", "stage": 1}
                return (
                    "Opción 2 — Reportar Falla / Diagnóstico:\n"
                    "¿Qué te gustaría probar primero?\n"
                    "a) Reiniciar módem/router\n"
                    "b) Verificar cables y conexiones\n"
                    "c) Ejecutar speedtest\n"
                    "(Responde 'a', 'b', 'c' o escribe 'diagnosticar <descripción>' para un diagnóstico completo)"
                )
            if text == "3":
                return (
                    "Opción 3 — Información de Cuenta:\n"
                    "- cuenta <id_cliente>: Muestra segmento e información de la cuenta y acciones disponibles.\n"
                     "- ejemplo: 'cuenta 123456'\n"
                     "(Automatizado: consulta de datos y recomendaciones sin contactar a soporte.)"
                )
            if text == "4":
                return (
                    "Opción 4 — Soluciones Técnicas Automatizadas:\n"
                    "- reiniciar equipo local: sigue los pasos que se te indiquen.\n"
                    "- pruebas remotas: si el partner API lo soporta, el bot intentará solicitar pruebas (comandos dependientes del proveedor).\n"
                    "- ejemplo: solicita 'reportar' o 'diagnosticar' para empezar.\n"
                    "(Automatizado: acciones sugeridas y comandos para ejecutar pruebas, sin intervención humana.)"
                )

        # Shortcut: deterministic short greeting (avoid invoking Ollama for simple salutations)
        low_text = text.lower()
        greeting_tokens = ("hola", "buenas", "buenos", "buenos días", "buenas tardes", "buenas noches", "hi", "hello")
        if low_text in greeting_tokens or any(low_text.startswith(t + " ") for t in greeting_tokens):
            return (
                "Que te gustaria hacer o revisar:\n"
                "1) Estado de mi Ticket — consulta automática por id (usa 'ticket <id>').\n"
                "2) Reportar Falla / Diagnóstico — diagnóstico automático y pasos (usa 'diagnosticar <descripción>').\n"
                "3) Información de cuenta — ver segmento y acciones (usa 'cuenta <id_cliente>').\n"
                "4) Pedir asistencia remota — solicita ayuda técnica (usa 'asistencia' o 'escalar').\n\n"
                "Elige una opción escribiendo el número o dando click en los botones de abajo."
            )

        # Detectar palabras clave de intermitencia y devolver un flujo de diagnóstico accionable
        if any(k in low_text for k in ("intermit", "intermitencia", "intermitente", "intermitir", "intermitencias")):
            diag_lines = [
                "Detecto intermitencia: propongo 4 pasos rápidos.",
                "1) Reproducir y anotar cuándo ocurre (hora y acción).",
                "2) Revisar si hay errores registrados en el sistema (si tengo acceso). Responde 'sí' para intentar o 'asistencia' para ayuda técnica.",
                "3) Comprobar conectividad: probar desde un equipo afectado y desde el servidor.",
                "4) Ver recursos del servidor: comprobar CPU, memoria y disco. Responde 'asistencia' si quieres un informe para el técnico.",
                "Si quieres, responde 'siguiente' para guiarte paso a paso, 'todos' para ver la lista completa, o 'asistencia' para solicitar ayuda técnica con un resumen."
            ]
            return "\n".join(diag_lines)

        # Si no coincide con comandos, proceder con la lógica previa: consultar KB remoto y LLM/fallback
        # Evitar consultar KB y LLM para comandos cortos o navegación: devolver una respuesta clara en lugar de llamar al LLM
        cmd = message.strip()
        short_cmds = {"menu", "help", "inicio", "1", "2", "3", "4", "a", "b", "c", "siguiente", "todos", "mas", "más"}
        # Only treat very short inputs (2 chars or less) as navigation/short commands.
        # This allows 3-digit bare numbers like '250' to be handled as ticket ids.
        if cmd in short_cmds or len(cmd) <= 2:
            # Si es un número corto, guiar al usuario a usar el formato correcto para tickets
            if cmd.isdigit():
                return "Parece un número corto. Para consultar un ticket usa 'ticket <id>' con al menos 3 dígitos o escribe 'menu' para ver opciones."
            # Mensaje genérico pidiendo más contexto
            return "No entendí completamente. ¿Puedes dar más detalles o escribir 'menu' para ver las opciones?"

        try:
            kb = self._query_partner_kb(message)
        except Exception as e:
            kb = {"status_code": None, "data": {"error": str(e)}}

        kb_text = ""
        if kb.get("data"):
            kb_text = json.dumps(kb["data"], ensure_ascii=False)

        combined_prompt = (
            f"Usuario: {message}\n\nInformación de la base de conocimiento (si aplica): {kb_text}\n\nResponde de forma clara y en español, proponiendo pasos de diagnóstico sencillos y no realizando acciones automáticas."
        )

        try:
            reply = getattr(self, "_run_llm", lambda p: "Sin motor LLM disponible")(combined_prompt)
        except Exception as e:
            reply = f"Error al generar respuesta: {e}"

        # Registrar interacción
        self._log_interaction(message, reply, extra={"kb_status": kb.get("status_code")})

        # Basado en cliente si se indica, decidir escalación automática
        # Buscamos un customer id en el mensaje (heurística simple)
        customer_id = None
        for token in text.split():
            if token.isdigit() and len(token) >= 4:
                customer_id = token
                break

        try:
            escalate, payload = self._should_escalate(message, reply)
        except Exception as e:
            self.logger.error(f"Error al decidir escalación: {e}")
            escalate, payload = False, None

        # Auto-escalation by segment
        if customer_id and self._should_auto_escalate_by_segment(customer_id):
            payload = self._create_escalation_payload(message, customer_id, "Escalamiento automático por segmento", "high")
            try:
                post_result = self._post_escalation(payload)
                status = post_result.get("status_code")
                self._log_interaction(message, reply, extra={"escalation_status": status, "escalation_response": post_result.get("data")})
                return f"{reply}\n\nSe ha escalado automáticamente tu caso. Un ingeniero te contactará. (Código HTTP: {status})"
            except Exception as e:
                self.logger.error(f"Error al enviar escalación automática: {e}")
                return f"{reply}\n\nIntenté escalar el caso automáticamente pero ocurrió un error: {e}"

        if escalate and payload:
            metadata = {"initiated_by": "chatbot", "user_message": message}
            payload.update(metadata)
            try:
                post_result = self._post_escalation(payload)
                status = post_result.get("status_code")
                self._log_interaction(message, reply, extra={"escalation_status": status, "escalation_response": post_result.get("data")})
                notify = (
                    "He escalado tu caso a un ingeniero de soporte técnico. "
                    "Se ha creado un ticket y un especialista te contactará pronto."
                )
                return f"{reply}\n\n{notify} (Código HTTP: {status})"
            except Exception as e:
                self.logger.error(f"Error al enviar escalación: {e}")
                return f"{reply}\n\nIntenté escalar el caso pero ocurrió un error: {e}"

        return reply
