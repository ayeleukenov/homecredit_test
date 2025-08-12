import os
import json
import logging
import re
from datetime import datetime
from typing import Any
from dotenv import load_dotenv
import anthropic
import asyncio

load_dotenv()
logger = logging.getLogger(__name__)


class ClaudeAnalyzer:
    def __init__(self):
        self.api_key = os.getenv("CLAUDE_API_KEY")
        if not self.api_key:
            raise ValueError("CLAUDE_API_KEY environment variable is required")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = "claude-3-5-sonnet-20241022"

    async def analyze_email(
        self,
        customer_email: str,
        subject: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        received_date: datetime = None,
    ) -> dict[str, Any]:
        """Analyze email content and return structured complaint data"""
        attachment_text = ""
        if attachments:
            for att in attachments:
                if att.get("extractedText"):
                    attachment_text += f"\n--- Attachment: {att.get('filename')} ---\n{att.get('extractedText')}\n"
        full_content = f"{content}\n{attachment_text}".strip()
        prompt = self._build_analysis_prompt(
            customer_email=customer_email,
            subject=subject,
            content=full_content,
            received_date=received_date,
        )
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    temperature=0.1,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            response_text = response.content[0].text
            analysis_data = self._parse_claude_response(response_text)
            analysis_data.update(
                self._generate_derived_fields(
                    analysis_data, subject, content, customer_email, received_date
                )
            )
            logger.info(f"Successfully analyzed email from {customer_email}")
            return analysis_data
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}")
            return self._generate_fallback_analysis(customer_email, subject, content)

    def _build_analysis_prompt(
        self,
        customer_email: str,
        subject: str,
        content: str,
        received_date: datetime = None,
    ) -> str:
        """Build comprehensive analysis prompt for Claude"""
        return f"""
Analyze this customer support email and extract structured information. Return ONLY valid JSON.
Email Details:
- Customer Email: {customer_email}
- Subject: {subject}
- Received Date: {received_date or datetime.utcnow()}
- Content: {content[:3000]}
Extract and return JSON with these exact fields:
{{
  "category": "returns|delivery|quality|technical|billing|other",
  "subcategory": "specific subcategory or null",
  "priority": "high|medium|low",
  "sentiment": "positive|negative|neutral",
  "confidenceScore": 0.85,
  "customerId": "extracted customer ID or null",
  "customerPhone": "extracted phone number or null",
  "department": "customer_service|technical|billing|returns|escalation",
  "tags": ["relevant", "tags", "for", "search"],
  "extractedEntities": {{
    "orderNumbers": ["ORDER123", "ORD456"],
    "amounts": [99.99, 25.50],
    "dates": ["2024-01-15", "2024-02-20"],
    "products": ["Product Name", "Service Type"],
    "locations": ["City", "Address"]
  }},
  "estimatedResolutionTime": 24,
  "escalationLevel": 0,
  "legalImplications": false,
  "compensationRequired": true,
  "followUpRequired": true
}}
Analysis Guidelines:
- category: Classify the main issue type
- priority: high=urgent/angry/legal, medium=normal complaint, low=simple question
- sentiment: Based on customer tone and language
- confidenceScore: Your confidence in the classification (0-1)
- extractedEntities: Extract all relevant entities from the text
- estimatedResolutionTime: Hours needed (simple=2-8, medium=8-24, complex=24-72)
- escalationLevel: 0=normal, 1=supervisor, 2=manager, 3=legal
- legalImplications: true if mentions legal action, lawsuits, regulations
- compensationRequired: true if customer wants refund/compensation
- followUpRequired: true if needs human follow-up
Return ONLY the JSON object, no other text.
"""

    def _parse_claude_response(self, response_text: str) -> dict[str, Any]:
        """Parse Claude's JSON response"""
        try:
            logger.info(f"Raw response length: {len(response_text)}")
            logger.info(f"Raw response repr: {repr(response_text)}")

            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                logger.info(f"Extracted JSON: {repr(json_str)}")  # Debug line
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
                
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse Claude response: {e}")
            logger.error(f"Response text: {response_text}")
            logger.error(f"Character at error position: {repr(response_text[440:450])}")  # Show problem area
            raise

    def _generate_derived_fields(
        self,
        analysis: dict[str, Any],
        subject: str,
        content: str,
        customer_email: str,
        received_date: str,
    ) -> dict[str, Any]:
        """Generate additional fields based on analysis"""
        department_mapping = {
            "returns": "returns_team",
            "delivery": "logistics_team",
            "quality": "quality_team",
            "technical": "tech_support",
            "billing": "billing_team",
            "other": "customer_service",
        }
        category = analysis.get("category", "other")
        return {
            "customerEmail": customer_email,
            "subject": subject,
            "receivedDate": datetime.utcnow().isoformat(),
            "assignedTo": department_mapping.get(category, "customer_service"),
            "description": f"{subject}\n\n{content}"[:1000],
            "source": "email",
            "status": "new",
            "lastUpdated": datetime.utcnow().isoformat(),
            "processingHistory": [
                {
                    "action": "ai_analysis_completed",
                    "timestamp": datetime.utcnow().isoformat(),
                    "userId": "claude_ai",
                    "details": {
                        "model": self.model,
                        "confidence": analysis.get("confidenceScore", 0.0),
                    },
                }
            ],
        }

    def _generate_fallback_analysis(
        self, customer_email: str, subject: str, content: str
    ) -> dict[str, Any]:
        """Generate fallback analysis when Claude API fails"""
        logger.warning("Using fallback analysis due to Claude API failure")
        content_lower = content.lower()
        subject_lower = subject.lower()
        if any(word in content_lower for word in ["return", "refund", "cancel"]):
            category = "returns"
        elif any(word in content_lower for word in ["delivery", "shipping", "arrived"]):
            category = "delivery"
        elif any(word in content_lower for word in ["broken", "defective", "quality"]):
            category = "quality"
        elif any(
            word in content_lower for word in ["login", "password", "error", "bug"]
        ):
            category = "technical"
        elif any(word in content_lower for word in ["charge", "bill", "payment"]):
            category = "billing"
        else:
            category = "other"
        if any(
            word in content_lower
            for word in ["urgent", "asap", "immediately", "angry", "furious"]
        ):
            priority = "high"
        elif any(word in content_lower for word in ["please", "help", "issue"]):
            priority = "medium"
        else:
            priority = "low"
        negative_words = [
            "angry",
            "frustrated",
            "terrible",
            "awful",
            "hate",
            "horrible",
        ]
        positive_words = ["good", "great", "thank", "appreciate", "love"]
        if any(word in content_lower for word in negative_words):
            sentiment = "negative"
        elif any(word in content_lower for word in positive_words):
            sentiment = "positive"
        else:
            sentiment = "neutral"
        return {
            "category": category,
            "subcategory": None,
            "priority": priority,
            "sentiment": sentiment,
            "confidenceScore": 0.3,
            "customerId": None,
            "customerPhone": None,
            "department": "customer_service",
            "tags": [category, priority],
            "extractedEntities": {
                "orderNumbers": [],
                "amounts": [],
                "dates": [],
                "products": [],
                "locations": [],
            },
            "estimatedResolutionTime": 24,
            "escalationLevel": 1 if priority == "high" else 0,
            "legalImplications": False,
            "compensationRequired": "refund" in content_lower,
            "followUpRequired": True,
            **self._generate_derived_fields({}, subject, content, customer_email, None),
        }

    async def analyze_attachment(
        self, filename: str, file_type: str, extracted_text: str
    ) -> dict[str, Any]:
        """Analyze attachment content"""
        prompt = f"""
Analyze this attachment content and extract relevant information:
Filename: {filename}
File Type: {file_type}
Content: {extracted_text[:2000]}
Return JSON with:
{{
  "summary": "brief summary of content",
  "relevantInfo": ["key", "points", "extracted"],
  "containsPersonalInfo": true/false,
  "documentType": "invoice|receipt|contract|image|other",
  "extractedData": {{
    "amounts": [99.99],
    "dates": ["2024-01-15"],
    "references": ["REF123"]
  }}
}}
"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    temperature=0.1,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            response_text = response.content[0].text
            return self._parse_claude_response(response_text)
        except Exception as e:
            logger.error(f"Error analyzing attachment: {e}")
            return {
                "summary": f"Attachment: {filename}",
                "relevantInfo": ["Could not analyze"],
                "containsPersonalInfo": False,
                "documentType": "other",
                "extractedData": {"amounts": [], "dates": [], "references": []},
            }

    async def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract entities from text"""
        prompt = f"""
Extract entities from this text and return JSON:
Text: {text[:1500]}
Return JSON with:
{{
  "orderNumbers": ["ORDER123"],
  "amounts": [99.99, 25.50],
  "dates": ["2024-01-15"],
  "products": ["Product Name"],
  "locations": ["City, State"],
  "phoneNumbers": ["+1-555-0123"],
  "emails": ["user@example.com"]
}}
Extract all instances of each entity type.
"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=800,
                    temperature=0.1,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            response_text = response.content[0].text
            return self._parse_claude_response(response_text)
        except Exception as e:
            logger.error(f"Error extracting entities: {e}")
            return {
                "orderNumbers": [],
                "amounts": [],
                "dates": [],
                "products": [],
                "locations": [],
                "phoneNumbers": [],
                "emails": [],
            }
