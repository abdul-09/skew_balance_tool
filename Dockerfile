# Reproducible way to run the skewproof CLI demo without installing Python
# locally. Not a deployment artifact - skewproof is a library/CLI, not a
# long-running service - this exists purely for "clone, build, run, see the
# same output every time" onboarding.
#
#   docker build -t skewproof .
#   docker run --rm skewproof
#   docker run --rm skewproof skewproof demo --day 3
FROM python:3.12-slim

WORKDIR /app

# Install from the committed lockfile so the image gets the exact versions
# CI tests against, then the package itself with no further dependency
# resolution.
COPY requirements/dev.txt requirements/dev.txt
RUN pip install --no-cache-dir -r requirements/dev.txt

COPY . .
RUN pip install --no-cache-dir -e . --no-deps

ENTRYPOINT ["skewproof"]
CMD ["demo"]
