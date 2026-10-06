"""Synthetic review fixtures. Never loads credentials or contacts a Canvas instance."""

from types import SimpleNamespace

from .canvas import CanvasClient
from .network import ServiceError


class DemoClient(CanvasClient):
    def __init__(self):
        super().__init__(
            SimpleNamespace(origin="https://canvas.example.edu", file_hosts=()), "", None
        )

    async def get(self, path, query=None, max_pages=1):
        self.sources.append(self.origin + path)
        self.pages_read += 1
        course = {
            "id": 101,
            "name": "DEMO: Introduction to Analysis",
            "course_code": "DEMO101",
            "html_url": self.origin + "/courses/101",
        }
        assignment = {
            "id": 201,
            "name": "DEMO: Problem set",
            "due_at": "2026-10-12T21:00:00Z",
            "description": "Practice limits. Synthetic example.",
            "html_url": self.origin + "/courses/101/assignments/201",
            "submission": {"workflow_state": "unsubmitted"},
        }
        data = {
            "/api/v1/users/self/profile": {"id": 1, "name": "Demo Student"},
            "/api/v1/courses": [course],
            "/api/v1/courses/101": {
                **course,
                "syllabus_body": "See module 301 for the demo syllabus.",
            },
            "/api/v1/courses/101/modules": [{"id": 301, "name": "Week 1", "items_count": 1}],
            "/api/v1/courses/101/modules/301/items": [
                {"id": 401, "type": "Page", "page_url": "syllabus", "title": "Syllabus"}
            ],
            "/api/v1/courses/101/pages/syllabus": {
                "title": "Demo syllabus",
                "body": "Class meets Monday. Check assignment deadlines in Canvas.",
            },
            "/api/v1/courses/101/pages": [{"title": "Demo syllabus", "url": "syllabus"}],
            "/api/v1/courses/101/assignments": [assignment],
            "/api/v1/courses/101/assignments/201": assignment,
            "/api/v1/courses/101/assignments/201/submissions/self": {
                "workflow_state": "unsubmitted"
            },
            "/api/v1/courses/101/discussion_topics/801/view": {
                "view": [{"id": 901, "message": "Synthetic discussion entry."}]
            },
            "/api/v1/announcements": [
                {
                    "id": 501,
                    "title": "Demo announcement",
                    "message": "Office hours moved to Tuesday.",
                }
            ],
            "/api/v1/planner/items": [{"plannable": assignment, "plannable_type": "assignment"}],
            "/api/v1/courses/101/enrollments": [
                {"type": "StudentEnrollment", "grades": {"current_score": 85}}
            ],
            "/api/v1/conversations/601": {
                "id": 601,
                "subject": "Demo message",
                "messages": [{"body": "Welcome to the demo."}],
            },
            "/api/v1/files/701": {"id": 701, "display_name": "Demo reading.txt", "size": 25},
        }
        if path in data:
            return data[path]
        if path in {
            "/api/v1/calendar_events",
            "/api/v1/users/self/todo",
            "/api/v1/users/self/upcoming_events",
            "/api/v1/conversations",
            "/api/v1/courses/101/discussion_topics",
            "/api/v1/courses/101/files",
        }:
            return []
        raise ServiceError("This resource is not part of the synthetic demo")

    async def file_text(self, file_id, max_chars=120000):
        if file_id != 701:
            raise ServiceError("This file is not part of the synthetic demo")
        return {
            "file": {"id": 701, "display_name": "Demo reading.txt"},
            "text": "Synthetic reading: limits describe the behavior of a function near a point.",
            "truncated": False,
            "extractable": True,
        }
