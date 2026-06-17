# Hosted Biomarker Timeline web service (webapp.py), for Railway.
#
# WeasyPrint (>=53) renders PDFs with Pango/HarfBuzz/Fontconfig rather than
# cairo, so those system libraries must be present in the image. They are
# installed below; everything else is pure-Python wheels from requirements.txt.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    PORT=8080

# System libraries WeasyPrint needs to render text and PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        libffi8 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

# 2 workers handles a personal-scale tool; raise/lower for your plan's memory.
# The long timeout gives WeasyPrint + matplotlib room to render large panels.
CMD ["sh", "-c", "gunicorn webapp:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 180 --access-logfile -"]
