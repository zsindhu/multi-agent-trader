# Premium Trader — Deploy & Operations
#
# Usage:
#   make preflight       Run smoke test (imports + migrations)
#   make deploy          Preflight, push, build & restart on the droplet
#   make logs            Tail container logs on the droplet
#   make status          Show running containers on the droplet
#
# Set DEPLOY_HOST in your .env or environment:
#   export DEPLOY_HOST=root@your-droplet-ip

-include .env
export

DEPLOY_HOST ?= $(error Set DEPLOY_HOST in .env or environment, e.g. root@123.45.67.89)
DEPLOY_DIR  ?= /opt/multi-agent-trader

.PHONY: preflight deploy logs status

preflight:
	@echo "── Running preflight smoke test ──"
	python scripts/preflight.py

deploy: preflight
	@echo "── Pushing to origin ──"
	git push
	@echo "── Deploying to $(DEPLOY_HOST) ──"
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_DIR) && git pull && docker compose up -d --build"
	@echo "── Deploy complete. Tailing logs... ──"
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_DIR) && docker compose logs -f --tail=40"

logs:
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_DIR) && docker compose logs -f --tail=60"

status:
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_DIR) && docker compose ps"
