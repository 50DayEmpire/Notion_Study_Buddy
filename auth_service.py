import webbrowser
from auth_utils import *
from dotenv import load_dotenv
from os import getenv
import asyncio
from authlib.integrations.httpx_client import AsyncOAuth2Client
from localWebServer import *

async def authFlow():
    load_dotenv()
    mcpUrl = getenv("BASE_NOTION_URL", "https://mcp.notion.com")
    redirect_uri = "http://localhost:8080"

    credencialesExistentes = load_client_config()

    # Paso 1: Descubrir metadata de OAuth
    metadata = await discover_oauth_metadata(mcpUrl)

    #Paso 2: Generar PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()

    if not credencialesExistentes:
        #Paso 3: Registro dinámico de cliente
        credenciales = await register_client(metadata, redirect_uri)

        #Guardar credenciales en un archivo local
        save_client_config(credenciales)
        credencialesExistentes = load_client_config()   

    client = AsyncOAuth2Client(
        client_id=credencialesExistentes["client_id"],
        client_secret=credencialesExistentes.get("client_secret"),  # Puede ser None para clientes públicos
        scope="",  # Ajusta los scopes según lo que tu aplicación necesite
        redirect_uri=redirect_uri,
    )
    state = generate_state()
    authorization_url, returned_state = client.create_authorization_url(
        metadata["authorization_endpoint"],
        response_type = "code",
        prompt = "consent",
        code_challenge=code_challenge,
        code_challenge_method = "S256",
        state=state,
        scope=""
    )
    # Abrir el navegador para que el usuario autorice
    webbrowser.open(authorization_url)

    #Montar servidor local ligero para capturar el código de autorización
    callback = run_local_server()
    code = handle_callback(callback, state)

    tokens = await exchange_code_for_tokens(
        code=code,
        code_verifier=code_verifier,
        metadata=metadata,
        client_id=credencialesExistentes["client_id"],
        client_secret=credencialesExistentes.get("client_secret"),
        redirect_uri=redirect_uri,
    )

    save_tokens(tokens)
    print("✅ Token exchange exitoso")


async def refresh_access_token(refresh_token: str, client_id: str, client_secret: str = None):
    """
    Maneja el flujo de refresh token en OAuth 2.0.
    """
    params = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        params["client_secret"] = client_secret

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    metadata = await discover_oauth_metadata(getenv("BASE_NOTION_URL", "https://mcp.notion.com"))

    async with httpx.AsyncClient() as client:
        response = await client.post(metadata["token_endpoint"], data=params, headers=headers)

        if response.status_code != 200:
            error_body = response.text
            try:
                error = response.json()
                if error.get("error") == "invalid_grant":
                    raise Exception("REAUTH_REQUIRED")  # refresh token caducado
                if error.get("error") == "invalid_client":
                    raise Exception("INVALID_CLIENT")   # client_id/secret inválidos
            except ValueError:
                # No es JSON, solo texto
                pass
            raise Exception(f"Token refresh failed: {response.status_code} - {error_body}")

        tokens = response.json()
        save_tokens(tokens)  # Actualiza tokens guardados



if __name__ == "__main__":    asyncio.run(authFlow())