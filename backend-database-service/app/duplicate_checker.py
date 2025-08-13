import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class DuplicateChecker:
    def __init__(self, similarity_threshold: float = 0.85, time_window_days: int = 7):
        self.similarity_threshold = similarity_threshold
        self.time_window_days = time_window_days

    async def check_duplicate(
        self, complaints_collection, new_complaint: Dict[str, Any]
    ) -> Optional[str]:
        """
        Check if the new complaint is a duplicate of existing ones.
        Returns the ID of the original complaint if duplicate found, None otherwise.
        """
        try:
            exact_duplicate = await self._check_exact_duplicate(
                complaints_collection, new_complaint
            )
            if exact_duplicate:
                logger.info(f"Exact duplicate found: {exact_duplicate}")
                return exact_duplicate
            similar_duplicate = await self._check_similar_duplicate(
                complaints_collection, new_complaint
            )
            if similar_duplicate:
                logger.info(f"Similar duplicate found: {similar_duplicate}")
                return similar_duplicate
            return None
        except Exception as e:
            logger.error(f"Error checking duplicates: {e}")
            return None

    async def _check_exact_duplicate(
        self, complaints_collection, new_complaint: Dict[str, Any]
    ) -> Optional[str]:
        """Check for exact duplicates using content hash"""
        content_hash = self._generate_content_hash(new_complaint)
        cutoff_date = datetime.utcnow() - timedelta(days=self.time_window_days)
        existing = await complaints_collection.find_one(
            {
                "customerEmail": new_complaint["customerEmail"],
                "contentHash": content_hash,
                "createdDate": {"$gte": cutoff_date},
            }
        )
        return str(existing["_id"]) if existing else None

    async def _check_similar_duplicate(
        self, complaints_collection, new_complaint: Dict[str, Any]
    ) -> Optional[str]:
        """Check for similar complaints using text similarity"""
        cutoff_date = datetime.utcnow() - timedelta(days=self.time_window_days)
        candidates_cursor = (
            complaints_collection.find(
                {
                    "customerEmail": new_complaint["customerEmail"],
                    "category": new_complaint.get("category"),
                    "createdDate": {"$gte": cutoff_date},
                    "$or": [
                        {"isDuplicate": {"$exists": False}},
                        {"isDuplicate": False},
                    ],
                }
            )
            .sort("createdDate", -1)
            .limit(10)
        )
        candidates = await candidates_cursor.to_list(length=10)
        for candidate in candidates:
            similarity = self._calculate_text_similarity(new_complaint, candidate)
            if similarity >= self.similarity_threshold:
                logger.info(f"Similar complaint found with {similarity:.2f} similarity")
                return str(candidate["_id"])
        return None

    def _generate_content_hash(self, complaint: Dict[str, Any]) -> str:
        """Generate hash from complaint content for exact duplicate detection"""
        content_parts = [
            complaint.get("customerEmail", "").lower().strip(),
            complaint.get("subject", "").lower().strip(),
            self._normalize_text(complaint.get("description", "")),
        ]
        content_string = "|".join(content_parts)
        return hashlib.md5(content_string.encode("utf-8")).hexdigest()

    def _calculate_text_similarity(
        self, complaint1: Dict[str, Any], complaint2: Dict[str, Any]
    ) -> float:
        """Calculate similarity between two complaints"""
        text1 = f"{complaint1.get('subject', '')} {complaint1.get('description', '')}"
        text2 = f"{complaint2.get('subject', '')} {complaint2.get('description', '')}"
        text1 = self._normalize_text(text1)
        text2 = self._normalize_text(text2)
        similarity = SequenceMatcher(None, text1, text2).ratio()
        if (
            complaint1.get("subject", "").lower().strip()
            == complaint2.get("subject", "").lower().strip()
        ):
            similarity = min(1.0, similarity + 0.1)
        return similarity

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison - gentler approach"""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"\s+", " ", text).strip()
        noise_patterns = [
            r"\b(please|thanks?|thank you|hi|hello|dear|regards?)\b",
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def get_duplicate_stats(self) -> Dict[str, Any]:
        """Get statistics about duplicate detection settings"""
        return {
            "similarity_threshold": self.similarity_threshold,
            "time_window_days": self.time_window_days,
            "detection_methods": ["exact_hash", "text_similarity"],
        }
