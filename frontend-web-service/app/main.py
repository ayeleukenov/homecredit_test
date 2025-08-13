import os
import logging
import io

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import aiohttp
from dotenv import load_dotenv

from s3_handler import S3Handler
s3_handler = S3Handler()

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Web Interface Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory="templates")
DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL")
EMAIL_SERVICE_URL = os.getenv("EMAIL_SERVICE_URL")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DATABASE_SERVICE_URL}/stats") as response:
                if response.status == 200:
                    stats = await response.json()
                else:
                    stats = {"error": "Could not fetch stats"}
            async with session.get(
                f"{DATABASE_SERVICE_URL}/complaints?limit=10"
            ) as response:
                if response.status == 200:
                    recent_complaints = await response.json()
                else:
                    recent_complaints = []
            async with session.get(f"{EMAIL_SERVICE_URL}/status") as response:
                if response.status == 200:
                    email_status = await response.json()
                else:
                    email_status = {"status": "unknown", "processed_count": 0}
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "stats": stats,
                "recent_complaints": recent_complaints,
                "email_status": email_status,
            },
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return templates.TemplateResponse(
            "error.html", {"request": request, "error": str(e)}
        )


@app.get("/complaints", response_class=HTMLResponse)
async def complaints_page(
    request: Request,
    page: int = 1,
    status_filter: str | None = None,
    category_filter: str | None = None,
):
    """Complaints listing page"""
    try:
        page_size = 20
        skip = (page - 1) * page_size
        params = {"skip": skip, "limit": page_size}
        if status_filter:
            params["status_filter"] = status_filter
        if category_filter:
            params["category_filter"] = category_filter
        async with aiohttp.ClientSession() as session:
            url = f"{DATABASE_SERVICE_URL}/complaints"
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    complaints = await response.json()
                else:
                    complaints = []
        return templates.TemplateResponse(
            "complaints.html",
            {
                "request": request,
                "complaints": complaints,
                "page": page,
                "status_filter": status_filter,
                "category_filter": category_filter,
            },
        )
    except Exception as e:
        logger.error(f"Error loading complaints: {e}")
        return templates.TemplateResponse(
            "error.html", {"request": request, "error": str(e)}
        )


@app.get("/complaint/{complaint_id}", response_class=HTMLResponse)
async def complaint_detail(request: Request, complaint_id: str):
    """Individual complaint detail page"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATABASE_SERVICE_URL}/complaints/{complaint_id}"
            ) as response:
                if response.status == 200:
                    complaint = await response.json()
                elif response.status == 404:
                    raise HTTPException(status_code=404, detail="Complaint not found")
                else:
                    raise Exception("Database service error")
        return templates.TemplateResponse(
            "complaint_detail.html", {"request": request, "complaint": complaint}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading complaint {complaint_id}: {e}")
        return templates.TemplateResponse(
            "error.html", {"request": request, "error": str(e)}
        )


@app.get("/test", response_class=HTMLResponse)
async def test_page(request: Request):
    """Test page for manual email processing"""
    return templates.TemplateResponse("test.html", {"request": request})


@app.post("/api/test-email")
async def test_email_processing(request: Request):
    """API endpoint to test email processing"""
    try:
        data = await request.json()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{EMAIL_SERVICE_URL}/process-manual", json=data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    error_text = await response.text()
                    raise Exception(f"Email service error: {error_text}")
    except Exception as e:
        logger.error(f"Error testing email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """API endpoint for stats"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DATABASE_SERVICE_URL}/stats") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception("Database service error")
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.get("/api/download/{complaint_id}/{attachment_index}")
async def download_attachment(complaint_id: str, attachment_index: int):
    """Generate download link for attachment"""
    try:
        # Get complaint details
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATABASE_SERVICE_URL}/complaints/{complaint_id}"
            ) as response:
                if response.status == 200:
                    complaint = await response.json()
                elif response.status == 404:
                    raise HTTPException(status_code=404, detail="Complaint not found")
                else:
                    raise Exception("Database service error")
        
        # Check if attachment exists
        if attachment_index >= len(complaint.get("attachments", [])):
            raise HTTPException(status_code=404, detail="Attachment not found")
        
        attachment = complaint["attachments"][attachment_index]
        s3_url = attachment.get("s3Url")
        
        if not s3_url:
            raise HTTPException(status_code=404, detail="File not available for download")
        
        # Generate presigned URL for download
        if s3_handler.is_configured():
            download_url = s3_handler.generate_presigned_url(s3_url, expiration=300)  # 5 minutes
            if download_url:
                return RedirectResponse(url=download_url)
            else:
                raise HTTPException(status_code=500, detail="Failed to generate download link")
        else:
            # Fallback: direct S3 URL (only if bucket is public)
            return RedirectResponse(url=s3_url)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating download link: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/attachment-info/{complaint_id}/{attachment_index}")
async def get_attachment_info(complaint_id: str, attachment_index: int):
    """Get attachment metadata without downloading"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATABASE_SERVICE_URL}/complaints/{complaint_id}"
            ) as response:
                if response.status == 200:
                    complaint = await response.json()
                elif response.status == 404:
                    raise HTTPException(status_code=404, detail="Complaint not found")
                else:
                    raise Exception("Database service error")
        
        if attachment_index >= len(complaint.get("attachments", [])):
            raise HTTPException(status_code=404, detail="Attachment not found")
        
        attachment = complaint["attachments"][attachment_index]
        
        return {
            "filename": attachment.get("filename"),
            "fileType": attachment.get("fileType"), 
            "fileSize": attachment.get("fileSize"),
            "hasS3Url": bool(attachment.get("s3Url")),
            "extractedText": attachment.get("extractedText", "")[:500] + "..." if len(attachment.get("extractedText", "")) > 500 else attachment.get("extractedText", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting attachment info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
