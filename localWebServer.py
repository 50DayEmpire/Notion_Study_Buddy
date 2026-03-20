from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from typing import Optional


@dataclass
class CallbackParams:
    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None
    error_description: Optional[str] = None
    timed_out: bool = False


# Resultado compartido entre handler y proceso principal.
callback_params = CallbackParams()


class OAuthServer(HTTPServer):
    callback_path = "/"

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global callback_params
        parsed_url = urlparse(self.path)

        if parsed_url.path != self.server.callback_path:
            self.send_response(404)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>Ruta no encontrada</h1>".encode("utf-8"))
            return

        query_components = parse_qs(parsed_url.query)
        callback_params = CallbackParams(
            code=query_components.get("code", [None])[0],
            state=query_components.get("state", [None])[0],
            error=query_components.get("error", [None])[0],
            error_description=query_components.get("error_description", [None])[0],
        )

        if callback_params.error:
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            message = callback_params.error_description or "Error OAuth recibido desde Notion."
            self.wfile.write(f"<h1>Error de autorizacion</h1><p>{message}</p>".encode("utf-8"))
            print(f"❌ Error OAuth: {callback_params.error} - {message}")
        elif callback_params.code:
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>Autorizado!</h1><p>Ya puedes cerrar esta ventana.</p>".encode("utf-8"))
            print(f"✅ Codigo capturado: {callback_params.code}")
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>Error en callback OAuth</h1><p>No se recibió el parámetro 'code'.</p>".encode("utf-8"))
            print("❌ Callback recibido sin 'code'.")

    def log_message(self, format, *args):
        # Evita ruido de logs por cada request en consola.
        return

def run_local_server():
    global callback_params
    callback_params = CallbackParams()

    server_address = ('127.0.0.1', 8080)
    httpd = OAuthServer(server_address, OAuthCallbackHandler)
    httpd.timeout = 120
    
    print("🌍 Esperando a que el usuario autorice en el navegador...")
    try:
        httpd.handle_request()
    finally:
        httpd.server_close()

    if callback_params.code is None and callback_params.error is None:
        callback_params.timed_out = True
        print("⏳ Timeout esperando callback OAuth.")

    return callback_params

if __name__ == "__main__":
    run_local_server()