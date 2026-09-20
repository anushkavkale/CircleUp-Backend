from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
import pathlib
import uuid
from django.utils import timezone
from django.contrib.auth.models import User


# Create your models here.
def pic_upload(instance, filepath):
    fname = str(uuid.uuid1())
    ext = pathlib.Path(filepath).suffix
    return f"Posts/{fname}{ext}"

def pfp(instance, filepath):
    fname = str(uuid.uuid1())
    ext = pathlib.Path(filepath).suffix
    return f"profilepictures/{fname}{ext}"




class Profile(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.CharField(max_length=125, blank=True, null=True,default="Hello World!.")
    pfp = models.ImageField(upload_to=pfp, blank=True, null=True)
    cover = models.ImageField(upload_to="covers/", blank=True, null=True)
    
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC
    )    
    is_verified = models.BooleanField(default=True)


    def __str__(self):
        return self.user.username
    
@receiver(post_save, sender=Profile)
def CreateProfile(sender, instance, created, **kwargs):
    if created:
        print(f"Profile Created for {instance.user}")

class PostsModel(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="posts", null=True)
    group = models.ForeignKey("Group", on_delete=models.CASCADE, related_name="posts", null=True, blank=True)

    content = models.CharField(max_length=250, null=True)
    
    image = models.ImageField(upload_to=pic_upload, blank=True, null=True)
    video = models.FileField(upload_to="videos/", blank=True, null=True)
    thumbnail = models.ImageField(upload_to="thumbnails/", blank=True, null=True)
    share_count = models.PositiveIntegerField(default=0)

    created = models.DateField(auto_now=True)

    liked_by = models.ManyToManyField(User, related_name="liked_posts", blank=True)
    disliked_by = models.ManyToManyField(User, related_name="disliked_posts", blank=True)

    saved_by = models.ManyToManyField(User, related_name="saved_posts", blank=True)

    def __str__(self):
        return self.content[:10]


def story_media_upload(instance, filepath):
    extension = pathlib.Path(filepath).suffix
    return f"stories/{uuid.uuid4()}{extension}"


class Story(models.Model):
    PRIVACY_CHOICES = [
        ("public", "Public"),
        ("friends", "Friends"),
        ("private", "Only me"),
    ]

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stories")
    content = models.CharField(max_length=250, blank=True)
    image = models.ImageField(upload_to=story_media_upload, blank=True, null=True)
    video = models.FileField(upload_to=story_media_upload, blank=True, null=True)
    privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES, default="public")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["author", "expires_at"]), models.Index(fields=["expires_at"])]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)


class StoryView(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="viewers")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="story_views")
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["story", "user"], name="unique_story_view")]
        indexes = [models.Index(fields=["story", "viewed_at"])]


class StoryReaction(models.Model):
    REACTION_CHOICES = [("like", "Like"), ("love", "Love"), ("laugh", "Laugh"), ("wow", "Wow")]
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="story_reactions")
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["story", "user"], name="unique_story_reaction")]


class StoryReply(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="story_replies")
    content = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["story", "created_at"])]


class ReelView(models.Model):
    post = models.ForeignKey(PostsModel, on_delete=models.CASCADE, related_name="reel_views")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reel_views")
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="unique_reel_view")]
        indexes = [models.Index(fields=["post", "viewed_at"])]


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_verification_tokens")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class LoginHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_history")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class UserBlock(models.Model):
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_users")
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_by_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["blocker", "blocked"], name="unique_user_block")]


class Comment(models.Model):
    post = models.ForeignKey(PostsModel, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, related_name="replies", null=True, blank=True)
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["post", "created_at"]), models.Index(fields=["parent", "created_at"])]


class FriendRequest(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected")]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_friend_requests")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_friend_requests")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sender", "recipient"], name="unique_friend_request")]
        indexes = [models.Index(fields=["recipient", "status"])]


class Group(models.Model):
    VISIBILITY_CHOICES = [("public", "Public"), ("private", "Private")]
    name = models.CharField(max_length=100)
    description = models.TextField(max_length=500, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_groups")
    avatar = models.ImageField(upload_to="group_avatars/", blank=True, null=True)
    cover = models.ImageField(upload_to="group_covers/", blank=True, null=True)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default="public")
    members = models.ManyToManyField(User, through="GroupMembership", related_name="postnest_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class GroupMembership(models.Model):
    ROLE_CHOICES = [("member", "Member"), ("moderator", "Moderator"), ("owner", "Owner")]
    STATUS_CHOICES = [("pending", "Pending"), ("active", "Active")]
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "user"], name="unique_group_member")]
        indexes = [models.Index(fields=["user", "group"])]
    
class Notifications(models.Model):
    NOTIFICATION_TYPES = [
        ("LIKE", "Like"),
        ("COMMENT", "Comment"),
        ("FOLLOW", "Follow"),
        ("MESSAGE", "Message"),
        ("REQUEST", "Message request"),
        ("GROUP", "Group activity"),
        ("MENTION", "Mention"),
    ]
    recipient = models.ForeignKey(User, related_name="Notireceived", on_delete=models.CASCADE)
    sender = models.ForeignKey(User, related_name="Notisent", on_delete=models.CASCADE)
    message = models.CharField(max_length=100)
    notif_type = models.CharField(max_length=10, choices=NOTIFICATION_TYPES, default="LIKE")
    created = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.message}"


class NotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preferences")
    likes = models.BooleanField(default=True)
    comments = models.BooleanField(default=True)
    follows = models.BooleanField(default=True)
    messages = models.BooleanField(default=True)
    requests = models.BooleanField(default=True)
    groups = models.BooleanField(default=True)


class Conversation(models.Model):
    user_one = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations_as_one",
    )
    user_two = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations_as_two",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_one", "user_two"],
                name="unique_user_conversation",
            )
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user_one.username} and {self.user_two.username}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    content = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender.username}: {self.content[:30]}"


class MessageRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    ]

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_requests_sent")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_requests_received")
    content = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.sender.username} -> {self.recipient.username} ({self.status})"


