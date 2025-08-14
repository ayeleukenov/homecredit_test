# 🤖 AI Customer Support System

## 🏗️ Architecture

Microservices:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Frontend Web   │────▶│  Email Service   │────▶│   AI Service    │
│    Service      │     │   (Port 8003)    │     │  (Port 8002)    │
│  (Port 8080)    │     └──────────────────┘     └─────────────────┘
└─────────────────┘              │                        │
         │                       ▼                        ▼
         │              ┌──────────────────┐     ┌─────────────────┐
         └─────────────▶│ Database Service │     │   Claude API    │
                        │   (Port 8001)    │     └─────────────────┘
                        └──────────────────┘
                                 │
                        ┌────────▼────────┐
                        │    MongoDB      │
                        └─────────────────┘
```

### Services Description

1. **Frontend Web Service** - Dashboard
2. **Email Service** - IMAP email processing, intelligent attachment handling, and telegram notifications
3. **AI Service** - Claude AI integration for content analysis
4. **Database Service** - MongoDB operations and duplicate detection

## 🚀 Quick Start

### Environment Setup

1. Clone the repository into your directory of choice:
```bash
git clone https://github.com/ayeleukenov/homecredit_test.git
```

2. Receive .env files from the owner of the repository and put them in the appropriate folders:
There is one .env files in the root, one specific in the email-service, and one specific in the ai-service folders.
Claude API Key will be given if asked because it is paid, otherwise please use your own.

### Docker Deployment

1. Build and start all services. Do that inside each of the 4 services:
```bash
docker compose up --build
```

2. Access the web interface:
```
http://127.0.0.1:8080
```

## 🧪 Testing the System

### Manual Email Test

1. Navigate to the test page: `http://localhost:8080/test`
2. Use the sample emails provided or create custom test cases
3. Submit and verify the complaint is created

### Email Processing Test

Send an email to homecredittest17@gmail.com. It will be automatically processed:
- Subject containing keywords like "urgent", "return", "refund"
- Attachments (PDF, images, documents)
- The system will automatically process within 30 seconds

### Telegram Notifications How-To

Join the channel - @homecredit_test_notification_ch
Only Medium and High priority emails get sent there.

### API Testing

Collection of postman requests will be provided alongside the .env files in a zip.

## 📈 Features Demonstration

### Core Features (MVP)
✅ **Email Reading** - IMAP integration for automatic email fetching  
✅ **AI Analysis** - Claude AI for classification and entity extraction  
✅ **MongoDB Storage** - Structured complaint storage with full schema  
✅ **Web Interface** - Dashboard, complaint listing, and detail views  
✅ **Attachment Processing** - OCR and text extraction from multiple formats  

### Advanced Features
✅ **S3 Integration** - Secure cloud storage for attachments  
✅ **Duplicate Detection** - Content hashing and similarity matching  
✅ **Redis Caching** - Performance optimization for AI analysis  
✅ **Telegram Notifications** - Real-time alerts for critical issues  
✅ **Escalation Management** - Automatic routing based on severity  
✅ **Entity Extraction** - Order numbers, amounts, dates, products  

## 🔍 System Capabilities

### Supported File Types
- 📄 PDF documents
- 📝 Word documents (DOC, DOCX)
- 🖼️ Images (JPG, PNG, GIF, BMP, TIFF)
- 📊 Spreadsheets (XLSX, XLS, CSV)
- 📋 Text files (TXT, RTF)

### AI Classification Categories
- **Returns** - Product returns and refunds
- **Delivery** - Shipping and delivery issues
- **Quality** - Product quality complaints
- **Technical** - Technical support requests
- **Billing** - Payment and invoice issues
- **Other** - General inquiries

### Performance Metrics
- System capacity projected: 1000+ emails/hour

## 🛠️ Technological Stack

### Backend
- **Python** - Yep
- **FastAPI** - High-performance web framework
- **Motor** - Async MongoDB driver
- **Anthropic Claude API** - AI analysis
- **Redis** - Caching layer
- **Boto3** - AWS S3 integration

### Processing
- **PyPDF2** - PDF text extraction
- **python-docx** - Word document processing
- **Tesseract OCR** - Image text extraction
- **Pillow** - Image processing

### Infrastructure
- **Docker** - Containerization
- **MongoDB** - Document database
- **Redis2** - Cache store
- **AWS S3** - File storage

## 📁 Project Structure

```
ai-customer-support/
├── backend-database-service/     # MongoDB operations
│   ├── app/
│   │   ├── main.py
│   │   ├── mongo_operations.py
│   │   └── duplicate_checker.py
│   └── Dockerfile
├── backend-ai-service/           # Claude AI integration
│   ├── app/
│   │   ├── main.py
│   │   └── claude_analyzer.py
│   └── Dockerfile
├── backend-email-service/        # Email processing
│   ├── app/
│   │   ├── main.py
│   │   ├── email_processor.py
│   │   └── s3_storage.py
│   └── Dockerfile
├── frontend-web-service/         # Web interface
│   ├── app/
│   │   └── main.py
│   ├── templates/
│   └── Dockerfile
├── shared/                       # Shared models
│   └── models/
│       └── complaint_model.py
└── docker-compose.yml
```

## 🔒 Security Considerations

- Environment variables for sensitive data
- S3 presigned URLs for secure downloads
- Input validation and sanitization
- Rate limiting on API endpoints
- MongoDB authentication enabled
- Encrypted S3 storage (AES256)
- Redis TTL 1 hour for checking duplicates and saving AI resources

## 📝 API Documentation

### Database Service (Port 8001)
- `GET /health` - Health check
- `GET /complaints` - List complaints with filtering
- `GET /complaints/{id}` - Get complaint details
- `POST /complaints` - Create new complaint
- `PUT /complaints/{id}` - Update complaint
- `GET /stats` - System statistics
- `GET /duplicate-stats` - Duplicate detection metrics

### AI Service (Port 8002)
- `GET /health` - Health check
- `POST /analyze` - Analyze email content
- `POST /analyze-attachment` - Analyze attachment
- `POST /extract-entities` - Extract entities from text
- `GET /categories` - Available categories

### Email Service (Port 8003)
- `GET /health` - Health check
- `GET /status` - Processing status
- `POST /process-manual` - Manual email processing
- `GET /processed-emails` - List processed emails
- `GET /s3-stats` - S3 storage statistics

## 🚦 Monitoring & Maintenance

### Health Checks
All services expose `/health` endpoints for monitoring.

### Logs
- Docker logs: `docker logs <container-name>`
- Application logs: INFO level by default
- Error tracking in processing history

### Database Indexes
Optimized indexes for:
- customerEmail
- status, category, priority
- createdDate, receivedDate
- contentHash (duplicate detection)

## 🤝 Contributing

This project was developed as a technical assessment. For improvements:

1. Fork the repository
2. Create a feature branch
3. Implement changes with tests
4. Submit a pull request

## 📄 License

This project is provided as-is for evaluation purposes.

## 👨‍💻 Author

Developed as a technical assessment for the AI Engineer position at Homecredit Bank.

## 📞 Support

For questions about this implementation:
- Review the code documentation
- Check the API endpoints
- Examine the Docker logs

---

**Note**: This is a demonstration system. For production use, additional security hardening, monitoring, and scaling considerations would be required.

"Art is never finished, only abandoned" - Da Vinci
