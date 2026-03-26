import asyncio

from mcpClient import (
	NotionStreamableClient,
	create_authenticated_client,
	recover_authenticated_client,
	is_auth_recoverable_error,
)


class TelegramIOAdapter:
	def __init__(self):
		self._client: NotionStreamableClient | None = None
		self._bootstrap_lock = asyncio.Lock()

	async def start(self):
		async with self._bootstrap_lock:
			if self._client is None:
				self._client = await create_authenticated_client()

	async def stop(self):
		async with self._bootstrap_lock:
			if self._client is not None:
				await self._client.close()
				self._client = None

	async def _recover_client(self):
		async with self._bootstrap_lock:
			if self._client is not None:
				await self._client.close()
			self._client = await recover_authenticated_client()

	async def handle_user_message(self, message: str) -> str:
		if self._client is None:
			await self.start()

		normalized_message = (message or "").strip()
		if not normalized_message:
			return "Escribe un mensaje para que pueda ayudarte con Notion."

		try:
			return await self._client.ask(normalized_message)
		except BaseException as error:
			if not is_auth_recoverable_error(error):
				return f"Error procesando tu mensaje: {error}"

			try:
				await self._recover_client()
				return await self._client.ask(normalized_message)
			except Exception as retry_error:
				return f"Error procesando tu mensaje tras recuperar autenticación: {retry_error}"
