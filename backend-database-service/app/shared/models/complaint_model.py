from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from bson import ObjectId
from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema.update(type="string")
        return json_schema


class Attachment(BaseModel):
    filename: str
    fileType: str
    fileSize: int
    s3Url: str | None = None
    extractedText: str | None = None
    analysisResults: dict[str, Any] | None = None


class ExtractedEntities(BaseModel):
    orderNumbers: list[str] = []
    amounts: list[float] = []
    dates: list[datetime] = []
    products: list[str] = []
    locations: list[str] = []


class KnowledgeBaseMatch(BaseModel):
    articleId: str
    title: str
    relevanceScore: float


class ProcessingHistoryEntry(BaseModel):
    action: str
    timestamp: datetime
    userId: str | None = None
    details: dict[str, Any] | None = None


class ComplaintModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    customerId: str | None = None
    customerEmail: str
    customerPhone: str | None = None
    subject: str
    description: str
    category: str  
    subcategory: str | None = None
    priority: str  
    status: str = "new"  
    sentiment: str  
    confidenceScore: float = 0.0  
    source: str = "email"  
    receivedDate: datetime
    createdDate: datetime = Field(default_factory=datetime.utcnow)
    assignedTo: str | None = None
    department: str | None = None
    tags: list[str] = []
    attachments: list[Attachment] = []
    extractedEntities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    knowledgeBaseMatches: list[KnowledgeBaseMatch] = []
    estimatedResolutionTime: int | None = None  
    escalationLevel: int = 0  
    legalImplications: bool = False
    compensationRequired: bool = False
    customerSatisfactionScore: float | None = None
    resolutionNotes: str | None = None
    internalNotes: str | None = None
    relatedComplaints: list[PyObjectId] = []
    followUpRequired: bool = False
    lastUpdated: datetime = Field(default_factory=datetime.utcnow)
    processingHistory: list[ProcessingHistoryEntry] = []

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


def complaint_to_dict(complaint: ComplaintModel) -> dict[str, Any]:
    """Convert ComplaintModel to dictionary for MongoDB insertion"""
    data = complaint.dict(by_alias=True)
    return data


def dict_to_complaint(data: dict[str, Any]) -> ComplaintModel:
    """Convert MongoDB document to ComplaintModel"""
    return ComplaintModel(**data)
