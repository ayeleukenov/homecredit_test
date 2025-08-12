import os
import logging
from typing import Any
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import sys

sys.path.append("/app/shared")
from shared.models.complaint_model import ComplaintModel, complaint_to_dict

logger = logging.getLogger(__name__)


class MongoOperations:
    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.db = None
        self.complaints_collection = None
        self.mongodb_url = os.getenv(
            "MONGODB_URL",
            "mongodb://admin:password123@mongodb:27017/ai_support?authSource=admin",
        )

    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(self.mongodb_url)
            await self.client.admin.command("ping")
            self.db = self.client.ai_support
            self.complaints_collection = self.db.complaints
            await self.create_indexes()
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")

    async def create_indexes(self):
        """Create database indexes for optimal performance"""
        try:
            await self.complaints_collection.create_index("customerEmail")
            await self.complaints_collection.create_index("status")
            await self.complaints_collection.create_index("category")
            await self.complaints_collection.create_index("priority")
            await self.complaints_collection.create_index("createdDate")
            await self.complaints_collection.create_index("receivedDate")
            await self.complaints_collection.create_index(
                [("status", 1), ("priority", -1), ("createdDate", -1)]
            )
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")

    async def create_complaint(self, complaint: ComplaintModel) -> str:
        """Create a new complaint in the database"""
        try:
            complaint_dict = complaint_to_dict(complaint)
            if not complaint_dict.get("processingHistory"):
                complaint_dict["processingHistory"] = []
            complaint_dict["processingHistory"].append(
                {
                    "action": "created",
                    "timestamp": datetime.utcnow(),
                    "userId": "system",
                    "details": {"source": "email-service"},
                }
            )
            result = await self.complaints_collection.insert_one(complaint_dict)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error creating complaint: {e}")
            raise

    async def get_complaints(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: str | None = None,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get complaints with optional filtering"""
        try:
            filter_query = {}
            if status_filter:
                filter_query["status"] = status_filter
            if category_filter:
                filter_query["category"] = category_filter
            cursor = (
                self.complaints_collection.find(filter_query)
                .sort("createdDate", -1)
                .skip(skip)
                .limit(limit)
            )
            complaints = []
            async for complaint in cursor:
                complaint["_id"] = str(complaint["_id"])
                if "relatedComplaints" in complaint:
                    complaint["relatedComplaints"] = [
                        str(oid) for oid in complaint["relatedComplaints"]
                    ]
                complaints.append(complaint)
            return complaints
        except Exception as e:
            logger.error(f"Error fetching complaints: {e}")
            raise

    async def get_complaint_by_id(self, complaint_id: str) -> dict[str, Any] | None:
        """Get a specific complaint by ID"""
        try:
            if not ObjectId.is_valid(complaint_id):
                return None
            complaint = await self.complaints_collection.find_one(
                {"_id": ObjectId(complaint_id)}
            )
            if complaint:
                complaint["_id"] = str(complaint["_id"])
                if "relatedComplaints" in complaint:
                    complaint["relatedComplaints"] = [
                        str(oid) for oid in complaint["relatedComplaints"]
                    ]
            return complaint
        except Exception as e:
            logger.error(f"Error fetching complaint {complaint_id}: {e}")
            raise

    async def update_complaint(
        self, complaint_id: str, update_data: dict[str, Any]
    ) -> bool:
        """Update a complaint"""
        try:
            if not ObjectId.is_valid(complaint_id):
                return False
            update_data["lastUpdated"] = datetime.utcnow()
            if "processingHistory" not in update_data:
                current_complaint = await self.get_complaint_by_id(complaint_id)
                if current_complaint:
                    update_data["processingHistory"] = current_complaint.get(
                        "processingHistory", []
                    )
            if "processingHistory" in update_data:
                update_data["processingHistory"].append(
                    {
                        "action": "updated",
                        "timestamp": datetime.utcnow(),
                        "userId": "system",
                        "details": {"fields_updated": list(update_data.keys())},
                    }
                )
            result = await self.complaints_collection.update_one(
                {"_id": ObjectId(complaint_id)}, {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating complaint {complaint_id}: {e}")
            raise

    async def get_stats(self) -> dict[str, Any]:
        """Get system statistics"""
        try:
            total_complaints = await self.complaints_collection.count_documents({})
            status_pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
            status_stats = {}
            async for doc in self.complaints_collection.aggregate(status_pipeline):
                status_stats[doc["_id"]] = doc["count"]
            category_pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
            category_stats = {}
            async for doc in self.complaints_collection.aggregate(category_pipeline):
                category_stats[doc["_id"]] = doc["count"]
            priority_pipeline = [{"$group": {"_id": "$priority", "count": {"$sum": 1}}}]
            priority_stats = {}
            async for doc in self.complaints_collection.aggregate(priority_pipeline):
                priority_stats[doc["_id"]] = doc["count"]
            return {
                "total_complaints": total_complaints,
                "status_distribution": status_stats,
                "category_distribution": category_stats,
                "priority_distribution": priority_stats,
                "last_updated": datetime.utcnow(),
            }
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            raise
