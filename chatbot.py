import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import json
import logging
from datetime import datetime
import subprocess

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

    def __init__(self, temperature: float = 0.2, model: str = "gpt-3.5-turbo"):
        load_dotenv()
        # We force fallback mode so the code runs without langchain/OpenAI.
        # If you later want to enable a real LLM, set OPENAI_API_KEY in .env
        # and implement dynamic imports/initialization.
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
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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

    def _load_local_data(self):
        def _load(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []

        self.tickets = _load(self.tickets_path)
        self.customers = _load(self.customers_path)
        self.comments = _load(self.comments_path)
        self.categories = _load(self.categories_path)
        self.logger.info(json.dumps({"type": "local_data_load", "tickets": len(self.tickets), "customers": len(self.customers), "comments": len(self.comments), "categories": len(self.categories)}))

    def _find_ticket(self, ticket_id: str):
        for t in self.tickets:
            # buscar por id o por clave 'ticket_id'
            if str(t.get("id", t.get("ticket_id", ""))) == str(ticket_id):
                return t
        return None

    def _get_customer_segment(self, customer_id: str):
        for c in self.customers:
            if str(c.get("id", c.get("customer_id", ""))) == str(customer_id):
                # posibles campos: segment, category, type
                return c.get("segment") or c.get("category") or c.get("type") or "unknown"
        return "unknown"

    def _diagnostic_flow(self, message: str) -> dict:
        """Flujo de diagnóstico simplificado que devuelve un dict con steps y severity."""
        low = message.lower()
        steps = []
        severity = "low"

        if any(k in low for k in ["no conecta", "no funciona", "corte", "sin servicio"]):
            steps = [
                "1) Reinicia el módem y el router (espera 30s).",
                "2) Verifica que los cables estén conectados correctamente.",
                "3) Consulta el estado del servicio en tu área.",
            ]
            severity = "high" if "corte" in low or "no funciona" in low else "medium"
        elif any(k in low for k in ["lentitud", "baja velocidad", "lag", "latencia"]):
            steps = [
                "1) Ejecuta un speedtest desde un equipo conectado por cable.",
                "2) Reinicia los equipos de red si hay muchos dispositivos conectados.",
                "3) Reduce dispositivos activos y vuelve a medir.",
            ]
            severity = "medium"
        else:
            steps = ["Proporciona más detalles: ¿corte, lentitud, intermitencia, hardware?"]
            severity = "low"

        return {"steps": steps, "severity": severity}

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
            return "No OLLAMA_MODEL configured"

        cmd = ["ollama", "run", model]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
            if proc.returncode == 0:
                return proc.stdout.strip()
            err = proc.stderr.strip() or proc.stdout.strip()
            return f"Ollama error: {err}"
        except FileNotFoundError:
            return "Ollama CLI no encontrada. Instala ollama o ajusta OLLAMA_MODEL."
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

    def ask(self, message: str) -> str:
        """Send a message to the chatbot and return the response. También decide si escalar y hace POST si es necesario."""
        text = message.strip()

        # Manejo de menú simple
        if text.lower() in ("menu", "help", "inicio"):
            menu = (
                "Menú principal:\n"
                "1. Consultar Estado de mi Ticket (envía: ticket <id>)\n"
                "2. Reportar Falla / Diagnóstico IA (envía: reportar <descripción>)\n"
                "3. Gestión de Cuenta (envía: cuenta <id_cliente>)\n"
                "4. Hablar con un Técnico (envía: escalar <id_cliente> o escalar ahora)\n"
            )
            return menu

        # Short menu choices: show automated options for 1..5
        if text in ("1", "2", "3", "4", "5"):
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
                    "Opción 3 — Gestión de Cuenta:\n"
                    "- cuenta <id_cliente>: Muestra segmento y acciones disponibles.\n"
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
            # opción 5: ayuda directa (humana)
            return (
                "Opción 5 — Ayuda directa:\n"
                "- Si quieres hablar con un técnico real, envía 'escalar <id_cliente>' o 'escalar ahora'.\n"
                "- Esto solicitará la creación de un ticket y la intervención humana."
            )

        # Manejo de respuestas rápidas para flujos interactivos
        if getattr(self, 'pending_action', None):
            pa = self.pending_action
            # diagnóstico rápido: opciones a/b/c
            if pa.get('action') == 'diagnostic_quick' and pa.get('stage') == 1:
                choice = text.lower()
                if choice in ('a', 'b', 'c'):
                    self.pending_action = None
                    if choice == 'a':
                        return "Has elegido reiniciar módem/router. Pasos: 1) Apaga el módem, espera 30s, enciende. 2) Verifica sincronía. Si persiste, escribe 'diagnosticar <descripción>'."
                    if choice == 'b':
                        return "Has elegido verificar cables. Pasos: 1) Confirma cables firmes en módem/router. 2) Cambia cable por otro si es posible. Si sigue fallando, escribe 'diagnosticar <descripción>'."
                    if choice == 'c':
                        return "Has elegido ejecutar speedtest. Ejecuta https://www.speedtest.net/ y comparte resultados (ping/download/upload). Si no sabes, escribe 'diagnosticar <descripción>'."
                else:
                    # si el usuario escribió otra cosa, cancelar el pending y continuar
                    self.pending_action = None
                    # fallthrough para manejar el mensaje como comando normal
                    pass

        # Short alias / numeric input: allow 'ver <id>' or bare numeric id as synonym for 'ticket <id>'
        def _format_ticket_from_dict(tid, data):
            # Campos comunes esperados en la respuesta del partner
            tn = data.get("ticket_number") or data.get("idTicket") or data.get("id")
            status_text = data.get("status") or data.get("status_text") or "Desconocido"
            summary = (data.get("description") or data.get("summary") or "").strip()

            # Cliente
            customer = ""
            if data.get("customer_name") or data.get("customer_lastname"):
                customer = f"{(data.get('customer_name') or '').strip()} {(data.get('customer_lastname') or '').strip()}".strip()
            elif data.get("customer") and isinstance(data.get("customer"), dict):
                customer = (data.get("customer", {}).get("name") or "").strip()

            # Prioridad, categoría, paquete y atención
            priority = data.get("priority") or (str(data.get("idPriority")) if data.get("idPriority") is not None else None) or "—"
            category = data.get("category") or (str(data.get("idCategory")) if data.get("idCategory") is not None else None) or "—"
            package = data.get("package") or (data.get("idPackage") and str(data.get("idPackage"))) or "—"
            attention = data.get("attention") or (str(data.get("idAttentionType")) if data.get("idAttentionType") is not None else None) or "—"

            # Empleado asignado y contacto
            employee = ""
            if data.get("employee_name") or data.get("employee_lastname"):
                employee = f"{(data.get('employee_name') or '').strip()} {(data.get('employee_lastname') or '').strip()}".strip()
            employee_email = data.get("employee_email") or data.get("employee_contact") or ""
            employee_phone = data.get("employee_phone_number") or data.get("employee_phone") or ""

            # Fechas
            date_open = data.get("date_opening") or data.get("date") or data.get("date_created") or None
            date_close = data.get("date_closing") or data.get("closed_at") or None

            # Construir lenguaje natural
            lines = []
            header = f"Ticket {tid} ({tn}) — estado: {status_text}."
            lines.append(header)

            if customer:
                lines.append(f"Cliente: {customer}.")
            if priority and priority != "—":
                lines.append(f"Prioridad: {priority}.")
            if category and category != "—":
                lines.append(f"Categoría: {category}.")
            if package and package != "—":
                lines.append(f"Paquete: {package}.")
            if attention and attention != "—":
                lines.append(f"Tipo de atención: {attention}.")

            if employee:
                contact = []
                if employee_email:
                    contact.append(employee_email)
                if employee_phone:
                    contact.append(str(employee_phone))
                if contact:
                    lines.append(f"Asignado a: {employee} ({', '.join(contact)}).")
                else:
                    lines.append(f"Asignado a: {employee}.")

            if date_open:
                lines.append(f"Apertura: {date_open}.")
            if date_close:
                lines.append(f"Cierre: {date_close}.")

            if summary:
                short = summary if len(summary) <= 300 else summary[:297] + "..."
                lines.append(f"Resumen: {short}.")

            # Sugerencias y comandos útiles
            lines.append("Puedes escribir 'mostrar json %s' para ver el JSON completo del ticket." % tid)
            lines.append("Escribe 'menu' para volver al menú principal.")

            return " \n".join(lines)

        is_ver = text.lower().startswith("ver ")
        is_ticket = text.lower().startswith("ticket ")
        is_numeric = text.isdigit() and len(text) >= 3

        if is_ver or is_ticket or is_numeric:
            if is_ver or is_ticket:
                tid = text.split(maxsplit=1)[1]
            else:
                tid = text

            # Try local data first
            t = self._find_ticket(tid)
            if t:
                return _format_ticket_from_dict(tid, t)

            # Try direct resource /tickets/{id}
            try:
                res = self._get_partner_resource(f"tickets/{tid}")
                status = res.get("status_code")
                data = res.get("data")

                # helper to normalize nested container responses
                def _extract_candidate(obj):
                    # If the API returns {"data": {...}} or {"data": [...]}
                    if isinstance(obj, dict):
                        if "data" in obj:
                            return obj["data"]
                        if "items" in obj and isinstance(obj["items"], list):
                            return obj["items"]
                    return obj

                data = _extract_candidate(data)

                if status == 200 and data:
                    # If we received a dict representing the ticket
                    if isinstance(data, dict):
                        return _format_ticket_from_dict(tid, data)
                    # If we received a list, pick the first match or search it
                    if isinstance(data, list) and data:
                        # try to find exact match in list
                        for item in data:
                            if str(item.get("idTicket") or item.get("id") or item.get("ticket_number")) == str(tid):
                                return _format_ticket_from_dict(tid, item)
                        return _format_ticket_from_dict(tid, data[0])

                # If API returned 204 No Content or empty body, try listing and query variations
                tried = []
                if status in (204, 200) and (not data or (isinstance(data, list) and len(data) == 0)):
                    variants = [
                        f"tickets/{tid}/",
                        f"tickets?idTicket={tid}",
                        f"tickets?ticket_number={tid}",
                        f"tickets?search={tid}",
                        "tickets/",
                    ]
                    for path in variants:
                        try:
                            tried.append(path)
                            list_res = self._get_partner_resource(path)
                            list_status = list_res.get("status_code")
                            list_data = _extract_candidate(list_res.get("data"))

                            if list_status == 200 and list_data:
                                # normalize to list if dict contains list
                                if isinstance(list_data, dict):
                                    # try common containers
                                    if isinstance(list_data.get("data"), list):
                                        list_data = list_data.get("data")
                                    elif isinstance(list_data.get("items"), list):
                                        list_data = list_data.get("items")

                                if isinstance(list_data, list):
                                    for item in list_data:
                                        if str(item.get("idTicket") or item.get("id") or item.get("ticket_number")) == str(tid):
                                            return _format_ticket_from_dict(tid, item)
                                        if item.get("ticket_number") and str(tid) in str(item.get("ticket_number")):
                                            return _format_ticket_from_dict(tid, item)
                                elif isinstance(list_data, dict):
                                    # maybe the dict itself is the ticket
                                    if str(list_data.get("idTicket") or list_data.get("id") or list_data.get("ticket_number")) == str(tid):
                                        return _format_ticket_from_dict(tid, list_data)
                        except Exception:
                            continue

                # Nothing found after trying variants
                self.logger.info(json.dumps({"type": "ticket_lookup_tried", "tid": tid, "tried": tried, "last_status": status}, ensure_ascii=False))
                return f"No encontré ticket con id {tid} (API status {status})"

            except Exception as e:
                return f"Error consultando ticket remoto: {e}"

        # Reportar / Diagnóstico
        if text.lower().startswith("reportar ") or text.lower().startswith("diagnosticar "):
            desc = text.split(maxsplit=1)[1]
            diag = self._diagnostic_flow(desc)
            steps_text = "\n".join(diag["steps"])
            # No customer id provided here; user can follow steps or pedir escalación
            return f"Diagnóstico sugerido (severity={diag['severity']}):\n{steps_text}\nSi quieres escalar, envía 'escalar <id_cliente>'"

        # Gestión de cuenta (stub)
        if text.lower().startswith("cuenta "):
            cid = text.split(maxsplit=1)[1]
            seg = self._get_customer_segment(cid)
            return f"Cliente {cid}: segmento={seg} (datos extra disponibles en customers.json)"

        # Escalar explícito
        if text.lower().startswith("escalar ") or text.lower() == "escalar ahora":
            parts = text.split()
            cid = parts[1] if len(parts) > 1 else None
            summary = "Solicitud de escalamiento solicitada por el cliente"
            severity = "high"
            payload = self._create_escalation_payload(text, cid, summary, severity)
            try:
                res = self._post_escalation(payload)
                return f"Escalación enviada. Código HTTP: {res.get('status_code')}"
            except Exception as e:
                return f"Error al enviar escalación: {e}"

        # Shortcut: deterministic short greeting (avoid invoking Ollama for simple salutations)
        low_text = text.lower()
        greeting_tokens = ("hola", "buenas", "buenos", "buenos días", "buenas tardes", "buenas noches", "hi", "hello")
        if low_text in greeting_tokens or any(low_text.startswith(t + " ") for t in greeting_tokens):
            return (
                "Hola, soy ChatGNS, estoy para ayudarte! Elige una opción:\n"
                "1) Estado de mi Ticket — consulta automática por id (usa 'ticket <id>').\n"
                "2) Reportar Falla / Diagnóstico — diagnóstico automático y pasos (usa 'diagnosticar <descripción>').\n"
                "3) Gestión de Cuenta — ver segmento y acciones (usa 'cuenta <id_cliente>').\n"
                "4) Soluciones Técnicas Automatizadas — pruebas y pasos guiados (usa 'reportar' o 'diagnosticar').\n"
                "5) Ayuda directa — hablar con un técnico (envía 'escalar <id_cliente>' o 'escalar ahora')."
            )

        # Si no coincide con comandos, proceder con la lógica previa: consultar KB remoto y LLM/fallback
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
            # usar _run_llm si existe, sino fallback
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
