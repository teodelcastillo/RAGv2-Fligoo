FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /code

# Install Poetry
RUN pip install --no-cache-dir poetry
RUN echo "poetry installed successfully."
# Copy project files
COPY pyproject.toml poetry.lock* /code/
RUN poetry config virtualenvs.create false && \
    poetry config installer.parallel false && \
    poetry install --no-root --only main

# Copy the rest of the source code
COPY . /code
