FROM us-west1-docker.pkg.dev/kaggle-playground-170215/kaggle-benchmarks/osworld-base:latest

# Patch agent.py to route all calls through OpenAI format when OPENAI_BASE_URL is set
RUN sed -i 's/elif self.model.startswith("gpt"):/elif os.environ.get("OPENAI_BASE_URL") or self.model.startswith("gpt"):/' \
    /tmp/OSWorld/mm_agents/agent.py

# Copy scripts
COPY scripts/ /opt/scripts/
RUN chmod +x /opt/scripts/*.sh

ENTRYPOINT ["/opt/scripts/entrypoint.sh"]
