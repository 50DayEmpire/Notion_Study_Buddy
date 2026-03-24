import asyncio
import httpx
from mcp import ClientSession
import os
import traceback
from dotenv import load_dotenv
from mcp.client.streamable_http import streamable_http_client
from auth_service import authFlow, refresh_access_token
from auth_utils import load_client_config
import json
from google import genai
import logging
from dataclasses import dataclass, asdict

@dataclass
class messageDto:
    role: str
    content: str

@dataclass
class peticionDto:
    model: str
    messages: list[messageDto]
    stream: bool = False
    max_tokens: int = 2048


logging.basicConfig(filename="mcp_client.log", filemode='w', format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)

class NotionStreamableClient:
    MAX_TOOL_CALLS_PER_TURN = 6

    def __init__(self, access_token: str, serverUrl: str, useSSE: bool = False):
        self.access_token = access_token
        self.serverUrl = serverUrl
        self.useSSE = useSSE
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "Notion AI Study Buddy/1.0",
            "Accept": "application/json, text/event-stream"  
        }
        self.endpoint = "https://api.vultrinference.com/v1/chat/completions"
        self.model = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"

    @staticmethod
    def _extract_json_payload(raw_text: str) -> dict | None:
        cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()

        # Primer intento: parseo directo
        try:
            parsed = json.loads(cleaned_text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        # Segundo intento: buscar el primer { y probar cierres progresivos
        start = cleaned_text.find("{")
        if start == -1:
            return None

        for end in range(len(cleaned_text), start, -1):
            try:
                parsed = json.loads(cleaned_text[start:end])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        return None

    # @staticmethod
    # def _build_tool_specs(mcp_tools) -> list[dict]:
    #     tool_specs = []
    #     logging.debug(f"Construyendo especificaciones de herramientas para: {[getattr(tool, 'name', None) for tool in mcp_tools]}")
    #     for tool in mcp_tools:
    #         tool_specs.append(
    #             {
    #                 "name": getattr(tool, "name", None),
    #                 "description": getattr(tool, "description", ""),
    #                 "inputSchema": getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None),
    #             }
    #         )
    #     logging.debug(f"Especificaciones de herramientas construidas: {tool_specs}")
    #     return tool_specs

    @staticmethod
    def _build_tool_specs(mcp_tools) -> list[dict]:
        tool_specs = []
        logging.debug(f"Construyendo especificaciones de herramientas para: {[getattr(tool, 'name', None) for tool in mcp_tools]}")
        for tool in mcp_tools:
            tool_specs.append(
                {
                    "name": getattr(tool, "name", None),
                    "title": getattr(tool, "title", None),
                    "description": getattr(tool, "description", ""),
                    "inputSchema": getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
                }
            )
        logging.debug(f"Especificaciones de herramientas construidas: {tool_specs}")
        return tool_specs

    async def connect_streamable(self):
        """
        Conecta al servidor de Notion usando el patrón de Streams (anyio).
        """
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(30.0, read=None)
        ) as http_client:
            # Usa el context manager oficial del SDK para obtener read/write streams.
            async with streamable_http_client(self.serverUrl, http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    logging.debug(f"Respuesta de list_tools: {response}")
                    print(f"✅ ¡Conexión Exitosa con Streams!")
                    tools = response.tools
                    
                    # 2. Bucle de interacción con el usuario
                    while True:
                        query = input("\nInteractúa con tu Study Buddy (o 'salir'): ")
                        if query.lower() in ['salir', 'exit', 'quit']: break

                        await self.process_query(session, tools, query)
                        logging.debug(f"Finalización de turno de interacción con el usuario. Mensajes acumulados:{self.mensajes}")

    async def process_query(self, session, mcp_tools, user_input):
        """
        Orquesta la comunicación entre Gemini y las herramientas de Notion.
        """
        tool_calls_used = 0
        tool_history = []
        tool_specs = self._build_tool_specs(mcp_tools)
        tool_specs_json = json.dumps(tool_specs, ensure_ascii=False)

        system_prompt = f"""
        Eres un Notion AI Study Buddy con acceso a herramientas MCP.
        Cuando el usuario te solicite algo relacionado con notion haz un plan con las herramientas necesarias para cumplir su solicitud.
        Si recibes un resultado de error de una herramienta revisa el inputSchema y la descripcion de esa herramienta para corregir tu llamado en el próximo intento.
        Si recibes un error de herramienta no encontrada revisa el nombre correcto en tool_specs y corrige tu llamado en el próximo intento.
        Herramientas disponibles (JSON estructurado): {tool_specs_json}
        Debes responder SIEMPRE con JSON válido en uno de estos formatos:
        1) Para usar herramienta:
        {{"type": "tool_call", "tool": "nombre_herramienta", "args": {{"param": "valor"}}}}
        2) Para responder al usuario:
        {{"type": "final", "answer": "tu respuesta final"}}

        Si te falta información, prefiere tool_call.
        """
        userprompt = f"""{user_input}"""

        self.mensajes = [messageDto(role="system", content=system_prompt), messageDto(role="user", content=userprompt)]

        peticion = peticionDto(
            model=self.model,
            messages=self.mensajes
        )

        vultrHeaders = {
            "Authorization": f"Bearer {os.getenv('VULTR_INFERENCE_API_KEY')}",
            "Content-Type": "application/json",
        }

        while True:
            async with httpx.AsyncClient(headers=vultrHeaders, timeout=httpx.Timeout(40.0, read=None)) as http_client:
                raw_text, content = await self.realizar_peticion(http_client, peticion)
                self.mensajes.append(messageDto(role="assistant", content=content))
                payload = self._extract_json_payload(raw_text)
                logging.debug(f"Payload extraído: {payload}")

                if payload is None:
                    print(f"\n🤖 Study Buddy: {raw_text}")
                    return

                response_type = payload.get("type")
                if response_type == "final":
                    final_answer = payload.get("answer")
                    if isinstance(final_answer, str) and final_answer.strip():
                        print(f"\n🤖 Study Buddy: {final_answer.strip()}")
                        return
                    print("❌ Respuesta final inválida del modelo (falta 'answer').")
                    return

                if response_type != "tool_call":
                    print(f"\n🤖 Study Buddy: {raw_text}")
                    return

                if tool_calls_used >= self.MAX_TOOL_CALLS_PER_TURN:
                    force_final_prompt = f"""
                    Alcanzaste el límite de {self.MAX_TOOL_CALLS_PER_TURN} herramientas en este turno.
                    Historial de herramientas usadas: {tool_history}
                    Responde SOLO con JSON final:
                    {{"type": "final", "answer": "..."}}
                    """
                    self.mensajes.append(messageDto(role="system", content=force_final_prompt))
                    peticion = peticionDto(
                        model=self.model,
                        messages=self.mensajes
                    )
                    final_text, final_content = await self.realizar_peticion(http_client, peticion)
                    final_payload = self._extract_json_payload(final_text)
                    self.mensajes.append(messageDto(role="assistant", content=final_content))
                    if final_payload and final_payload.get("type") == "final" and isinstance(final_payload.get("answer"), str):
                        print(f"\n🤖 Study Buddy: {final_payload['answer'].strip()}")
                    else:
                        print(f"\n🤖 Study Buddy: {final_text}")
                    return

                tool_name = payload.get("tool")
                tool_args = payload.get("args", {})

                # if not isinstance(tool_name, str) or tool_name not in tool_names:
                #     print(f"❌ Herramienta no permitida o inexistente: {tool_name}")
                #     return

                # if not isinstance(tool_args, dict):
                #     print("❌ Argumentos inválidos para tool_call (deben ser un objeto JSON).")
                #     return

                try:
                    print(f"🛠️ Usando herramienta ({tool_calls_used + 1}/{self.MAX_TOOL_CALLS_PER_TURN}): {tool_name}...")
                    result = await session.call_tool(tool_name, tool_args)
                    logging.debug(f"Resultado de la herramienta '{tool_name}': {result.content}")
                    tool_calls_used += 1
                    tool_history.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": str(result.content),
                    })
                    
                except Exception as e:
                    print(f"❌ Error al ejecutar herramienta {tool_name}: {e}")
                    return

                system_prompt = f"""
                Historial de herramientas ejecutadas hasta ahora:
                {tool_history}

                Puedes hacer otra llamada de herramienta o responder final si completaste la tarea del usuario.

                Responde SIEMPRE con JSON válido:
                - {{"type": "tool_call", "tool": "nombre_herramienta", "args": {{...}}}}
                - {{"type": "final", "answer": "..."}}
                """
                logging.debug(f"Actualizando system prompt para la siguiente iteración: {system_prompt}")
                self.mensajes.append(messageDto(role="system", content=system_prompt))
                peticion = peticionDto(
                    model=self.model,
                    messages=self.mensajes
                )

    async def realizar_peticion(self, httpClient:httpx.AsyncClient, peticion: peticionDto) -> tuple[str,str]:
        response = await httpClient.post(self.endpoint, json=asdict(peticion))
        response.raise_for_status()
        logging.debug(f"Respuesta bruta del modelo: {response.text}")

        try:
            data = response.json()
        except ValueError as json_error:
            raise ValueError(f"Respuesta inválida del proveedor: body no es JSON válido. Body: {response.text}") from json_error

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"Respuesta inválida del proveedor: falta 'choices'. Body: {response.text}")

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
        #posible agregar mensaje a self.mensajes aqui
        content = message.get("content") if isinstance(message, dict) else None

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
            content = "\n".join(text_parts)

        if content is None and isinstance(message, dict):
            refusal = message.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                content = refusal

        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Respuesta inválida del proveedor: falta contenido en 'message.content'. Body: {response.text}")

        if "</think>" in content:
            clean_content = content.split("</think>", 1)[1].strip()
        else:
            clean_content = content.strip()
        logging.debug(f"Contenido limpio extraído: {clean_content}")
        return (clean_content,content)


async def _safe_response_text(response: httpx.Response | None) -> str:
    if response is None:
        return "sin cuerpo de respuesta"

    try:
        raw = await response.aread()
        return raw.decode(response.encoding or "utf-8", errors="replace")
    except Exception:
        return "no se pudo leer el cuerpo de la respuesta"


def _is_unauthorized(status_code: int | None) -> bool:
    return status_code == 401


async def _load_tokens_from_disk(token_path: str) -> dict:
    with open(token_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


async def _recover_authentication(tokens: dict, token_path: str) -> dict:
    client_config = load_client_config() or {}
    client_id = client_config.get("client_id")
    client_secret = client_config.get("client_secret")
    refresh_token = tokens.get("refresh_token")

    if not client_id or not refresh_token:
        print("🔐 Faltan datos para refresh; iniciando reautenticación completa...")
        await authFlow()
        return await _load_tokens_from_disk(token_path)

    try:
        print("🔄 Access token vencido/no autorizado. Intentando refresh...")
        await refresh_access_token(refresh_token, client_id, client_secret)
        print("✅ Refresh exitoso. Reintentando conexión...")
        return await _load_tokens_from_disk(token_path)
    except Exception as refresh_error:
        refresh_error_msg = str(refresh_error)
        if refresh_error_msg in {"REAUTH_REQUIRED", "INVALID_CLIENT"}:
            print("🔐 Refresh no válido; iniciando reautenticación completa...")
            await authFlow()
            return await _load_tokens_from_disk(token_path)
        raise


def _extract_unauthorized_from_group(group_error: ExceptionGroup) -> httpx.HTTPStatusError | None:
    for sub_error in group_error.exceptions:
        if isinstance(sub_error, httpx.HTTPStatusError):
            status_code = sub_error.response.status_code if sub_error.response is not None else None
            if _is_unauthorized(status_code):
                return sub_error
        if isinstance(sub_error, ExceptionGroup):
            nested = _extract_unauthorized_from_group(sub_error)
            if nested is not None:
                return nested
    return None


# --- Lógica de ejecución ---
async def run_bot_connection():
    load_dotenv()  # Carga las variables de entorno desde el archivo .env
    TOKEN_PATH  = "client_tokens.json"

    if not os.path.exists(TOKEN_PATH):
        print("🔐 No se encontraron tokens guardados. Iniciando flujo de autenticación...")
        await authFlow()
    
    tokens = await _load_tokens_from_disk(TOKEN_PATH)

    serverUrl = os.getenv("NOTION_MCP_SERVER_URL") or "https://mcp.notion.com/mcp"
    client = NotionStreamableClient(tokens["access_token"], serverUrl)
    
    try:
        await client.connect_streamable()
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response is not None else "desconocido"
        response_text = await _safe_response_text(e.response)
        if _is_unauthorized(e.response.status_code if e.response is not None else None):
            print("⚠️ Respuesta unauthorized detectada. Iniciando recuperación de sesión...")
            tokens = await _recover_authentication(tokens, TOKEN_PATH)
            retry_client = NotionStreamableClient(tokens["access_token"], serverUrl)
            await retry_client.connect_streamable()
        else:
            print(f"❌ Error HTTP al conectar con Streams: {status_code}")
            print(f"Detalle del servidor: {response_text}")
    except ExceptionGroup as e:
        unauthorized_error = _extract_unauthorized_from_group(e)
        if unauthorized_error is not None:
            print("⚠️ Unauthorized detectado dentro de ExceptionGroup. Iniciando recuperación...")
            tokens = await _recover_authentication(tokens, TOKEN_PATH)
            retry_client = NotionStreamableClient(tokens["access_token"], serverUrl)
            await retry_client.connect_streamable()
        else:
            print("❌ Error agrupado en TaskGroup. Mostrando causa(s) real(es):")
            for index, sub_error in enumerate(e.exceptions, start=1):
                print(f"\n--- Sub-excepción {index}: {type(sub_error).__name__} ---")
                if isinstance(sub_error, httpx.HTTPStatusError):
                    status_code = sub_error.response.status_code if sub_error.response is not None else "desconocido"
                    response_text = await _safe_response_text(sub_error.response)
                    print(f"HTTP status: {status_code}")
                    print(f"HTTP body: {response_text}")
                traceback.print_exception(type(sub_error), sub_error, sub_error.__traceback__)
    except Exception as e:
        print(f"❌ Error al conectar con Streams: {e}")
        traceback.print_exception(type(e), e, e.__traceback__)
        # Aquí podrías poner un bloque 'try-except' adicional para 
        # hacer el fallback a /sse si este falla.

if __name__ == "__main__":
    asyncio.run(run_bot_connection())