import os
import sys
from datetime import datetime
from typing import Any
import io
import logging

import imaplib
import email
import aiohttp
import PyPDF2
import docx
import pytesseract
from PIL import Image
from dotenv import load_dotenv


from s3_storage import S3StorageService

load_dotenv()

sys.path.append("/app/shared")
from shared_temp.models.complaint_model import (
    ComplaintModel,
    ExtractedEntities,
    Attachment,
)

logger = logging.getLogger(__name__)


class EmailProcessor:
    def __init__(self):
        self.ai_service_url = os.getenv("AI_SERVICE_URL")
        self.database_service_url = os.getenv("DATABASE_SERVICE_URL")
        self.email_server = os.getenv("EMAIL_SERVER")
        self.email_user = os.getenv("EMAIL_USER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.processed_count = 0
        self.last_processed = None
        self.errors = []
        self.processed_emails = []

        self.s3_storage = S3StorageService()

    async def initialize(self):
        """Initialize email processor"""
        if not self.email_user or not self.email_password:
            logger.warning("Email credentials not provided. Manual processing only.")
        else:
            logger.info("Email processor initialized with IMAP connection")

        if self.s3_storage.enabled:
            logger.info("S3 storage is enabled for attachments")
        else:
            logger.warning(
                "S3 storage is disabled - attachments will be stored without files"
            )

    async def get_status(self) -> dict[str, Any]:
        """Get current processing status including S3 info"""
        s3_stats = self.s3_storage.get_storage_stats()

        return {
            "status": "running",
            "processed_count": self.processed_count,
            "last_processed": self.last_processed or "Never",
            "errors": self.errors[-5:],
            "s3_storage": s3_stats,
        }

    async def process_new_emails(self) -> None:
        """Process new emails from IMAP server"""
        if not self.email_user or not self.email_password:
            logger.warning("No email credentials configured")
            return
        try:
            mail = imaplib.IMAP4_SSL(self.email_server)
            mail.login(self.email_user, self.email_password)
            mail.select("inbox")
            typ, data = mail.search(None, "UNSEEN")
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
        typ, data = mail.fetch(email_id, "(RFC822)")
        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)
        customer_email = email.utils.parseaddr(email_message["From"])[1]
        subject = email_message["Subject"] or "No Subject"
        received_date = email.utils.parsedate_to_datetime(email_message["Date"])
        content = self._extract_email_content(email_message)

        attachments = await self._extract_attachments(email_message)

        complaint_id = await self.process_single_email(
            customer_email=customer_email,
            subject=subject,
            content=content,
            received_date=received_date,
            attachments=attachments,
        )

        await self._update_attachments_with_complaint_id(attachments, complaint_id)

        mail.store(email_id, "+FLAGS", "\\Seen")
        logger.info(
            f"Processed email from {customer_email}, created complaint {complaint_id}"
        )

    def _extract_email_content(self, email_message) -> str:
        """Extract text content from email"""
        content = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        content += payload.decode("utf-8", errors="ignore")
                elif part.get_content_type() == "text/html":
                    import re

                    payload = part.get_payload(decode=True)
                    if payload:
                        html_content = payload.decode("utf-8", errors="ignore")
                        text_content = re.sub(r"<[^>]+>", "", html_content)
                        content += text_content
        else:
            payload = email_message.get_payload(decode=True)
            if payload:
                content = payload.decode("utf-8", errors="ignore")
        return content.strip()

    async def _extract_attachments(self, email_message) -> list[dict[str, Any]]:
        """Extract and process attachments with S3 upload"""
        attachments = []
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_disposition() == "attachment":
                    filename = part.get_filename()
                    if filename:
                        try:
                            file_data = part.get_payload(decode=True)
                            attachment_info = await self._process_attachment(
                                filename=filename,
                                file_data=file_data,
                                content_type=part.get_content_type(),
                            )
                            attachments.append(attachment_info)
                        except Exception as e:
                            logger.error(f"Error processing attachment {filename}: {e}")
        return attachments

    async def _process_attachment(
        self, filename: str, file_data: bytes, content_type: str = None
    ) -> dict[str, Any]:
        """Process a single attachment with S3 upload"""
        file_type = filename.split(".")[-1].lower() if "." in filename else "unknown"
        file_size = len(file_data)

        attachment_info = {
            "filename": filename,
            "fileType": file_type,
            "fileSize": file_size,
            "s3Url": None,
            "extractedText": "",
            "analysisResults": None,
        }

        try:
            s3_url = self.s3_storage.upload_attachment(
                file_data=file_data, filename=filename, content_type=content_type
            )
            if s3_url:
                attachment_info["s3Url"] = s3_url
                logger.info(f"Uploaded {filename} to S3: {s3_url}")
            else:
                logger.warning(
                    f"Failed to upload {filename} to S3, continuing without file storage"
                )
        except Exception as e:
            logger.error(f"Error uploading {filename} to S3: {e}")

        try:
            if file_type == "pdf":
                attachment_info["extractedText"] = self._extract_pdf_text(file_data)
            elif file_type in ["doc", "docx"]:
                attachment_info["extractedText"] = self._extract_docx_text(file_data)
            elif file_type in ["jpg", "jpeg", "png", "gif"]:
                attachment_info["extractedText"] = await self._extract_image_text(
                    file_data
                )
            elif file_type in ["txt"]:
                attachment_info["extractedText"] = file_data.decode(
                    "utf-8", errors="ignore"
                )
        except Exception as e:
            logger.error(f"Error extracting text from {filename}: {e}")

        return attachment_info

    async def _update_attachments_with_complaint_id(
        self, attachments: list[dict[str, Any]], complaint_id: str
    ):
        """Update S3 attachment paths to include complaint ID"""
        if not self.s3_storage.enabled or not complaint_id:
            return

        for attachment in attachments:
            old_s3_url = attachment.get("s3Url")
            if old_s3_url:
                try:

                    file_data = self.s3_storage.download_attachment(old_s3_url)
                    if file_data:

                        new_s3_url = self.s3_storage.upload_attachment(
                            file_data=file_data,
                            filename=attachment["filename"],
                            complaint_id=complaint_id,
                        )
                        if new_s3_url:

                            self.s3_storage.delete_attachment(old_s3_url)

                            attachment["s3Url"] = new_s3_url
                            logger.info(
                                f"Moved attachment to complaint folder: {new_s3_url}"
                            )
                except Exception as e:
                    logger.error(f"Error moving attachment to complaint folder: {e}")

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
        attachments: list[dict[str, Any]],
    ) -> str:
        """Process a single email and create complaint"""
        try:
            analysis_request = {
                "customer_email": customer_email,
                "subject": subject,
                "content": content,
                "attachments": attachments,
                "received_date": received_date.isoformat(),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ai_service_url}/analyze", json=analysis_request
                ) as response:
                    if response.status == 200:
                        analysis_result = await response.json()
                        analysis_data = analysis_result["analysis_results"]
                    else:
                        logger.error(f"AI service returned {response.status}")
                        raise Exception("AI analysis failed")
            complaint = ComplaintModel(
                customerEmail=customer_email,
                subject=subject,
                description=analysis_data.get("description", f"{subject}\n\n{content}"),
                category=analysis_data.get("category", "other"),
                subcategory=analysis_data.get("subcategory"),
                priority=analysis_data.get("priority", "medium"),
                sentiment=analysis_data.get("sentiment", "neutral"),
                confidenceScore=analysis_data.get("confidenceScore", 0.0),
                receivedDate=received_date,
                customerId=analysis_data.get("customerId"),
                customerPhone=analysis_data.get("customerPhone"),
                department=analysis_data.get("department", "customer_service"),
                tags=analysis_data.get("tags", []),
                attachments=[Attachment(**att) for att in attachments],
                extractedEntities=ExtractedEntities(
                    **analysis_data.get("extractedEntities", {})
                ),
                estimatedResolutionTime=analysis_data.get(
                    "estimatedResolutionTime", 24
                ),
                escalationLevel=analysis_data.get("escalationLevel", 0),
                legalImplications=analysis_data.get("legalImplications", False),
                compensationRequired=analysis_data.get("compensationRequired", False),
                followUpRequired=analysis_data.get("followUpRequired", True),
                assignedTo=analysis_data.get("assignedTo", "customer_service"),
                source=analysis_data.get("source", "email"),
                status=analysis_data.get("status", "new"),
                processingHistory=analysis_data.get("processingHistory", []),
            )
            complaint_data = complaint.dict(by_alias=True)
            if "_id" in complaint_data:
                del complaint_data["_id"]

            def convert_datetime_to_string(obj):
                if isinstance(obj, dict):
                    return {
                        key: convert_datetime_to_string(value)
                        for key, value in obj.items()
                    }
                elif isinstance(obj, list):
                    return [convert_datetime_to_string(item) for item in obj]
                elif isinstance(obj, datetime):
                    return obj.isoformat()
                else:
                    return obj

            complaint_data = convert_datetime_to_string(complaint_data)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.database_service_url}/complaints", json=complaint_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        complaint_id = result["id"]
                    else:
                        logger.error(f"Database service returned {response.status}")
                        response_text = await response.text()
                        logger.error(f"Database service error: {response_text}")
                        raise Exception("Database save failed")
            self.processed_emails.append(
                {
                    "id": complaint_id,
                    "customer_email": customer_email,
                    "subject": subject,
                    "processed_at": datetime.utcnow().isoformat(),
                    "category": analysis_data.get("category"),
                    "priority": analysis_data.get("priority"),
                    "attachments_count": len(attachments),
                    "s3_attachments": sum(1 for att in attachments if att.get("s3Url")),
                }
            )
            if len(self.processed_emails) > 100:
                self.processed_emails = self.processed_emails[-100:]
            return complaint_id
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            raise

    async def get_processed_emails(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get list of recently processed emails"""
        return self.processed_emails[-limit:]
