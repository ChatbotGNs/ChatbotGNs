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

    def _find_ticket(self, ticket_id: str):
        for t in self.tickets:
            # buscar por id o por clave 'ticket_id'
            if str(t.get("id", t.get("ticket_id", ""))) == str(ticket_id):
                return t
        return None

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
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
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

    def ask(self, message: str) -> str:
        """Send a message to the chatbot and return the response. También decide si escalar y hace POST si es necesario."""
        text = message.strip()

        # Helper corto: detectar que el usuario indica que no puede o quiere ayuda
        def _user_needs_assistance(txt: str) -> bool:
            low = (txt or "").lower()
            triggers = [
                "no puedo", "no sé", "no se", "no tengo", "no puedo hacerlo", "no entiendo",
                "necesito ayuda", "me ayudas", "ayuda", "no tengo acceso", "no tengo permisos",
                "no quiero", "no puedo seguir"
            ]
            return any(t in low for t in triggers)

        # Responder 'menu' localmente (no consultar KB)
        if text.lower() in ("menu", "help", "inicio"):
            return (
                "Hola — ¿qué necesitas?\n"
                "1) Estado de ticket — 'ticket <id>'\n"
                "2) Diagnóstico rápido — 'diagnosticar <descripción>'\n"
                "3) Información de cuenta — 'cuenta <id_cliente>'\n"
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
                "Hola, soy ChatGNS, estoy para ayudarte! Elige una opción:\n"
                "1) Estado de mi Ticket — consulta automática por id (usa 'ticket <id>').\n"
                "2) Reportar Falla / Diagnóstico — diagnóstico automático y pasos (usa 'diagnosticar <descripción>').\n"
                "3) Información de cuenta — ver segmento y acciones (usa 'cuenta <id_cliente>').\n"
                "4) Pedir asistencia remota — solicita ayuda técnica (usa 'asistencia' o 'escalar')."
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
