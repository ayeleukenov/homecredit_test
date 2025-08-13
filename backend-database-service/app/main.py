from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Any
import os
import logging
from datetime import datetime
from mongo_operations import MongoOperations
import sys

sys.path.append("/app/shared")
from shared.models.complaint_model import ComplaintModel, complaint_to_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Database Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
mongo_ops = MongoOperations()


@app.on_event("startup")
async def startup_event():
    """Initialize database connection on startup"""
    try:
        await mongo_ops.connect()
        logger.info("Database service started successfully")
    except Exception as e:
        logger.error(f"Failed to start database service: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up database connections on shutdown"""
    await mongo_ops.disconnect()
    logger.info("Database service shut down")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}


@app.get("/duplicate-stats", response_model=dict[str, Any])
async def get_duplicate_stats():
    """Get duplicate detection statistics"""
    try:
        stats = await mongo_ops.get_duplicate_stats()
        return stats
    except Exception as e:
        logger.error(f"Error fetching duplicate stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch duplicate stats: {str(e)}",
        )


@app.post("/complaints", response_model=dict[str, str])
async def create_complaint(complaint: ComplaintModel):
    """Create a new complaint record"""
    try:
        complaint_id = await mongo_ops.create_complaint(complaint)
        logger.info(f"Created complaint with ID: {complaint_id}")
        return {"id": str(complaint_id), "message": "Complaint created successfully"}
    except Exception as e:
        logger.error(f"Error creating complaint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create complaint: {str(e)}",
        )


@app.get("/complaints", response_model=list[dict[str, Any]])
async def get_complaints(
    skip: int = 0,
    limit: int = 100,
    status_filter: str | None = None,
    category_filter: str | None = None,
):
    """Get complaints with optional filtering"""
    try:
        complaints = await mongo_ops.get_complaints(
            skip=skip,
            limit=limit,
            status_filter=status_filter,
            category_filter=category_filter,
        )
        return complaints
    except Exception as e:
        logger.error(f"Error fetching complaints: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch complaints: {str(e)}",
        )


@app.get("/complaints/{complaint_id}", response_model=dict[str, Any])
async def get_complaint(complaint_id: str):
    """Get a specific complaint by ID"""
    try:
        complaint = await mongo_ops.get_complaint_by_id(complaint_id)
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found"
            )
        return complaint
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching complaint {complaint_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch complaint: {str(e)}",
        )


@app.put("/complaints/{complaint_id}", response_model=dict[str, str])
async def update_complaint(complaint_id: str, update_data: dict[str, Any]):
    """Update a complaint"""
    try:
        updated = await mongo_ops.update_complaint(complaint_id, update_data)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found"
            )
        logger.info(f"Updated complaint {complaint_id}")
        return {"id": complaint_id, "message": "Complaint updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating complaint {complaint_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update complaint: {str(e)}",
        )


@app.get("/stats", response_model=dict[str, Any])
async def get_stats():
    """Get system statistics"""
    try:
        stats = await mongo_ops.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", 8001))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
