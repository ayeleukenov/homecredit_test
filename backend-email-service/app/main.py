import os
import logging
import asyncio
from datetime import datetime
import io

from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from email_processor import EmailProcessor
from fastapi.responses import StreamingResponse
from s3_storage import S3StorageService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Email Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

email_processor = EmailProcessor()
s3_storage = S3StorageService()


class EmailProcessingStatus(BaseModel):
    status: str
    processed_count: int
    last_processed: str
    errors: list[str]


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
            detail=f"Failed to get status: {str(e)}",
        )


@app.post("/process-manual")
async def process_manual_email(email_data: ManualEmailRequest):
    """Manually process an email (for testing)"""
    try:
        received_date = datetime.utcnow()
        if email_data.received_date:
            try:
                received_date = datetime.fromisoformat(
                    email_data.received_date.replace("Z", "+00:00")
                )
            except ValueError:
                pass
        result = await email_processor.process_single_email(
            customer_email=email_data.customer_email,
            subject=email_data.subject,
            content=email_data.content,
            received_date=received_date,
            attachments=[],
        )
        return {"message": "Email processed successfully", "complaint_id": result}
    except Exception as e:
        logger.error(f"Error processing manual email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process email: {str(e)}",
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
            detail=f"Failed to start processing: {str(e)}",
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
            detail=f"Failed to get processed emails: {str(e)}",
        )


@app.get("/attachment/{attachment_path:path}")
async def download_attachment_from_s3(attachment_path: str):
    """Download attachment directly from S3 (used by frontend service)"""
    try:

        bucket_name = s3_storage.bucket_name
        region = s3_storage.region
        s3_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{attachment_path}"

        file_data = s3_storage.download_attachment(s3_url)
        if not file_data:
            raise HTTPException(status_code=404, detail="Attachment not found in S3")

        filename = attachment_path.split("/")[-1]

        content_type = (
            s3_storage._get_content_type(filename) or "application/octet-stream"
        )

        logger.info(f"Successfully downloaded {filename} from S3")

        return StreamingResponse(
            io.BytesIO(file_data),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading attachment from S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download attachment: {str(e)}",
        )


@app.get("/s3-stats")
async def get_s3_statistics():
    """Get S3 storage statistics"""
    try:
        stats = s3_storage.get_storage_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting S3 stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get S3 stats: {str(e)}",
        )


@app.delete("/attachment/{attachment_path:path}")
async def delete_attachment_from_s3(attachment_path: str):
    """Delete attachment from S3"""
    try:

        bucket_name = s3_storage.bucket_name
        region = s3_storage.region
        s3_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{attachment_path}"

        success = s3_storage.delete_attachment(s3_url)
        if not success:
            raise HTTPException(status_code=404, detail="Attachment not found")

        return {"message": "Attachment deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting attachment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete attachment: {str(e)}",
        )


async def background_email_processing():
    """Background task to continuously process emails"""
    while True:
        try:
            await email_processor.process_new_emails()
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error in background email processing: {e}")
            await asyncio.sleep(60)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", 8003))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
