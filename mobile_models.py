from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database import Base


class MobileUser(Base):
    __tablename__ = "mobile_users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    core_user_id = Column(String(128), nullable=False)
    core_organization_id = Column(String(128), nullable=True)
    phone = Column(String(32), nullable=True)
    email = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    role_snapshot = Column(JSONB, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    devices = relationship("MobileDevice", back_populates="mobile_user")
    sessions = relationship(
        "MobileSession",
        foreign_keys="MobileSession.mobile_user_id",
        back_populates="mobile_user",
    )
    linked_device_sessions = relationship(
        "LinkedDeviceSession",
        back_populates="mobile_user",
    )
    push_tokens = relationship("PushToken", back_populates="mobile_user")

    __table_args__ = (
        UniqueConstraint("core_user_id", name="uq_mobile_users_core_user_id"),
        Index("ix_mobile_users_core_user_id", "core_user_id"),
        Index("ix_mobile_users_core_organization_id", "core_organization_id"),
        Index("ix_mobile_users_phone", "phone"),
        Index("ix_mobile_users_email", "email"),
        Index("ix_mobile_users_status", "status"),
        Index("ix_mobile_users_created_at", "created_at"),
    )


class MobileDevice(Base):
    __tablename__ = "mobile_devices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    device_id = Column(String(255), nullable=False)
    platform = Column(String(32), nullable=False)
    device_name = Column(String(255), nullable=True)
    device_model = Column(String(255), nullable=True)
    os_version = Column(String(64), nullable=True)
    app_version = Column(String(64), nullable=True)
    push_token = Column(Text, nullable=True)
    push_provider = Column(String(32), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    mobile_user = relationship("MobileUser", back_populates="devices")

    __table_args__ = (
        UniqueConstraint("mobile_user_id", "device_id", name="uq_mobile_devices_user_device"),
        Index("ix_mobile_devices_mobile_user_id", "mobile_user_id"),
        Index("ix_mobile_devices_device_id", "device_id"),
        Index("ix_mobile_devices_platform", "platform"),
        Index("ix_mobile_devices_is_active", "is_active"),
        Index("ix_mobile_devices_created_at", "created_at"),
    )


class MobileSession(Base):
    __tablename__ = "mobile_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    device_id = Column(String(255), nullable=False)
    access_token_jti = Column(String(255), nullable=True)
    refresh_token_hash = Column(String(255), nullable=False)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    revocation_reason = Column(Text, nullable=True)

    mobile_user = relationship("MobileUser", foreign_keys=[mobile_user_id], back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_mobile_sessions_refresh_token_hash"),
        Index("ix_mobile_sessions_mobile_user_id", "mobile_user_id"),
        Index("ix_mobile_sessions_device_id", "device_id"),
        Index("ix_mobile_sessions_status", "status"),
        Index("ix_mobile_sessions_refresh_token_hash", "refresh_token_hash"),
        Index("ix_mobile_sessions_expires_at", "expires_at"),
        Index("ix_mobile_sessions_created_at", "created_at"),
    )


class LinkedDeviceSession(Base):
    __tablename__ = "linked_device_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    core_session_id = Column(String(128), nullable=False)
    device_name = Column(String(255), nullable=True)
    browser = Column(String(128), nullable=True)
    browser_version = Column(String(64), nullable=True)
    platform = Column(String(128), nullable=True)
    os_version = Column(String(128), nullable=True)
    device_type = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    mobile_user = relationship("MobileUser", back_populates="linked_device_sessions")

    __table_args__ = (
        UniqueConstraint("mobile_user_id", "core_session_id", name="uq_linked_device_sessions_user_core_session"),
        Index("ix_linked_device_sessions_mobile_user_id", "mobile_user_id"),
        Index("ix_linked_device_sessions_core_session_id", "core_session_id"),
        Index("ix_linked_device_sessions_status", "status"),
        Index("ix_linked_device_sessions_last_active_at", "last_active_at"),
        Index("ix_linked_device_sessions_created_at", "created_at"),
    )


class PushToken(Base):
    __tablename__ = "push_tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    device_id = Column(String(255), nullable=False)
    provider = Column(String(32), nullable=False)
    token = Column(Text, nullable=False)
    platform = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    mobile_user = relationship("MobileUser", back_populates="push_tokens")

    __table_args__ = (
        Index("ix_push_tokens_mobile_user_id", "mobile_user_id"),
        Index("ix_push_tokens_device_id", "device_id"),
        Index("ix_push_tokens_token", "token"),
        Index("ix_push_tokens_is_active", "is_active"),
        Index("ix_push_tokens_created_at", "created_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    notification_type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=True)
    status = Column(String(32), nullable=False, default="created")
    priority = Column(String(32), nullable=False, default="normal")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    deliveries = relationship("NotificationDelivery", back_populates="notification")

    __table_args__ = (
        Index("ix_notifications_mobile_user_id", "mobile_user_id"),
        Index("ix_notifications_notification_type", "notification_type"),
        Index("ix_notifications_status", "status"),
        Index("ix_notifications_created_at", "created_at"),
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    notification_id = Column(BigInteger, ForeignKey("notifications.id"), nullable=False)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    device_id = Column(String(255), nullable=True)
    channel = Column(String(32), nullable=False)
    provider = Column(String(32), nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)

    notification = relationship("Notification", back_populates="deliveries")

    __table_args__ = (
        Index("ix_notification_deliveries_notification_id", "notification_id"),
        Index("ix_notification_deliveries_mobile_user_id", "mobile_user_id"),
        Index("ix_notification_deliveries_device_id", "device_id"),
        Index("ix_notification_deliveries_status", "status"),
        Index("ix_notification_deliveries_created_at", "created_at"),
    )


class QrLoginSession(Base):
    __tablename__ = "qr_login_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    qr_token_hash = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    web_session_id = Column(String(255), nullable=True)
    requested_ip = Column(String(64), nullable=True)
    requested_user_agent = Column(Text, nullable=True)
    approved_by_mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    approved_device_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    events = relationship("QrLoginEvent", back_populates="qr_login_session")

    __table_args__ = (
        UniqueConstraint("qr_token_hash", name="uq_qr_login_sessions_qr_token_hash"),
        Index("ix_qr_login_sessions_qr_token_hash", "qr_token_hash"),
        Index("ix_qr_login_sessions_status", "status"),
        Index("ix_qr_login_sessions_expires_at", "expires_at"),
        Index("ix_qr_login_sessions_approved_by_mobile_user_id", "approved_by_mobile_user_id"),
        Index("ix_qr_login_sessions_created_at", "created_at"),
    )


class QrLoginEvent(Base):
    __tablename__ = "qr_login_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    qr_login_session_id = Column(BigInteger, ForeignKey("qr_login_sessions.id"), nullable=False)
    event_type = Column(String(32), nullable=False)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    device_id = Column(String(255), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    qr_login_session = relationship("QrLoginSession", back_populates="events")

    __table_args__ = (
        Index("ix_qr_login_events_qr_login_session_id", "qr_login_session_id"),
        Index("ix_qr_login_events_event_type", "event_type"),
        Index("ix_qr_login_events_mobile_user_id", "mobile_user_id"),
        Index("ix_qr_login_events_device_id", "device_id"),
        Index("ix_qr_login_events_created_at", "created_at"),
    )


class TwoFactorChallenge(Base):
    __tablename__ = "two_factor_challenges"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    challenge_type = Column(String(64), nullable=False)
    delivery_channel = Column(String(32), nullable=False)
    destination_masked = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    attempts_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    attempts = relationship("TwoFactorAttempt", back_populates="challenge")

    __table_args__ = (
        Index("ix_two_factor_challenges_mobile_user_id", "mobile_user_id"),
        Index("ix_two_factor_challenges_challenge_type", "challenge_type"),
        Index("ix_two_factor_challenges_status", "status"),
        Index("ix_two_factor_challenges_expires_at", "expires_at"),
        Index("ix_two_factor_challenges_created_at", "created_at"),
    )


class TwoFactorAttempt(Base):
    __tablename__ = "two_factor_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    challenge_id = Column(BigInteger, ForeignKey("two_factor_challenges.id"), nullable=False)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    attempt_result = Column(String(32), nullable=False)
    ip_address = Column(String(64), nullable=True)
    device_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    challenge = relationship("TwoFactorChallenge", back_populates="attempts")

    __table_args__ = (
        Index("ix_two_factor_attempts_challenge_id", "challenge_id"),
        Index("ix_two_factor_attempts_mobile_user_id", "mobile_user_id"),
        Index("ix_two_factor_attempts_attempt_result", "attempt_result"),
        Index("ix_two_factor_attempts_device_id", "device_id"),
        Index("ix_two_factor_attempts_created_at", "created_at"),
    )


class MobileCheckRequest(Base):
    __tablename__ = "mobile_check_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    core_user_id = Column(String(128), nullable=False)
    core_organization_id = Column(String(128), nullable=True)
    core_check_id = Column(String(128), nullable=True)
    source = Column(String(32), nullable=False, default="mobile")
    status = Column(String(32), nullable=False, default="draft")
    title = Column(String(255), nullable=True)
    document_name = Column(String(255), nullable=True)
    document_type = Column(String(64), nullable=True)
    created_from_device_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    files = relationship("MobileCheckFile", back_populates="mobile_check_request")
    results = relationship("MobileCheckResult", back_populates="mobile_check_request")
    status_events = relationship("MobileCheckStatusEvent", back_populates="mobile_check_request")

    __table_args__ = (
        Index("ix_mobile_check_requests_mobile_user_id", "mobile_user_id"),
        Index("ix_mobile_check_requests_core_user_id", "core_user_id"),
        Index("ix_mobile_check_requests_core_organization_id", "core_organization_id"),
        Index("ix_mobile_check_requests_core_check_id", "core_check_id"),
        Index("ix_mobile_check_requests_status", "status"),
        Index("ix_mobile_check_requests_created_at", "created_at"),
    )


class MobileCheckFile(Base):
    __tablename__ = "mobile_check_files"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_check_request_id = Column(BigInteger, ForeignKey("mobile_check_requests.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(128), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    storage_provider = Column(String(64), nullable=True)
    storage_key = Column(String(512), nullable=True)
    file_url = Column(Text, nullable=True)
    checksum = Column(String(255), nullable=True)
    upload_status = Column(String(32), nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    mobile_check_request = relationship("MobileCheckRequest", back_populates="files")

    __table_args__ = (
        Index("ix_mobile_check_files_mobile_check_request_id", "mobile_check_request_id"),
        Index("ix_mobile_check_files_upload_status", "upload_status"),
        Index("ix_mobile_check_files_created_at", "created_at"),
    )


class MobileCheckResult(Base):
    __tablename__ = "mobile_check_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_check_request_id = Column(BigInteger, ForeignKey("mobile_check_requests.id"), nullable=False)
    core_check_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False)
    originality_percent = Column(Float, nullable=True)
    ai_probability_percent = Column(Float, nullable=True)
    plagiarism_percent = Column(Float, nullable=True)
    report_url = Column(Text, nullable=True)
    summary = Column(JSONB, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    mobile_check_request = relationship("MobileCheckRequest", back_populates="results")

    __table_args__ = (
        Index("ix_mobile_check_results_mobile_check_request_id", "mobile_check_request_id"),
        Index("ix_mobile_check_results_core_check_id", "core_check_id"),
        Index("ix_mobile_check_results_status", "status"),
        Index("ix_mobile_check_results_created_at", "created_at"),
    )


class MobileCheckStatusEvent(Base):
    __tablename__ = "mobile_check_status_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_check_request_id = Column(BigInteger, ForeignKey("mobile_check_requests.id"), nullable=False)
    old_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=False)
    event_source = Column(String(64), nullable=False)
    message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    mobile_check_request = relationship("MobileCheckRequest", back_populates="status_events")

    __table_args__ = (
        Index("ix_mobile_check_status_events_mobile_check_request_id", "mobile_check_request_id"),
        Index("ix_mobile_check_status_events_new_status", "new_status"),
        Index("ix_mobile_check_status_events_event_source", "event_source"),
        Index("ix_mobile_check_status_events_created_at", "created_at"),
    )


class AccessDelegationRequest(Base):
    __tablename__ = "access_delegation_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    requested_by_mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    target_core_user_id = Column(String(128), nullable=True)
    target_phone = Column(String(32), nullable=True)
    target_email = Column(String(255), nullable=True)
    core_organization_id = Column(String(128), nullable=True)
    requested_role = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    requires_2fa = Column(Boolean, nullable=False, default=False)
    two_factor_challenge_id = Column(BigInteger, ForeignKey("two_factor_challenges.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_access_delegation_requests_requested_by_mobile_user_id", "requested_by_mobile_user_id"),
        Index("ix_access_delegation_requests_target_core_user_id", "target_core_user_id"),
        Index("ix_access_delegation_requests_core_organization_id", "core_organization_id"),
        Index("ix_access_delegation_requests_status", "status"),
        Index("ix_access_delegation_requests_created_at", "created_at"),
    )


class AdminActionRequest(Base):
    __tablename__ = "admin_action_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    requested_by_mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    target_core_user_id = Column(String(128), nullable=True)
    core_organization_id = Column(String(128), nullable=True)
    action_type = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    requires_2fa = Column(Boolean, nullable=False, default=False)
    two_factor_challenge_id = Column(BigInteger, ForeignKey("two_factor_challenges.id"), nullable=True)
    core_request_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    events = relationship("AdminActionEvent", back_populates="admin_action_request")

    __table_args__ = (
        Index("ix_admin_action_requests_requested_by_mobile_user_id", "requested_by_mobile_user_id"),
        Index("ix_admin_action_requests_target_core_user_id", "target_core_user_id"),
        Index("ix_admin_action_requests_core_organization_id", "core_organization_id"),
        Index("ix_admin_action_requests_action_type", "action_type"),
        Index("ix_admin_action_requests_status", "status"),
        Index("ix_admin_action_requests_created_at", "created_at"),
    )


class AdminActionEvent(Base):
    __tablename__ = "admin_action_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    admin_action_request_id = Column(BigInteger, ForeignKey("admin_action_requests.id"), nullable=False)
    event_type = Column(String(64), nullable=False)
    actor_mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    admin_action_request = relationship("AdminActionRequest", back_populates="events")

    __table_args__ = (
        Index("ix_admin_action_events_admin_action_request_id", "admin_action_request_id"),
        Index("ix_admin_action_events_event_type", "event_type"),
        Index("ix_admin_action_events_actor_mobile_user_id", "actor_mobile_user_id"),
        Index("ix_admin_action_events_created_at", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    core_user_id = Column(String(128), nullable=True)
    device_id = Column(String(255), nullable=True)
    session_id = Column(BigInteger, ForeignKey("mobile_sessions.id"), nullable=True)
    action = Column(String(128), nullable=False)
    entity_type = Column(String(128), nullable=True)
    entity_id = Column(String(128), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_audit_logs_mobile_user_id", "mobile_user_id"),
        Index("ix_audit_logs_core_user_id", "core_user_id"),
        Index("ix_audit_logs_device_id", "device_id"),
        Index("ix_audit_logs_session_id", "session_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    event_type = Column(String(128), nullable=False)
    severity = Column(String(32), nullable=False)
    ip_address = Column(String(64), nullable=True)
    device_id = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_security_events_mobile_user_id", "mobile_user_id"),
        Index("ix_security_events_event_type", "event_type"),
        Index("ix_security_events_severity", "severity"),
        Index("ix_security_events_device_id", "device_id"),
        Index("ix_security_events_created_at", "created_at"),
    )


class MobileUserSettings(Base):
    __tablename__ = "mobile_user_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    language = Column(String(16), nullable=False, default="ru")
    timezone = Column(String(64), nullable=False, default="Asia/Almaty")
    push_enabled = Column(Boolean, nullable=False, default=True)
    sms_enabled = Column(Boolean, nullable=False, default=True)
    email_enabled = Column(Boolean, nullable=False, default=True)
    biometric_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("mobile_user_id", name="uq_mobile_user_settings_mobile_user_id"),
        Index("ix_mobile_user_settings_mobile_user_id", "mobile_user_id"),
        Index("ix_mobile_user_settings_created_at", "created_at"),
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=False)
    notification_type = Column(String(64), nullable=False)
    push_enabled = Column(Boolean, nullable=False, default=True)
    sms_enabled = Column(Boolean, nullable=False, default=False)
    email_enabled = Column(Boolean, nullable=False, default=False)
    in_app_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("mobile_user_id", "notification_type", name="uq_notification_preferences_user_type"),
        Index("ix_notification_preferences_mobile_user_id", "mobile_user_id"),
        Index("ix_notification_preferences_notification_type", "notification_type"),
        Index("ix_notification_preferences_created_at", "created_at"),
    )


class AppVersion(Base):
    __tablename__ = "app_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False)
    version = Column(String(64), nullable=False)
    build_number = Column(String(64), nullable=False)
    min_supported_version = Column(String(64), nullable=True)
    force_update = Column(Boolean, nullable=False, default=False)
    release_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("platform", "version", "build_number", name="uq_app_versions_platform_version_build"),
        Index("ix_app_versions_platform", "platform"),
        Index("ix_app_versions_created_at", "created_at"),
    )


class CoreApiRequest(Base):
    __tablename__ = "core_api_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mobile_user_id = Column(BigInteger, ForeignKey("mobile_users.id"), nullable=True)
    method = Column(String(16), nullable=False)
    endpoint = Column(String(512), nullable=False)
    status_code = Column(Integer, nullable=True)
    request_id = Column(String(128), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_core_api_requests_mobile_user_id", "mobile_user_id"),
        Index("ix_core_api_requests_method", "method"),
        Index("ix_core_api_requests_endpoint", "endpoint"),
        Index("ix_core_api_requests_status_code", "status_code"),
        Index("ix_core_api_requests_request_id", "request_id"),
        Index("ix_core_api_requests_created_at", "created_at"),
    )


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_sync_jobs_job_type", "job_type"),
        Index("ix_sync_jobs_status", "status"),
        Index("ix_sync_jobs_created_at", "created_at"),
    )
