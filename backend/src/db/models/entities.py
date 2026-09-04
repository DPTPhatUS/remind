from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, IdMixin, TimestampMixin


class UserAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="caregiver")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Patient(IdMixin, TimestampMixin, Base):
    __tablename__ = "patients"

    display_name: Mapped[str] = mapped_column(String(160))
    date_of_birth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    accessibility_settings: Mapped[dict] = mapped_column(JSON, default=dict)


class CaregiverAccess(IdMixin, TimestampMixin, Base):
    __tablename__ = "caregiver_access"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"))
    access_level: Mapped[str] = mapped_column(String(32), default="admin")


class Person(IdMixin, TimestampMixin, Base):
    __tablename__ = "people"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    relationship_to_patient: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognition_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    consent_status: Mapped[str] = mapped_column(String(32), default="unknown")

    face_links: Mapped[list["FaceSubjectLink"]] = relationship(back_populates="person")


class FaceSubjectLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "face_subject_links"

    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="compreface")
    subject: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_interaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    person: Mapped[Person] = relationship(back_populates="face_links")


class Interaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "interactions"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    started_at: Mapped[str] = mapped_column(String(64))
    ended_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="open")


class InteractionParticipant(IdMixin, TimestampMixin, Base):
    __tablename__ = "interaction_participants"

    interaction_id: Mapped[str] = mapped_column(ForeignKey("interactions.id", ondelete="CASCADE"))
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )
    face_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    face_track_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    recognition_status: Mapped[str] = mapped_column(String(32), default="unknown")


class TranscriptSegment(IdMixin, TimestampMixin, Base):
    __tablename__ = "transcript_segments"

    interaction_id: Mapped[str] = mapped_column(ForeignKey("interactions.id", ondelete="CASCADE"))
    speaker_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MemoryClaim(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_claims"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_text: Mapped[str] = mapped_column(Text)
    structured_value: Mapped[dict] = mapped_column(JSON, default=dict)
    source_type: Mapped[str] = mapped_column(String(64), default="interaction")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    patient_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)


class Relationship(IdMixin, TimestampMixin, Base):
    __tablename__ = "relationships"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    from_person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    to_person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(160))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Event(IdMixin, TimestampMixin, Base):
    __tablename__ = "events"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    emotional_importance: Mapped[str] = mapped_column(String(32), default="normal")
    patient_visible: Mapped[bool] = mapped_column(Boolean, default=True)


class EventParticipant(IdMixin, TimestampMixin, Base):
    __tablename__ = "event_participants"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MediaAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "media_assets"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    interaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    retention_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")


Index(
    "ix_relationship_unique_patient_from_type",
    Relationship.patient_id,
    Relationship.from_person_id,
)
Index(
    "ix_memory_claim_patient_subject",
    MemoryClaim.patient_id,
    MemoryClaim.subject_type,
    MemoryClaim.subject_id,
)
