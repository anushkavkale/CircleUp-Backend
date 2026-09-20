import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import User

from .models import Conversation, Message, Notifications


class ConversationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.room_group_name = f"conversation_{self.conversation_id}"
        user = self.scope.get("user")

        if not user or user.is_anonymous or not await self.user_in_conversation(user.id):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json({"type": "error", "error": "Invalid message format."})
            return

        if payload.get("type") != "message":
            return

        content = str(payload.get("content", "")).strip()
        if not content or len(content) > 2000:
            await self.send_json({"type": "error", "error": "Message must contain 1-2000 characters."})
            return

        message = await self.create_message(self.scope["user"].id, content)
        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "chat.message", "message": message},
        )

    async def chat_message(self, event):
        await self.send_json({"type": "message", "message": event["message"]})

    @database_sync_to_async
    def user_in_conversation(self, user_id):
        return Conversation.objects.filter(id=self.conversation_id).filter(
            user_one_id=user_id
        ).exists() or Conversation.objects.filter(id=self.conversation_id, user_two_id=user_id).exists()

    @database_sync_to_async
    def create_message(self, user_id, content):
        conversation = Conversation.objects.select_related("user_one", "user_two").get(id=self.conversation_id)
        message = Message.objects.create(
            conversation=conversation,
            sender_id=user_id,
            content=content,
        )
        conversation.save(update_fields=["updated_at"])
        recipient = conversation.user_two if conversation.user_one_id == user_id else conversation.user_one
        sender = User.objects.get(id=user_id)
        Notifications.objects.create(
            recipient=recipient,
            sender=sender,
            message=f"{sender} sent you a message.",
            notif_type="MESSAGE",
        )
        return {
            "id": message.id,
            "sender": {"id": sender.id, "username": sender.username},
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "is_read": message.is_read,
        }
