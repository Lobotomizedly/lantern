"""
Review Queue Service

Manages the review workflow for generated artifacts. Handles approval,
rejection, feedback routing, and publication notifications.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.services.artifact_service import (
    ArtifactRecord,
    ArtifactService,
    ArtifactStatus,
    ArtifactType,
)

logger = logging.getLogger(__name__)


class ReviewDecision(str, Enum):
    """Possible review decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"
    ESCALATE = "escalate"


class ReviewStatus(str, Enum):
    """Status of a review queue item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ReviewPriority(str, Enum):
    """Review priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReviewFeedback(BaseModel):
    """Feedback provided during review."""

    id: UUID = Field(default_factory=uuid4)
    reviewer_id: UUID
    reviewer_name: Optional[str] = None
    decision: ReviewDecision
    comments: str
    specific_issues: List[str] = Field(default_factory=list)
    suggested_changes: List[str] = Field(default_factory=list)
    quality_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Overall quality score 0-1",
    )
    grounding_adequate: bool = True
    citations_verified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewQueueItem(BaseModel):
    """An item in the review queue."""

    id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID
    artifact_type: ArtifactType
    artifact_title: str
    status: ReviewStatus = ReviewStatus.PENDING
    priority: ReviewPriority = ReviewPriority.NORMAL
    assigned_to: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    feedback: List[ReviewFeedback] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    due_by: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReviewMetrics(BaseModel):
    """Metrics about the review process."""

    total_pending: int = 0
    total_in_progress: int = 0
    total_completed_today: int = 0
    average_review_time_hours: float = 0.0
    approval_rate: float = 0.0
    by_type: Dict[str, int] = Field(default_factory=dict)
    by_reviewer: Dict[str, int] = Field(default_factory=dict)


class NotificationConfig(BaseModel):
    """Configuration for review notifications."""

    enable_email: bool = True
    enable_slack: bool = False
    enable_webhook: bool = False
    email_recipients: List[str] = Field(default_factory=list)
    slack_channel: Optional[str] = None
    webhook_url: Optional[str] = None


# Type for notification hooks
NotificationHook = Callable[[str, Dict[str, Any]], None]


class ReviewService:
    """
    Service for managing the artifact review workflow.

    Handles:
    - Adding items to review queue
    - Assigning reviewers
    - Processing approve/reject decisions
    - Providing feedback
    - Routing approved artifacts to publication
    - Sending notifications
    """

    def __init__(
        self,
        artifact_service: Optional[ArtifactService] = None,
        notification_config: Optional[NotificationConfig] = None,
    ):
        """
        Initialize the review service.

        Args:
            artifact_service: Artifact service for status updates
            notification_config: Notification settings
        """
        self.artifact_service = artifact_service or ArtifactService()
        self.notification_config = notification_config or NotificationConfig()

        # In-memory storage (use database in production)
        self._queue: Dict[UUID, ReviewQueueItem] = {}
        self._completed: Dict[UUID, ReviewQueueItem] = {}

        # Notification hooks
        self._notification_hooks: List[NotificationHook] = []

    def register_notification_hook(self, hook: NotificationHook) -> None:
        """
        Register a notification hook.

        Args:
            hook: Callback function for notifications
        """
        self._notification_hooks.append(hook)

    async def add_to_queue(
        self,
        artifact_id: UUID,
        priority: ReviewPriority = ReviewPriority.NORMAL,
        due_by: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        assign_to: Optional[UUID] = None,
    ) -> ReviewQueueItem:
        """
        Add an artifact to the review queue.

        Args:
            artifact_id: ID of artifact to review
            priority: Review priority
            due_by: Optional deadline
            tags: Optional tags for filtering
            assign_to: Optional reviewer assignment

        Returns:
            ReviewQueueItem
        """
        # Get artifact details
        artifact = await self.artifact_service.get_artifact(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status != ArtifactStatus.DRAFT:
            raise ValueError(
                f"Artifact must be in draft status to review. "
                f"Current status: {artifact.status}"
            )

        # Create queue item
        queue_item = ReviewQueueItem(
            artifact_id=artifact_id,
            artifact_type=artifact.request.artifact_type,
            artifact_title=artifact.request.title or f"Artifact {artifact_id}",
            priority=priority,
            due_by=due_by,
            tags=tags or [],
            assigned_to=assign_to,
            assigned_at=datetime.utcnow() if assign_to else None,
        )

        self._queue[queue_item.id] = queue_item

        # Update artifact status
        await self.artifact_service.submit_for_review(artifact_id)

        # Send notification
        await self._notify(
            "review_queued",
            {
                "queue_item_id": str(queue_item.id),
                "artifact_id": str(artifact_id),
                "artifact_type": queue_item.artifact_type.value,
                "title": queue_item.artifact_title,
                "priority": priority.value,
            },
        )

        logger.info(f"Added artifact {artifact_id} to review queue: {queue_item.id}")

        return queue_item

    async def get_queue_item(
        self,
        item_id: UUID,
    ) -> Optional[ReviewQueueItem]:
        """Get a queue item by ID."""
        return self._queue.get(item_id) or self._completed.get(item_id)

    async def get_queue(
        self,
        status: Optional[ReviewStatus] = None,
        priority: Optional[ReviewPriority] = None,
        artifact_type: Optional[ArtifactType] = None,
        assigned_to: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ReviewQueueItem]:
        """
        Get items from the review queue with filters.

        Args:
            status: Filter by status
            priority: Filter by priority
            artifact_type: Filter by artifact type
            assigned_to: Filter by assignee
            tags: Filter by tags (any match)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of queue items
        """
        items = list(self._queue.values())

        if status:
            items = [i for i in items if i.status == status]

        if priority:
            items = [i for i in items if i.priority == priority]

        if artifact_type:
            items = [i for i in items if i.artifact_type == artifact_type]

        if assigned_to:
            items = [i for i in items if i.assigned_to == assigned_to]

        if tags:
            items = [
                i for i in items
                if any(tag in i.tags for tag in tags)
            ]

        # Sort by priority (urgent first) then by created_at
        priority_order = {
            ReviewPriority.URGENT: 0,
            ReviewPriority.HIGH: 1,
            ReviewPriority.NORMAL: 2,
            ReviewPriority.LOW: 3,
        }
        items.sort(
            key=lambda x: (priority_order.get(x.priority, 2), x.created_at)
        )

        return items[offset:offset + limit]

    async def assign_reviewer(
        self,
        item_id: UUID,
        reviewer_id: UUID,
    ) -> ReviewQueueItem:
        """
        Assign a reviewer to a queue item.

        Args:
            item_id: Queue item ID
            reviewer_id: User ID of reviewer

        Returns:
            Updated queue item
        """
        item = self._queue.get(item_id)
        if not item:
            raise ValueError(f"Queue item not found: {item_id}")

        item.assigned_to = reviewer_id
        item.assigned_at = datetime.utcnow()
        item.status = ReviewStatus.IN_PROGRESS
        item.updated_at = datetime.utcnow()

        await self._notify(
            "reviewer_assigned",
            {
                "queue_item_id": str(item_id),
                "reviewer_id": str(reviewer_id),
                "artifact_id": str(item.artifact_id),
                "title": item.artifact_title,
            },
        )

        logger.info(f"Assigned reviewer {reviewer_id} to queue item {item_id}")

        return item

    async def start_review(
        self,
        item_id: UUID,
        reviewer_id: UUID,
    ) -> ReviewQueueItem:
        """
        Start reviewing an item.

        Args:
            item_id: Queue item ID
            reviewer_id: Reviewer user ID

        Returns:
            Updated queue item
        """
        item = self._queue.get(item_id)
        if not item:
            raise ValueError(f"Queue item not found: {item_id}")

        if item.status != ReviewStatus.PENDING:
            raise ValueError(f"Item is not pending: {item.status}")

        # Assign if not already assigned
        if not item.assigned_to:
            item.assigned_to = reviewer_id
            item.assigned_at = datetime.utcnow()

        item.status = ReviewStatus.IN_PROGRESS
        item.updated_at = datetime.utcnow()

        return item

    async def submit_feedback(
        self,
        item_id: UUID,
        feedback: ReviewFeedback,
    ) -> ReviewQueueItem:
        """
        Submit review feedback for a queue item.

        Args:
            item_id: Queue item ID
            feedback: Review feedback

        Returns:
            Updated queue item
        """
        item = self._queue.get(item_id)
        if not item:
            raise ValueError(f"Queue item not found: {item_id}")

        # Add feedback
        item.feedback.append(feedback)
        item.updated_at = datetime.utcnow()

        # Process decision
        if feedback.decision == ReviewDecision.APPROVE:
            await self._handle_approval(item, feedback)
        elif feedback.decision == ReviewDecision.REJECT:
            await self._handle_rejection(item, feedback)
        elif feedback.decision == ReviewDecision.REQUEST_REVISION:
            await self._handle_revision_request(item, feedback)
        elif feedback.decision == ReviewDecision.ESCALATE:
            await self._handle_escalation(item, feedback)

        return item

    async def approve(
        self,
        item_id: UUID,
        reviewer_id: UUID,
        comments: str = "",
        quality_score: Optional[float] = None,
    ) -> ReviewQueueItem:
        """
        Approve a queue item.

        Args:
            item_id: Queue item ID
            reviewer_id: Reviewer user ID
            comments: Optional comments
            quality_score: Optional quality score

        Returns:
            Updated queue item
        """
        feedback = ReviewFeedback(
            reviewer_id=reviewer_id,
            decision=ReviewDecision.APPROVE,
            comments=comments or "Approved",
            quality_score=quality_score,
        )

        return await self.submit_feedback(item_id, feedback)

    async def reject(
        self,
        item_id: UUID,
        reviewer_id: UUID,
        reason: str,
        specific_issues: Optional[List[str]] = None,
    ) -> ReviewQueueItem:
        """
        Reject a queue item.

        Args:
            item_id: Queue item ID
            reviewer_id: Reviewer user ID
            reason: Rejection reason
            specific_issues: List of specific issues

        Returns:
            Updated queue item
        """
        feedback = ReviewFeedback(
            reviewer_id=reviewer_id,
            decision=ReviewDecision.REJECT,
            comments=reason,
            specific_issues=specific_issues or [],
        )

        return await self.submit_feedback(item_id, feedback)

    async def request_revision(
        self,
        item_id: UUID,
        reviewer_id: UUID,
        feedback_text: str,
        suggested_changes: Optional[List[str]] = None,
    ) -> ReviewQueueItem:
        """
        Request revisions to an artifact.

        Args:
            item_id: Queue item ID
            reviewer_id: Reviewer user ID
            feedback_text: Revision feedback
            suggested_changes: Specific suggestions

        Returns:
            Updated queue item
        """
        feedback = ReviewFeedback(
            reviewer_id=reviewer_id,
            decision=ReviewDecision.REQUEST_REVISION,
            comments=feedback_text,
            suggested_changes=suggested_changes or [],
        )

        return await self.submit_feedback(item_id, feedback)

    async def _handle_approval(
        self,
        item: ReviewQueueItem,
        feedback: ReviewFeedback,
    ) -> None:
        """Handle approval decision."""
        item.status = ReviewStatus.COMPLETED
        item.updated_at = datetime.utcnow()

        # Move to completed
        self._completed[item.id] = item
        if item.id in self._queue:
            del self._queue[item.id]

        # Update artifact
        await self.artifact_service.approve(
            item.artifact_id,
            notes=feedback.comments,
        )

        # Notify
        await self._notify(
            "artifact_approved",
            {
                "artifact_id": str(item.artifact_id),
                "title": item.artifact_title,
                "reviewer_id": str(feedback.reviewer_id),
                "quality_score": feedback.quality_score,
            },
        )

        logger.info(f"Approved artifact {item.artifact_id}")

    async def _handle_rejection(
        self,
        item: ReviewQueueItem,
        feedback: ReviewFeedback,
    ) -> None:
        """Handle rejection decision."""
        item.status = ReviewStatus.COMPLETED
        item.updated_at = datetime.utcnow()

        # Move to completed
        self._completed[item.id] = item
        if item.id in self._queue:
            del self._queue[item.id]

        # Update artifact
        await self.artifact_service.reject(
            item.artifact_id,
            reason=feedback.comments,
        )

        # Notify
        await self._notify(
            "artifact_rejected",
            {
                "artifact_id": str(item.artifact_id),
                "title": item.artifact_title,
                "reviewer_id": str(feedback.reviewer_id),
                "reason": feedback.comments,
            },
        )

        logger.info(f"Rejected artifact {item.artifact_id}")

    async def _handle_revision_request(
        self,
        item: ReviewQueueItem,
        feedback: ReviewFeedback,
    ) -> None:
        """Handle revision request."""
        # Keep in queue with pending status
        item.status = ReviewStatus.PENDING
        item.assigned_to = None
        item.assigned_at = None
        item.updated_at = datetime.utcnow()

        # Update artifact
        await self.artifact_service.request_revision(
            item.artifact_id,
            feedback=feedback.comments,
        )

        # Notify
        await self._notify(
            "revision_requested",
            {
                "artifact_id": str(item.artifact_id),
                "title": item.artifact_title,
                "reviewer_id": str(feedback.reviewer_id),
                "feedback": feedback.comments,
                "suggested_changes": feedback.suggested_changes,
            },
        )

        logger.info(f"Requested revision for artifact {item.artifact_id}")

    async def _handle_escalation(
        self,
        item: ReviewQueueItem,
        feedback: ReviewFeedback,
    ) -> None:
        """Handle escalation."""
        item.priority = ReviewPriority.URGENT
        item.status = ReviewStatus.PENDING
        item.assigned_to = None
        item.assigned_at = None
        item.updated_at = datetime.utcnow()
        item.tags.append("escalated")

        # Notify
        await self._notify(
            "review_escalated",
            {
                "artifact_id": str(item.artifact_id),
                "title": item.artifact_title,
                "escalated_by": str(feedback.reviewer_id),
                "reason": feedback.comments,
            },
        )

        logger.info(f"Escalated review for artifact {item.artifact_id}")

    async def route_to_publication(
        self,
        artifact_id: UUID,
        publish_config: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """
        Route an approved artifact to publication.

        Args:
            artifact_id: Artifact ID
            publish_config: Publication configuration

        Returns:
            Published artifact record
        """
        artifact = await self.artifact_service.publish(
            artifact_id,
            publish_config=publish_config,
        )

        # Notify
        await self._notify(
            "artifact_published",
            {
                "artifact_id": str(artifact_id),
                "title": artifact.request.title,
                "publish_config": publish_config,
            },
        )

        return artifact

    async def _notify(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """
        Send notifications for review events.

        Args:
            event_type: Type of event
            data: Event data
        """
        # Call registered hooks
        for hook in self._notification_hooks:
            try:
                hook(event_type, data)
            except Exception as e:
                logger.error(f"Notification hook error: {e}")

        # Built-in notifications
        if self.notification_config.enable_email:
            await self._send_email_notification(event_type, data)

        if self.notification_config.enable_slack:
            await self._send_slack_notification(event_type, data)

        if self.notification_config.enable_webhook:
            await self._send_webhook_notification(event_type, data)

    async def _send_email_notification(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Send email notification."""
        # TODO: Implement email sending
        logger.debug(f"Email notification: {event_type} - {data}")

    async def _send_slack_notification(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Send Slack notification."""
        # TODO: Implement Slack integration
        logger.debug(f"Slack notification: {event_type} - {data}")

    async def _send_webhook_notification(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Send webhook notification."""
        # TODO: Implement webhook calls
        logger.debug(f"Webhook notification: {event_type} - {data}")

    async def get_metrics(self) -> ReviewMetrics:
        """
        Get review queue metrics.

        Returns:
            ReviewMetrics
        """
        from datetime import timedelta

        today = datetime.utcnow().date()

        # Count by status
        pending = sum(
            1 for i in self._queue.values()
            if i.status == ReviewStatus.PENDING
        )
        in_progress = sum(
            1 for i in self._queue.values()
            if i.status == ReviewStatus.IN_PROGRESS
        )

        # Completed today
        completed_today = sum(
            1 for i in self._completed.values()
            if i.updated_at.date() == today
        )

        # Average review time
        review_times = []
        for item in self._completed.values():
            if item.feedback:
                duration = (
                    item.feedback[-1].created_at - item.created_at
                ).total_seconds() / 3600
                review_times.append(duration)

        avg_time = sum(review_times) / len(review_times) if review_times else 0

        # Approval rate
        total_completed = len(self._completed)
        approvals = sum(
            1 for i in self._completed.values()
            if any(f.decision == ReviewDecision.APPROVE for f in i.feedback)
        )
        approval_rate = approvals / total_completed if total_completed > 0 else 0

        # By type
        by_type: Dict[str, int] = {}
        for item in self._queue.values():
            t = item.artifact_type.value
            by_type[t] = by_type.get(t, 0) + 1

        # By reviewer
        by_reviewer: Dict[str, int] = {}
        for item in self._completed.values():
            if item.feedback:
                reviewer = str(item.feedback[-1].reviewer_id)
                by_reviewer[reviewer] = by_reviewer.get(reviewer, 0) + 1

        return ReviewMetrics(
            total_pending=pending,
            total_in_progress=in_progress,
            total_completed_today=completed_today,
            average_review_time_hours=avg_time,
            approval_rate=approval_rate,
            by_type=by_type,
            by_reviewer=by_reviewer,
        )

    async def get_reviewer_workload(
        self,
        reviewer_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get workload for a specific reviewer.

        Args:
            reviewer_id: Reviewer user ID

        Returns:
            Workload information
        """
        assigned = [
            i for i in self._queue.values()
            if i.assigned_to == reviewer_id
        ]

        completed = [
            i for i in self._completed.values()
            if i.feedback and i.feedback[-1].reviewer_id == reviewer_id
        ]

        return {
            "reviewer_id": str(reviewer_id),
            "active_assignments": len(assigned),
            "completed_total": len(completed),
            "pending_items": [
                {
                    "id": str(i.id),
                    "artifact_id": str(i.artifact_id),
                    "title": i.artifact_title,
                    "priority": i.priority.value,
                    "assigned_at": i.assigned_at.isoformat() if i.assigned_at else None,
                }
                for i in assigned
            ],
        }

    async def cleanup_expired(
        self,
        max_age_days: int = 7,
    ) -> int:
        """
        Clean up expired review items.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of items cleaned
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        cleaned = 0

        to_remove = [
            item_id for item_id, item in self._queue.items()
            if item.created_at < cutoff
            and item.status == ReviewStatus.PENDING
        ]

        for item_id in to_remove:
            item = self._queue[item_id]
            item.status = ReviewStatus.EXPIRED
            self._completed[item_id] = item
            del self._queue[item_id]
            cleaned += 1

        logger.info(f"Cleaned up {cleaned} expired review items")

        return cleaned
