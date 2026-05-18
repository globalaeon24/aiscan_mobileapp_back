from sqlalchemy import (
    Column, Integer, String, Text, Float, ForeignKey, DateTime, Boolean
)
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    users = relationship("User", back_populates="organization_rel")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    agreed_privacy = Column(Boolean, default=False)
    agreed_at = Column(DateTime, nullable=True)

    organization_rel = relationship("Organization", back_populates="users")
    scan_results = relationship("ScanResult", back_populates="user", cascade="all, delete")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    user_scan_index = Column(Integer, nullable=False)
    file_name = Column(String, nullable=True)
    author_name = Column(String, nullable=False)

    scanned_text = Column(Text, nullable=False)
    highlighted_text = Column(Text, nullable=True)
    ai_percentage = Column(Float, nullable=False)
    ai_fragments = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="scan_results")