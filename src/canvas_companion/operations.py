"""Fixed Canvas read operations adapted from the original personal connector."""

from typing import Any

from .network import ServiceError as CanvasError


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CanvasError(f"{name} must be an integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CanvasError(f"{name} must be an integer.") from exc
    if result <= 0:
        raise CanvasError(f"{name} must be positive.")
    return result


def _date_query(args: dict[str, Any]) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if args.get("start_date"):
        query["start_date"] = args["start_date"]
    if args.get("end_date"):
        query["end_date"] = args["end_date"]
    return query


async def _active_course_ids(client) -> list[int]:
    courses = await client.get(
        "/api/v1/courses",
        {"enrollment_state": "active", "state[]": ["available", "completed"]},
        max_pages=10,
    )
    if not isinstance(courses, list):
        return []
    return [
        int(course["id"]) for course in courses if isinstance(course, dict) and course.get("id")
    ]


async def tool_list_courses(client, args: dict[str, Any]) -> Any:
    query: dict[str, Any] = {
        "include[]": ["term"],
        "state[]": ["available", "completed", "unpublished"],
    }
    if not args.get("include_completed", True):
        query["enrollment_state"] = "active"
        query["state[]"] = ["available", "unpublished"]
    return await client.get("/api/v1/courses", query, max_pages=int(args.get("max_pages", 10)))


async def tool_get_course(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    return await client.get(
        f"/api/v1/courses/{course_id}", {"include[]": ["term", "syllabus_body", "tabs"]}
    )


async def tool_list_modules(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    return await client.get(
        f"/api/v1/courses/{course_id}/modules",
        {"include[]": ["items", "content_details"]},
        max_pages=int(args.get("max_pages", 10)),
    )


async def tool_list_assignments(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    query: dict[str, Any] = {
        "include[]": ["submission"],
        "order_by": args.get("order_by", "due_at"),
    }
    if args.get("bucket"):
        query["bucket"] = args["bucket"]
    if args.get("search_term"):
        query["search_term"] = args["search_term"]
    return await client.get(
        f"/api/v1/courses/{course_id}/assignments", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_get_assignment(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    assignment_id = _integer(args.get("assignment_id"), "assignment_id")
    return await client.get(
        f"/api/v1/courses/{course_id}/assignments/{assignment_id}", {"include[]": ["submission"]}
    )


async def tool_get_submission(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    assignment_id = _integer(args.get("assignment_id"), "assignment_id")
    return await client.get(
        f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self",
        {"include[]": ["submission_comments", "rubric_assessment", "full_rubric_assessment"]},
    )


async def tool_list_announcements(client, args: dict[str, Any]) -> Any:
    raw_ids = args.get("course_ids") or await _active_course_ids(client)
    course_ids = [_integer(value, "course_id") for value in raw_ids]
    if not course_ids:
        return []
    query = _date_query(args)
    query["context_codes[]"] = [f"course_{course_id}" for course_id in course_ids]
    query["active_only"] = True
    query["latest_only"] = bool(args.get("latest_only", False))
    return await client.get(
        "/api/v1/announcements", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_list_calendar(client, args: dict[str, Any]) -> Any:
    query = _date_query(args)
    query["type"] = args.get("event_type", "event")
    query["all_events"] = bool(args.get("all_events", True))
    if args.get("course_ids"):
        query["context_codes[]"] = [
            f"course_{_integer(value, 'course_id')}" for value in args["course_ids"]
        ]
    return await client.get(
        "/api/v1/calendar_events", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_list_planner(client, args: dict[str, Any]) -> Any:
    query = _date_query(args)
    if args.get("course_ids"):
        query["context_codes[]"] = [
            f"course_{_integer(value, 'course_id')}" for value in args["course_ids"]
        ]
    if args.get("item_filter"):
        query["filter"] = args["item_filter"]
    if args.get("include_completed_courses", False):
        query["include[]"] = ["completed_courses"]
    return await client.get(
        "/api/v1/planner/items", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_list_todo(client, _: dict[str, Any]) -> Any:
    return await client.get("/api/v1/users/self/todo", max_pages=10)


async def tool_list_upcoming(client, _: dict[str, Any]) -> Any:
    return await client.get("/api/v1/users/self/upcoming_events", max_pages=10)


async def tool_list_pages(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    query: dict[str, Any] = {"sort": args.get("sort", "title"), "order": args.get("order", "asc")}
    if args.get("search_term"):
        query["search_term"] = args["search_term"]
    if args.get("include_body", False):
        query["include[]"] = ["body"]
    return await client.get(
        f"/api/v1/courses/{course_id}/pages", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_get_page(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    page_url = str(args.get("page_url", "")).strip()
    if not page_url or "/" in page_url or "\\" in page_url:
        raise CanvasError("page_url must be the Canvas page slug, not a URL.")
    return await client.get(f"/api/v1/courses/{course_id}/pages/{page_url}")


async def tool_list_discussions(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    query: dict[str, Any] = {
        "order_by": args.get("order_by", "recent_activity"),
        "only_announcements": bool(args.get("only_announcements", False)),
        "exclude_context_module_locked_topics": True,
    }
    if args.get("search_term"):
        query["search_term"] = args["search_term"]
    return await client.get(
        f"/api/v1/courses/{course_id}/discussion_topics",
        query,
        max_pages=int(args.get("max_pages", 10)),
    )


async def tool_get_discussion(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    topic_id = _integer(args.get("topic_id"), "topic_id")
    return await client.get(f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}/view")


async def tool_list_files(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    query: dict[str, Any] = {
        "sort": args.get("sort", "updated_at"),
        "order": args.get("order", "desc"),
        "include[]": ["user"],
    }
    if args.get("search_term"):
        query["search_term"] = args["search_term"]
    return await client.get(
        f"/api/v1/courses/{course_id}/files", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_get_file_metadata(client, args: dict[str, Any]) -> Any:
    file_id = _integer(args.get("file_id"), "file_id")
    return await client.get(f"/api/v1/files/{file_id}")


async def tool_get_grades(client, args: dict[str, Any]) -> Any:
    course_id = _integer(args.get("course_id"), "course_id")
    return await client.get(
        f"/api/v1/courses/{course_id}/enrollments",
        {
            "user_id": "self",
            "type[]": ["StudentEnrollment"],
            "include[]": ["current_points", "current_score"],
        },
        max_pages=5,
    )


async def tool_list_inbox(client, args: dict[str, Any]) -> Any:
    query: dict[str, Any] = {
        "scope": args.get("scope", "inbox"),
        "filter_mode": args.get("filter_mode", "and"),
        "include_all_conversation_ids": False,
    }
    if args.get("course_id"):
        query["filter[]"] = [f"course_{_integer(args['course_id'], 'course_id')}"]
    return await client.get(
        "/api/v1/conversations", query, max_pages=int(args.get("max_pages", 10))
    )


async def tool_get_inbox_conversation(client, args: dict[str, Any]) -> Any:
    conversation_id = _integer(args.get("conversation_id"), "conversation_id")
    return await client.get(
        f"/api/v1/conversations/{conversation_id}", {"auto_mark_as_read": False}
    )


HANDLERS = {
    "canvas_list_courses": tool_list_courses,
    "canvas_get_course": tool_get_course,
    "canvas_list_modules": tool_list_modules,
    "canvas_list_assignments": tool_list_assignments,
    "canvas_get_assignment": tool_get_assignment,
    "canvas_get_my_submission": tool_get_submission,
    "canvas_list_announcements": tool_list_announcements,
    "canvas_list_calendar": tool_list_calendar,
    "canvas_list_planner": tool_list_planner,
    "canvas_list_todo": tool_list_todo,
    "canvas_list_upcoming": tool_list_upcoming,
    "canvas_list_pages": tool_list_pages,
    "canvas_get_page": tool_get_page,
    "canvas_list_discussions": tool_list_discussions,
    "canvas_get_discussion": tool_get_discussion,
    "canvas_list_files": tool_list_files,
    "canvas_get_file_metadata": tool_get_file_metadata,
    "canvas_get_my_grades": tool_get_grades,
    "canvas_list_inbox": tool_list_inbox,
    "canvas_get_inbox_conversation": tool_get_inbox_conversation,
}
