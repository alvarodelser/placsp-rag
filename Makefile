# PLACSP deployment helpers.
# APP_VERSION is the git commit baked into the search-api image so relevance
# feedback rows record which build produced them. Computed automatically here,
# so no .env editing is needed.
export APP_VERSION := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

.PHONY: deploy build up down ps logs version

## Build images (stamping the current commit) and (re)start the stack.
deploy:
	APP_VERSION=$(APP_VERSION) docker compose up -d --build

## Build images only, stamping the current commit.
build:
	APP_VERSION=$(APP_VERSION) docker compose build

## Start the stack without rebuilding.
up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f placsp-search-api

## Print the commit that will be stamped.
version:
	@echo $(APP_VERSION)
