.PHONY: help up dev down logs ps test test-down check

help:
	@echo "up         Build and start the local stack"
	@echo "dev        Start with Python source reload"
	@echo "down       Stop the local stack; retain database data"
	@echo "logs       Follow service logs"
	@echo "ps         Show service health"
	@echo "test       Run lint, formatting checks and tests in Docker"
	@echo "test-down  Remove isolated test containers"
	@echo "check      Validate Compose configuration"

up:
	docker compose up --build -d --wait

dev:
	docker compose -f compose.yaml -f compose.dev.yaml up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
	docker compose -f compose.test.yaml down

test-down:
	docker compose -f compose.test.yaml down

check:
	docker compose config --quiet
	docker compose -f compose.yaml -f compose.dev.yaml config --quiet
	docker compose -f compose.test.yaml config --quiet
