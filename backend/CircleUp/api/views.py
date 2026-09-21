from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from friendship.models import Follow, Block
from django.shortcuts import get_object_or_404
from .serializers import *
from .models import *

from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.hashers import make_password
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.db.models import F, Q
import re

# Create your views here.

@method_decorator(ensure_csrf_cookie, name="dispatch")
class csrftoken(APIView):
    def get(self,request):
        return Response({"detial" : "CSRF cookie set."})


    
class Signup(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            profile = Profile(user=user, is_verified=True)
            profile.save()
            return Response({"message": "User registered successfully!"}, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Signin(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)

        if user is not None:
            refresh = RefreshToken.for_user(user)
            LoginHistory.objects.create(
                user=user,
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
            return Response({
                "message": "Logged in successfully",
                "user_id": user.id,
                "username": user.username,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }, status=status.HTTP_200_OK)

        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)


class logoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response({"message": "logged out !!"})


class VerifyEmail(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        verification = get_object_or_404(EmailVerificationToken, token=token)
        verification.user.profile.is_verified = True
        verification.user.profile.save(update_fields=["is_verified"])
        verification.delete()
        return Response({"message": "Email verified successfully."})


class PasswordResetConfirm(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            user = User.objects.get(pk=urlsafe_base64_decode(request.data.get("uid")).decode())
        except (User.DoesNotExist, TypeError, ValueError, OverflowError):
            return Response({"error": "Invalid reset link."}, status=status.HTTP_400_BAD_REQUEST)
        token = request.data.get("token", "")
        password = request.data.get("new_password", "")
        if not default_token_generator.check_token(user, token):
            return Response({"error": "Invalid or expired reset link."}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 8:
            return Response({"error": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
        user.password = make_password(password)
        user.save(update_fields=["password"])
        return Response({"message": "Password reset successfully."})

class Posts(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
            Post = PostsModel.objects.exclude(profile__visibility="private")
            serializer = PostsSerializer(Post, many=True, context={"request": request})
            data = serializer.data
            return Response(data)
    
    def post(self,request):
        serializer = PostsSerializer(data=request.data)
        if serializer.is_valid():
            group = serializer.validated_data.get("group")
            if group and not group.members.filter(id=request.user.id).exists():
                return Response({"error": "You must join this group before posting."}, status=status.HTTP_403_FORBIDDEN)
            serializer.save(profile=request.user.profile, group=group)
            if group:
                for member in group.members.exclude(id=request.user.id):
                    SendNotification("Group", member, request.user, f"{request.user} posted in {group.name}.")
            NotifyMentions(request.user, serializer.validated_data.get("content", ""))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors ,status=status.HTTP_400_BAD_REQUEST)


def can_view_story(story, user):
    if story.author_id == user.id or story.privacy == "public":
        return True
    if story.privacy == "private":
        return False
    return FriendRequest.objects.filter(
        Q(sender=story.author, recipient=user, status="accepted")
        | Q(sender=user, recipient=story.author, status="accepted")
    ).exists()


class Stories(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked_ids = UserBlock.objects.filter(
            Q(blocker=request.user) | Q(blocked=request.user)
        ).values_list("blocker_id", "blocked_id")
        blocked_users = {user_id for pair in blocked_ids for user_id in pair if user_id != request.user.id}
        stories = Story.objects.filter(expires_at__gt=timezone.now()).exclude(
            author_id__in=blocked_users
        ).select_related("author", "author__profile").prefetch_related("replies", "reactions")
        visible_stories = [story for story in stories if can_view_story(story, request.user)]
        return Response({"stories": StorySerializer(visible_stories, many=True, context={"request": request}).data})

    def post(self, request):
        image = request.FILES.get("image")
        video = request.FILES.get("video")
        content = request.data.get("content", "").strip()
        privacy = request.data.get("privacy", "public")
        if not image and not video:
            return Response({"error": "Add an image or video to your story."}, status=status.HTTP_400_BAD_REQUEST)
        if image and video:
            return Response({"error": "Upload either an image or a video, not both."}, status=status.HTTP_400_BAD_REQUEST)
        if privacy not in {choice[0] for choice in Story.PRIVACY_CHOICES}:
            return Response({"error": "Invalid story privacy setting."}, status=status.HTTP_400_BAD_REQUEST)
        if video and video.size > 50 * 1024 * 1024:
            return Response({"error": "Story videos must be 50 MB or smaller."}, status=status.HTTP_400_BAD_REQUEST)
        story = Story.objects.create(
            author=request.user,
            content=content,
            image=image,
            video=video,
            privacy=privacy,
            expires_at=timezone.now() + timezone.timedelta(hours=24),
        )
        return Response(StorySerializer(story, context={"request": request}).data, status=status.HTTP_201_CREATED)


class StoryViewAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk, expires_at__gt=timezone.now())
        if not can_view_story(story, request.user):
            return Response({"error": "This story is not available to you."}, status=status.HTTP_403_FORBIDDEN)
        StoryView.objects.update_or_create(story=story, user=request.user)
        return Response({"viewers": story.viewers.count()})


class StoryReactionAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk, expires_at__gt=timezone.now())
        if not can_view_story(story, request.user):
            return Response({"error": "This story is not available to you."}, status=status.HTTP_403_FORBIDDEN)
        reaction = request.data.get("reaction", "").lower()
        valid_reactions = {choice[0] for choice in StoryReaction.REACTION_CHOICES}
        if reaction not in valid_reactions:
            return Response({"error": "Choose a valid story reaction."}, status=status.HTTP_400_BAD_REQUEST)
        existing = StoryReaction.objects.filter(story=story, user=request.user).first()
        if existing and existing.reaction == reaction:
            existing.delete()
            selected_reaction = None
        else:
            StoryReaction.objects.update_or_create(story=story, user=request.user, defaults={"reaction": reaction})
            selected_reaction = reaction
        return Response({
            "reaction": selected_reaction,
            "reactions": {value: story.reactions.filter(reaction=value).count() for value, _ in StoryReaction.REACTION_CHOICES},
        })


class StoryReplyAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk, expires_at__gt=timezone.now())
        if not can_view_story(story, request.user):
            return Response({"error": "This story is not available to you."}, status=status.HTTP_403_FORBIDDEN)
        content = request.data.get("content", "").strip()
        if not content:
            return Response({"error": "Reply cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
        reply = StoryReply.objects.create(story=story, author=request.user, content=content[:500])
        return Response(StoryReplySerializer(reply).data, status=status.HTTP_201_CREATED)


class StoryViewers(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        story = get_object_or_404(Story, pk=pk, author=request.user)
        viewers = User.objects.filter(story_views__story=story).distinct().select_related("profile")
        return Response({"viewers": [{"id": user.id, "username": user.username} for user in viewers]})


class StoryDelete(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        story = get_object_or_404(Story, pk=pk, author=request.user)
        story.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class Reels(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        posts = PostsModel.objects.filter(
            video__isnull=False,
        ).exclude(video="").exclude(profile__visibility="private").select_related("profile__user").order_by("-created", "-id")
        return Response(PostsSerializer(posts, many=True, context={"request": request}).data)


class ReelViewAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(PostsModel, pk=pk, video__isnull=False)
        ReelView.objects.get_or_create(post=post, user=request.user)
        return Response({"views": post.reel_views.count()})


class ReelShareAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(PostsModel, pk=pk, video__isnull=False)
        PostsModel.objects.filter(pk=post.pk).update(share_count=F("share_count") + 1)
        post.refresh_from_db(fields=["share_count"])
        return Response({"shares": post.share_count})


class PostComments(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = get_object_or_404(PostsModel, pk=pk)
        return Response({"comments": CommentSerializer(post.comments.select_related("author"), many=True).data})

    def post(self, request, pk):
        post = get_object_or_404(PostsModel, pk=pk)
        content = request.data.get("content", "").strip()
        parent = None
        parent_id = request.data.get("parent")
        if parent_id:
            parent = get_object_or_404(Comment, pk=parent_id, post=post)
        if not content:
            return Response({"error": "Comment cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
        comment = Comment.objects.create(post=post, author=request.user, parent=parent, content=content)
        recipient = parent.author if parent else post.profile.user
        if recipient != request.user:
            SendNotification("Comment", recipient, request.user, content[:40])
        NotifyMentions(request.user, content)
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CommentDetail(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        if comment.author_id != request.user.id:
            return Response({"error": "You can only edit your own comment."}, status=status.HTTP_403_FORBIDDEN)
        content = request.data.get("content", "").strip()
        if not content:
            return Response({"error": "Comment cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
        comment.content = content
        comment.save(update_fields=["content"])
        return Response(CommentSerializer(comment).data)

    def delete(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        if comment.author_id != request.user.id and comment.post.profile.user_id != request.user.id:
            return Response({"error": "You cannot delete this comment."}, status=status.HTTP_403_FORBIDDEN)
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class toggleLike(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        try:
            post = PostsModel.objects.get(pk=pk)
        except PostsModel.DoesNotExist:
            return Response({"error": "Post not found"}, status=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        other_user = post.profile.user
        if user in post.liked_by.all():
            post.liked_by.remove(user)
            liked = False
        else:
            post.disliked_by.remove(user)
            post.liked_by.add(user)
            liked = True
            if user != other_user:
                SendNotification("Like", other_user, user, post.content[:18])
        return Response({"Liked": liked, "Count": post.liked_by.count()})


class toggleDislike(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(PostsModel, pk=pk)
        if post.disliked_by.filter(pk=request.user.pk).exists():
            post.disliked_by.remove(request.user)
            disliked = False
        else:
            post.liked_by.remove(request.user)
            post.disliked_by.add(request.user)
            disliked = True
        return Response({"Disliked": disliked, "Count": post.disliked_by.count()})
    
class toggleSave(APIView):
    permission_classes=[IsAuthenticated]

    def post(self,request,pk):
        try:
            post = PostsModel.objects.get(pk=pk)      
        except PostsModel.DoesNotExist:
            return Response({"error": "Post not found"}, status=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        other_user = post.profile.user
        if user in post.saved_by.all():
            post.saved_by.remove(user)
            Saved = False
        elif user == other_user:
            post.saved_by.add(user)
            Saved = True
        else:
            post.saved_by.add(user)
            Saved = True
        return Response({"Saved": Saved, "Count": post.saved_by.count()})
        

        

class ProfileData(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request):
        user = request.user

        profile = Profile.objects.get(user=user)
        liked_posts = user.liked_posts.all()
        saved_posts = user.saved_posts.all()

        disliked_posts = user.disliked_posts.all()
        LikedPosts = PostsSerializer(liked_posts, many=True, context={"request": request})
        DislikedPosts = PostsSerializer(disliked_posts, many=True, context={"request": request})
        SavedPosts = PostsSerializer(saved_posts, many=True)

        profile_data = {
            "id": profile.id,
            "bio": profile.bio,
            "user": {"username": user.username,
                     "email": user.email},
            "liked_posts": LikedPosts.data,
            "disliked_posts": DislikedPosts.data,
            "saved_posts": SavedPosts.data
        }
        if profile.pfp and hasattr(profile.pfp, "url"):
            profile_data["pfp"] = profile.pfp.url  
        else:
            profile_data["pfp"] = None  
        profile_data["cover"] = request.build_absolute_uri(profile.cover.url) if profile.cover else None
        profile_data["visibility"] = profile.visibility

        

        return Response(profile_data)
    
    def patch(self,request):
        try:
            profile = Profile.objects.get(user=request.user)
        except Profile.DoesNotExist:
            return Response ({"error": "Profile not found"})
        
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request, username):
        user = request.user
        profileUser = get_object_or_404(User, username=username)
        if profileUser != user and UserBlock.objects.filter(Q(blocker=user, blocked=profileUser) | Q(blocker=profileUser, blocked=user)).exists():
            return Response({"error": "This profile is unavailable."}, status=status.HTTP_403_FORBIDDEN)
        profile = get_object_or_404(Profile, user=profileUser)
        

        liked_posts = user.liked_posts.all()
        saved_posts = user.saved_posts.all()
        LikedPosts = PostsSerializer(liked_posts, many=True)
        SavedPosts = PostsSerializer(saved_posts, many=True)
        
        owner = profileUser == user

        data = {
            "username": profile.user.username,
            "bio": profile.bio,
            "followers_count": len(Follow.objects.followers(profile.user)),
            "following_count": len(Follow.objects.following(profile.user)),
            "isowner": owner,
            "visibility": profile.visibility,

        }

        if profile.pfp and hasattr(profile.pfp, "url"):
            data["pfp"] = profile.pfp.url  
        else:
            data["pfp"] = None  

        if owner:
            data["liked"] = LikedPosts.data
            data["saved"] = SavedPosts.data

        data["cover"] = request.build_absolute_uri(profile.cover.url) if profile.cover else None
        data["posts"] = PostsSerializer(profile.posts.all(), many=True).data if owner or profile.visibility == "public" else []
        data["followers"] = UserSerializer(Follow.objects.followers(profile.user), many=True).data
        data["following"] = UserSerializer(Follow.objects.following(profile.user), many=True).data

        return Response(data)
            
def SendNotification(type, recipient, sender, content):
    preference_map = {
        "Like": "likes",
        "Comment": "comments",
        "Follow": "follows",
        "Message": "messages",
        "Request": "requests",
        "Group": "groups",
    }
    preference, _ = NotificationPreference.objects.get_or_create(user=recipient)
    if not getattr(preference, preference_map.get(type, "messages"), True):
        return
    if type == "Like":
        if not Notifications.objects.filter(recipient=recipient, sender=sender, message=f"{sender} liked your post! {content}", notif_type="LIKE").exists():
            Notifications.objects.create(recipient=recipient, sender=sender, message=f"{sender} liked your post! '{content}'",notif_type="LIKE")

    if type == "Follow":
        if not Notifications.objects.filter(recipient=recipient, sender=sender, message=f"{sender} started following you!.", notif_type="FOLLOW").exists():
            Notifications.objects.create(recipient=recipient, sender=sender, message=f"{sender} started following you!.",notif_type="FOLLOW")

    if type == "Comment":
        Notifications.objects.create(
            recipient=recipient,
            sender=sender,
            message=f"{sender} commented: '{content}'",
            notif_type="COMMENT",
        )

    if type == "Group":
        Notifications.objects.create(recipient=recipient, sender=sender, message=content, notif_type="GROUP")


def NotifyMentions(sender, content):
    for username in set(re.findall(r"@([A-Za-z0-9_]+)", content or "")):
        recipient = User.objects.filter(username=username).first()
        if recipient and recipient != sender:
            Notifications.objects.create(recipient=recipient, sender=sender, message=f"{sender} mentioned you.", notif_type="MENTION")

    if type == "Message":
        Notifications.objects.create(
            recipient=recipient,
            sender=sender,
            message=f"{sender} sent you a message.",
            notif_type="MESSAGE",
        )

    if type == "Request":
        if not Notifications.objects.filter(recipient=recipient, sender=sender, notif_type="REQUEST", message=f"{sender} sent you a message request.").exists():
            Notifications.objects.create(
                recipient=recipient,
                sender=sender,
                message=f"{sender} sent you a message request.",
                notif_type="REQUEST",
            )

class toggleFollow(APIView):
    def post(self, request, pk):
        try:
            other_user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        user = request.user

        if other_user == user:
            return Response({"error": "You cannot add yourself!"}, status=status.HTTP_400_BAD_REQUEST)
        
        if other_user in Follow.objects.following(user):
            Follow.objects.remove_follower(request.user, other_user)
            following=False
            return Response({"message": f"You are not following {other_user} anymore!!", "Following":following},status=status.HTTP_200_OK)
        
        Follow.objects.add_follower(user, other_user)
        SendNotification("Follow", other_user, user, None)
        following=True
        return Response({"message": f"{user} is following {other_user} now !!!", "Following":following})
    
class getFollowings(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        Followings = Follow.objects.following(user)
        following_ser = ({"id": u.id} for u in Followings)
        return Response({"followings":following_ser})


class FollowingsPosts(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        
        followings = Follow.objects.following(user)

        posts = PostsModel.objects.filter(profile__user__in=followings).order_by('-created')

        serializer = PostsSerializer(posts,many=True)

        return Response({"posts": serializer.data})


class Feed(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        friend_ids = User.objects.filter(
            Q(sent_friend_requests__recipient=request.user, sent_friend_requests__status="accepted")
            | Q(received_friend_requests__sender=request.user, received_friend_requests__status="accepted")
        ).values("id")
        group_ids = Group.objects.filter(members=request.user).values("id")
        posts = PostsModel.objects.filter(
            Q(profile__user=request.user)
            | Q(profile__user__in=friend_ids)
            | Q(group__in=group_ids)
        ).exclude(profile__user__in=UserBlock.objects.filter(blocked=request.user).values("blocker")).select_related("profile__user", "group").order_by("-created")
        return Response(PostsSerializer(posts, many=True).data)


class AllUsers(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        users = User.objects.exclude(id=user.id).select_related("profile").order_by("username")

        result = []
        for other_user in users:
            profile = getattr(other_user, "profile", None)
            result.append({
                "id": other_user.id,
                "username": other_user.username,
                "email": other_user.email,
                "bio": profile.bio if profile else "",
                "pfp": profile.pfp.url if profile and profile.pfp else None,
                "is_following": other_user in Follow.objects.following(user),
                "is_following_back": user in Follow.objects.following(other_user),
                "can_message": users_follow_each_other(user, other_user),
            })

        return Response({"users": result})


class UserSearch(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response({"users": []})

        users = User.objects.exclude(pk=request.user.pk).filter(
            username__icontains=query
        ).select_related("profile").order_by("username")[:20]
        accepted_ids = set(User.objects.filter(
            Q(sent_friend_requests__recipient=request.user, sent_friend_requests__status="accepted")
            | Q(received_friend_requests__sender=request.user, received_friend_requests__status="accepted")
        ).values_list("id", flat=True))
        pending_ids = set(FriendRequest.objects.filter(
            Q(sender=request.user, status="pending") | Q(recipient=request.user, status="pending")
        ).values_list("sender_id", "recipient_id"))
        pending_user_ids = {user_id for pair in pending_ids for user_id in pair if user_id != request.user.pk}

        results = []
        for user in users:
            profile = getattr(user, "profile", None)
            results.append({
                "id": user.id,
                "username": user.username,
                "bio": profile.bio if profile else "",
                "pfp": request.build_absolute_uri(profile.pfp.url) if profile and profile.pfp else None,
                "relationship": "friends" if user.id in accepted_ids else "pending" if user.id in pending_user_ids else "none",
            })
        return Response({"users": results})


class FriendRequests(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        incoming = FriendRequest.objects.filter(recipient=request.user).select_related("sender", "recipient")
        outgoing = FriendRequest.objects.filter(sender=request.user).select_related("sender", "recipient")
        friends = User.objects.filter(
            Q(sent_friend_requests__recipient=request.user, sent_friend_requests__status="accepted")
            | Q(received_friend_requests__sender=request.user, received_friend_requests__status="accepted")
        ).distinct()
        return Response({
            "incoming": FriendRequestSerializer(incoming, many=True).data,
            "outgoing": FriendRequestSerializer(outgoing, many=True).data,
            "friends": UserSerializer(friends, many=True).data,
        })

    def post(self, request):
        username = request.data.get("username", "").strip()
        if not username:
            return Response({"error": "Enter a username."}, status=status.HTTP_400_BAD_REQUEST)
        recipient = get_object_or_404(User, username__iexact=username)
        if recipient == request.user:
            return Response({"error": "You cannot send a request to yourself."}, status=status.HTTP_400_BAD_REQUEST)
        existing = FriendRequest.objects.filter(sender=request.user, recipient=recipient).first()
        if existing and existing.status == "pending":
            return Response({"error": "Request already pending."}, status=status.HTTP_400_BAD_REQUEST)
        if existing and existing.status == "accepted":
            return Response({"message": "You are already friends."}, status=status.HTTP_200_OK)
        reverse = FriendRequest.objects.filter(sender=recipient, recipient=request.user, status="pending").first()
        if reverse:
            reverse.status = "accepted"
            reverse.save(update_fields=["status", "updated_at"])
            return Response({"message": "Friend request accepted."})
        if FriendRequest.objects.filter(sender=recipient, recipient=request.user, status="accepted").exists():
            return Response({"message": "You are already friends."}, status=status.HTTP_200_OK)
        request_obj, _ = FriendRequest.objects.update_or_create(
            sender=request.user,
            recipient=recipient,
            defaults={"status": "pending"},
        )
        return Response(FriendRequestSerializer(request_obj).data, status=status.HTTP_201_CREATED)


class FriendRequestDecision(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, decision):
        friend_request = get_object_or_404(FriendRequest, pk=pk, recipient=request.user, status="pending")
        if decision not in ("accept", "reject"):
            return Response({"error": "Invalid decision."}, status=status.HTTP_400_BAD_REQUEST)
        friend_request.status = "accepted" if decision == "accept" else "rejected"
        friend_request.save(update_fields=["status", "updated_at"])
        return Response({"message": f"Friend request {friend_request.status}."})


class Groups(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = Group.objects.filter(members=request.user).select_related("owner")
        return Response({"groups": GroupSerializer(groups, many=True, context={"request": request}).data})

    def post(self, request):
        name = request.data.get("name", "").strip()
        description = request.data.get("description", "").strip()
        visibility = request.data.get("visibility", "public")
        if not name:
            return Response({"error": "Group name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if visibility not in ("public", "private"):
            return Response({"error": "Invalid group visibility."}, status=status.HTTP_400_BAD_REQUEST)
        group = Group.objects.create(
            name=name,
            description=description,
            owner=request.user,
            visibility=visibility,
            avatar=request.FILES.get("avatar"),
            cover=request.FILES.get("cover"),
        )
        GroupMembership.objects.create(group=group, user=request.user, role="owner")
        return Response(GroupSerializer(group, context={"request": request}).data, status=status.HTTP_201_CREATED)


class GroupDirectory(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = Group.objects.select_related("owner").filter(Q(visibility="public") | Q(members=request.user)).distinct()
        return Response({"groups": GroupSerializer(groups, many=True, context={"request": request}).data})


class GroupDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        group = get_object_or_404(Group.objects.select_related("owner"), pk=pk)
        membership = GroupMembership.objects.filter(group=group, user=request.user, status="active").exists()
        if group.visibility == "private" and not membership and group.owner_id != request.user.id:
            return Response({"error": "Join this private group to view it."}, status=status.HTTP_403_FORBIDDEN)
        data = GroupSerializer(group, context={"request": request}).data
        memberships = GroupMembership.objects.filter(group=group).select_related("user", "user__profile")
        data["members"] = GroupMemberSerializer(
            memberships.filter(status="active"), many=True, context={"request": request}
        ).data
        manager = memberships.filter(user=request.user, status="active", role__in=["owner", "moderator"]).exists()
        data["can_manage"] = manager
        if manager:
            data["pending_members"] = GroupMemberSerializer(
                memberships.filter(status="pending"), many=True, context={"request": request}
            ).data
        data["posts"] = PostsSerializer(group.posts.select_related("profile__user"), many=True, context={"request": request}).data
        return Response(data)


class GroupMembershipAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        group = get_object_or_404(Group, pk=pk)
        membership = GroupMembership.objects.filter(group=group, user=request.user).first()
        if action == "join":
            status_value = "pending" if group.visibility == "private" else "active"
            membership, created = GroupMembership.objects.get_or_create(group=group, user=request.user, defaults={"status": status_value})
            if not created and membership.status == "pending":
                return Response({"message": "Join request already pending."})
            if not created:
                membership.status = status_value
                membership.save(update_fields=["status"])
            return Response({"message": "Join request sent." if status_value == "pending" else "Joined group."})
        if action == "leave":
            if group.owner_id == request.user.id:
                return Response({"error": "The group owner cannot leave the group."}, status=status.HTTP_400_BAD_REQUEST)
            if membership:
                membership.delete()
            return Response({"message": "Left group."})
        return Response({"error": "Invalid group action."}, status=status.HTTP_400_BAD_REQUEST)


class GroupMemberAction(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, user_id, action):
        group = get_object_or_404(Group, pk=pk)
        manager = GroupMembership.objects.filter(group=group, user=request.user, status="active", role__in=["owner", "moderator"]).exists()
        if not manager:
            return Response({"error": "Only group managers can manage members."}, status=status.HTTP_403_FORBIDDEN)
        member = get_object_or_404(User, pk=user_id)
        if action == "add":
            GroupMembership.objects.update_or_create(group=group, user=member, defaults={"status": "active"})
            return Response({"message": "Member added."})
        if action in ("approve", "reject"):
            membership = get_object_or_404(GroupMembership, group=group, user=member, status="pending")
            if action == "approve":
                membership.status = "active"
                membership.save(update_fields=["status"])
            else:
                membership.delete()
            return Response({"message": f"Membership {action}d."})
        if action == "promote":
            membership = get_object_or_404(GroupMembership, group=group, user=member, status="active")
            membership.role = "moderator"
            membership.save(update_fields=["role"])
            return Response({"message": "Member promoted."})
        if action == "demote":
            membership = get_object_or_404(GroupMembership, group=group, user=member, status="active")
            if membership.role != "moderator":
                return Response({"error": "Member is not a moderator."}, status=status.HTTP_400_BAD_REQUEST)
            membership.role = "member"
            membership.save(update_fields=["role"])
            return Response({"message": "Moderator demoted."})
        if action == "remove":
            if member.id == group.owner_id:
                return Response({"error": "The group owner cannot be removed."}, status=status.HTTP_400_BAD_REQUEST)
            GroupMembership.objects.filter(group=group, user=member).delete()
            return Response({"message": "Member removed."})
        return Response({"error": "Invalid member action."}, status=status.HTTP_400_BAD_REQUEST)


def users_follow_each_other(first_user, second_user):
    return (
        second_user in Follow.objects.following(first_user)
        and first_user in Follow.objects.following(second_user)
    )


class Conversations(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conversations = Conversation.objects.filter(
            Q(user_one=request.user) | Q(user_two=request.user)
        ).exclude(
            user_one__in=UserBlock.objects.filter(blocked=request.user).values("blocker")
        ).exclude(
            user_two__in=UserBlock.objects.filter(blocked=request.user).values("blocker")
        ).prefetch_related("messages")
        serializer = ConversationSerializer(
            conversations,
            many=True,
            context={"request": request},
        )
        return Response({"conversations": serializer.data})

    def post(self, request):
        username = request.data.get("username", "").strip()
        other_user = get_object_or_404(User, username=username)

        if UserBlock.objects.filter(Q(blocker=request.user, blocked=other_user) | Q(blocker=other_user, blocked=request.user)).exists():
            return Response({"error": "Messaging is unavailable for this user."}, status=status.HTTP_403_FORBIDDEN)

        if other_user == request.user:
            return Response(
                {"error": "You cannot message yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_one, user_two = sorted(
            [request.user, other_user],
            key=lambda user: user.id,
        )

        existing_conversation = Conversation.objects.filter(
            user_one=user_one,
            user_two=user_two,
        ).first()
        if existing_conversation:
            serializer = ConversationSerializer(
                existing_conversation,
                context={"request": request},
            )
            return Response(serializer.data)

        if not users_follow_each_other(request.user, other_user):
            content = request.data.get("content", "").strip()
            if not content:
                return Response(
                    {"error": "You need to send a message request first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            pending_request = MessageRequest.objects.filter(
                sender=request.user,
                recipient=other_user,
                status="pending",
            ).first()
            if not pending_request:
                pending_request = MessageRequest.objects.create(
                    sender=request.user,
                    recipient=other_user,
                    content=content,
                )
                SendNotification("Request", other_user, request.user, None)
            return Response(
                {
                    "request_created": True,
                    "message_request": MessageRequestSerializer(pending_request).data,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        conversation, _ = Conversation.objects.get_or_create(
            user_one=user_one,
            user_two=user_two,
        )
        serializer = ConversationSerializer(
            conversation,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MessageRequests(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        incoming = MessageRequest.objects.filter(
            recipient=request.user,
            status="pending",
        ).select_related("sender", "recipient")
        outgoing = MessageRequest.objects.filter(
            sender=request.user,
            status="pending",
        ).select_related("sender", "recipient")
        return Response({
            "incoming": MessageRequestSerializer(incoming, many=True).data,
            "outgoing": MessageRequestSerializer(outgoing, many=True).data,
        })


class MessageRequestDecision(APIView):
    permission_classes = [IsAuthenticated]

    def get_request(self, request, pk):
        return get_object_or_404(
            MessageRequest.objects.select_related("sender", "recipient"),
            id=pk,
            recipient=request.user,
            status="pending",
        )

    def post(self, request, pk, decision):
        message_request = self.get_request(request, pk)
        if decision == "reject":
            message_request.status = "rejected"
            message_request.save(update_fields=["status", "updated_at"])
            return Response({"message": "Message request rejected."})

        user_one, user_two = sorted(
            [message_request.sender, message_request.recipient],
            key=lambda user: user.id,
        )
        conversation, _ = Conversation.objects.get_or_create(
            user_one=user_one,
            user_two=user_two,
        )
        Message.objects.create(
            conversation=conversation,
            sender=message_request.sender,
            content=message_request.content,
        )
        conversation.save(update_fields=["updated_at"])
        message_request.status = "accepted"
        message_request.save(update_fields=["status", "updated_at"])
        return Response({
            "message": "Message request accepted.",
            "conversation": ConversationSerializer(
                conversation,
                context={"request": request},
            ).data,
        })


class ConversationMessages(APIView):
    permission_classes = [IsAuthenticated]

    def get_conversation(self, request, pk):
        return get_object_or_404(
            Conversation.objects.prefetch_related("messages__sender"),
            Q(id=pk) & (Q(user_one=request.user) | Q(user_two=request.user)),
        )

    def get(self, request, pk):
        conversation = self.get_conversation(request, pk)
        conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
        serializer = MessageSerializer(conversation.messages.all(), many=True)
        return Response({"messages": serializer.data})

    def post(self, request, pk):
        conversation = self.get_conversation(request, pk)
        content = request.data.get("content", "").strip()
        if not content:
            return Response(
                {"error": "Message content cannot be empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        conversation.save(update_fields=["updated_at"])
        recipient = conversation.user_two if conversation.user_one == request.user else conversation.user_one
        SendNotification("Message", recipient, request.user, content)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get_message(self, request, pk):
        return get_object_or_404(
            Message.objects.select_related("sender", "conversation"),
            Q(id=pk) & (
                Q(conversation__user_one=request.user)
                | Q(conversation__user_two=request.user)
            ),
        )

    def patch(self, request, pk):
        message = self.get_message(request, pk)
        if message.sender_id != request.user.id:
            return Response(
                {"error": "You can only edit your own messages."},
                status=status.HTTP_403_FORBIDDEN,
            )

        content = request.data.get("content", "").strip()
        if not content:
            return Response(
                {"error": "Message content cannot be empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(content) > 2000:
            return Response(
                {"error": "Messages must be 2000 characters or shorter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message.content = content
        message.save(update_fields=["content"])
        return Response(MessageSerializer(message).data)

    def delete(self, request, pk):
        message = self.get_message(request, pk)
        if message.sender_id != request.user.id:
            return Response(
                {"error": "You can only delete your own messages."},
                status=status.HTTP_403_FORBIDDEN,
            )

        message.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class getNoti(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request):
        user = request.user
        mode = request.query_params.get("mode")
        if mode == "bell":
            recevied = (
                user.Notireceived
                .select_related("sender", "sender__profile")
                .order_by("-created")[:3]
            )
        elif mode == "page":
             recevied = (
                user.Notireceived
                .select_related("sender", "sender__profile")
                .order_by("-created")
            )

        unread_count = user.Notireceived.filter(is_read=False).count()
        serializer = NotificationSerializer(
            recevied,
            many = True,
            context={"request":request}
        )
        return Response({"notifications": serializer.data, "unread_count": unread_count})


class NotificationRead(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None):
        notifications = request.user.Notireceived.filter(is_read=False)
        if pk:
            notifications = notifications.filter(pk=pk)
        updated = notifications.update(is_read=True)
        return Response({"marked_read": updated})


class NotificationPreferences(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response({field: getattr(preference, field) for field in ["likes", "comments", "follows", "messages", "requests", "groups"]})

    def patch(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        allowed = ["likes", "comments", "follows", "messages", "requests", "groups"]
        for field in allowed:
            if field in request.data:
                setattr(preference, field, bool(request.data[field]))
        preference.save()
        return Response({field: getattr(preference, field) for field in allowed})


class ChangePassword(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.check_password(request.data.get("current_password", "")):
            return Response({"error": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        new_password = request.data.get("new_password", "")
        if len(new_password) < 8:
            return Response({"error": "New password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(new_password)
        request.user.save(update_fields=["password"])
        return Response({"message": "Password changed successfully."})


class PasswordResetRequest(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user = User.objects.filter(email=request.data.get("email", "").strip()).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            send_mail(
                "Reset your CircleUp password",
                f"Reset your CircleUp password: {settings.FRONTEND_URL}/password-reset/confirm?uid={uid}&token={token}",
                None,
                [user.email],
                fail_silently=False,
            )
        return Response({"message": "If an account exists, password reset instructions will be sent."})


class LoginHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        history = request.user.login_history.all()[:20]
        return Response({"history": [{"id": item.id, "ip_address": item.ip_address, "user_agent": item.user_agent, "created_at": item.created_at} for item in history]})


class ActiveSessions(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = []
        for session in Session.objects.filter(expire_date__gte=timezone.now()):
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(request.user.id):
                sessions.append({"session_key": session.session_key, "current": session.session_key == request.session.session_key, "expires_at": session.expire_date})
        return Response({"sessions": sessions})

    def delete(self, request):
        for session in Session.objects.filter(expire_date__gte=timezone.now()):
            if str(session.get_decoded().get("_auth_user_id")) == str(request.user.id) and session.session_key != request.session.session_key:
                session.delete()
        return Response({"message": "Other sessions revoked."})


class BlockUser(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, username):
        blocked = get_object_or_404(User, username=username)
        if blocked == request.user:
            return Response({"error": "You cannot block yourself."}, status=status.HTTP_400_BAD_REQUEST)
        block, created = UserBlock.objects.get_or_create(blocker=request.user, blocked=blocked)
        if not created:
            block.delete()
            return Response({"blocked": False})
        return Response({"blocked": True})

class UserCheck(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request):
        return Response({"message": "Authenticated!"})

class DeletePost(APIView):
    permission_classes =[IsAuthenticated]

    def post(self,request):
        post_id = request.data.get('id')
        try:
            post = PostsModel.objects.get(id=post_id)
        except PostsModel.DoesNotExist:
            return Response({"error": "Post not found"})
        
        post.delete()
        return Response({"message": "Post has been deleted"},status=status.HTTP_200_OK)
    
class Visibility(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        visibility = request.data.get("visibility")
        profile = Profile.objects.get(user=user)

        choices = ["public", "private"]
        if visibility not in choices:
            return Response({"error":"invalid data"}, status=status.HTTP_400_BAD_REQUEST)

        profile.visibility = visibility
        profile.save()

        return Response({"message": "Visibility updated", "visibility": profile.visibility}, status=status.HTTP_200_OK)
    
class UpdateAccount(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self,request):
        user = request.user

        username = request.data.get("username")
        email = request.data.get("email")

        if username:
            if User.objects.exclude(id=user.id).filter(username=username).exists():
                return Response({"error": "Username is already taken"}, status=status.HTTP_400_BAD_REQUEST)
            user.username = username
        
        if email:
            if User.objects.exclude(id=user.id).filter(username=username).exists():
                return Response({"error": "Email is already taken"}, status=status.HTTP_400_BAD_REQUEST)
            user.email = email
        
        user.save()
        return Response(
            {"message": "Account has been updated successfully", "username": user.username, "email": user.email},
            status=status.HTTP_200_OK
        )

class DeleteUser(APIView):
    permission_classes = [IsAuthenticated]
    def post(self,request):
        user = request.user
        user.delete()

        return Response({"message": "User deleted"}, status=status.HTTP_200_OK)
