# Dockerfile for instruct-bench sandbox containers
# Provides isolated environment for testing agent prompt injection vulnerabilities

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Git for git-based tasks
    git \
    # Node.js for Claude Code agent
    nodejs \
    npm \
    # Archive tools for encryption/password-protection tests
    zip \
    unzip \
    p7zip-full \
    # Networking tools (optional, for debugging)
    curl \
    # Virtual X server and clipboard for clipboard exfiltration tests
    xvfb \
    xclip \
    # Process utilities (pgrep, pkill, ps, etc.)
    procps \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Create pbpaste shim for macOS compatibility (injections use pbpaste)
# Also create pbcopy for completeness
RUN printf '#!/bin/bash\nxclip -selection clipboard -o\n' > /usr/local/bin/pbpaste && \
    printf '#!/bin/bash\nxclip -selection clipboard\n' > /usr/local/bin/pbcopy && \
    chmod +x /usr/local/bin/pbpaste /usr/local/bin/pbcopy

# Install Python dependencies for document manipulation tasks
RUN pip install --no-cache-dir \
    # PowerPoint manipulation (pptx tasks)
    python-pptx \
    # Word document manipulation (docx tasks)
    python-docx \
    # HTTP requests (data exfiltration tests)
    requests \
    # PDF handling (if needed)
    PyPDF2 \
    # Excel handling (xlsx tasks)
    openpyxl \
    # SQLite is built-in, but add aiosqlite for async
    aiosqlite \
    # Web server (code tasks)
    flask \
    # Email capabilities
    yagmail \
    secure-smtplib \
    # Calendar handling (iCal format)
    icalendar \
    python-dateutil \
    # Google APIs (Calendar, Gmail, etc.)
    google-api-python-client \
    google-auth-oauthlib \
    # MCP Python SDK
    mcp

# Install coding agent CLIs and MCP tools
RUN npm install -g \
    # Claude Code (Anthropic)
    @anthropic-ai/claude-code@2.0.76 \
    # Codex (OpenAI)
    @openai/codex@0.87.0 \
    # Gemini CLI (Google) - needs zod-to-json-schema as peer dependency
    @google/gemini-cli \
    zod-to-json-schema \
    # MCP SDK and tools (for MCP server tasks)
    @modelcontextprotocol/sdk \
    @modelcontextprotocol/server-filesystem \
    # TypeScript for MCP server development
    typescript \
    ts-node \
    @types/node \
    # PowerPoint generation
    pptxgenjs \
    # Browser automation
    playwright

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create non-root user for security
RUN useradd -m -s /bin/bash agent && \
    mkdir -p /workspace && \
    chown -R agent:agent /workspace

# Set working directory
WORKDIR /workspace

# Default to non-root user
USER agent

# Use entrypoint to set up Xvfb and clipboard before running agent
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Git config to avoid warnings
RUN git config --global user.email "agent@sandbox.local" && \
    git config --global user.name "Sandbox Agent" && \
    git config --global init.defaultBranch main

# No default entrypoint - agent command specified at runtime (claude, codex, gemini)
# Example: docker run instruct-bench-agent claude --print "task"
#          docker run instruct-bench-agent codex "task"
#          docker run instruct-bench-agent gemini "task"
