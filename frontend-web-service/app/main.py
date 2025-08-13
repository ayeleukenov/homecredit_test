import os
import logging
import io

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
import aiohttp
from dotenv import load_dotenv

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
    
    
@app.get("/download-attachment/{complaint_id}/{filename}")
async def download_attachment(complaint_id: str, filename: str):
    """Download attachment from S3 via email service"""
    try:
        # Get complaint details to find the S3 URL
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DATABASE_SERVICE_URL}/complaints/{complaint_id}") as response:
                if response.status != 200:
                    raise HTTPException(status_code=404, detail="Complaint not found")
                
                complaint = await response.json()
                
                # Find the attachment by filename
                attachment = None
                for att in complaint.get('attachments', []):
                    if att['filename'] == filename:
                        attachment = att
                        break
                
                if not attachment or not attachment.get('s3Url'):
                    raise HTTPException(status_code=404, detail="Attachment not found")
                
                # Get the S3 key from the URL
                s3_url = attachment['s3Url']
                # Extract the key part after the domain
                if '.amazonaws.com/' in s3_url:
                    s3_key = s3_url.split('.amazonaws.com/')[-1]
                else:
                    raise HTTPException(status_code=400, detail="Invalid S3 URL format")
                
                # Download through the email service
                email_service_url = os.getenv("EMAIL_SERVICE_URL", "http://backend-email-service:8003")
                async with session.get(f"{email_service_url}/attachment/{s3_key}") as download_response:
                    if download_response.status != 200:
                        raise HTTPException(status_code=404, detail="File not found in storage")
                    
                    content = await download_response.read()
                    content_type = download_response.headers.get('content-type', 'application/octet-stream')
                    
                    return StreamingResponse(
                        io.BytesIO(content),
                        media_type=content_type,
                        headers={"Content-Disposition": f"attachment; filename={filename}"}
                    )
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading attachment: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
