import asyncio

from mcpClient import NotionStreamableClient, create_authenticated_client


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

	async def handle_user_message(self, message: str) -> str:
		if self._client is None:
			await self.start()

		normalized_message = (message or "").strip()
		if not normalized_message:
			return "Escribe un mensaje para que pueda ayudarte con Notion."

		try:
			return await self._client.ask(normalized_message)
		except Exception as error:
			return f"Error procesando tu mensaje: {error}"
