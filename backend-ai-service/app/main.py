from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import os
import logging
from datetime import datetime
import json
from claude_analyzer import ClaudeAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="AI Processing Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
claude_analyzer = ClaudeAnalyzer()


class EmailAnalysisRequest(BaseModel):
    customer_email: str
    subject: str
    content: str
    attachments: list[dict[str, Any]] | None = []
    received_date: datetime


class EmailAnalysisResponse(BaseModel):
    analysis_results: dict[str, Any]
    processing_time: float
    confidence_score: float


@app.on_event("startup")
async def startup_event():
    """Initialize AI service on startup"""
    try:
        if not os.getenv("CLAUDE_API_KEY"):
            raise ValueError("CLAUDE_API_KEY environment variable is required")
        logger.info("AI Processing service started successfully")
    except Exception as e:
        logger.error(f"Failed to start AI processing service: {e}")
        raise


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}


@app.post("/analyze", response_model=EmailAnalysisResponse)
async def analyze_email(request: EmailAnalysisRequest):
    """Analyze email content using Claude"""
    try:
        start_time = datetime.utcnow()
        analysis_results = await claude_analyzer.analyze_email(
            customer_email=request.customer_email,
            subject=request.subject,
            content=request.content,
            attachments=request.attachments,
            received_date=request.received_date,
        )
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"Email analysis completed in {processing_time:.2f}s")
        return EmailAnalysisResponse(
            analysis_results=analysis_results,
            processing_time=processing_time,
            confidence_score=analysis_results.get("confidenceScore", 0.0),
        )
    except Exception as e:
        logger.error(f"Error analyzing email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze email: {str(e)}",
        )


@app.post("/analyze-attachment")
async def analyze_attachment(filename: str, file_type: str, extracted_text: str):
    """Analyze attachment content"""
    try:
        analysis = await claude_analyzer.analyze_attachment(
            filename=filename, file_type=file_type, extracted_text=extracted_text
        )
        return {"analysis": analysis}
    except Exception as e:
        logger.error(f"Error analyzing attachment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze attachment: {str(e)}",
        )


@app.post("/extract-entities")
async def extract_entities(text: str):
    """Extract entities from text"""
    try:
        entities = await claude_analyzer.extract_entities(text)
        return {"entities": entities}
    except Exception as e:
        logger.error(f"Error extracting entities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract entities: {str(e)}",
        )


@app.get("/categories")
async def get_available_categories():
    """Get available complaint categories"""
    return {
        "categories": [
            "returns",
            "delivery",
            "quality",
            "technical",
            "billing",
            "other",
        ],
        "priorities": ["high", "medium", "low"],
        "sentiments": ["positive", "negative", "neutral"],
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", 8002))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
