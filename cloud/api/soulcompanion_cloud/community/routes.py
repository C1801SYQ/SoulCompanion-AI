"""Community resources reuse the application's verified-user dependency."""

from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query, Request, Response

from ..family_identity import ChildAgeBand
from ..models import User
from .models import (
    CommentCreate, CommunityPage, CommunityTopic, ContentReportCreate, ContentReportReceipt,
    ContentReportResolve, ContentReportStatus, ContentStatus, EmptyCommunityBody, ModerationAction,
    OwnedComment, OwnedContentFeedback, OwnedPost, PostCreate, PostPatch, PostRelationState,
    PublicComment, PublicPost, RelationReceipt,
)
from .pagination import PageResult
from .service import CommunityRecord, CommunityService


TargetType = Literal["posts", "comments"]
Limit = Annotated[int, Query(ge=1, le=50)]
Cursor = Annotated[str | None, Query(max_length=1024)]
RequestKey = Annotated[str, Header(alias="Idempotency-Key", max_length=64)]


def register_routes(
    app: FastAPI, service: CommunityService, current_user: Callable[[Request], Awaitable[User]],
) -> None:
    router = APIRouter(prefix="/api/v2")
    Authenticated = Annotated[User, Depends(current_user)]

    @router.get("/community/posts", response_model=CommunityPage[PublicPost])
    async def posts(age_band: ChildAgeBand | None = None, topic: CommunityTopic | None = None,
                    limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_posts(age_band, topic, limit, cursor)

    @router.get("/community/posts/{post_id}", response_model=PublicPost)
    async def post(post_id: str) -> CommunityRecord:
        return await service.get_post(post_id)

    @router.get("/community/posts/{post_id}/comments", response_model=CommunityPage[PublicComment])
    async def comments(post_id: str, limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_comments(post_id, limit, cursor)

    @router.get("/community/comments/{comment_id}", response_model=PublicComment)
    async def comment(comment_id: str) -> CommunityRecord:
        return await service.get_comment(comment_id)

    @router.post("/community/posts", response_model=OwnedPost, status_code=201)
    async def create_post(body: PostCreate, user: Authenticated, response: Response, key: RequestKey = "") -> CommunityRecord:
        result, created = await service.create_post(str(user.id), body, key)
        response.status_code = 201 if created else 200
        return result

    @router.patch("/community/posts/{post_id}", response_model=OwnedPost)
    async def edit_post(post_id: str, body: PostPatch, user: Authenticated) -> CommunityRecord:
        return await service.edit_post(str(user.id), post_id, body)

    @router.delete("/community/posts/{post_id}", status_code=204)
    async def withdraw_post(post_id: str, user: Authenticated, expected_revision: Annotated[int, Query(ge=1)]) -> Response:
        await service.withdraw(str(user.id), "post", post_id, expected_revision)
        return Response(status_code=204)

    @router.post("/community/posts/{post_id}/comments", response_model=OwnedComment, status_code=201)
    async def create_comment(post_id: str, body: CommentCreate, user: Authenticated,
                             response: Response, key: RequestKey = "") -> CommunityRecord:
        result, created = await service.create_comment(str(user.id), post_id, body, key)
        response.status_code = 201 if created else 200
        return result

    @router.delete("/community/comments/{comment_id}", status_code=204)
    async def withdraw_comment(comment_id: str, user: Authenticated, expected_revision: Annotated[int, Query(ge=1)]) -> Response:
        await service.withdraw(str(user.id), "comment", comment_id, expected_revision)
        return Response(status_code=204)

    @router.get("/me/community/posts", response_model=CommunityPage[OwnedPost])
    async def my_posts(user: Authenticated, limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_owned(str(user.id), "post", limit, cursor)

    @router.get("/me/community/comments", response_model=CommunityPage[OwnedComment])
    async def my_comments(user: Authenticated, limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_owned(str(user.id), "comment", limit, cursor)

    @router.get("/me/community/posts/{post_id}/relations", response_model=PostRelationState)
    async def my_relations(post_id: str, user: Authenticated) -> CommunityRecord:
        return await service.get_relation_state(str(user.id), post_id)

    @router.get("/me/community/{target_type}/{target_id}/feedback", response_model=OwnedContentFeedback)
    async def my_feedback(target_type: TargetType, target_id: str, user: Authenticated) -> CommunityRecord:
        return await service.get_owned_feedback(str(user.id), "post" if target_type == "posts" else "comment", target_id)

    @router.api_route("/community/posts/{post_id}/like", methods=["PUT", "DELETE"], response_model=RelationReceipt)
    async def like(post_id: str, request: Request, user: Authenticated, body: EmptyCommunityBody | None = Body(default=None)) -> CommunityRecord:
        return await service.set_relation(str(user.id), post_id, "like", request.method == "PUT")

    @router.api_route("/community/posts/{post_id}/bookmark", methods=["PUT", "DELETE"], response_model=RelationReceipt)
    async def bookmark(post_id: str, request: Request, user: Authenticated, body: EmptyCommunityBody | None = Body(default=None)) -> CommunityRecord:
        return await service.set_relation(str(user.id), post_id, "bookmark", request.method == "PUT")

    @router.get("/me/community/bookmarks", response_model=CommunityPage[PublicPost])
    async def my_bookmarks(user: Authenticated, limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_bookmarks(str(user.id), limit, cursor)

    @router.post("/community/content-reports", response_model=ContentReportReceipt, status_code=201)
    async def create_report(body: ContentReportCreate, user: Authenticated, response: Response, key: RequestKey = "") -> CommunityRecord:
        result, created = await service.create_content_report(str(user.id), body, key)
        response.status_code = 201 if created else 200
        return result

    @router.get("/ops/moderation", response_model=CommunityPage[dict])
    async def moderation_queue(user: Authenticated, status: ContentStatus = "pending", limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_moderation(str(user.id), status, limit, cursor)

    @router.get("/ops/moderation/{target_type}/{target_id}", response_model=dict)
    async def moderation_content(target_type: TargetType, target_id: str, user: Authenticated) -> CommunityRecord:
        return await service.get_moderation(str(user.id), "post" if target_type == "posts" else "comment", target_id)

    @router.post("/ops/moderation/{target_type}/{target_id}/{action}", response_model=dict)
    async def moderate(target_type: TargetType, target_id: str, action: Literal["approve", "reject", "hide"],
                       body: ModerationAction, user: Authenticated, key: RequestKey = "") -> CommunityRecord:
        return await service.moderate(str(user.id), "post" if target_type == "posts" else "comment", target_id, action, body, key)

    @router.get("/ops/content-reports", response_model=CommunityPage[dict])
    async def report_queue(user: Authenticated, status: ContentReportStatus = "open", limit: Limit = 20, cursor: Cursor = None) -> PageResult[CommunityRecord]:
        return await service.list_content_reports(str(user.id), status, limit, cursor)

    @router.post("/ops/content-reports/{report_id}/resolve", response_model=dict)
    async def resolve_report(report_id: str, body: ContentReportResolve, user: Authenticated, key: RequestKey = "") -> CommunityRecord:
        return await service.resolve_content_report(str(user.id), report_id, body, key)

    @router.get("/me/community/{target_type}/{target_id}", response_model=OwnedPost | OwnedComment)
    async def my_content(target_type: TargetType, target_id: str, user: Authenticated) -> CommunityRecord:
        return await service.get_owned(str(user.id), "post" if target_type == "posts" else "comment", target_id)

    app.include_router(router)
