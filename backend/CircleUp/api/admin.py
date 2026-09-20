from django.contrib import admin
from .models import * 


# Register your models here.
admin.site.register(PostsModel)
admin.site.register(Profile)
admin.site.register(Notifications)
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(MessageRequest)
admin.site.register(Comment)
admin.site.register(FriendRequest)
admin.site.register(Group)
admin.site.register(GroupMembership)
admin.site.register(ReelView)
admin.site.register(EmailVerificationToken)
admin.site.register(LoginHistory)
admin.site.register(UserBlock)