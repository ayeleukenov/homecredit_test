import os
import imaplib
import email
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import base64
import io

# For attachment processing
import PyPDF2
import docx
from PIL import Image
import pytesseract
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.append('/app/shared')
from shared_temp.models.complaint_model import ComplaintModel, ExtractedEntities, Attachment

logger = logging.getLogger(__name__)

class EmailProcessor:
    def __init__(self):
        self.ai_service_url = os.getenv("AI_SERVICE_URL")
        self.database_service_url = os.getenv("DATABASE_SERVICE_URL")
        
        # Email configuration
        self.email_server = os.getenv("EMAIL_SERVER")
        self.email_user = os.getenv("EMAIL_USER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        
        # Processing state
        self.processed_count = 0
        self.last_processed = None
        self.errors = []
        self.processed_emails = []
        
    async def initialize(self):
        """Initialize email processor"""
        if not self.email_user or not self.email_password:
            logger.warning("Email credentials not provided. Manual processing only.")
        else:
            logger.info("Email processor initialized with IMAP connection")

    async def get_status(self) -> Dict[str, Any]:
        """Get current processing status"""
        return {
            "status": "running",
            "processed_count": self.processed_count,
            "last_processed": self.last_processed or "Never",
            "errors": self.errors[-5:]  # Last 5 errors
        }

    async def process_new_emails(self) -> None:
        """Process new emails from IMAP server"""
        if not self.email_user or not self.email_password:
            logger.warning("No email credentials configured")
            return
            
        try:
            # Connect to IMAP server
            mail = imaplib.IMAP4_SSL(self.email_server)
            mail.login(self.email_user, self.email_password)
            mail.select('inbox')
            
            # Search for unread emails
            typ, data = mail.search(None, 'UNSEEN')
            
            if data[0]:
                email_ids = data[0].split()
                logger.info(f"Found {len(email_ids)} unread emails")
                
                for email_id in email_ids:
                    try:
                        await self._process_email_from_imap(mail, email_id)
                        self.processed_count += 1
                    except Exception as e:
                        error_msg = f"Error processing email {email_id}: {e}"
                        logger.error(error_msg)
                        self.errors.append(error_msg)
                        
                self.last_processed = datetime.utcnow().isoformat()
                        
            mail.close()
            mail.logout()
            
        except Exception as e:
            error_msg = f"Error connecting to email server: {e}"
            logger.error(error_msg)
            self.errors.append(error_msg)

    async def _process_email_from_imap(self, mail, email_id) -> None:
        """Process a single email from IMAP"""
        typ, data = mail.fetch(email_id, '(RFC822)')
        raw_email = data[0][1]
        
        # Parse email
        email_message = email.message_from_bytes(raw_email)
        
        # Extract email details
        customer_email = email.utils.parseaddr(email_message['From'])[1]
        subject = email_message['Subject'] or "No Subject"
        received_date = email.utils.parsedate_to_datetime(email_message['Date'])
        
        # Extract email content
        content = self._extract_email_content(email_message)
        
        # Extract attachments
        attachments = await self._extract_attachments(email_message)
        
        # Process the email
        complaint_id = await self.process_single_email(
            customer_email=customer_email,
            subject=subject,
            content=content,
            received_date=received_date,
            attachments=attachments
        )
        
        # Mark email as read
        mail.store(email_id, '+FLAGS', '\\Seen')
        
        logger.info(f"Processed email from {customer_email}, created complaint {complaint_id}")

    def _extract_email_content(self, email_message) -> str:
        """Extract text content from email"""
        content = ""
        
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        content += payload.decode('utf-8', errors='ignore')
                elif part.get_content_type() == "text/html":
                    # Basic HTML to text conversion
                    import re
                    payload = part.get_payload(decode=True)
                    if payload:
                        html_content = payload.decode('utf-8', errors='ignore')
                        # Remove HTML tags
                        text_content = re.sub(r'<[^>]+>', '', html_content)
                        content += text_content
        else:
            payload = email_message.get_payload(decode=True)
            if payload:
                content = payload.decode('utf-8', errors='ignore')
                
        return content.strip()

    async def _extract_attachments(self, email_message) -> List[Dict[str, Any]]:
        """Extract and process attachments"""
        attachments = []
        
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_disposition() == 'attachment':
                    filename = part.get_filename()
                    if filename:
                        try:
                            # Get file content
                            file_data = part.get_payload(decode=True)
                            
                            # Process attachment
                            attachment_info = await self._process_attachment(
                                filename=filename,
                                file_data=file_data
                            )
                            
                            attachments.append(attachment_info)
                            
                        except Exception as e:
                            logger.error(f"Error processing attachment {filename}: {e}")
                            
        return attachments

    async def _process_attachment(self, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Process a single attachment"""
        file_type = filename.split('.')[-1].lower() if '.' in filename else 'unknown'
        file_size = len(file_data)
        
        attachment_info = {
            "filename": filename,
            "fileType": file_type,
            "fileSize": file_size,
            "s3Url": None,  # Would upload to S3 in production
            "extractedText": "",
            "analysisResults": None
        }
        
        try:
            # Extract text based on file type
            if file_type == 'pdf':
                attachment_info["extractedText"] = self._extract_pdf_text(file_data)
            elif file_type in ['doc', 'docx']:
                attachment_info["extractedText"] = self._extract_docx_text(file_data)
            elif file_type in ['jpg', 'jpeg', 'png', 'gif']:
                attachment_info["extractedText"] = await self._extract_image_text(file_data)
            elif file_type in ['txt']:
                attachment_info["extractedText"] = file_data.decode('utf-8', errors='ignore')
                
        except Exception as e:
            logger.error(f"Error extracting text from {filename}: {e}")
            
        return attachment_info

    def _extract_pdf_text(self, file_data: bytes) -> str:
        """Extract text from PDF"""
        try:
            pdf_file = io.BytesIO(file_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
                
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return ""

    def _extract_docx_text(self, file_data: bytes) -> str:
        """Extract text from DOCX"""
        try:
            doc_file = io.BytesIO(file_data)
            doc = docx.Document(doc_file)
            
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
                
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {e}")
            return ""

    async def _extract_image_text(self, file_data: bytes) -> str:
        """Extract text from image using OCR"""
        try:
            image = Image.open(io.BytesIO(file_data))
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting image text: {e}")
            return ""

    async def process_single_email(
        self,
        customer_email: str,
        subject: str,
        content: str,
        received_date: datetime,
        attachments: List[Dict[str, Any]]
    ) -> str:
        """Process a single email and create complaint"""
        
        try:
            # Call AI service for analysis
            analysis_request = {
                "customer_email": customer_email,
                "subject": subject,
                "content": content,
                "attachments": attachments,
                "received_date": received_date.isoformat()  # Convert to string
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ai_service_url}/analyze",
                    json=analysis_request
                ) as response:
                    if response.status == 200:
                        analysis_result = await response.json()
                        analysis_data = analysis_result["analysis_results"]
                    else:
                        logger.error(f"AI service returned {response.status}")
                        raise Exception("AI analysis failed")
            
            # Create complaint model
            complaint = ComplaintModel(
                customerEmail=customer_email,
                subject=subject,
                description=analysis_data.get("description", f"{subject}\n\n{content}"),
                category=analysis_data.get("category", "other"),
                subcategory=analysis_data.get("subcategory"),
                priority=analysis_data.get("priority", "medium"),
                sentiment=analysis_data.get("sentiment", "neutral"),
                confidenceScore=analysis_data.get("confidenceScore", 0.0),
                receivedDate=received_date,  # Keep as datetime object for the model
                customerId=analysis_data.get("customerId"),
                customerPhone=analysis_data.get("customerPhone"),
                department=analysis_data.get("department", "customer_service"),
                tags=analysis_data.get("tags", []),
                attachments=[
                    Attachment(**att) for att in attachments
                ],
                extractedEntities=ExtractedEntities(**analysis_data.get("extractedEntities", {})),
                estimatedResolutionTime=analysis_data.get("estimatedResolutionTime", 24),
                escalationLevel=analysis_data.get("escalationLevel", 0),
                legalImplications=analysis_data.get("legalImplications", False),
                compensationRequired=analysis_data.get("compensationRequired", False),
                followUpRequired=analysis_data.get("followUpRequired", True),
                assignedTo=analysis_data.get("assignedTo", "customer_service"),
                source=analysis_data.get("source", "email"),
                status=analysis_data.get("status", "new"),
                processingHistory=analysis_data.get("processingHistory", [])
            )
            
            # Convert to dict and handle datetime serialization
            complaint_data = complaint.dict(by_alias=True)
            
            # Remove the _id field if present - let MongoDB generate it
            if '_id' in complaint_data:
                del complaint_data['_id']
            
            # Convert datetime objects to ISO format strings
            def convert_datetime_to_string(obj):
                if isinstance(obj, dict):
                    return {key: convert_datetime_to_string(value) for key, value in obj.items()}
                elif isinstance(obj, list):
                    return [convert_datetime_to_string(item) for item in obj]
                elif isinstance(obj, datetime):
                    return obj.isoformat()
                else:
                    return obj
            
            complaint_data = convert_datetime_to_string(complaint_data)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.database_service_url}/complaints",
                    json=complaint_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        complaint_id = result["id"]
                    else:
                        logger.error(f"Database service returned {response.status}")
                        response_text = await response.text()
                        logger.error(f"Database service error: {response_text}")
                        raise Exception("Database save failed")
            
            # Add to processed emails list
            self.processed_emails.append({
                "id": complaint_id,
                "customer_email": customer_email,
                "subject": subject,
                "processed_at": datetime.utcnow().isoformat(),  # Convert to string
                "category": analysis_data.get("category"),
                "priority": analysis_data.get("priority")
            })
            
            # Keep only last 100 processed emails
            if len(self.processed_emails) > 100:
                self.processed_emails = self.processed_emails[-100:]
            
            return complaint_id
            
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            raise
    async def get_processed_emails(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get list of recently processed emails"""
        return self.processed_emails[-limit:]
    