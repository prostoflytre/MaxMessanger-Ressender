from pymax import Client

async def send_message_from_tg(chat_recipient: str, message: str, client: Client) -> None:

    chats = await client.fetch_chats()
    print(f"Fetched chats {len(chats)}")

    for chat in chats:
        title = await client.get_user(chat.id)
        print(f"Checking chat.id: {chat.id}, chat.title: {title}")
        if  await client.get_user(chat.id) == chat_recipient:
            await client.send_message(chat.id, message)
            print(f"Sent message to chat {chat_recipient}")
            return

    print(f"Chat with title {chat_recipient} was not found")
