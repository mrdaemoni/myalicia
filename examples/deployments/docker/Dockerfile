# Containerized myalicia.
#
# Build:
#   docker build -t myalicia .
#
# Run:
#   docker run -d \
#     -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
#     -e TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN \
#     -v $HOME/Documents/my-vault:/vault \
#     -v $HOME/.alicia:/root/.alicia \
#     --name myalicia \
#     myalicia
#
# Or use docker-compose: see docker-compose.yml in this folder.

FROM python:3.12-slim

# System deps for some optional features (voice/audio, image generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install myalicia. Pin the version once releases exist.
RUN pip install --no-cache-dir 'myalicia[telegram,voice]'

# The vault and config live as mounted volumes
VOLUME ["/vault", "/root/.alicia"]

# Override at runtime via env vars
ENV ALICIA_VAULT_ROOT=/vault

# Run the agent
CMD ["python", "-m", "myalicia.cli", "run"]
