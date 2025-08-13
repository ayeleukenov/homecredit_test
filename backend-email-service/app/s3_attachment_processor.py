
import os
import io
import hashlib
import mimetypes
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import asyncio

import aiohttp
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import aioboto3
import PyPDF2
import docx
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np
import magic
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class S3AttachmentProcessor:
    def __init__(self):
        
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = os.getenv("AWS_REGION")
        self.s3_bucket = os.getenv("S3_BUCKET_NAME")
        self.s3_prefix = os.getenv("S3_PREFIX")
        
        
        self.cloudfront_domain = os.getenv("CLOUDFRONT_DOMAIN")
        
        
        self.ai_service_url = os.getenv("AI_SERVICE_URL")
        self.max_file_size = int(os.getenv("MAX_ATTACHMENT_SIZE", "50")) * 1024 * 1024  
        self.allowed_extensions = {
            'pdf', 'doc', 'docx', 'txt', 'rtf',
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff',
            'xlsx', 'xls', 'csv'
        }
        
        
        if not all([self.aws_access_key, self.aws_secret_key, self.s3_bucket]):
            logger.warning("S3 credentials not fully configured. Some features may not work.")
        
        
        self._init_s3_client()
        
        
        self.document_types = {
            'invoice': ['invoice', 'bill', 'payment', 'amount due', 'total', '$', 'tax'],
            'receipt': ['receipt', 'paid', 'transaction', 'purchase', 'bought'],
            'contract': ['agreement', 'contract', 'terms', 'conditions', 'signature'],
            'warranty': ['warranty', 'guarantee', 'coverage', 'repair', 'replace'],
            'legal': ['legal', 'court', 'lawsuit', 'attorney', 'lawyer', 'damages'],
            'medical': ['medical', 'doctor', 'hospital', 'prescription', 'diagnosis'],
            'shipping': ['tracking', 'shipment', 'delivery', 'ups', 'fedex', 'dhl'],
            'product_manual': ['manual', 'instructions', 'user guide', 'setup'],
            'screenshot': ['screenshot', 'error message', 'bug report', 'system']
        }

    def _init_s3_client(self):
        """Initialize AWS S3 client"""
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
                region_name=self.aws_region
            )
            
            
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            logger.info(f"S3 client initialized successfully for bucket: {self.s3_bucket}")
            
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            self.s3_client = None
        except ClientError as e:
            logger.error(f"S3 client initialization failed: {e}")
            self.s3_client = None
        except Exception as e:
            logger.error(f"Unexpected error initializing S3: {e}")
            self.s3_client = None

    async def process_attachment(
        self, 
        filename: str, 
        file_data: bytes, 
        complaint_id: str = None
    ) -> Dict[str, Any]:
        """
        Process attachment with S3 storage
        """
        try:
            
            validation_result = await self._validate_file(filename, file_data)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'error': validation_result['error'],
                    'filename': filename
                }

            
            file_hash = self._generate_file_hash(file_data)
            file_info = {
                'filename': secure_filename(filename),
                'original_filename': filename,
                'file_hash': file_hash,
                'file_size': len(file_data),
                'mime_type': validation_result['mime_type'],
                'file_type': validation_result['file_type'],
                'processed_at': datetime.utcnow().isoformat(),
                'complaint_id': complaint_id
            }

            
            s3_key = self._generate_s3_key(file_hash, file_info['file_type'])
            existing_file = await self._check_file_exists(s3_key)
            
            if existing_file:
                logger.info(f"File {file_hash} already exists in S3, skipping upload")
                file_info['s3_key'] = s3_key
                file_info['s3_url'] = self._generate_file_url(s3_key)
                file_info['file_exists'] = True
            else:
                
                upload_result = await self._upload_to_s3(file_data, s3_key, file_info)
                if not upload_result['success']:
                    return {
                        'success': False,
                        'error': upload_result['error'],
                        'filename': filename
                    }
                
                file_info.update(upload_result)
                file_info['file_exists'] = False

            
            extraction_result = await self._extract_content(file_data, file_info)
            file_info.update(extraction_result)

            
            if file_info.get('extracted_text') or file_info.get('image_analysis'):
                ai_analysis = await self._analyze_with_ai(file_info)
                file_info['analysisResults'] = ai_analysis

            
            doc_classification = self._classify_document(file_info)
            file_info['document_classification'] = doc_classification

            
            security_scan = await self._security_scan(file_info)
            file_info['security_scan'] = security_scan

            
            await self._store_metadata(file_info)

            file_info['success'] = True
            logger.info(f"Successfully processed attachment: {filename}")
            return file_info

        except Exception as e:
            logger.error(f"Error processing attachment {filename}: {e}")
            return {
                'success': False,
                'error': str(e),
                'filename': filename
            }

    def _generate_s3_key(self, file_hash: str, file_type: str) -> str:
        """Generate S3 object key with organized structure"""
        
        today = datetime.utcnow()
        return f"{self.s3_prefix}{today.year}/{today.month:02d}/{today.day:02d}/{file_hash}.{file_type}"

    def _generate_file_hash(self, file_data: bytes) -> str:
        """Generate SHA-256 hash for file identification"""
        return hashlib.sha256(file_data).hexdigest()

    def _generate_file_url(self, s3_key: str) -> str:
        """Generate public URL for S3 object"""
        if self.cloudfront_domain:
            
            return f"https://{self.cloudfront_domain}/{s3_key}"
        else:
            
            return f"https://{self.s3_bucket}.s3.{self.aws_region}.amazonaws.com/{s3_key}"

    async def _check_file_exists(self, s3_key: str) -> bool:
        """Check if file already exists in S3"""
        try:
            if not self.s3_client:
                return False
            
            self.s3_client.head_object(Bucket=self.s3_bucket, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            logger.error(f"Error checking S3 object existence: {e}")
            return False

    async def _upload_to_s3(self, file_data: bytes, s3_key: str, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """Upload file to S3 with proper metadata and settings"""
        try:
            if not self.s3_client:
                return {
                    'success': False,
                    'error': 'S3 client not initialized'
                }

            
            metadata = {
                'original-filename': file_info['original_filename'],
                'file-hash': file_info['file_hash'],
                'processed-at': file_info['processed_at'],
                'complaint-id': file_info.get('complaint_id', ''),
                'file-size': str(file_info['file_size'])
            }

            
            upload_params = {
                'Bucket': self.s3_bucket,
                'Key': s3_key,
                'Body': file_data,
                'ContentType': file_info['mime_type'],
                'Metadata': metadata,
                'ServerSideEncryption': 'AES256',  
                'StorageClass': 'STANDARD_IA'  
            }

            
            if os.getenv("S3_PUBLIC_READ", "false").lower() == "true":
                upload_params['ACL'] = 'public-read'

            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.put_object(**upload_params)
            )

            
            s3_url = self._generate_file_url(s3_key)
            
            
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.s3_bucket, 'Key': s3_key},
                ExpiresIn=3600  
            )

            logger.info(f"File uploaded to S3: {s3_key}")

            return {
                'success': True,
                's3_key': s3_key,
                's3_url': s3_url,
                'presigned_url': presigned_url,
                'storage_location': 'aws_s3'
            }

        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            return {
                'success': False,
                'error': f'S3 upload failed: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Unexpected error during S3 upload: {e}")
            return {
                'success': False,
                'error': f'Upload error: {str(e)}'
            }

    async def _store_metadata(self, file_info: Dict[str, Any]) -> bool:
        """Store file metadata as JSON in S3"""
        try:
            if not self.s3_client:
                return False

            
            metadata = {
                'file_info': file_info,
                'stored_at': datetime.utcnow().isoformat(),
                'version': '1.0'
            }

            
            file_hash = file_info['file_hash']
            metadata_key = f"{self.s3_prefix}metadata/{file_hash}.json"

            
            import json
            metadata_json = json.dumps(metadata, indent=2, default=str)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=metadata_key,
                    Body=metadata_json.encode('utf-8'),
                    ContentType='application/json',
                    ServerSideEncryption='AES256'
                )
            )

            logger.info(f"Metadata stored: {metadata_key}")
            return True

        except Exception as e:
            logger.error(f"Error storing metadata: {e}")
            return False

    async def get_file_from_s3(self, s3_key: str) -> Optional[bytes]:
        """Download file from S3"""
        try:
            if not self.s3_client:
                return None

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
            )
            
            return response['Body'].read()

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"File not found in S3: {s3_key}")
            else:
                logger.error(f"Error downloading from S3: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading from S3: {e}")
            return None

    async def delete_file_from_s3(self, s3_key: str) -> bool:
        """Delete file from S3"""
        try:
            if not self.s3_client:
                return False

            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.delete_object(Bucket=self.s3_bucket, Key=s3_key)
            )

            
            file_hash = s3_key.split('/')[-1].split('.')[0]  
            metadata_key = f"{self.s3_prefix}metadata/{file_hash}.json"
            
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self.s3_client.delete_object(Bucket=self.s3_bucket, Key=metadata_key)
                )
            except:
                pass  

            logger.info(f"File deleted from S3: {s3_key}")
            return True

        except Exception as e:
            logger.error(f"Error deleting from S3: {e}")
            return False

    async def generate_presigned_download_url(self, s3_key: str, expires_in: int = 3600) -> Optional[str]:
        """Generate presigned URL for secure file download"""
        try:
            if not self.s3_client:
                return None

            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.s3_bucket, 'Key': s3_key},
                ExpiresIn=expires_in
            )

            return presigned_url

        except Exception as e:
            logger.error(f"Error generating presigned URL: {e}")
            return None

    async def generate_presigned_upload_url(self, s3_key: str, file_type: str, expires_in: int = 3600) -> Optional[Dict[str, Any]]:
        """Generate presigned URL for direct client-side uploads"""
        try:
            if not self.s3_client:
                return None

            
            conditions = [
                {"acl": "private"},
                {"Content-Type": file_type},
                ["content-length-range", 1, self.max_file_size]
            ]

            response = self.s3_client.generate_presigned_post(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Fields={"acl": "private", "Content-Type": file_type},
                Conditions=conditions,
                ExpiresIn=expires_in
            )

            return response

        except Exception as e:
            logger.error(f"Error generating presigned upload URL: {e}")
            return None

    async def list_files(self, prefix: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List files in S3 bucket"""
        try:
            if not self.s3_client:
                return []

            list_prefix = prefix or self.s3_prefix
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.list_objects_v2(
                    Bucket=self.s3_bucket,
                    Prefix=list_prefix,
                    MaxKeys=limit
                )
            )

            files = []
            for obj in response.get('Contents', []):
                
                if '/metadata/' in obj['Key']:
                    continue
                    
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'url': self._generate_file_url(obj['Key'])
                })

            return files

        except Exception as e:
            logger.error(f"Error listing S3 files: {e}")
            return []

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get S3 storage statistics"""
        try:
            if not self.s3_client:
                return {'error': 'S3 not configured'}

            
            files = await self.list_files(limit=1000)  
            
            total_files = len(files)
            total_size = sum(file['size'] for file in files)
            
            
            file_types = {}
            for file in files:
                file_ext = file['key'].split('.')[-1].lower()
                file_types[file_ext] = file_types.get(file_ext, 0) + 1

            return {
                'total_files': total_files,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'file_types': file_types,
                'storage_provider': 'aws_s3',
                'bucket_name': self.s3_bucket,
                'region': self.aws_region,
                'cdn_enabled': bool(self.cloudfront_domain)
            }

        except Exception as e:
            logger.error(f"Error getting S3 stats: {e}")
            return {'error': str(e)}

    
    
    
    async def _validate_file(self, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Validate file type, size, and security"""
        try:
            
            if len(file_data) > self.max_file_size:
                return {
                    'valid': False,
                    'error': f'File too large. Maximum size is {self.max_file_size // (1024*1024)}MB'
                }

            
            file_ext = filename.lower().split('.')[-1] if '.' in filename else ''
            if file_ext not in self.allowed_extensions:
                return {
                    'valid': False,
                    'error': f'File type .{file_ext} not allowed'
                }

            
            try:
                mime_type = magic.from_buffer(file_data, mime=True)
            except:
                
                mime_type, _ = mimetypes.guess_type(filename)

            
            if self._is_suspicious_file(filename, file_data):
                return {
                    'valid': False,
                    'error': 'File failed security scan'
                }

            return {
                'valid': True,
                'mime_type': mime_type,
                'file_type': file_ext
            }

        except Exception as e:
            return {
                'valid': False,
                'error': f'Validation error: {str(e)}'
            }

    def _is_suspicious_file(self, filename: str, file_data: bytes) -> bool:
        """Basic security checks for suspicious files"""
        suspicious_patterns = [
            b'<script',  
            b'eval(',     
            b'exec(',     
            b'<?php',     
            b'
        ]
        
        
        file_start = file_data[:1024].lower()
        return any(pattern in file_start for pattern in suspicious_patterns)

    
    
    
    async def _extract_content(self, file_data: bytes, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """Extract content based on file type (keeping existing implementation)"""
        
        
        file_type = file_info['file_type'].lower()
        result = {
            'extracted_text': '',
            'extraction_method': '',
            'extraction_confidence': 0.0,
            'page_count': 0,
            'word_count': 0,
            'image_analysis': None
        }

        try:
            if file_type == 'pdf':
                result.update(await self._extract_pdf_content(file_data))
            elif file_type in ['doc', 'docx']:
                result.update(await self._extract_docx_content(file_data))
            elif file_type in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
                result.update(await self._extract_image_content(file_data))
            elif file_type == 'txt':
                result.update(await self._extract_text_content(file_data))
            elif file_type in ['xlsx', 'xls', 'csv']:
                result.update(await self._extract_spreadsheet_content(file_data, file_type))

            
            if result['extracted_text']:
                result['word_count'] = len(result['extracted_text'].split())

        except Exception as e:
            logger.error(f"Error extracting content: {e}")
            result['extraction_error'] = str(e)

        return result
