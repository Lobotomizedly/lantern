# =============================================================================
# Lantern Backend - Development Makefile
# =============================================================================

.PHONY: help install install-dev install-ml install-all test test-cov test-fast \
        lint format type-check check migrate migrate-create run-dev run-prod \
        docker-build docker-up docker-down docker-logs docker-shell clean \
        db-reset docs serve-docs

# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := python3
PIP := pip
PYTEST := pytest
UVICORN := uvicorn
ALEMBIC := alembic
DOCKER_COMPOSE := docker compose

# Colors for terminal output
BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
NC := \033[0m # No Color

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "$(BLUE)Lantern Backend - Development Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Usage:$(NC) make [target]"
	@echo ""
	@echo "$(YELLOW)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# =============================================================================
# Installation
# =============================================================================

install: ## Install production dependencies
	@echo "$(BLUE)Installing production dependencies...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -e .
	@echo "$(GREEN)Production dependencies installed!$(NC)"

install-dev: ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	pre-commit install
	@echo "$(GREEN)Development dependencies installed!$(NC)"

install-ml: ## Install ML dependencies
	@echo "$(BLUE)Installing ML dependencies...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[ml]"
	$(PYTHON) -m spacy download en_core_web_lg
	@echo "$(GREEN)ML dependencies installed!$(NC)"

install-all: ## Install all dependencies (dev + ml)
	@echo "$(BLUE)Installing all dependencies...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[all]"
	pre-commit install
	$(PYTHON) -m spacy download en_core_web_lg
	@echo "$(GREEN)All dependencies installed!$(NC)"

# =============================================================================
# Testing
# =============================================================================

test: ## Run all tests
	@echo "$(BLUE)Running tests...$(NC)"
	$(PYTEST)

test-cov: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	$(PYTEST) --cov=app --cov-report=html --cov-report=term-missing

test-fast: ## Run tests without coverage (faster)
	@echo "$(BLUE)Running tests (fast mode)...$(NC)"
	$(PYTEST) --no-cov -x -q

test-unit: ## Run only unit tests
	@echo "$(BLUE)Running unit tests...$(NC)"
	$(PYTEST) -m unit

test-integration: ## Run only integration tests
	@echo "$(BLUE)Running integration tests...$(NC)"
	$(PYTEST) -m integration

test-watch: ## Run tests in watch mode
	@echo "$(BLUE)Running tests in watch mode...$(NC)"
	$(PYTEST) --watch

# =============================================================================
# Code Quality
# =============================================================================

lint: ## Run linter (ruff)
	@echo "$(BLUE)Running linter...$(NC)"
	ruff check app tests
	@echo "$(GREEN)Linting passed!$(NC)"

lint-fix: ## Run linter and auto-fix issues
	@echo "$(BLUE)Running linter with auto-fix...$(NC)"
	ruff check app tests --fix
	@echo "$(GREEN)Linting completed!$(NC)"

format: ## Format code with black and isort
	@echo "$(BLUE)Formatting code...$(NC)"
	black app tests
	isort app tests
	@echo "$(GREEN)Formatting completed!$(NC)"

format-check: ## Check code formatting without making changes
	@echo "$(BLUE)Checking code format...$(NC)"
	black app tests --check
	isort app tests --check-only
	@echo "$(GREEN)Format check passed!$(NC)"

type-check: ## Run type checker (mypy)
	@echo "$(BLUE)Running type checker...$(NC)"
	mypy app
	@echo "$(GREEN)Type check passed!$(NC)"

check: lint format-check type-check ## Run all code quality checks
	@echo "$(GREEN)All checks passed!$(NC)"

pre-commit: ## Run pre-commit hooks on all files
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	pre-commit run --all-files

# =============================================================================
# Database
# =============================================================================

migrate: ## Run database migrations
	@echo "$(BLUE)Running database migrations...$(NC)"
	$(ALEMBIC) upgrade head
	@echo "$(GREEN)Migrations completed!$(NC)"

migrate-create: ## Create a new migration (usage: make migrate-create name="migration_name")
	@echo "$(BLUE)Creating new migration...$(NC)"
	$(ALEMBIC) revision --autogenerate -m "$(name)"
	@echo "$(GREEN)Migration created!$(NC)"

migrate-down: ## Rollback last migration
	@echo "$(BLUE)Rolling back last migration...$(NC)"
	$(ALEMBIC) downgrade -1
	@echo "$(GREEN)Rollback completed!$(NC)"

migrate-history: ## Show migration history
	@echo "$(BLUE)Migration history:$(NC)"
	$(ALEMBIC) history --verbose

db-reset: ## Reset database (drop all tables and re-run migrations)
	@echo "$(RED)WARNING: This will drop all tables!$(NC)"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	@echo "$(BLUE)Resetting database...$(NC)"
	$(ALEMBIC) downgrade base
	$(ALEMBIC) upgrade head
	@echo "$(GREEN)Database reset completed!$(NC)"

# =============================================================================
# Development Server
# =============================================================================

run-dev: ## Run development server with auto-reload
	@echo "$(BLUE)Starting development server...$(NC)"
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

run-prod: ## Run production server
	@echo "$(BLUE)Starting production server...$(NC)"
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --workers 4

run-worker: ## Run Celery worker
	@echo "$(BLUE)Starting Celery worker...$(NC)"
	celery -A app.worker.celery_app worker --loglevel=info

run-beat: ## Run Celery beat scheduler
	@echo "$(BLUE)Starting Celery beat...$(NC)"
	celery -A app.worker.celery_app beat --loglevel=info

run-flower: ## Run Flower (Celery monitoring)
	@echo "$(BLUE)Starting Flower...$(NC)"
	celery -A app.worker.celery_app flower --port=5555

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build Docker images
	@echo "$(BLUE)Building Docker images...$(NC)"
	$(DOCKER_COMPOSE) build
	@echo "$(GREEN)Docker images built!$(NC)"

docker-build-no-cache: ## Build Docker images without cache
	@echo "$(BLUE)Building Docker images (no cache)...$(NC)"
	$(DOCKER_COMPOSE) build --no-cache
	@echo "$(GREEN)Docker images built!$(NC)"

docker-up: ## Start all Docker services
	@echo "$(BLUE)Starting Docker services...$(NC)"
	$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)Services started!$(NC)"
	@echo "$(YELLOW)Backend:$(NC)    http://localhost:8000"
	@echo "$(YELLOW)Frontend:$(NC)   http://localhost:3000"
	@echo "$(YELLOW)Temporal UI:$(NC) http://localhost:8080"
	@echo "$(YELLOW)MinIO:$(NC)      http://localhost:9001"
	@echo "$(YELLOW)OpenSearch:$(NC) http://localhost:5601"
	@echo "$(YELLOW)Flower:$(NC)     http://localhost:5555"

docker-down: ## Stop all Docker services
	@echo "$(BLUE)Stopping Docker services...$(NC)"
	$(DOCKER_COMPOSE) down
	@echo "$(GREEN)Services stopped!$(NC)"

docker-down-volumes: ## Stop all Docker services and remove volumes
	@echo "$(RED)WARNING: This will remove all data volumes!$(NC)"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	$(DOCKER_COMPOSE) down -v
	@echo "$(GREEN)Services stopped and volumes removed!$(NC)"

docker-logs: ## View logs from all services
	$(DOCKER_COMPOSE) logs -f

docker-logs-backend: ## View backend logs
	$(DOCKER_COMPOSE) logs -f backend

docker-logs-worker: ## View worker logs
	$(DOCKER_COMPOSE) logs -f worker

docker-shell: ## Open shell in backend container
	$(DOCKER_COMPOSE) exec backend /bin/bash

docker-shell-worker: ## Open shell in worker container
	$(DOCKER_COMPOSE) exec worker /bin/bash

docker-ps: ## List running containers
	$(DOCKER_COMPOSE) ps

docker-restart: docker-down docker-up ## Restart all Docker services

# =============================================================================
# Documentation
# =============================================================================

docs: ## Build documentation
	@echo "$(BLUE)Building documentation...$(NC)"
	mkdocs build
	@echo "$(GREEN)Documentation built!$(NC)"

serve-docs: ## Serve documentation locally
	@echo "$(BLUE)Serving documentation at http://localhost:8001$(NC)"
	mkdocs serve -a localhost:8001

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Clean up temporary files
	@echo "$(BLUE)Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "coverage_html" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	rm -rf build/ dist/ .eggs/ 2>/dev/null || true
	@echo "$(GREEN)Cleanup completed!$(NC)"

clean-docker: ## Clean up Docker resources
	@echo "$(BLUE)Cleaning Docker resources...$(NC)"
	docker system prune -f
	@echo "$(GREEN)Docker cleanup completed!$(NC)"

# =============================================================================
# Utilities
# =============================================================================

shell: ## Start interactive Python shell
	@echo "$(BLUE)Starting Python shell...$(NC)"
	ipython

seed: ## Seed database with sample data
	@echo "$(BLUE)Seeding database...$(NC)"
	$(PYTHON) -m app.scripts.seed_data
	@echo "$(GREEN)Database seeded!$(NC)"

create-admin: ## Create admin user (usage: make create-admin email="admin@example.com")
	@echo "$(BLUE)Creating admin user...$(NC)"
	$(PYTHON) -m app.scripts.create_admin --email $(email)
	@echo "$(GREEN)Admin user created!$(NC)"

generate-secret: ## Generate a secure secret key
	@echo "$(BLUE)Generated secret key:$(NC)"
	@$(PYTHON) -c "import secrets; print(secrets.token_hex(32))"
