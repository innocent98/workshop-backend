# workchop-api

A FastAPI project

## Features

- FastAPI framework with async support
- Pydantic v2 for data validation
- SQLAlchemy 2.0 for database ORM
- Alembic for database migrations
- JWT authentication
- Docker and docker-compose support
- Comprehensive testing setup with pytest
- Pre-commit hooks for code quality
- GitHub Actions CI/CD
- Structured logging with Loguru
- API documentation with Swagger UI and ReDoc

## Requirements

- Python 3.11+
- PostgreSQL (if using database)
- Redis (if using caching)
- Docker & Docker Compose (optional)

## Project Structure

```
workchop-api/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   └── api.py
│   │   └── deps.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logger.py
│   ├── db/
│   │   ├── models/
│   │   ├── base.py
│   │   └── session.py
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   ├── middleware/
│   └── main.py
├── tests/
│   ├── api/
│   └── services/
├── alembic/
│   └── versions/
├── scripts/
├── docs/
├── .github/
│   └── workflows/
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pytest.ini
└── README.md
```

## Getting Started

### 1. Clone and Setup

```bash
cd workchop-api
cp .env.example .env
# Edit .env with your configuration
```

### 2. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. Database Setup

```bash
# Run migrations
alembic upgrade head

# Create initial data (if needed)
python scripts/init_db.py
```

### 4. Run Development Server

```bash
# With uvicorn
uvicorn app.main:app --reload

# Or with python
python -m app.main
```

The API will be available at:
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

### 5. Using Docker

```bash
# Build and run
docker-compose up --build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop containers
docker-compose down
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_health.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black app tests
isort app tests

# Lint code
flake8 app tests
mypy app

# Run pre-commit hooks
pre-commit install
pre-commit run --all-files
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# View migration history
alembic history
```

## Environment Variables

See `.env.example` for all available environment variables.

Key variables:
- `SECRET_KEY`: Secret key for JWT tokens (generate with `openssl rand -hex 32`)
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `ENVIRONMENT`: development/staging/production

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Deployment

### Using Docker

```bash
# Build production image
docker build -t workchop-api:latest .

# Run container
docker run -p 8000:8000 --env-file .env workchop-api:latest
```

### Manual Deployment

```bash
# Install production dependencies
pip install -r requirements.txt

# Run with gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Submit a pull request

## License

MIT License

## Author

Your Name (your.email@example.com)
