import os
import logging
import uuid
from datetime import datetime
from typing import Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class S3StorageService:
    def __init__(self):
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        self.region = os.getenv("AWS_REGION")
        self.s3_client = None
        self.enabled = False
        self._initialize_client()

    def _initialize_client(self):
        """Initialize S3 client with credentials validation"""
        try:
            if not self.aws_access_key_id or not self.aws_secret_access_key:
                logger.warning("AWS credentials not found. S3 storage disabled.")
                return
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region,
            )
            self._ensure_bucket_exists()
            self.enabled = True
            logger.info(
                f"S3 storage initialized successfully. Bucket: {self.bucket_name}"
            )
        except NoCredentialsError:
            logger.error("AWS credentials not configured properly")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")

    def _ensure_bucket_exists(self):
        """Ensure the S3 bucket exists, create if it doesn't"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Bucket {self.bucket_name} exists")
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                logger.info(f"Creating bucket {self.bucket_name}")
                try:
                    if self.region == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={
                                "LocationConstraint": self.region
                            },
                        )
                    logger.info(f"Bucket {self.bucket_name} created successfully")
                except Exception as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
                    raise
            else:
                logger.error(f"Error checking bucket: {e}")
                raise

    def upload_attachment(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = None,
        complaint_id: str = None,
    ) -> Optional[str]:
        """
        Upload attachment to S3 and return the URL
        Args:
            file_data: File content as bytes
            filename: Original filename
            content_type: MIME type of the file
            complaint_id: Associated complaint ID for organization
        Returns:
            S3 URL if successful, None if failed
        """
        if not self.enabled:
            logger.warning("S3 storage not available, skipping upload")
            return None
        try:
            file_extension = filename.split(".")[-1] if "." in filename else ""
            unique_filename = (
                f"{uuid.uuid4().hex}.{file_extension}"
                if file_extension
                else f"{uuid.uuid4().hex}"
            )
            date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
            if complaint_id:
                s3_key = f"attachments/{date_prefix}/{complaint_id}/{unique_filename}"
            else:
                s3_key = f"attachments/{date_prefix}/temp/{unique_filename}"
            metadata = {
                "original-filename": filename,
                "upload-timestamp": datetime.utcnow().isoformat(),
            }
            if complaint_id:
                metadata["complaint-id"] = complaint_id
            upload_params = {
                "Bucket": self.bucket_name,
                "Key": s3_key,
                "Body": file_data,
                "Metadata": metadata,
            }
            if content_type:
                upload_params["ContentType"] = content_type
            else:
                content_type = self._get_content_type(filename)
                if content_type:
                    upload_params["ContentType"] = content_type
            self.s3_client.put_object(**upload_params)
            s3_url = (
                f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}"
            )
            logger.info(f"Successfully uploaded {filename} to S3: {s3_url}")
            return s3_url
        except Exception as e:
            logger.error(f"Failed to upload {filename} to S3: {e}")
            return None

    def download_attachment(self, s3_url: str) -> Optional[bytes]:
        """
        Download attachment from S3 using the URL
        Args:
            s3_url: Full S3 URL of the file
        Returns:
            File content as bytes if successful, None if failed
        """
        if not self.enabled:
            logger.warning("S3 storage not available")
            return None
        try:
            s3_key = self._extract_s3_key_from_url(s3_url)
            if not s3_key:
                logger.error(f"Invalid S3 URL: {s3_url}")
                return None
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            file_data = response["Body"].read()
            logger.info(f"Successfully downloaded file from S3: {s3_key}")
            return file_data
        except Exception as e:
            logger.error(f"Failed to download file from S3: {e}")
            return None

    def delete_attachment(self, s3_url: str) -> bool:
        """
        Delete attachment from S3
        Args:
            s3_url: Full S3 URL of the file
        Returns:
            True if successful, False if failed
        """
        if not self.enabled:
            logger.warning("S3 storage not available")
            return False
        try:
            s3_key = self._extract_s3_key_from_url(s3_url)
            if not s3_key:
                logger.error(f"Invalid S3 URL: {s3_url}")
                return False
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Successfully deleted file from S3: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from S3: {e}")
            return False

    def _extract_s3_key_from_url(self, s3_url: str) -> Optional[str]:
        """Extract S3 key from full S3 URL"""
        try:
            if f"{self.bucket_name}.s3.{self.region}.amazonaws.com/" in s3_url:
                return s3_url.split(
                    f"{self.bucket_name}.s3.{self.region}.amazonaws.com/"
                )[1]
            elif f"s3.{self.region}.amazonaws.com/{self.bucket_name}/" in s3_url:
                return s3_url.split(
                    f"s3.{self.region}.amazonaws.com/{self.bucket_name}/"
                )[1]
            else:
                logger.error(f"Unrecognized S3 URL format: {s3_url}")
                return None
        except Exception:
            return None

    def _get_content_type(self, filename: str) -> Optional[str]:
        """Get content type based on file extension"""
        extension_mapping = {
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "zip": "application/zip",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
        }
        if "." in filename:
            extension = filename.split(".")[-1].lower()
            return extension_mapping.get(extension)
        return None

    def get_storage_stats(self) -> dict:
        """Get storage statistics"""
        if not self.enabled:
            return {"enabled": False, "error": "S3 storage not configured"}
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            total_size = 0
            total_objects = 0
            for page in paginator.paginate(
                Bucket=self.bucket_name, Prefix="attachments/"
            ):
                if "Contents" in page:
                    total_objects += len(page["Contents"])
                    total_size += sum(obj["Size"] for obj in page["Contents"])
            return {
                "enabled": True,
                "bucket_name": self.bucket_name,
                "total_objects": total_objects,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
            }
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {"enabled": True, "error": str(e)}
