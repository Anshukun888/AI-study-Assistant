"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, List, Dict, Any


# User schemas
class UserRegister(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user response."""
    id: int
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


# Document schemas
class DocumentCreate(BaseModel):
    """Schema for document creation."""
    filename: str
    extracted_text: str


class DocumentResponse(BaseModel):
    """Schema for document response."""
    id: int
    user_id: int
    filename: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentDetailResponse(BaseModel):
    """Schema for detailed document response."""
    id: int
    user_id: int
    filename: str
    extracted_text: str
    created_at: datetime
    summaries: List['SummaryResponse'] = []
    questions: List['QuestionResponse'] = []

    class Config:
        from_attributes = True


# Summary schemas
class SummaryCreate(BaseModel):
    """Schema for summary creation."""
    document_id: int
    content: str


class SummaryResponse(BaseModel):
    """Schema for summary response."""
    id: int
    document_id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# Question schemas
class QuestionCreate(BaseModel):
    """Schema for question creation."""
    document_id: int
    content_json: str


class QuestionResponse(BaseModel):
    """Schema for question response."""
    id: int
    document_id: int
    content_json: str
    created_at: datetime

    class Config:
        from_attributes = True


# AI request schemas
class GenerateSummaryRequest(BaseModel):
    """Schema for summary generation request."""
    document_id: int


class GenerateMCQRequest(BaseModel):
    """Schema for MCQ generation request."""
    document_id: int


class GenerateExamAnswerRequest(BaseModel):
    """Schema for exam answer generation request."""
    document_id: int
    question: str


class AskRequest(BaseModel):
    """Schema for ask question request."""
    document_id: int
    question: str


# Analytics (weak topic) schemas
class AnalyticsUpdateRequest(BaseModel):
    """Schema for updating topic attempt (correct/wrong)."""
    topic: str
    is_correct: bool


class WeakTopicResponse(BaseModel):
    """Schema for weak topic in GET /analytics/weak-topics."""
    topic: str
    weak_score: float
    level: str


# Smart revision planner schemas
class StudyPlanRequest(BaseModel):
    """Schema for POST /study/plan."""
    exam_date: str  # YYYY-MM-DD


class StudyPlanDay(BaseModel):
    day: int
    topics: List[str]


class StudyPlanResponse(BaseModel):
    """Schema for revision plan response."""
    plan: List[StudyPlanDay]
    message: Optional[str] = None


# Practice mode schemas
class PracticeGenerateRequest(BaseModel):
    """Schema for POST /practice/generate."""
    topic: str
    difficulty: str = "medium"


class PracticeMCQItem(BaseModel):
    question: str
    options: List[str]
    correct_index: int
    correct_answer: str
    explanation: str


class PracticeShortItem(BaseModel):
    question: str
    correct_answer: str
    explanation: str


class PracticeGenerateResponse(BaseModel):
    mcqs: List[PracticeMCQItem] = []
    short_questions: List[PracticeShortItem] = []


# Update forward references
DocumentDetailResponse.model_rebuild()
SummaryResponse.model_rebuild()
QuestionResponse.model_rebuild()

