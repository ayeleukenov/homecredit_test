import os
import boto3
import uuid
import logging
from typing import Optional
from botocore.exceptions import ClientError, NoCredentialsError
from datetime import datetime

logger = logging.getLogger(__name__)


class S3Handler:
    def __init__(self):
        self.bucket_name = os.getenv("S3_BUCKET_NAME", "ai-support-attachments")
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.s3_client = None
        self._initialize_s3_client()

    def _initialize_s3_client(self):
        """Initialize S3 client with credentials"""
        try:
            if self.aws_access_key and self.aws_secret_key:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=self.aws_access_key,
                    aws_secret_access_key=self.aws_secret_key,
                    region_name=self.aws_region,
                )
                logger.info("S3 client initialized successfully")
            else:
                self.s3_client = boto3.client("s3", region_name=self.aws_region)
                logger.info("S3 client initialized with default credentials")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            self.s3_client = None

    def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        """
        Upload file to S3 and return the URL
        Args:
            file_data: Raw file bytes
            filename: Original filename
            content_type: MIME type of the file
        Returns:
            S3 URL or None if upload failed
        """
        if not self.s3_client:
            logger.error("S3 client not initialized")
            return None
        try:
            file_extension = filename.split(".")[-1] if "." in filename else ""
            unique_filename = f"{uuid.uuid4()}-{filename}"
            s3_key = (
                f"attachments/{datetime.now().strftime('%Y/%m/%d')}/{unique_filename}"
            )
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_data,
                ContentType=content_type,
                Metadata={
                    "original_filename": filename,
                    "upload_date": datetime.utcnow().isoformat(),
                },
            )
            s3_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            logger.info(f"File uploaded successfully: {s3_url}")
            return s3_url
        except ClientError as e:
            logger.error(f"AWS S3 error uploading file {filename}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading file {filename}: {e}")
            return None

    def generate_presigned_url(
        self, s3_url: str, expiration: int = 3600
    ) -> Optional[str]:
        """
        Generate presigned URL for downloading file
        Args:
            s3_url: Full S3 URL
            expiration: URL expiration time in seconds (default 1 hour)
        Returns:
            Presigned URL or None if failed
        """
        if not self.s3_client:
            logger.error("S3 client not initialized")
            return None
        try:
            s3_key = self._extract_s3_key_from_url(s3_url)
            if not s3_key:
                logger.error(f"Could not extract S3 key from URL: {s3_url}")
                return None
            presigned_url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return presigned_url
        except ClientError as e:
            logger.error(f"Error generating presigned URL for {s3_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {e}")
            return None

    def _extract_s3_key_from_url(self, s3_url: str) -> Optional[str]:
        """Extract S3 key from full S3 URL"""
        try:
            if f"{self.bucket_name}.s3." in s3_url:
                return s3_url.split(
                    f"{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/"
                )[1]
            return None
        except Exception:
            return None

    def delete_file(self, s3_url: str) -> bool:
        """
        Delete file from S3
        Args:
            s3_url: Full S3 URL
        Returns:
            True if successful, False otherwise
        """
        if not self.s3_client:
            return False
        try:
            s3_key = self._extract_s3_key_from_url(s3_url)
            if not s3_key:
                return False
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"File deleted successfully: {s3_url}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file {s3_url}: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if S3 is properly configured"""
        return self.s3_client is not None
