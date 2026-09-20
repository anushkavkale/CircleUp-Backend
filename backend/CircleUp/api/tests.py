from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from .models import FriendRequest, Group, GroupMembership, PostsModel, Profile, Story, StoryReaction, StoryReply, StoryView


class SocialInteractionTests(TestCase):
	def setUp(self):
		self.owner = User.objects.create_user(username="owner", password="password123")
		self.other = User.objects.create_user(username="other", password="password123")
		Profile.objects.create(user=self.owner)
		Profile.objects.create(user=self.other)
		self.post = PostsModel.objects.create(profile=self.owner.profile, content="Test post")
		self.client.force_login(self.other)

	def test_like_and_dislike_are_mutually_exclusive(self):
		like_response = self.client.post(f"/api/toggleLike/{self.post.id}/")
		self.assertEqual(like_response.status_code, 200)
		self.assertTrue(self.post.liked_by.filter(pk=self.other.pk).exists())
		self.assertFalse(self.post.disliked_by.filter(pk=self.other.pk).exists())

		dislike_response = self.client.post(f"/api/toggleDislike/{self.post.id}/")
		self.assertEqual(dislike_response.status_code, 200)
		self.post.refresh_from_db()
		self.assertFalse(self.post.liked_by.filter(pk=self.other.pk).exists())
		self.assertTrue(self.post.disliked_by.filter(pk=self.other.pk).exists())

		self.client.post(f"/api/toggleDislike/{self.post.id}/")
		self.assertFalse(self.post.disliked_by.filter(pk=self.other.pk).exists())


class FriendSearchTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username="searcher", password="password123")
		self.friend = User.objects.create_user(username="friendly", password="password123")
		self.pending = User.objects.create_user(username="pending", password="password123")
		Profile.objects.create(user=self.user)
		Profile.objects.create(user=self.friend)
		Profile.objects.create(user=self.pending)
		FriendRequest.objects.create(sender=self.user, recipient=self.friend, status="accepted")
		FriendRequest.objects.create(sender=self.user, recipient=self.pending, status="pending")
		self.client.force_login(self.user)

	def test_user_search_returns_relationship_status(self):
		friend_response = self.client.get("/api/users/search/?q=fri")
		pending_response = self.client.get("/api/users/search/?q=pen")
		self.assertEqual(friend_response.status_code, 200)
		self.assertEqual(pending_response.status_code, 200)
		self.assertEqual(friend_response.json()["users"][0]["relationship"], "friends")
		self.assertEqual(pending_response.json()["users"][0]["relationship"], "pending")

	def test_existing_friend_cannot_receive_duplicate_request(self):
		response = self.client.post("/api/friend-requests/", {"username": "friendly"})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["message"], "You are already friends.")


class GroupManagementTests(TestCase):
	def setUp(self):
		self.owner = User.objects.create_user(username="groupowner", password="password123")
		self.member = User.objects.create_user(username="groupmember", password="password123")
		Profile.objects.create(user=self.owner)
		Profile.objects.create(user=self.member)
		self.group = Group.objects.create(name="Test group", owner=self.owner)
		GroupMembership.objects.create(group=self.group, user=self.owner, role="owner", status="active")
		GroupMembership.objects.create(group=self.group, user=self.member, status="pending")
		self.client.force_login(self.owner)

	def test_manager_can_approve_promote_and_demote_member(self):
		approve = self.client.post(f"/api/groups/{self.group.id}/members/{self.member.id}/approve/")
		self.assertEqual(approve.status_code, 200)

		promote = self.client.post(f"/api/groups/{self.group.id}/members/{self.member.id}/promote/")
		self.assertEqual(promote.status_code, 200)
		membership = GroupMembership.objects.get(group=self.group, user=self.member)
		self.assertEqual(membership.role, "moderator")

		demote = self.client.post(f"/api/groups/{self.group.id}/members/{self.member.id}/demote/")
		self.assertEqual(demote.status_code, 200)
		membership.refresh_from_db()
		self.assertEqual(membership.role, "member")


class StoryTests(TestCase):
	def setUp(self):
		self.author = User.objects.create_user(username="storyauthor", password="password123")
		self.friend = User.objects.create_user(username="storyfriend", password="password123")
		self.stranger = User.objects.create_user(username="storystranger", password="password123")
		Profile.objects.create(user=self.author)
		Profile.objects.create(user=self.friend)
		Profile.objects.create(user=self.stranger)
		FriendRequest.objects.create(sender=self.author, recipient=self.friend, status="accepted")

	def test_expired_stories_are_not_returned(self):
		Story.objects.create(author=self.author, privacy="public", expires_at=timezone.now() - timedelta(minutes=1))
		self.client.force_login(self.stranger)
		response = self.client.get("/api/stories/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["stories"], [])

	def test_friends_privacy_and_story_interactions(self):
		story = Story.objects.create(author=self.author, privacy="friends", expires_at=timezone.now() + timedelta(hours=24))
		self.client.force_login(self.stranger)
		stranger_response = self.client.get("/api/stories/")
		self.assertEqual(stranger_response.json()["stories"], [])

		self.client.force_login(self.friend)
		friend_response = self.client.get("/api/stories/")
		self.assertEqual(len(friend_response.json()["stories"]), 1)
		self.assertEqual(self.client.post(f"/api/stories/{story.id}/view/").status_code, 200)
		self.assertEqual(self.client.post(f"/api/stories/{story.id}/react/", {"reaction": "love"}).status_code, 200)
		reply_response = self.client.post(f"/api/stories/{story.id}/reply/", {"content": "Nice story!"})
		self.assertEqual(reply_response.status_code, 201)
		self.assertTrue(StoryView.objects.filter(story=story, user=self.friend).exists())
		self.assertTrue(StoryReaction.objects.filter(story=story, user=self.friend, reaction="love").exists())
		self.assertTrue(StoryReply.objects.filter(story=story, author=self.friend).exists())
