import os
from typing import Optional

from sqlalchemy.orm import Session

from mobile_models import (
    Notification,
    NotificationDelivery,
    PushToken,
)

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:  # Firebase is optional until credentials are provisioned.
    firebase_admin = None
    credentials = None
    messaging = None


def _firebase_app():
    credentials_file = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE", "").strip()
    if not credentials_file or firebase_admin is None:
        return None
    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app(
        credentials.Certificate(credentials_file)
    )


def deliver_notification(
    db: Session,
    notification: Notification,
) -> int:
    app = _firebase_app()
    if app is None or messaging is None:
        return 0
    tokens = (
        db.query(PushToken)
        .filter(
            PushToken.mobile_user_id == notification.mobile_user_id,
            PushToken.is_active.is_(True),
            PushToken.revoked_at.is_(None),
        )
        .all()
    )
    payload = notification.payload or {}
    sent = 0
    for token in tokens:
        existing = (
            db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.device_id == token.device_id,
                NotificationDelivery.channel == "push",
            )
            .first()
        )
        if existing is not None:
            continue
        delivery = NotificationDelivery(
            notification_id=notification.id,
            mobile_user_id=notification.mobile_user_id,
            device_id=token.device_id,
            channel="push",
            provider="fcm",
            status="sending",
        )
        db.add(delivery)
        db.flush()
        try:
            message_id = messaging.send(
                messaging.Message(
                    token=token.token,
                    notification=messaging.Notification(
                        title=notification.title,
                        body=notification.body or "",
                    ),
                    data={
                        "notification_id": str(notification.id),
                        "check_id": str(payload.get("check_id") or ""),
                        "route": str(payload.get("route") or ""),
                        "type": notification.notification_type,
                    },
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            channel_id="checks",
                            click_action="FLUTTER_NOTIFICATION_CLICK",
                        ),
                    ),
                    apns=messaging.APNSConfig(
                        headers={"apns-priority": "10"},
                        payload=messaging.APNSPayload(
                            aps=messaging.Aps(
                                sound="default",
                                content_available=True,
                            )
                        ),
                    ),
                ),
                app=app,
            )
            delivery.provider_message_id = message_id
            delivery.status = "sent"
            delivery.sent_at = notification.sent_at
            sent += 1
        except Exception as exc:
            delivery.status = "failed"
            delivery.error_message = str(exc)[:1000]
    if sent:
        notification.status = "sent"
    db.commit()
    return sent
