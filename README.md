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
- Poetry (for dependency management)
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
├── pyproject.toml
├── poetry.lock
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
# Install Poetry (if not already installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate the virtual environment (optional, Poetry will use it automatically)
poetry shell
```

### 3. Database Setup

```bash
# Run migrations
poetry run alembic upgrade head

# Create initial data (if needed)
poetry run python scripts/init_db.py
```

### 4. Run Development Server

```bash
# With Poetry
poetry run uvicorn app.main:app --reload

# Or use the Makefile
make run
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
poetry run pytest

# Or use Makefile
make test

# Run with coverage
make test-cov

# Run specific test file
poetry run pytest tests/test_health.py

# Run with verbose output
poetry run pytest -v
```

### Code Quality

```bash
# Format code
make format
# Or manually:
poetry run black app tests
poetry run isort app tests

# Lint code
make lint
# Or manually:
poetry run flake8 app tests
poetry run mypy app

# Run pre-commit hooks
poetry run pre-commit install
poetry run pre-commit run --all-files
```

### Database Migrations

```bash
# Create a new migration
make migrate-create
# Or manually:
poetry run alembic revision --autogenerate -m "description"

# Apply migrations
make migrate
# Or manually:
poetry run alembic upgrade head

# Rollback migration
poetry run alembic downgrade -1

# View migration history
poetry run alembic history
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
poetry install --only main

# Run with gunicorn
poetry run gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
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
