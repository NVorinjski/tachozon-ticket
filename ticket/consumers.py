# ticket/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # NEU: alle eingeloggten Tabs hören auch auf Broadcast
        await self.channel_layer.group_add("broadcast", self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        # NEU:
        await self.channel_layer.group_discard("broadcast", self.channel_name)

    async def send_notification(self, event):
        await self.send(text_data=json.dumps(event["content"]))
