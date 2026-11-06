import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel

load_dotenv()


async def main():
    async with TelegramClient(
        "boostio_telethon",
        int(os.getenv("api_id")),
        os.getenv("api_hash")
    ) as client:

        async for dialog in client.iter_dialogs():

            if (
                isinstance(dialog.entity, Channel)
                and "BOOSTio" in dialog.name
            ):
                print("Canal:", dialog.name)
                print("ID Telethon:", dialog.id)
                print("ID interno:", dialog.entity.id)

                destino = dialog.input_entity

                await client.send_message(
                    destino,
                    "🔥 Teste de envio BOOSTio",
                    parse_mode=None
                )

                print("Mensagem enviada com sucesso!")
                return

        print("Canal BOOSTio não encontrado na conta.")


asyncio.run(main())