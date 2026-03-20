from typing import Optional, List, TypedDict
import httpx
from authlib.oauth2.rfc7636 import create_s256_code_challenge
import secrets
import os
import json

from localWebServer import CallbackParams


class OAuthMetadata(TypedDict, total=False):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str]
    code_challenge_methods_supported: Optional[List[str]]
    grant_types_supported: Optional[List[str]]
    response_types_supported: Optional[List[str]]
    scopes_supported: Optional[List[str]]

async def discover_oauth_metadata(mcp_server_url: str) -> OAuthMetadata:
    # Construir URL del recurso protegido (RFC 9470)
    protected_resource_url = f"{mcp_server_url}/.well-known/oauth-protected-resource"

    async with httpx.AsyncClient() as client:
        # Paso 1: Obtener Protected Resource Metadata
        pr_response = await client.get(protected_resource_url)
        if pr_response.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch protected resource metadata: {pr_response.status_code}"
            )

        protected_resource = pr_response.json()
        auth_servers = protected_resource.get("authorization_servers")

        if not isinstance(auth_servers, list) or len(auth_servers) == 0:
            raise RuntimeError(
                "No authorization servers found in protected resource metadata"
            )

        # Usar el primer servidor de autorización
        auth_server_url = auth_servers[0]

        # Paso 2: Obtener Authorization Server Metadata (RFC 8414)
        metadata_url = f"{auth_server_url}/.well-known/oauth-authorization-server"
        metadata_response = await client.get(metadata_url)

        if metadata_response.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch authorization server metadata: {metadata_response.status_code}"
            )

        metadata: OAuthMetadata = metadata_response.json()

        # Validar campos obligatorios
        if not metadata.get("authorization_endpoint") or not metadata.get("token_endpoint"):
            raise RuntimeError("Missing required OAuth endpoints in metadata")

        # Advertencia si PKCE S256 no está anunciado
        if "code_challenge_methods_supported" not in metadata or \
           "S256" not in metadata["code_challenge_methods_supported"]:
            print("⚠️ Server does not advertise S256 PKCE support, but we will use it anyway")

        return metadata
    

def generate_pkce_pair():
    # 1. Generar un code_verifier aleatorio (mínimo 43 caracteres recomendado)
    # Usamos secrets.token_urlsafe para obtener un string seguro y URL-safe
    code_verifier = secrets.token_urlsafe(64)

    # 2. Generar el code_challenge usando SHA-256 y base64url
    code_challenge = create_s256_code_challenge(code_verifier)

    return code_verifier, code_challenge

class ClientRegistration(TypedDict, total=False):
    client_name: str
    client_uri: Optional[str]
    redirect_uris: List[str]
    grant_types: List[str]
    response_types: List[str]
    token_endpoint_auth_method: str
    scope: Optional[str]

class ClientCredentials(TypedDict, total=False):
    client_id: str
    client_secret: Optional[str]
    client_id_issued_at: Optional[int]
    client_secret_expires_at: Optional[int]


class TokenResponse(TypedDict, total=False):
    access_token: str
    token_type: str
    expires_in: Optional[int]
    refresh_token: Optional[str]
    scope: Optional[str]


async def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    metadata: OAuthMetadata,
    client_id: str,
    client_secret: Optional[str],
    redirect_uri: str,
) -> TokenResponse:
    token_endpoint = metadata.get("token_endpoint")
    if not token_endpoint:
        raise RuntimeError("Missing token endpoint in OAuth metadata")

    form_data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    if client_secret:
        form_data["client_secret"] = client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "Notion-AI-Challenge-Client/1.0",
            },
            data=form_data,
        )

    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            f"Token exchange failed: {response.status_code} - {response.text}"
        )

    tokens: TokenResponse = response.json()
    if not tokens.get("access_token"):
        raise RuntimeError("Missing access_token in token response")

    return tokens

async def register_client(metadata: OAuthMetadata, redirect_uri: str) -> ClientCredentials:
    # Validar que el servidor soporte Dynamic Client Registration
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise RuntimeError("Server does not support dynamic client registration")

    # Construir la solicitud de registro
    registration_request: ClientRegistration = {
        "client_name": "Notion AI Study Buddy",
        "client_uri": "https://github.com/50DayEmpire/Notion_Study_Buddy",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            registration_endpoint,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=registration_request,
        )

        if response.status_code != 201 and response.status_code != 200:
            # Manejo de error detallado
            raise RuntimeError(
                f"Client registration failed: {response.status_code} - {response.text}"
            )

        credentials: ClientCredentials = response.json()

        # Validar que se devolvió al menos el client_id
        if "client_id" not in credentials:
            raise RuntimeError("Invalid registration response: missing client_id")

        return credentials


CLIENT_CONFIG_PATH = "client_credentials.json"  
def save_client_config(credentials: ClientCredentials):
    """
    Guarda el client_id y metadatos del registro dinámico en un archivo local.
    """
    try:
        with open(CLIENT_CONFIG_PATH, "w") as f:
            json.dump(credentials, f, indent=4)
        print(f"✅ Credenciales de cliente guardadas en {CLIENT_CONFIG_PATH}")
    except Exception as e:
        print(f"❌ Error al guardar configuración: {e}")

def load_client_config():
    """
    Carga las credenciales si el archivo existe.
    """
    if os.path.exists(CLIENT_CONFIG_PATH):
        with open(CLIENT_CONFIG_PATH, "r") as f:
            return json.load(f)
    return None

def generate_state() -> str:
    return secrets.token_hex(32)

def save_tokens(tokens: TokenResponse):
    """
    Guarda los tokens de acceso y refresco en un archivo local.
    """
    try:
        with open("client_tokens.json", "w") as f:
            json.dump(tokens, f, indent=4)
        print("✅ Tokens guardados en client_tokens.json")
    except Exception as e:
        print(f"❌ Error al guardar tokens: {e}")


def handle_callback(params: CallbackParams, stored_state: str) -> str:
    if params.timed_out:
        raise TimeoutError("Timeout esperando callback OAuth")

    if params.error:
        description = params.error_description or "Unknown error"
        raise ValueError(f"OAuth error: {params.error} - {description}")

    if params.state != stored_state:
        raise ValueError("Invalid state parameter - possible CSRF attack")

    if not params.code:
        raise ValueError("Missing authorization code")

    return params.code
