from rest_framework import serializers
from .models import * 
from django.contrib.auth.models import User
from django.utils import timezone

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id","username"]

class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = Profile
        fields = ["id", "bio", "user", "pfp", "cover", "visibility", "is_verified"]


class PostsSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)  # <-- nested serializer
    likes = serializers.SerializerMethodField()
    dislikes = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_disliked = serializers.SerializerMethodField()
    saves = serializers.SerializerMethodField()
    views = serializers.SerializerMethodField()
    class Meta:
        model = PostsModel
        fields = ["id", "content", "created", "profile", "group", "image", "video", "thumbnail", "likes", "dislikes", "is_liked", "is_disliked", "saves", "views", "share_count"]

    def validate(self, attrs):
        if attrs.get("image") and attrs.get("video"):
            raise serializers.ValidationError("Upload either an image or a video, not both.")
        return attrs

    def validate_video(self, value):
        max_size = 50 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError("Video files must be 50 MB or smaller.")
        return value

    def get_likes(self, obj):
        return obj.liked_by.count()
    def get_dislikes(self, obj):
        return obj.disliked_by.count()
    def get_is_liked(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.liked_by.filter(pk=request.user.pk).exists())
    def get_is_disliked(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.disliked_by.filter(pk=request.user.pk).exists())
    def get_saves(self, obj):
        return obj.saved_by.count()

    def get_views(self, obj):
        return obj.reel_views.count() if obj.video else 0


class StoryReplySerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = StoryReply
        fields = ["id", "author", "content", "created_at"]


class StorySerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    author_pfp = serializers.SerializerMethodField()
    viewers = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    replies = StoryReplySerializer(many=True, read_only=True)
    expires_in = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = ["id", "author", "author_pfp", "content", "image", "video", "privacy", "created_at", "expires_at", "expires_in", "viewers", "reactions", "my_reaction", "replies"]

    def get_author_pfp(self, obj):
        request = self.context.get("request")
        if request and hasattr(obj.author, "profile") and obj.author.profile.pfp:
            return request.build_absolute_uri(obj.author.profile.pfp.url)
        return None

    def get_viewers(self, obj):
        return obj.viewers.count()

    def get_reactions(self, obj):
        return {reaction: obj.reactions.filter(reaction=reaction).count() for reaction, _ in StoryReaction.REACTION_CHOICES}

    def get_my_reaction(self, obj):
        request = self.context.get("request")
        reaction = obj.reactions.filter(user=request.user).first() if request and request.user.is_authenticated else None
        return reaction.reaction if reaction else None

    def get_expires_in(self, obj):
        seconds = max(0, int((obj.expires_at - timezone.now()).total_seconds()))
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "author", "parent", "content", "created_at", "replies"]

    def get_replies(self, obj):
        return CommentSerializer(obj.replies.select_related("author"), many=True).data


class FriendRequestSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    recipient = UserSerializer(read_only=True)

    class Meta:
        model = FriendRequest
        fields = ["id", "sender", "recipient", "status", "created_at"]


class GroupSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    membership_status = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "description", "owner", "avatar", "cover", "visibility", "member_count", "is_member", "membership_status", "created_at"]

    def get_is_member(self, obj):
        return obj.groupmembership_set.filter(user=self.context["request"].user, status="active").exists()

    def get_member_count(self, obj):
        return obj.members.filter(groupmembership__status="active").count()

    def get_membership_status(self, obj):
        membership = obj.groupmembership_set.filter(user=self.context["request"].user).first()
        return membership.status if membership else None


class GroupMemberSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    bio = serializers.CharField(source="user.profile.bio", read_only=True, allow_null=True)
    pfp = serializers.SerializerMethodField()

    class Meta:
        model = GroupMembership
        fields = ["id", "username", "bio", "pfp", "role", "status", "joined_at"]

    def get_pfp(self, obj):
        request = self.context.get("request")
        if request and hasattr(obj.user, "profile") and obj.user.profile.pfp:
            return request.build_absolute_uri(obj.user.profile.pfp.url)
        return None

    
class SignupSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["username","email","password","password2"]
    
    def validate_username(self,value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username is already taken")
        return value
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value
    
    def create(self, validated_data):
        validated_data.pop('password2', None)
        user = User.objects.create_user(**validated_data)
        return user

class NotificationSerializer(serializers.ModelSerializer):
    user_pfp = serializers.SerializerMethodField()
    sender_username = serializers.CharField(source="sender.username", read_only=True)

    class Meta:
        model = Notifications
        fields = ["id", "message", "created", "notif_type", "sender_username", "user_pfp", "is_read"]

    def get_user_pfp(self,obj):
        request = self.context.get("request")
        if request and obj.sender and hasattr(obj.sender, "profile") and obj.sender.profile.pfp:
            return request.build_absolute_uri(obj.sender.profile.pfp.url)
        return None


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "sender", "content", "created_at", "is_read"]


class ConversationSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "other_user", "last_message", "unread_count", "updated_at"]

    def get_other_user(self, obj):
        request_user = self.context["request"].user
        other_user = obj.user_two if obj.user_one == request_user else obj.user_one
        return UserSerializer(other_user).data

    def get_last_message(self, obj):
        message = obj.messages.order_by("-created_at").first()
        return MessageSerializer(message).data if message else None

    def get_unread_count(self, obj):
        request_user = self.context["request"].user
        return obj.messages.exclude(sender=request_user).filter(is_read=False).count()


class MessageRequestSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    recipient = UserSerializer(read_only=True)

    class Meta:
        model = MessageRequest
        fields = ["id", "sender", "recipient", "content", "status", "created_at"]
