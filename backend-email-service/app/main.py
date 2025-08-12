# email-service/app/main.py
from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List
import os
import logging
from datetime import datetime
import asyncio

from email_processor import EmailProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Email Service", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize email processor
email_processor = EmailProcessor()

class EmailProcessingStatus(BaseModel):
    status: str
    processed_count: int
    last_processed: str
    errors: List[str]

class ManualEmailRequest(BaseModel):
    customer_email: str
    subject: str
    content: str
    received_date: str = None

@app.on_event("startup")
async def startup_event():
    """Initialize email service on startup"""
    try:
        await email_processor.initialize()
        
        # Start background email processing
        asyncio.create_task(background_email_processing())
        
        logger.info("Email service started successfully")
    except Exception as e:
        logger.error(f"Failed to start email service: {e}")
        raise

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.get("/status", response_model=EmailProcessingStatus)
async def get_processing_status():
    """Get email processing status"""
    try:
        status = await email_processor.get_status()
        return EmailProcessingStatus(**status)
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}"
        )

@app.post("/process-manual")
async def process_manual_email(email_data: ManualEmailRequest):
    """Manually process an email (for testing)"""
    try:
        # Convert received_date string to datetime if provided
        received_date = datetime.utcnow()
        if email_data.received_date:
            try:
                received_date = datetime.fromisoformat(email_data.received_date.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        result = await email_processor.process_single_email(
            customer_email=email_data.customer_email,
            subject=email_data.subject,
            content=email_data.content,
            received_date=received_date,
            attachments=[]
        )
        
        return {"message": "Email processed successfully", "complaint_id": result}
        
    except Exception as e:
        logger.error(f"Error processing manual email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process email: {str(e)}"
        )

@app.post("/start-processing")
async def start_email_processing(background_tasks: BackgroundTasks):
    """Start email processing manually"""
    try:
        background_tasks.add_task(email_processor.process_new_emails)
        return {"message": "Email processing started"}
    except Exception as e:
        logger.error(f"Error starting email processing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start processing: {str(e)}"
        )

@app.get("/processed-emails")
async def get_processed_emails(limit: int = 50):
    """Get list of recently processed emails"""
    try:
        emails = await email_processor.get_processed_emails(limit)
        return {"emails": emails}
    except Exception as e:
        logger.error(f"Error getting processed emails: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get processed emails: {str(e)}"
        )

async def background_email_processing():
    """Background task to continuously process emails"""
    while True:
        try:
            await email_processor.process_new_emails()
            # Wait 30 seconds before checking for new emails again
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error in background email processing: {e}")
            # Wait longer on error to avoid spam
            await asyncio.sleep(60)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", 8003))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
    