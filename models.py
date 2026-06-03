from datetime import datetime
from enum import Enum
import uuid
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class ReportType(Enum):
    INCIDENT = "incident"
    SAFEGUARDING = "safeguarding"
    COMPLAINT = "complaint"

class UserRole(Enum):
    STAFF = "staff"
    MANAGER = "manager"
    DSL = "designated_safeguarding_lead"  
    ADMIN = "admin"

class SiteLocation(str, Enum):
    OPERATIONS = "Operations"
    HEALTH_AND_SAFETY = "Health and Safety"
    COMPLIANCE = "Compliance"
    GLOBAL = "Global"

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.STAFF)
    site_location = Column(String, default=SiteLocation.OPERATIONS.value) 
    reports_filed = relationship("Report", foreign_keys="Report.reporter_id")

class Report(Base):
    __tablename__ = 'reports'
    id = Column(Integer, primary_key=True)
    report_type = Column(SQLEnum(ReportType), nullable=False)
    site_location = Column(String, default=SiteLocation.OPERATIONS.value) 
    category = Column(String, default="General")
    cqc_tag = Column(String, nullable=True) 
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, default="Open")
    
    due_date = Column(DateTime, nullable=True) 
    attachment_path = Column(String, nullable=True)
    action_plan = Column(Text, nullable=True)
    review_date = Column(DateTime, nullable=True)
    
    # RCA ENGINE (5 WHYS)
    rca_1 = Column(String, nullable=True)
    rca_2 = Column(String, nullable=True)
    rca_3 = Column(String, nullable=True)
    rca_4 = Column(String, nullable=True)
    rca_5 = Column(String, nullable=True)
    
    secure_link_id = Column(String, unique=True, index=True, nullable=True)
    secure_link_expires = Column(DateTime, nullable=True)
    effectiveness_rating = Column(Integer, nullable=True) 
    
    escalation_level = Column(Integer, default=0) 
    is_pilot = Column(Boolean, default=False)
    pilot_feedback = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    reporter_id = Column(Integer, ForeignKey('users.id'))
    assigned_to_id = Column(Integer, ForeignKey('users.id'), nullable=True)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
