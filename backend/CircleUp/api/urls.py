from django.urls import path
from .views import * 
urlpatterns = [
    
    path("signup/", Signup.as_view()),
    path("verify-email/<uuid:token>/", VerifyEmail.as_view(), name="email-verify"),
    path("signin/", Signin.as_view(), name=""),
    path("csrftoken/", csrftoken.as_view(), name=""),

    path("logout/", logoutView.as_view(), name=""),

    path("posts/", Posts.as_view()),
    path("stories/", Stories.as_view()),
    path("stories/<int:pk>/view/", StoryViewAction.as_view()),
    path("stories/<int:pk>/react/", StoryReactionAction.as_view()),
    path("stories/<int:pk>/reply/", StoryReplyAction.as_view()),
    path("stories/<int:pk>/viewers/", StoryViewers.as_view()),
    path("stories/<int:pk>/", StoryDelete.as_view()),
    path("reels/", Reels.as_view()),
    path("reels/<int:pk>/view/", ReelViewAction.as_view()),
    path("reels/<int:pk>/share/", ReelShareAction.as_view()),
    path("deletepost/", DeletePost.as_view(), name=""),

    path("profile/" , ProfileData.as_view()),
    path("publicprofile/<username>", UserProfileView.as_view(), name=""),
    
    path("visibility/", Visibility.as_view(), name=""),
    path("updateaccount/", UpdateAccount.as_view(), name=""),

    path("toggleLike/<int:pk>/", toggleLike.as_view()),
    path("toggleDislike/<int:pk>/", toggleDislike.as_view()),
    path("toggleSave/<int:pk>/", toggleSave.as_view()),

    path("follow/<int:pk>/", toggleFollow.as_view()),
    path("getfollow/", getFollowings.as_view()),
    path("followingsposts/", FollowingsPosts.as_view()),
    path("feed/", Feed.as_view()),
    path("all-users/", AllUsers.as_view()),
    path("users/search/", UserSearch.as_view()),
    path("comments/<int:pk>/", PostComments.as_view()),
    path("comment/<int:pk>/", CommentDetail.as_view()),
    path("friend-requests/", FriendRequests.as_view()),
    path("friend-requests/<int:pk>/<str:decision>/", FriendRequestDecision.as_view()),
    path("groups/", Groups.as_view()),
    path("groups/all/", GroupDirectory.as_view()),
    path("groups/<int:pk>/", GroupDetail.as_view()),
    path("groups/<int:pk>/<str:action>/", GroupMembershipAction.as_view()),
    path("groups/<int:pk>/members/<int:user_id>/<str:action>/", GroupMemberAction.as_view()),
    path("conversations/", Conversations.as_view()),
    path("conversations/<int:pk>/messages/", ConversationMessages.as_view()),
    path("message-requests/", MessageRequests.as_view()),
    path("message-requests/<int:pk>/<str:decision>/", MessageRequestDecision.as_view()),
    path("messages/<int:pk>/", MessageDetail.as_view()),

    path("getNoti/", getNoti.as_view()),
    path("notifications/read/", NotificationRead.as_view()),
    path("notifications/read/<int:pk>/", NotificationRead.as_view()),
    path("notification-preferences/", NotificationPreferences.as_view()),
    path("change-password/", ChangePassword.as_view()),
    path("password-reset/", PasswordResetRequest.as_view()),
    path("password-reset/confirm/", PasswordResetConfirm.as_view()),
    path("login-history/", LoginHistoryView.as_view()),
    path("sessions/", ActiveSessions.as_view()),
    path("block/<slug:username>/", BlockUser.as_view()),

    path("check/", UserCheck.as_view(), name=""),

    path("deleteuser/", DeleteUser.as_view(), name="")

]
