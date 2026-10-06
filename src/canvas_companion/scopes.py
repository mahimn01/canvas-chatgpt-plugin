"""Exact Canvas developer-key permissions used by the fixed tool catalog."""

PATHS = [
    "/api/v1/users/:user_id/profile",
    "/api/v1/courses",
    "/api/v1/courses/:id",
    "/api/v1/courses/:course_id/modules",
    "/api/v1/courses/:course_id/modules/:module_id/items",
    "/api/v1/courses/:course_id/assignments",
    "/api/v1/courses/:course_id/assignments/:id",
    "/api/v1/courses/:course_id/assignments/:assignment_id/submissions/:user_id",
    "/api/v1/announcements",
    "/api/v1/calendar_events",
    "/api/v1/planner/items",
    "/api/v1/users/self/todo",
    "/api/v1/users/self/upcoming_events",
    "/api/v1/courses/:course_id/pages",
    "/api/v1/courses/:course_id/pages/:url_or_id",
    "/api/v1/courses/:course_id/discussion_topics",
    "/api/v1/courses/:course_id/discussion_topics/:topic_id/view",
    "/api/v1/courses/:course_id/files",
    "/api/v1/files/:id",
    "/api/v1/courses/:course_id/enrollments",
    "/api/v1/conversations",
    "/api/v1/conversations/:id",
]
SCOPES = ["url:GET|" + path for path in PATHS]
